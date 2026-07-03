"""Phase 7N feature-driven transition-regime redesign.

Phase 7M proved that the split-local 7L reversal rule is not reusable. 7N keeps
the same offline-only posture but removes the hardcoded chronological split: it
scores every active 7F follow-through row as continuation vs transition/exhaustion
and can reinterpret only rows where feature evidence favors a direction flip.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_breakout_followthrough import build_breakout_followthrough_frame
from libs.models.regime_v2.evaluation.playbook_ft_context_gate import apply_ft_context_gate
from libs.models.regime_v2.evaluation.playbook_ft_wf import build_ft_walkforward_report

_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES = (2.0, 5.0, 10.0)
_ACTION_REVERSE = "reverse_direction"
_ACTION_SUPPRESS = "suppress"
_ACTION_TAG_ONLY = "tag_only"


def apply_ft_transition_regime(
    refined_state_df: pd.DataFrame,
    *,
    min_transition_edge: float = 0.18,
    min_reversal_penalty: float = 0.60,
    min_context_score: float = 0.70,
    min_followthrough_score: float = 0.25,
    transition_directions: Sequence[str] = ("up", "down"),
    allowed_market_phases: Sequence[str] = ("compressed_wait", "breakout_setup"),
    allowed_horizon_biases: Sequence[str] = ("wait_for_expansion", "mid", "short_to_mid"),
    action: str = _ACTION_REVERSE,
) -> pd.DataFrame:
    """Apply a generic transition-regime score to active follow-through rows.

    Unlike 7L, this rule has no target split input. It only uses row-local
    transition evidence: reversal pressure, weak hold/follow/return quality,
    context score, market phase, and horizon bias.
    """
    frame = refined_state_df.copy()
    if frame.empty:
        return _ensure_columns(frame)
    directions = {str(value).lower() for value in transition_directions}
    phases = {str(value) for value in allowed_market_phases}
    horizons = {str(value) for value in allowed_horizon_biases}
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        item = dict(row)
        scores = _transition_scores(item)
        direction = str(item.get("breakout_followthrough_direction") or "none").lower()
        eligible, reason = _eligible(
            item,
            scores=scores,
            direction=direction,
            directions=directions,
            phases=phases,
            horizons=horizons,
            min_transition_edge=float(min_transition_edge),
            min_reversal_penalty=float(min_reversal_penalty),
            min_context_score=float(min_context_score),
            min_followthrough_score=float(min_followthrough_score),
        )
        item["ft_transition_regime_continuation_score"] = scores["continuation_score"]
        item["ft_transition_regime_reversal_score"] = scores["reversal_score"]
        item["ft_transition_regime_edge"] = scores["transition_edge"]
        item["ft_transition_regime_original_direction"] = direction
        item["ft_transition_regime_applied"] = bool(eligible and action != _ACTION_TAG_ONLY)
        item["ft_transition_regime_action"] = action if eligible else "none"
        item["ft_transition_regime_reason"] = reason
        if eligible and action == _ACTION_REVERSE:
            item["breakout_followthrough_direction"] = _opposite_direction(direction)
            item["breakout_followthrough_transition_direction"] = item["breakout_followthrough_direction"]
            item["breakout_followthrough_reason"] = "transition_regime_reversal_confirmed"
            item["playbook_state_reason"] = "transition_regime_reversal_confirmed"
        elif eligible and action == _ACTION_SUPPRESS:
            item["breakout_followthrough_active"] = False
            item["breakout_followthrough_reason"] = "transition_regime_suppressed"
            item["playbook_state"] = item.get("playbook_state_base", item.get("playbook_state"))
            item["playbook_state_group"] = "wait"
            item["playbook_state_is_executable"] = False
            item["playbook_state_is_wait"] = True
            item["playbook_state_reason"] = "transition_regime_suppressed"
        else:
            item["breakout_followthrough_transition_direction"] = direction
        rows.append(item)
    return pd.DataFrame(rows, index=frame.index)


def build_ft_transition_regime_report(
    regime_df: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    threshold: float | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize a 7N transition-regime frame."""
    frame = _ensure_columns(regime_df.copy())
    active = frame[frame["breakout_followthrough_active"] == True]
    flagged = frame[frame["ft_transition_regime_action"] != "none"]
    applied = frame[frame["ft_transition_regime_applied"] == True]
    return {
        "phase": "phase_7n_ft_transition_regime",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "threshold": threshold,
            "row_count": int(len(frame)),
            "active_total": int(len(active)),
            "flagged_count": int(len(flagged)),
            "applied_count": int(len(applied)),
            "avg_transition_edge": _mean(frame.get("ft_transition_regime_edge")),
            "avg_flagged_transition_edge": _mean(flagged.get("ft_transition_regime_edge")) if len(flagged) else None,
            "action_distribution": _counts(frame.get("ft_transition_regime_action")),
            "reason_distribution": _counts(frame.get("ft_transition_regime_reason")),
            "active_direction_distribution": _counts(active.get("breakout_followthrough_direction")) if len(active) else {},
            "original_direction_distribution": _counts(applied.get("ft_transition_regime_original_direction")) if len(applied) else {},
            "config": dict(config or {}),
        },
        "applied_rows": _rows(applied),
        "flagged_rows": _rows(flagged),
    }


