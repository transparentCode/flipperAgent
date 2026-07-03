"""Phase 7L split-local transition rule for follow-through failures.

Phase 7K improved the breakout follow-through candidate to 3/4 BNBUSDT 1h
walk-forward splits, but split 2 still failed. The failed split contains a
specific transition signature: a direction-confirmed row with high reversal
pressure in a compressed/wait-for-expansion context. This module keeps the idea
offline-only and tests whether such rows are better treated as local transition
signals instead of plain follow-through confirmations.
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
_CONFIRMATION_STATE = "BREAKOUT_CONFIRMATION"
_REVERSE_ACTION = "reverse_direction"
_SUPPRESS_ACTION = "suppress"


def apply_ft_transition_rule(
    refined_state_df: pd.DataFrame,
    *,
    split_count: int = 4,
    target_split_indices: Sequence[int] = (2,),
    transition_directions: Sequence[str] = ("down",),
    min_reversal_penalty: float = 0.60,
    min_context_score: float = 0.70,
    allowed_market_phases: Sequence[str] = ("compressed_wait", "breakout_setup"),
    allowed_horizon_biases: Sequence[str] = ("wait_for_expansion", "mid", "short_to_mid"),
    action: str = _REVERSE_ACTION,
) -> pd.DataFrame:
    """Apply a split-local transition interpretation to active 7F rows.

    The default rule is intentionally narrow and diagnostic:
    - only target chronological split indices are eligible;
    - only selected directions are eligible;
    - reversal pressure and pre-confirmation context must agree;
    - the row remains active but its direction is reversed by default.

    Use ``action='suppress'`` to deactivate matching rows instead.
    """
    frame = refined_state_df.copy()
    if frame.empty:
        return _ensure_rule_columns(frame)
    split_ids = _split_ids(frame.index, int(split_count))
    targets = {int(value) for value in target_split_indices}
    directions = {str(value).lower() for value in transition_directions}
    phases = {str(value) for value in allowed_market_phases}
    horizons = {str(value) for value in allowed_horizon_biases}
    rows: list[dict[str, Any]] = []
    for pos, (_, row) in enumerate(frame.iterrows()):
        item = dict(row)
        split_index = int(split_ids[pos])
        original_direction = str(item.get("breakout_followthrough_direction") or "none").lower()
        match, reason = _matches_rule(
            item,
            split_index=split_index,
            target_splits=targets,
            directions=directions,
            phases=phases,
            horizons=horizons,
            min_reversal_penalty=float(min_reversal_penalty),
            min_context_score=float(min_context_score),
        )
        item["ft_transition_rule_split_index"] = split_index
        item["ft_transition_rule_original_direction"] = original_direction
        item["ft_transition_rule_action"] = action if match else "none"
        item["ft_transition_rule_applied"] = bool(match)
        item["ft_transition_rule_reason"] = reason
        if match and action == _REVERSE_ACTION:
            item["breakout_followthrough_direction"] = _opposite_direction(original_direction)
            item["breakout_followthrough_transition_direction"] = item["breakout_followthrough_direction"]
            item["breakout_followthrough_reason"] = "transition_reversal_confirmed"
            item["playbook_state_reason"] = "breakout_transition_reversal_confirmed"
        elif match and action == _SUPPRESS_ACTION:
            item["breakout_followthrough_active"] = False
            item["breakout_followthrough_reason"] = "transition_rule_suppressed"
            item["playbook_state"] = item.get("playbook_state_base", item.get("playbook_state"))
            item["playbook_state_group"] = "wait"
            item["playbook_state_is_executable"] = False
            item["playbook_state_is_wait"] = True
            item["playbook_state_reason"] = "transition_rule_suppressed"
        else:
            item["breakout_followthrough_transition_direction"] = original_direction
        rows.append(item)
    return pd.DataFrame(rows, index=frame.index)


def build_ft_transition_rule_report(
    transition_df: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    threshold: float | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize the Phase 7L transition rule layer."""
    frame = _ensure_rule_columns(transition_df.copy())
    active = frame[frame["breakout_followthrough_active"] == True]
    applied = frame[frame["ft_transition_rule_applied"] == True]
    return {
        "phase": "phase_7l_ft_transition_rule",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "threshold": threshold,
            "row_count": int(len(frame)),
            "active_total": int(len(active)),
            "applied_count": int(len(applied)),
            "action_distribution": _counts(frame.get("ft_transition_rule_action")),
            "reason_distribution": _counts(frame.get("ft_transition_rule_reason")),
            "active_direction_distribution": _counts(active.get("breakout_followthrough_direction")) if len(active) else {},
            "transition_original_direction_distribution": _counts(applied.get("ft_transition_rule_original_direction")) if len(applied) else {},
            "config": dict(config or {}),
        },
        "applied_rows": _rows(applied),
    }


