"""Phase 7V transition micro-state split prototype.

7U showed that setup-transition candidates should be separated by policy-safe
market phase. 7V turns that separation into explicit diagnostic micro-states.
These states are not executable and do not mutate the main playbook state.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_transition_setup import build_setup_transition_candidate_frame
from libs.models.regime_v2.evaluation.playbook_transition_state import label_breakout_transition_outcomes

MICRO_STATE_NONE = "NO_TRANSITION_MICRO_STATE"
MICRO_STATE_BREAKOUT_SETUP = "BREAKOUT_SETUP_TRANSITION_CANDIDATE"
MICRO_STATE_COMPRESSION_OBSERVE = "COMPRESSION_TRANSITION_OBSERVE_ONLY"
MICRO_STATE_OTHER_OBSERVE = "OTHER_TRANSITION_OBSERVE_ONLY"

_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES = (2.0, 5.0, 10.0)


def build_transition_micro_state_frame(candidate_df: pd.DataFrame) -> pd.DataFrame:
    """Add diagnostic transition micro-state columns to a 7P candidate frame."""
    frame = candidate_df.copy()
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        item = dict(row)
        active = bool(item.get("breakout_transition_active", False))
        phase = str(item.get("ft_context_gate_market_phase") or "")
        micro_state, reason, research, observe = _resolve_micro_state(active, phase)
        item["breakout_transition_micro_state"] = micro_state
        item["breakout_transition_micro_reason"] = reason
        item["breakout_transition_micro_is_research_candidate"] = bool(research)
        item["breakout_transition_micro_is_observation_only"] = bool(observe)
        item["breakout_transition_micro_runtime_enabled"] = False
        rows.append(item)
    return pd.DataFrame(rows, index=frame.index)


def build_transition_micro_state_report(
    micro_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize micro-state distribution and outcome separation."""
    frame = micro_df.copy()
    active = frame[frame.get("breakout_transition_active", False) == True]
    state_rows = []
    for state in sorted(set(str(value) for value in active.get("breakout_transition_micro_state", pd.Series(dtype=str)).tolist())):
        state_frame = active[active["breakout_transition_micro_state"] == state]
        state_rows.append(_state_summary(state, state_frame, ohlcv, horizons, fees_bps))
    return {
        "phase": "phase_7v_transition_micro_state_report",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "row_count": int(len(frame)),
            "active_count": int(len(active)),
            "research_candidate_count": int(frame.get("breakout_transition_micro_is_research_candidate", pd.Series(dtype=bool)).sum()),
            "observation_only_count": int(frame.get("breakout_transition_micro_is_observation_only", pd.Series(dtype=bool)).sum()),
            "micro_state_distribution": _counts(active.get("breakout_transition_micro_state")) if len(active) else {},
            "runtime_enabled_count": int(frame.get("breakout_transition_micro_runtime_enabled", pd.Series(dtype=bool)).sum()),
            "best_state": _best_state(state_rows),
            "recommendation": _recommendation(state_rows),
            "config": dict(config or {}),
        },
        "micro_states": state_rows,
        "recent_active": _rows(active.tail(12)),
    }


def build_transition_micro_state_retest_report(
    analysis_df: pd.DataFrame,
    context_df: pd.DataFrame,
    state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES,
    lookback_bars: int = 8,
    min_candidate_score: float = 0.62,
    min_context_score: float = 0.70,
    max_risk_score: float = 0.72,
    max_conflict_count: int = 1,
    min_wick_score: float = 0.35,
    min_attempt_score: float = 0.50,
) -> dict[str, Any]:
    """Build 7P candidates, split micro-states, and summarize outcomes."""
    config = {
        "lookback_bars": int(lookback_bars),
        "min_candidate_score": float(min_candidate_score),
        "min_context_score": float(min_context_score),
        "max_risk_score": float(max_risk_score),
        "max_conflict_count": int(max_conflict_count),
        "min_wick_score": float(min_wick_score),
        "min_attempt_score": float(min_attempt_score),
    }
    candidates = build_setup_transition_candidate_frame(
        analysis_df,
        context_df,
        state_df,
        ohlcv,
        **config,
    )
    micro = build_transition_micro_state_frame(candidates)
    report = build_transition_micro_state_report(
        micro,
        ohlcv,
        asset=asset,
        timeframe=timeframe,
        horizons=tuple(int(h) for h in horizons),
        fees_bps=tuple(float(f) for f in fees_bps),
        config=config,
    )
    return {"phase": "phase_7v_transition_micro_state_retest", "summary": report["summary"], "micro_state_report": report}