def build_ft_transition_regime_retest_report(
    analysis_df: pd.DataFrame,
    context_df: pd.DataFrame,
    state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    threshold: float | None = None,
    split_count: int = 4,
    breakout_window: int = 20,
    hold_bars: int = 2,
    follow_bars: int = 3,
    max_false_breakout_risk: float = 0.65,
    max_shock_risk: float = 0.80,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES,
    min_split_support: int = 2,
    min_passing_rate: float = 0.60,
    min_avg_return: float = 0.0,
    max_worst_loss: float = 0.0010,
    gate_min_context_score: float = 0.70,
    gate_max_risk_score: float = 0.72,
    gate_max_conflict_count: int = 1,
    min_transition_edge: float = 0.18,
    min_reversal_penalty: float = 0.60,
    min_transition_context_score: float = 0.70,
    transition_directions: Sequence[str] = ("up", "down"),
    action: str = _ACTION_REVERSE,
) -> dict[str, Any]:
    """Run 7K -> 7F -> 7N transition-regime -> 7H walk-forward."""
    gated = apply_ft_context_gate(
        analysis_df,
        context_df,
        state_df,
        min_context_score=float(gate_min_context_score),
        max_risk_score=float(gate_max_risk_score),
        max_conflict_count=int(gate_max_conflict_count),
    )
    refined = build_breakout_followthrough_frame(
        analysis_df,
        gated,
        ohlcv,
        breakout_window=int(breakout_window),
        hold_bars=int(hold_bars),
        follow_bars=int(follow_bars),
        min_followthrough_score=float(threshold or 0.0),
        max_false_breakout_risk=float(max_false_breakout_risk),
        max_shock_risk=float(max_shock_risk),
    )
    config = {
        "gate_min_context_score": float(gate_min_context_score),
        "gate_max_risk_score": float(gate_max_risk_score),
        "gate_max_conflict_count": int(gate_max_conflict_count),
        "min_transition_edge": float(min_transition_edge),
        "min_reversal_penalty": float(min_reversal_penalty),
        "min_transition_context_score": float(min_transition_context_score),
        "transition_directions": [str(value) for value in transition_directions],
        "action": str(action),
    }
    transitioned = apply_ft_transition_regime(
        refined,
        min_transition_edge=float(min_transition_edge),
        min_reversal_penalty=float(min_reversal_penalty),
        min_context_score=float(min_transition_context_score),
        min_followthrough_score=float(threshold or 0.0),
        transition_directions=tuple(str(value) for value in transition_directions),
        action=str(action),
    )
    regime_report = build_ft_transition_regime_report(
        transitioned,
        asset=asset,
        timeframe=timeframe,
        threshold=threshold,
        config=config,
    )
    walkforward = build_ft_walkforward_report(
        transitioned,
        ohlcv,
        asset=asset,
        timeframe=timeframe,
        threshold=threshold,
        split_count=int(split_count),
        horizons=tuple(int(h) for h in horizons),
        fees_bps=tuple(float(f) for f in fees_bps),
        min_split_support=int(min_split_support),
        min_passing_rate=float(min_passing_rate),
        min_avg_return=float(min_avg_return),
        max_worst_loss=float(max_worst_loss),
    )
    return {
        "phase": "phase_7n_ft_transition_regime_retest",
        "summary": _variant_summary(regime_report, walkforward),
        "transition_regime_report": regime_report,
        "walkforward_report": walkforward,
    }