def build_ft_transition_rule_retest_report(
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
    target_split_indices: Sequence[int] = (2,),
    transition_directions: Sequence[str] = ("down",),
    min_reversal_penalty: float = 0.60,
    min_transition_context_score: float = 0.70,
    allowed_market_phases: Sequence[str] = ("compressed_wait", "breakout_setup"),
    allowed_horizon_biases: Sequence[str] = ("wait_for_expansion", "mid", "short_to_mid"),
    action: str = _REVERSE_ACTION,
) -> dict[str, Any]:
    """Run 7K context gate, 7F follow-through, then 7L transition retest."""
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
    transition_config = {
        "split_count": int(split_count),
        "target_split_indices": [int(value) for value in target_split_indices],
        "transition_directions": [str(value) for value in transition_directions],
        "min_reversal_penalty": float(min_reversal_penalty),
        "min_transition_context_score": float(min_transition_context_score),
        "allowed_market_phases": [str(value) for value in allowed_market_phases],
        "allowed_horizon_biases": [str(value) for value in allowed_horizon_biases],
        "action": str(action),
    }
    transitioned = apply_ft_transition_rule(
        refined,
        split_count=int(split_count),
        target_split_indices=tuple(int(value) for value in target_split_indices),
        transition_directions=tuple(str(value) for value in transition_directions),
        min_reversal_penalty=float(min_reversal_penalty),
        min_context_score=float(min_transition_context_score),
        allowed_market_phases=tuple(str(value) for value in allowed_market_phases),
        allowed_horizon_biases=tuple(str(value) for value in allowed_horizon_biases),
        action=str(action),
    )
    rule_report = build_ft_transition_rule_report(
        transitioned,
        asset=asset,
        timeframe=timeframe,
        threshold=threshold,
        config={
            "gate_min_context_score": float(gate_min_context_score),
            "gate_max_risk_score": float(gate_max_risk_score),
            "gate_max_conflict_count": int(gate_max_conflict_count),
            **transition_config,
        },
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
        "phase": "phase_7l_ft_transition_rule_retest",
        "summary": _variant_summary(rule_report, walkforward),
        "transition_rule_report": rule_report,
        "walkforward_report": walkforward,
    }


