"""Pre-confirmation context gate for Phase 7K follow-through redesign.

Phase 7J showed that post-confirmation invalidation removes obvious bad rows but
leaves the candidate sparse and unstable. 7K moves the filter earlier: it gates
WAIT_COMPRESSION / BREAKOUT_SETUP rows before Phase 7F follow-through scoring so
only context-supported breakout candidates can become confirmations.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_breakout_followthrough import build_breakout_followthrough_frame
from libs.models.regime_v2.evaluation.playbook_ft_wf import build_ft_walkforward_report

_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES = (2.0, 5.0, 10.0)
_ELIGIBLE_STATES = {"BREAKOUT_SETUP", "WAIT_COMPRESSION"}
_BLOCK_STATE = "OBSERVE_ONLY"


def apply_ft_context_gate(
    analysis_df: pd.DataFrame,
    context_df: pd.DataFrame,
    state_df: pd.DataFrame,
    *,
    min_context_score: float = 0.70,
    max_risk_score: float = 0.72,
    max_conflict_count: int = 1,
    allow_watch_risk: bool = True,
    require_breakout_playbook: bool = False,
    require_confirmed_context: bool = False,
) -> pd.DataFrame:
    """Gate candidate states before Phase 7F follow-through scoring.

    The gate is intentionally diagnostic-only. It joins Phase 7A context and raw
    RegimeV2 analysis features onto Phase 7B states, scores each candidate, and
    downgrades unsupported eligible states to OBSERVE_ONLY so 7F cannot promote
    them into BREAKOUT_CONFIRMATION.
    """
    if state_df.empty:
        return _ensure_gate_columns(state_df.copy())
    joined = state_df.copy().join(context_df.add_prefix("ctx__"), how="left")
    joined = joined.join(_analysis_features(analysis_df).add_prefix("ana__"), how="left")
    rows: list[dict[str, Any]] = []
    for _, row in joined.iterrows():
        rows.append(
            _gate_row(
                row,
                min_context_score=float(min_context_score),
                max_risk_score=float(max_risk_score),
                max_conflict_count=int(max_conflict_count),
                allow_watch_risk=bool(allow_watch_risk),
                require_breakout_playbook=bool(require_breakout_playbook),
                require_confirmed_context=bool(require_confirmed_context),
            )
        )
    return pd.DataFrame(rows, index=joined.index)


def build_ft_context_gate_report(
    gated_state_df: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    threshold: float | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize the Phase 7K context gate."""
    frame = _ensure_gate_columns(gated_state_df.copy())
    before = frame[frame["ft_context_gate_candidate"] == True]
    active = frame[frame["ft_context_gate_active"] == True]
    blocked = frame[(frame["ft_context_gate_candidate"] == True) & (frame["ft_context_gate_active"] != True)]
    return {
        "phase": "phase_7k_ft_context_gate",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "threshold": threshold,
            "row_count": int(len(frame)),
            "candidate_before": int(len(before)),
            "candidate_after": int(len(active)),
            "blocked_count": int(len(blocked)),
            "candidate_reduction_rate": _rate(len(blocked), len(before)),
            "avg_context_score": _mean(frame.get("ft_context_gate_score")),
            "avg_active_context_score": _mean(active.get("ft_context_gate_score")) if len(active) else None,
            "reason_distribution": _counts(frame.get("ft_context_gate_reason")),
            "market_phase_distribution_after": _counts(active.get("ft_context_gate_market_phase")) if len(active) else {},
            "horizon_distribution_after": _counts(active.get("ft_context_gate_horizon_bias")) if len(active) else {},
            "config": dict(config or {}),
        },
        "recent_blocked": _recent(blocked),
        "recent_active": _recent(active),
    }