def build_transition_micro_state_matrix_report(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Combine 7V reports across assets."""
    rows = [_variant_row(report) for report in reports]
    rows.sort(key=lambda row: (_float(row.get("breakout_setup_avg_return")), _float(row.get("compression_avg_return"))), reverse=True)
    breakout_better = sum(1 for row in rows if _float(row.get("breakout_setup_avg_return")) > _float(row.get("compression_avg_return")))
    return {
        "phase": "phase_7v_transition_micro_state_matrix",
        "summary": {
            "variant_count": len(rows),
            "assets": sorted({str(row.get("asset")) for row in rows}),
            "breakout_better_count": breakout_better,
            "runtime_enabled_count": sum(int(row.get("runtime_enabled_count") or 0) for row in rows),
            "best_variant": rows[0] if rows else None,
            "recommendation": "keep_micro_state_split_diagnostic" if breakout_better > 0 else "micro_state_split_not_useful",
        },
        "variants": rows,
    }


def render_transition_micro_state_markdown(report: Mapping[str, Any]) -> str:
    """Render Markdown for 7V reports."""
    if report.get("phase") == "phase_7v_transition_micro_state_matrix":
        return _render_matrix(report)
    return _render_single(report)


def _resolve_micro_state(active: bool, phase: str) -> tuple[str, str, bool, bool]:
    if not active:
        return MICRO_STATE_NONE, "inactive", False, False
    if phase == "breakout_setup":
        return MICRO_STATE_BREAKOUT_SETUP, "breakout_setup_transition_research_candidate", True, False
    if phase == "compressed_wait":
        return MICRO_STATE_COMPRESSION_OBSERVE, "compressed_wait_transition_observe_only", False, True
    return MICRO_STATE_OTHER_OBSERVE, "other_transition_observe_only", False, True


def _state_summary(state: str, frame: pd.DataFrame, ohlcv: pd.DataFrame, horizons: Sequence[int], fees_bps: Sequence[float]) -> dict[str, Any]:
    outcomes = _outcome_stats(frame, ohlcv, horizons, fees_bps)
    return {
        "micro_state": state,
        "active_count": int(len(frame)),
        "direction_distribution": _counts(frame.get("breakout_transition_direction")) if len(frame) else {},
        "phase_distribution": _counts(frame.get("ft_context_gate_market_phase")) if len(frame) else {},
        **outcomes,
    }


def _outcome_stats(frame: pd.DataFrame, ohlcv: pd.DataFrame, horizons: Sequence[int], fees_bps: Sequence[float]) -> dict[str, Any]:
    values: list[float] = []
    positive = 0
    for horizon in horizons:
        for fee in fees_bps:
            records = label_breakout_transition_outcomes(frame, ohlcv, horizon_bars=int(horizon), fee_bps=float(fee))
            for row in records:
                if row.get("outcome_label") != "labeled":
                    continue
                value = _float(row.get("directional_net_return"))
                values.append(value)
                positive += int(bool(row.get("directional_positive")))
    return {
        "labeled_count": len(values),
        "avg_directional_net_return": sum(values) / len(values) if values else None,
        "worst_directional_net_return": min(values) if values else None,
        "positive_rate": float(positive) / float(len(values)) if values else None,
    }


def _best_state(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return dict(sorted(rows, key=lambda row: _float(row.get("avg_directional_net_return")), reverse=True)[0])


def _recommendation(rows: Sequence[Mapping[str, Any]]) -> str:
    by_state = {str(row.get("micro_state")): row for row in rows}
    breakout = by_state.get(MICRO_STATE_BREAKOUT_SETUP, {})
    compression = by_state.get(MICRO_STATE_COMPRESSION_OBSERVE, {})
    if _float(breakout.get("avg_directional_net_return")) > _float(compression.get("avg_directional_net_return")):
        return "split_state_supported_but_runtime_disabled"
    return "split_state_diagnostic_only"


def _variant_row(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = dict(report.get("summary", {}))
    micro_report = dict(report.get("micro_state_report", {}))
    states = {str(row.get("micro_state")): dict(row) for row in micro_report.get("micro_states", [])}
    breakout = states.get(MICRO_STATE_BREAKOUT_SETUP, {})
    compression = states.get(MICRO_STATE_COMPRESSION_OBSERVE, {})
    return {
        "asset": summary.get("asset"),
        "timeframe": summary.get("timeframe"),
        "active_count": summary.get("active_count"),
        "research_candidate_count": summary.get("research_candidate_count"),
        "observation_only_count": summary.get("observation_only_count"),
        "runtime_enabled_count": summary.get("runtime_enabled_count"),
        "breakout_setup_active": breakout.get("active_count", 0),
        "breakout_setup_avg_return": breakout.get("avg_directional_net_return"),
        "breakout_setup_worst_return": breakout.get("worst_directional_net_return"),
        "compression_active": compression.get("active_count", 0),
        "compression_avg_return": compression.get("avg_directional_net_return"),
        "compression_worst_return": compression.get("worst_directional_net_return"),
        "recommendation": summary.get("recommendation"),
    }


def _render_matrix(report: Mapping[str, Any]) -> str:
    s = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7V Transition Micro-State Matrix",
        "",
        f"- Variants: {s.get('variant_count', 0)}",
        f"- Breakout-better count: {s.get('breakout_better_count', 0)}",
        f"- Runtime-enabled count: {s.get('runtime_enabled_count', 0)}",
        f"- Recommendation: {s.get('recommendation')}",
        "",
        "| Asset | Active | Research | Observe | Breakout avg | Compression avg | Breakout worst | Compression worst |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report.get("variants", []):
        lines.append(
            "| {asset} | {active} | {research} | {observe} | {bavg} | {cavg} | {bworst} | {cworst} |".format(
                asset=row.get("asset"),
                active=row.get("active_count"),
                research=row.get("research_candidate_count"),
                observe=row.get("observation_only_count"),
                bavg=row.get("breakout_setup_avg_return"),
                cavg=row.get("compression_avg_return"),
                bworst=row.get("breakout_setup_worst_return"),
                cworst=row.get("compression_worst_return"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _render_single(report: Mapping[str, Any]) -> str:
    s = dict(report.get("summary", {}))
    return "\n".join(["# RegimeV2 Phase 7V Transition Micro-State Report", "", f"- Asset/timeframe: {s.get('asset')}|{s.get('timeframe')}", f"- Active candidates: {s.get('active_count')}", f"- Research candidates: {s.get('research_candidate_count')}", f"- Observation-only: {s.get('observation_only_count')}", f"- Runtime-enabled: {s.get('runtime_enabled_count')}", f"- Recommendation: {s.get('recommendation')}", ""])


def _rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for idx, row in frame.iterrows():
        rows.append({"timestamp": str(idx), "micro_state": row.get("breakout_transition_micro_state"), "direction": row.get("breakout_transition_direction"), "phase": row.get("ft_context_gate_market_phase"), "score": row.get("breakout_transition_score"), "runtime_enabled": row.get("breakout_transition_micro_runtime_enabled")})
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
    "MICRO_STATE_BREAKOUT_SETUP",
    "MICRO_STATE_COMPRESSION_OBSERVE",
    "MICRO_STATE_NONE",
    "build_transition_micro_state_frame",
    "build_transition_micro_state_matrix_report",
    "build_transition_micro_state_report",
    "build_transition_micro_state_retest_report",
    "render_transition_micro_state_markdown",
]