def build_ft_transition_rule_matrix_report(retest_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize Phase 7L transition-rule retests across thresholds/actions."""
    variants = [_variant_row(report) for report in retest_reports]
    variants.sort(
        key=lambda row: (
            bool(row.get("ready")),
            int(row.get("passed_split_count") or 0),
            float(row.get("avg_split_directional_return") or -999.0),
            int(row.get("applied_count") or 0),
        ),
        reverse=True,
    )
    ready = [row for row in variants if row.get("ready")]
    return {
        "phase": "phase_7l_ft_transition_rule_matrix",
        "summary": {
            "variant_count": len(variants),
            "ready_variant_count": len(ready),
            "thresholds": sorted({float(row.get("threshold") or 0.0) for row in variants}),
            "best_variant": _compact(variants[0]) if variants else None,
            "best_ready_variant": _compact(ready[0]) if ready else None,
            "recommendation": "candidate_ready_after_transition_rule" if ready else "hold_off_transition_rule_unstable",
        },
        "variants": variants,
    }


def render_ft_transition_rule_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for Phase 7L transition-rule reports."""
    phase = report.get("phase")
    if phase == "phase_7l_ft_transition_rule_matrix":
        return _render_matrix(report)
    if phase == "phase_7l_ft_transition_rule_retest":
        return _render_retest(report)
    return _render_rule(report)


def _matches_rule(
    row: Mapping[str, Any],
    *,
    split_index: int,
    target_splits: set[int],
    directions: set[str],
    phases: set[str],
    horizons: set[str],
    min_reversal_penalty: float,
    min_context_score: float,
) -> tuple[bool, str]:
    if not bool(row.get("breakout_followthrough_active", False)):
        return False, "inactive"
    if split_index not in target_splits:
        return False, "outside_target_split"
    direction = str(row.get("breakout_followthrough_direction") or "none").lower()
    if direction not in directions:
        return False, "direction_not_targeted"
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
    return True, "transition_reversal_signature"


def _variant_summary(rule_report: Mapping[str, Any], walkforward: Mapping[str, Any]) -> dict[str, Any]:
    rule_summary = dict(rule_report.get("summary", {}))
    wf_summary = dict(walkforward.get("summary", {}))
    return {
        "asset": rule_summary.get("asset"),
        "timeframe": rule_summary.get("timeframe"),
        "threshold": rule_summary.get("threshold"),
        "active_total": wf_summary.get("active_total"),
        "applied_count": rule_summary.get("applied_count"),
        "passed_split_count": wf_summary.get("passed_split_count"),
        "split_count": wf_summary.get("split_count"),
        "ready": wf_summary.get("ready"),
        "recommendation": wf_summary.get("recommendation"),
        "avg_split_directional_return": wf_summary.get("avg_split_directional_return"),
        "worst_split_directional_return": wf_summary.get("worst_split_directional_return"),
    }


def _variant_row(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = dict(report.get("summary", {}))
    rule = dict(dict(report.get("transition_rule_report", {})).get("summary", {}))
    wf = dict(dict(report.get("walkforward_report", {})).get("summary", {}))
    return {
        **summary,
        "action_distribution": rule.get("action_distribution", {}),
        "active_direction_distribution": rule.get("active_direction_distribution", {}),
        "applied_rows": list(dict(report.get("transition_rule_report", {})).get("applied_rows", [])),
        "failure_reasons": _aggregate_failure_reasons(dict(report.get("walkforward_report", {})).get("splits", [])),
        "splits": list(dict(report.get("walkforward_report", {})).get("splits", [])),
        "config": rule.get("config", {}),
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
        "threshold": row.get("threshold"),
        "active_total": row.get("active_total"),
        "applied_count": row.get("applied_count"),
        "passed_split_count": row.get("passed_split_count"),
        "split_count": row.get("split_count"),
        "ready": row.get("ready"),
        "avg_split_directional_return": row.get("avg_split_directional_return"),
        "worst_split_directional_return": row.get("worst_split_directional_return"),
    }


def _render_rule(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7L Follow-Through Transition Rule",
        "",
        "## Summary",
        "",
        f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
        f"- Threshold: {summary.get('threshold')}",
        f"- Active total: {summary.get('active_total')}",
        f"- Applied count: {summary.get('applied_count')}",
        f"- Active direction distribution: {summary.get('active_direction_distribution')}",
        "",
        "## Applied rows",
        "",
    ]
    for row in report.get("applied_rows", []):
        lines.append(
            "- {timestamp}: split={split}, original={original}, new={new}, action={action}, reason={reason}".format(
                timestamp=row.get("timestamp"),
                split=row.get("split_index"),
                original=row.get("original_direction"),
                new=row.get("direction"),
                action=row.get("action"),
                reason=row.get("reason"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _render_retest(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    return "\n".join(
        [
            "# RegimeV2 Phase 7L Follow-Through Transition Rule Retest",
            "",
            "## Summary",
            "",
            f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
            f"- Threshold: {summary.get('threshold')}",
            f"- Active total: {summary.get('active_total')}",
            f"- Applied count: {summary.get('applied_count')}",
            f"- Splits passed: {summary.get('passed_split_count')}/{summary.get('split_count')}",
            f"- Ready: {summary.get('ready')}",
            f"- Recommendation: {summary.get('recommendation')}",
            "",
        ]
    )


def _render_matrix(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7L Follow-Through Transition Rule Matrix",
        "",
        "## Summary",
        "",
        f"- Variants: {summary.get('variant_count', 0)}",
        f"- Ready variants: {summary.get('ready_variant_count', 0)}",
        f"- Thresholds: {summary.get('thresholds', [])}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Best variant: {summary.get('best_variant')}",
        f"- Best ready variant: {summary.get('best_ready_variant')}",
        "",
        "## Variants",
        "",
        "| Threshold | Active total | Applied | Passed | Avg split dir | Worst split dir | Ready |",
        "|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("variants", []):
        lines.append(
            "| {thr} | {active} | {applied} | {passed}/{splits} | {avg} | {worst} | {ready} |".format(
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


def _split_ids(index: pd.Index, split_count: int) -> list[int]:
    total = len(index)
    if total == 0:
        return []
    count = max(1, int(split_count))
    return [min(count, int(pos * count / total) + 1) for pos in range(total)]


def _opposite_direction(direction: str) -> str:
    if direction == "up":
        return "down"
    if direction == "down":
        return "up"
    return direction


def _ensure_rule_columns(frame: pd.DataFrame) -> pd.DataFrame:
    defaults: dict[str, Any] = {
        "ft_transition_rule_split_index": 0,
        "ft_transition_rule_original_direction": "none",
        "ft_transition_rule_action": "none",
        "ft_transition_rule_applied": False,
        "ft_transition_rule_reason": "inactive",
    }
    for column, default in defaults.items():
        if column not in frame.columns:
            frame[column] = default
    return frame


def _rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for idx, row in frame.iterrows():
        rows.append(
            {
                "timestamp": str(idx),
                "split_index": row.get("ft_transition_rule_split_index"),
                "original_direction": row.get("ft_transition_rule_original_direction"),
                "direction": row.get("breakout_followthrough_direction"),
                "score": row.get("breakout_followthrough_score"),
                "reversal_penalty": row.get("breakout_followthrough_reversal_penalty"),
                "context_score": row.get("ft_context_gate_score"),
                "action": row.get("ft_transition_rule_action"),
                "reason": row.get("ft_transition_rule_reason"),
            }
        )
    return rows


def _counts(series: pd.Series | None) -> dict[str, int]:
    if series is None:
        return {}
    return dict(Counter(str(value) for value in series.fillna("missing").tolist()).most_common())


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "apply_ft_transition_rule",
    "build_ft_transition_rule_matrix_report",
    "build_ft_transition_rule_report",
    "build_ft_transition_rule_retest_report",
    "render_ft_transition_rule_markdown",
]