def build_ft_context_gate_retest_report(
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
    min_context_score: float = 0.70,
    max_risk_score: float = 0.72,
    max_conflict_count: int = 1,
    allow_watch_risk: bool = True,
    require_breakout_playbook: bool = False,
    require_confirmed_context: bool = False,
) -> dict[str, Any]:
    """Apply Phase 7K context gating, then rerun 7F and 7H."""
    config = {
        "min_context_score": float(min_context_score),
        "max_risk_score": float(max_risk_score),
        "max_conflict_count": int(max_conflict_count),
        "allow_watch_risk": bool(allow_watch_risk),
        "require_breakout_playbook": bool(require_breakout_playbook),
        "require_confirmed_context": bool(require_confirmed_context),
    }
    gated = apply_ft_context_gate(
        analysis_df,
        context_df,
        state_df,
        **config,
    )
    gate_report = build_ft_context_gate_report(
        gated,
        asset=asset,
        timeframe=timeframe,
        threshold=threshold,
        config=config,
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
    walkforward = build_ft_walkforward_report(
        refined,
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
        "phase": "phase_7k_ft_context_gate_retest",
        "summary": _variant_summary(gate_report, walkforward),
        "gate_report": gate_report,
        "walkforward_report": walkforward,
    }


def build_ft_context_gate_matrix_report(retest_reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize Phase 7K context-gate retests across variants."""
    variants = [_variant_row(report) for report in retest_reports]
    variants.sort(
        key=lambda row: (
            bool(row.get("ready")),
            int(row.get("passed_split_count") or 0),
            float(row.get("avg_split_directional_return") or -999.0),
            int(row.get("active_total") or 0),
        ),
        reverse=True,
    )
    ready = [row for row in variants if row.get("ready")]
    return {
        "phase": "phase_7k_ft_context_gate_matrix",
        "summary": {
            "variant_count": len(variants),
            "ready_variant_count": len(ready),
            "thresholds": sorted({float(row.get("threshold") or 0.0) for row in variants}),
            "best_variant": _compact(variants[0]) if variants else None,
            "best_ready_variant": _compact(ready[0]) if ready else None,
            "recommendation": "candidate_ready_after_context_gate" if ready else "hold_off_context_gate_unstable",
        },
        "variants": variants,
    }


def render_ft_context_gate_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for Phase 7K reports."""
    phase = report.get("phase")
    if phase == "phase_7k_ft_context_gate_matrix":
        return _render_matrix(report)
    if phase == "phase_7k_ft_context_gate_retest":
        return _render_retest(report)
    return _render_gate(report)


def _gate_row(
    row: Mapping[str, Any],
    *,
    min_context_score: float,
    max_risk_score: float,
    max_conflict_count: int,
    allow_watch_risk: bool,
    require_breakout_playbook: bool,
    require_confirmed_context: bool,
) -> dict[str, Any]:
    item = dict(row)
    base_state = str(item.get("playbook_state") or "")
    candidate = base_state in _ELIGIBLE_STATES
    score, components = _context_score(item)
    reason = _reason(
        row=item,
        candidate=candidate,
        score=score,
        min_context_score=min_context_score,
        max_risk_score=max_risk_score,
        max_conflict_count=max_conflict_count,
        allow_watch_risk=allow_watch_risk,
        require_breakout_playbook=require_breakout_playbook,
        require_confirmed_context=require_confirmed_context,
    )
    active = candidate and reason == "passed"
    item["ft_context_gate_candidate"] = bool(candidate)
    item["ft_context_gate_active"] = bool(active)
    item["ft_context_gate_score"] = float(score)
    item["ft_context_gate_reason"] = reason
    item["ft_context_gate_components"] = components
    item["ft_context_gate_market_phase"] = _text(item.get("ctx__playbook_context_market_phase"))
    item["ft_context_gate_risk_state"] = _text(item.get("ctx__playbook_context_risk_state"))
    item["ft_context_gate_horizon_bias"] = _text(item.get("ctx__playbook_context_horizon_bias"))
    item["ft_context_gate_conflict_tags"] = _text(item.get("ctx__playbook_context_conflict_tags"))
    item["ft_context_gate_dominant_playbook"] = _text(item.get("ctx__playbook_context_dominant_playbook"))
    item["playbook_state_base_before_context_gate"] = base_state
    if candidate and not active:
        item["playbook_state"] = _BLOCK_STATE
        item["playbook_state_group"] = "wait"
        item["playbook_state_is_executable"] = False
        item["playbook_state_is_wait"] = True
        item["playbook_state_reason"] = "context_gate_blocked"
    return item


def _context_score(row: Mapping[str, Any]) -> tuple[float, dict[str, float]]:
    phase = _text(row.get("ctx__playbook_context_market_phase"))
    risk_state = _text(row.get("ctx__playbook_context_risk_state"))
    horizon = _text(row.get("ctx__playbook_context_horizon_bias"))
    playbook = _text(row.get("ctx__playbook_context_dominant_playbook"))
    alignment = _text(row.get("ctx__playbook_context_alignment"))
    risk_score = _float(row.get("ctx__playbook_context_risk_score"), 1.0)
    conflict_count = _float(row.get("ctx__playbook_context_conflict_count"), 5.0)
    compression = _float(row.get("ana__compression_score"))
    setup = max(_float(row.get("ana__pre_breakout_setup_score")), _float(row.get("ana__policy_breakout_setup_score")))
    displacement = max(_float(row.get("ana__displacement_breakout_score")), _float(row.get("ana__policy_displacement_breakout_score")))
    retest = max(_float(row.get("ana__post_breakout_retest_score")), _float(row.get("ana__policy_retest_breakout_score")))
    false_risk = _float(row.get("ana__false_breakout_risk"), 1.0)
    shock = _float(row.get("ana__shock_risk"), 1.0)
    breakout_score = _float(row.get("ctx__playbook_context_score_breakout"))

    phase_score = {
        "displacement_breakout": 1.0,
        "retest_breakout": 0.95,
        "breakout_setup": 0.80,
        "compressed_wait": 0.65,
    }.get(phase, 0.25 if "trend" in phase else 0.15)
    risk_component = 1.0 if risk_state == "ok" else 0.70 if risk_state == "watch" else 0.0
    risk_component *= max(0.0, min(1.0, 1.0 - risk_score / 1.25))
    horizon_component = {
        "mid_to_long": 1.0,
        "wait_for_expansion": 0.85,
        "mid": 0.70,
        "long": 0.55,
        "short_to_mid": 0.45,
    }.get(horizon, 0.25)
    playbook_component = 1.0 if playbook == "breakout" else 0.55 if playbook in {"trend", "none"} else 0.25
    alignment_component = 1.0 if alignment in {"aligned", "neutral_or_missing"} else 0.45
    conflict_component = max(0.0, 1.0 - 0.25 * conflict_count)
    evidence_component = max(compression * 0.55 + setup * 0.75, displacement, retest, breakout_score)
    quality_component = max(0.0, min(1.0, 1.0 - 0.55 * false_risk - 0.35 * shock))

    components = {
        "phase": phase_score,
        "risk": risk_component,
        "horizon": horizon_component,
        "playbook": playbook_component,
        "alignment": alignment_component,
        "conflict": conflict_component,
        "evidence": evidence_component,
        "quality": quality_component,
    }
    score = (
        0.18 * phase_score
        + 0.17 * risk_component
        + 0.14 * horizon_component
        + 0.12 * playbook_component
        + 0.10 * alignment_component
        + 0.09 * conflict_component
        + 0.13 * evidence_component
        + 0.07 * quality_component
    )
    return max(0.0, min(1.0, float(score))), {key: round(float(value), 4) for key, value in components.items()}


def _reason(
    *,
    row: Mapping[str, Any],
    candidate: bool,
    score: float,
    min_context_score: float,
    max_risk_score: float,
    max_conflict_count: int,
    allow_watch_risk: bool,
    require_breakout_playbook: bool,
    require_confirmed_context: bool,
) -> str:
    if not candidate:
        return "not_candidate_state"
    risk_state = _text(row.get("ctx__playbook_context_risk_state"))
    risk_score = _float(row.get("ctx__playbook_context_risk_score"), 1.0)
    conflict_count = int(_float(row.get("ctx__playbook_context_conflict_count"), 99.0))
    playbook = _text(row.get("ctx__playbook_context_dominant_playbook"))
    confirmed = bool(row.get("ctx__playbook_context_is_confirmed", False))
    tags = _text(row.get("ctx__playbook_context_conflict_tags"))
    if risk_state == "blocked":
        return "risk_blocked"
    if risk_state == "watch" and not allow_watch_risk:
        return "watch_risk_blocked"
    if risk_score > max_risk_score:
        return "risk_score_high"
    if conflict_count > max_conflict_count:
        return "too_many_conflicts"
    if "breakout_shock_conflict" in tags:
        return "shock_conflict"
    if require_breakout_playbook and playbook != "breakout":
        return "not_breakout_playbook"
    if require_confirmed_context and not confirmed:
        return "context_not_confirmed"
    if score < min_context_score:
        return "score_below_context_threshold"
    return "passed"


def _analysis_features(analysis_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "compression_score",
        "pre_breakout_setup_score",
        "displacement_breakout_score",
        "post_breakout_retest_score",
        "policy_breakout_setup_score",
        "policy_displacement_breakout_score",
        "policy_retest_breakout_score",
        "false_breakout_risk",
        "shock_risk",
    ]
    out = pd.DataFrame(index=analysis_df.index)
    for col in columns:
        out[col] = pd.to_numeric(analysis_df[col], errors="coerce") if col in analysis_df.columns else 0.0
    return out.fillna(0.0)


def _variant_summary(gate: Mapping[str, Any], walkforward: Mapping[str, Any]) -> dict[str, Any]:
    gate_summary = dict(gate.get("summary", {}))
    wf_summary = dict(walkforward.get("summary", {}))
    return {
        "asset": gate_summary.get("asset"),
        "timeframe": gate_summary.get("timeframe"),
        "threshold": gate_summary.get("threshold"),
        "candidate_before": gate_summary.get("candidate_before"),
        "candidate_after": gate_summary.get("candidate_after"),
        "blocked_count": gate_summary.get("blocked_count"),
        "active_total": wf_summary.get("active_total"),
        "passed_split_count": wf_summary.get("passed_split_count"),
        "split_count": wf_summary.get("split_count"),
        "ready": wf_summary.get("ready"),
        "recommendation": wf_summary.get("recommendation"),
        "avg_split_directional_return": wf_summary.get("avg_split_directional_return"),
        "worst_split_directional_return": wf_summary.get("worst_split_directional_return"),
    }


def _variant_row(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = dict(report.get("summary", {}))
    gate = dict(dict(report.get("gate_report", {})).get("summary", {}))
    wf = dict(dict(report.get("walkforward_report", {})).get("summary", {}))
    return {
        **summary,
        "reason_distribution": gate.get("reason_distribution", {}),
        "market_phase_distribution_after": gate.get("market_phase_distribution_after", {}),
        "horizon_distribution_after": gate.get("horizon_distribution_after", {}),
        "direction_distribution": wf.get("direction_distribution", {}),
        "failure_reasons": _aggregate_failure_reasons(dict(report.get("walkforward_report", {})).get("splits", [])),
        "splits": list(dict(report.get("walkforward_report", {})).get("splits", [])),
        "config": gate.get("config", {}),
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
        "candidate_before": row.get("candidate_before"),
        "candidate_after": row.get("candidate_after"),
        "active_total": row.get("active_total"),
        "passed_split_count": row.get("passed_split_count"),
        "split_count": row.get("split_count"),
        "ready": row.get("ready"),
        "avg_split_directional_return": row.get("avg_split_directional_return"),
        "worst_split_directional_return": row.get("worst_split_directional_return"),
    }


def _render_gate(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7K Follow-Through Context Gate",
        "",
        "## Summary",
        "",
        f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
        f"- Threshold: {summary.get('threshold')}",
        f"- Candidates before/after: {summary.get('candidate_before')}/{summary.get('candidate_after')}",
        f"- Blocked: {summary.get('blocked_count')}",
        f"- Avg context score: {summary.get('avg_context_score')}",
        f"- Avg active context score: {summary.get('avg_active_context_score')}",
        "",
        "## Reason distribution",
        "",
    ]
    for reason, count in dict(summary.get("reason_distribution", {})).items():
        lines.append(f"- {reason}: {count}")
    lines.append("")
    return "\n".join(lines)


def _render_retest(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    return "\n".join(
        [
            "# RegimeV2 Phase 7K Follow-Through Context Gate Retest",
            "",
            "## Summary",
            "",
            f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}",
            f"- Threshold: {summary.get('threshold')}",
            f"- Candidates before/after: {summary.get('candidate_before')}/{summary.get('candidate_after')}",
            f"- Active total after 7F: {summary.get('active_total')}",
            f"- Splits passed: {summary.get('passed_split_count')}/{summary.get('split_count')}",
            f"- Ready: {summary.get('ready')}",
            f"- Recommendation: {summary.get('recommendation')}",
            "",
        ]
    )


def _render_matrix(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7K Follow-Through Context Gate Matrix",
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
        "| Threshold | Candidates before | Candidates after | Active total | Passed | Avg split dir | Worst split dir | Ready |",
        "|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("variants", []):
        lines.append(
            "| {thr} | {before} | {after} | {active} | {passed}/{splits} | {avg} | {worst} | {ready} |".format(
                thr=row.get("threshold"),
                before=row.get("candidate_before"),
                after=row.get("candidate_after"),
                active=row.get("active_total"),
                passed=row.get("passed_split_count"),
                splits=row.get("split_count"),
                avg=row.get("avg_split_directional_return"),
                worst=row.get("worst_split_directional_return"),
                ready=row.get("ready"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _ensure_gate_columns(frame: pd.DataFrame) -> pd.DataFrame:
    defaults: dict[str, Any] = {
        "ft_context_gate_candidate": False,
        "ft_context_gate_active": False,
        "ft_context_gate_score": 0.0,
        "ft_context_gate_reason": "not_candidate_state",
        "ft_context_gate_market_phase": "",
        "ft_context_gate_horizon_bias": "",
    }
    for column, default in defaults.items():
        if column not in frame.columns:
            frame[column] = default
    return frame


def _recent(frame: pd.DataFrame, *, limit: int = 10) -> list[dict[str, Any]]:
    rows = []
    for idx, row in frame.tail(limit).iterrows():
        rows.append(
            {
                "timestamp": str(idx),
                "state": row.get("playbook_state_base_before_context_gate", row.get("playbook_state")),
                "reason": row.get("ft_context_gate_reason"),
                "score": row.get("ft_context_gate_score"),
                "phase": row.get("ft_context_gate_market_phase"),
                "horizon": row.get("ft_context_gate_horizon_bias"),
            }
        )
    return rows


def _counts(series: pd.Series | None) -> dict[str, int]:
    if series is None:
        return {}
    return dict(Counter(str(value) for value in series.fillna("missing").tolist()).most_common())


def _mean(series: pd.Series | None) -> float | None:
    if series is None or len(series) == 0:
        return None
    values = pd.to_numeric(series, errors="coerce").dropna()
    return float(values.mean()) if len(values) else None


def _rate(numerator: int, denominator: int) -> float | None:
    return float(numerator) / float(denominator) if denominator > 0 else None


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value)
    return default if text.lower() == "nan" else text


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = [
    "apply_ft_context_gate",
    "build_ft_context_gate_matrix_report",
    "build_ft_context_gate_report",
    "build_ft_context_gate_retest_report",
    "render_ft_context_gate_markdown",
]