def build_ft_transition_regime_matrix_report(retest_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize 7N transition-regime retests."""
    variants = [_variant_row(report) for report in retest_reports]
    variants.sort(
        key=lambda row: (
            bool(row.get("ready")),
            int(row.get("passed_split_count") or 0),
            float(row.get("avg_split_directional_return") or -999.0),
            float(row.get("worst_split_directional_return") or -999.0),
            -int(row.get("applied_count") or 0),
        ),
        reverse=True,
    )
    ready = [row for row in variants if row.get("ready")]
    return {
        "phase": "phase_7n_ft_transition_regime_matrix",
        "summary": {
            "variant_count": len(variants),
            "ready_variant_count": len(ready),
            "thresholds": sorted({float(row.get("threshold") or 0.0) for row in variants}),
            "assets": sorted({str(row.get("asset")) for row in variants}),
            "best_variant": _compact(variants[0]) if variants else None,
            "best_ready_variant": _compact(ready[0]) if ready else None,
            "recommendation": "candidate_ready_after_transition_regime" if ready else "hold_off_transition_regime_unstable",
        },
        "variants": variants,
    }


def render_ft_transition_regime_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for 7N reports."""
    if report.get("phase") == "phase_7n_ft_transition_regime_matrix":
        return _render_matrix(report)
    return _render_retest(report) if report.get("phase") == "phase_7n_ft_transition_regime_retest" else _render_single(report)


def _transition_scores(row: Mapping[str, Any]) -> dict[str, float]:
    follow = _float(row.get("breakout_followthrough_follow_score"))
    hold = _float(row.get("breakout_followthrough_hold_score"))
    direction_return = _float(row.get("breakout_followthrough_direction_return_score"))
    reversal = _float(row.get("breakout_followthrough_reversal_penalty"))
    volume = _float(row.get("breakout_followthrough_volume_score"))
    context = _float(row.get("ft_context_gate_score"))
    phase = str(row.get("ft_context_gate_market_phase") or "")
    horizon = str(row.get("ft_context_gate_horizon_bias") or "")
    phase_bias = 1.0 if phase in {"compressed_wait", "breakout_setup"} else 0.35
    horizon_bias = 1.0 if horizon == "wait_for_expansion" else 0.70 if horizon in {"mid", "short_to_mid"} else 0.35
    continuation = (
        0.28 * follow
        + 0.24 * hold
        + 0.24 * direction_return
        + 0.14 * (1.0 - reversal)
        + 0.05 * volume
        + 0.05 * context
    )
    reversal_score = (
        0.34 * reversal
        + 0.18 * (1.0 - hold)
        + 0.16 * (1.0 - direction_return)
        + 0.12 * (1.0 - follow)
        + 0.10 * phase_bias
        + 0.06 * horizon_bias
        + 0.04 * context
    )
    edge = reversal_score - continuation
    return {
        "continuation_score": round(max(0.0, min(1.0, continuation)), 6),
        "reversal_score": round(max(0.0, min(1.0, reversal_score)), 6),
        "transition_edge": round(edge, 6),
    }


def _eligible(
    row: Mapping[str, Any],
    *,
    scores: Mapping[str, float],
    direction: str,
    directions: set[str],
    phases: set[str],
    horizons: set[str],
    min_transition_edge: float,
    min_reversal_penalty: float,
    min_context_score: float,
    min_followthrough_score: float,
) -> tuple[bool, str]:
    if not bool(row.get("breakout_followthrough_active", False)):
        return False, "inactive"
    if direction not in directions:
        return False, "direction_not_targeted"
    if _float(row.get("breakout_followthrough_score")) < min_followthrough_score:
        return False, "followthrough_score_low"
    if _float(row.get("breakout_followthrough_reversal_penalty")) < min_reversal_penalty:
        return False, "reversal_penalty_low"
    if _float(row.get("ft_context_gate_score")) < min_context_score:
        return False, "context_score_low"
    phase = str(row.get("ft_context_gate_market_phase") or "")
    if phase not in phases:
        return False, "market_phase_not_allowed"
    horizon = str(row.get("ft_context_gate_horizon_bias") or "")
    if horizon not in horizons:
        return False, "horizon_bias_not_allowed"
    if float(scores.get("transition_edge") or 0.0) < min_transition_edge:
        return False, "transition_edge_low"
    return True, "transition_regime_signature"


def _variant_summary(regime_report: Mapping[str, Any], walkforward: Mapping[str, Any]) -> dict[str, Any]:
    rs = dict(regime_report.get("summary", {}))
    ws = dict(walkforward.get("summary", {}))
    return {
        "asset": rs.get("asset"),
        "timeframe": rs.get("timeframe"),
        "threshold": rs.get("threshold"),
        "active_total": ws.get("active_total"),
        "flagged_count": rs.get("flagged_count"),
        "applied_count": rs.get("applied_count"),
        "passed_split_count": ws.get("passed_split_count"),
        "split_count": ws.get("split_count"),
        "ready": ws.get("ready"),
        "recommendation": ws.get("recommendation"),
        "avg_split_directional_return": ws.get("avg_split_directional_return"),
        "worst_split_directional_return": ws.get("worst_split_directional_return"),
    }


def _variant_row(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = dict(report.get("summary", {}))
    regime = dict(dict(report.get("transition_regime_report", {})).get("summary", {}))
    return {
        **summary,
        "action_distribution": regime.get("action_distribution", {}),
        "active_direction_distribution": regime.get("active_direction_distribution", {}),
        "applied_rows": list(dict(report.get("transition_regime_report", {})).get("applied_rows", [])),
        "failure_reasons": _aggregate_failure_reasons(dict(report.get("walkforward_report", {})).get("splits", [])),
        "splits": list(dict(report.get("walkforward_report", {})).get("splits", [])),
        "config": regime.get("config", {}),
    }


def _aggregate_failure_reasons(splits: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for split in splits:
        counter.update(str(reason) for reason in split.get("failure_reasons", []))
    return dict(counter.most_common())


def _compact(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "asset": row.get("asset"),
        "timeframe": row.get("timeframe"),
        "threshold": row.get("threshold"),
        "active_total": row.get("active_total"),
        "flagged_count": row.get("flagged_count"),
        "applied_count": row.get("applied_count"),
        "passed_split_count": row.get("passed_split_count"),
        "split_count": row.get("split_count"),
        "ready": row.get("ready"),
        "avg_split_directional_return": row.get("avg_split_directional_return"),
        "worst_split_directional_return": row.get("worst_split_directional_return"),
    }


def _render_single(report: Mapping[str, Any]) -> str:
    s = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7N Follow-Through Transition Regime",
        "",
        f"- Asset/timeframe: {s.get('asset')}|{s.get('timeframe')}",
        f"- Active total: {s.get('active_total')}",
        f"- Flagged/applied: {s.get('flagged_count')}/{s.get('applied_count')}",
        f"- Active direction distribution: {s.get('active_direction_distribution')}",
        "",
    ]
    return "\n".join(lines)


def _render_retest(report: Mapping[str, Any]) -> str:
    s = dict(report.get("summary", {}))
    return "\n".join(
        [
            "# RegimeV2 Phase 7N Follow-Through Transition Regime Retest",
            "",
            f"- Asset/timeframe: {s.get('asset')}|{s.get('timeframe')}",
            f"- Threshold: {s.get('threshold')}",
            f"- Active total: {s.get('active_total')}",
            f"- Applied: {s.get('applied_count')}",
            f"- Splits passed: {s.get('passed_split_count')}/{s.get('split_count')}",
            f"- Ready: {s.get('ready')}",
            "",
        ]
    )


def _render_matrix(report: Mapping[str, Any]) -> str:
    s = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7N Follow-Through Transition Regime Matrix",
        "",
        f"- Variants: {s.get('variant_count', 0)}",
        f"- Ready variants: {s.get('ready_variant_count', 0)}",
        f"- Recommendation: {s.get('recommendation')}",
        f"- Best variant: {s.get('best_variant')}",
        "",
        "| Asset | Threshold | Active | Applied | Passed | Avg split dir | Worst split dir | Ready |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("variants", []):
        lines.append(
            "| {asset} | {thr} | {active} | {applied} | {passed}/{splits} | {avg} | {worst} | {ready} |".format(
                asset=row.get("asset"),
                thr=row.get("threshold"),
                active=row.get("active_total"),
                applied=row.get("applied_count"),
                passed=row.get("passed_split_count"),
                splits=row.get("split_count"),
                avg=row.get("avg_split_directional_return"),
                worst=row.get("worst_split_directional_return"),
                ready=row.get("ready"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for idx, row in frame.iterrows():
        rows.append(
            {
                "timestamp": str(idx),
                "original_direction": row.get("ft_transition_regime_original_direction"),
                "direction": row.get("breakout_followthrough_direction"),
                "score": row.get("breakout_followthrough_score"),
                "reversal_penalty": row.get("breakout_followthrough_reversal_penalty"),
                "context_score": row.get("ft_context_gate_score"),
                "transition_edge": row.get("ft_transition_regime_edge"),
                "continuation_score": row.get("ft_transition_regime_continuation_score"),
                "reversal_score": row.get("ft_transition_regime_reversal_score"),
                "reason": row.get("ft_transition_regime_reason"),
                "action": row.get("ft_transition_regime_action"),
            }
        )
    return rows


def _ensure_columns(frame: pd.DataFrame) -> pd.DataFrame:
    defaults: dict[str, Any] = {
        "ft_transition_regime_continuation_score": 0.0,
        "ft_transition_regime_reversal_score": 0.0,
        "ft_transition_regime_edge": 0.0,
        "ft_transition_regime_original_direction": "none",
        "ft_transition_regime_action": "none",
        "ft_transition_regime_applied": False,
        "ft_transition_regime_reason": "inactive",
    }
    for column, default in defaults.items():
        if column not in frame.columns:
            frame[column] = default
    return frame


def _opposite_direction(direction: str) -> str:
    if direction == "up":
        return "down"
    if direction == "down":
        return "up"
    return direction


def _counts(series: pd.Series | None) -> dict[str, int]:
    if series is None:
        return {}
    return dict(Counter(str(value) for value in series.fillna("missing").tolist()).most_common())


def _mean(series: pd.Series | None) -> float | None:
    if series is None or len(series) == 0:
        return None
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.mean()) if len(values) else None


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "apply_ft_transition_regime",
    "build_ft_transition_regime_matrix_report",
    "build_ft_transition_regime_report",
    "build_ft_transition_regime_retest_report",
    "render_ft_transition_regime_markdown",
]
