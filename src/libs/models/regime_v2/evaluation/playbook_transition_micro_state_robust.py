"""Phase 7W rolling robustness for transition micro-states."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from libs.models.regime_v2.evaluation.playbook_transition_micro_state import (
    MICRO_STATE_BREAKOUT_SETUP,
    MICRO_STATE_COMPRESSION_OBSERVE,
    build_transition_micro_state_frame,
)
from libs.models.regime_v2.evaluation.playbook_transition_setup import build_setup_transition_candidate_frame
from libs.models.regime_v2.evaluation.playbook_transition_state import label_breakout_transition_outcomes

_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES = (2.0, 5.0, 10.0)


def build_micro_state_window_specs(
    row_count: int,
    *,
    window_size: int = 360,
    step_size: int = 180,
    include_full: bool = True,
) -> list[dict[str, Any]]:
    """Build deterministic full/rolling windows over a frame length."""
    specs: list[dict[str, Any]] = []
    total = int(row_count)
    if total <= 0:
        return specs
    if include_full:
        specs.append({"window_id": "full", "start": 0, "end": total, "row_count": total, "is_full": True})
    size = max(1, int(window_size))
    step = max(1, int(step_size))
    start = 0
    window_idx = 1
    while start + size <= total:
        end = start + size
        specs.append({"window_id": f"w{window_idx}_{start}_{end}", "start": start, "end": end, "row_count": size, "is_full": False})
        start += step
        window_idx += 1
    if specs and specs[-1]["end"] != total and total > size:
        start = max(0, total - size)
        existing = {(item["start"], item["end"]) for item in specs}
        if (start, total) not in existing:
            specs.append({"window_id": f"w{window_idx}_{start}_{total}", "start": start, "end": total, "row_count": total - start, "is_full": False})
    return specs


def build_transition_micro_state_robust_report(
    micro_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    window_size: int = 360,
    step_size: int = 180,
    min_state_active: int = 6,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Stress-test micro-state separation over full and rolling windows."""
    frame = micro_df.copy()
    windows = []
    for spec in build_micro_state_window_specs(len(frame), window_size=int(window_size), step_size=int(step_size), include_full=True):
        window_frame = frame.iloc[int(spec["start"]): int(spec["end"])]
        windows.append(_window_summary(spec, window_frame, ohlcv, min_state_active, horizons, fees_bps))
    supported = [row for row in windows if row.get("support_ok")]
    supported_better = [row for row in supported if row.get("breakout_better")]
    return {
        "phase": "phase_7w_transition_micro_state_robust_report",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "window_count": len(windows),
            "supported_window_count": len(supported),
            "breakout_better_count": sum(1 for row in windows if row.get("breakout_better")),
            "supported_breakout_better_count": len(supported_better),
            "support_ready": len(supported) > 0 and len(supported_better) == len(supported),
            "runtime_enabled_count": int(frame.get("breakout_transition_micro_runtime_enabled", pd.Series(dtype=bool)).sum()),
            "worst_breakout_return": _min_value(row.get("breakout_setup_worst_return") for row in windows),
            "worst_compression_return": _min_value(row.get("compression_worst_return") for row in windows),
            "recommendation": _recommendation(windows, supported),
            "config": dict(config or {}),
        },
        "windows": windows,
    }


def build_transition_micro_state_robust_retest_report(
    analysis_df: pd.DataFrame,
    context_df: pd.DataFrame,
    state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    asset: str | None = None,
    timeframe: str | None = None,
    window_size: int = 360,
    step_size: int = 180,
    min_state_active: int = 6,
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
    """Build candidates, micro-states, then run rolling robustness."""
    config = {
        "lookback_bars": int(lookback_bars),
        "min_candidate_score": float(min_candidate_score),
        "min_context_score": float(min_context_score),
        "max_risk_score": float(max_risk_score),
        "max_conflict_count": int(max_conflict_count),
        "min_wick_score": float(min_wick_score),
        "min_attempt_score": float(min_attempt_score),
        "window_size": int(window_size),
        "step_size": int(step_size),
        "min_state_active": int(min_state_active),
    }
    candidates = build_setup_transition_candidate_frame(analysis_df, context_df, state_df, ohlcv, lookback_bars=int(lookback_bars), min_candidate_score=float(min_candidate_score), min_context_score=float(min_context_score), max_risk_score=float(max_risk_score), max_conflict_count=int(max_conflict_count), min_wick_score=float(min_wick_score), min_attempt_score=float(min_attempt_score))
    micro = build_transition_micro_state_frame(candidates)
    report = build_transition_micro_state_robust_report(micro, ohlcv, asset=asset, timeframe=timeframe, window_size=int(window_size), step_size=int(step_size), min_state_active=int(min_state_active), horizons=tuple(int(h) for h in horizons), fees_bps=tuple(float(f) for f in fees_bps), config=config)
    return {"phase": "phase_7w_transition_micro_state_robust_retest", "summary": report["summary"], "robust_report": report}


def build_transition_micro_state_robust_matrix_report(reports: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Combine 7W reports across assets."""
    rows = [_variant_row(report) for report in reports]
    supported_total = sum(int(row.get("supported_window_count") or 0) for row in rows)
    supported_better = sum(int(row.get("supported_breakout_better_count") or 0) for row in rows)
    return {
        "phase": "phase_7w_transition_micro_state_robust_matrix",
        "summary": {
            "variant_count": len(rows),
            "assets": sorted({str(row.get("asset")) for row in rows}),
            "supported_window_count": supported_total,
            "supported_breakout_better_count": supported_better,
            "support_ready_asset_count": sum(1 for row in rows if row.get("support_ready")),
            "runtime_enabled_count": sum(int(row.get("runtime_enabled_count") or 0) for row in rows),
            "recommendation": "keep_diagnostic_not_robust" if supported_better > 0 else "micro_state_split_not_robust",
            "best_variant": _best_variant(rows),
        },
        "variants": rows,
    }


def render_transition_micro_state_robust_markdown(report: Mapping[str, Any]) -> str:
    """Render Phase 7W Markdown."""
    if report.get("phase") == "phase_7w_transition_micro_state_robust_matrix":
        return _render_matrix(report)
    summary = dict(report.get("summary", {}))
    return "\n".join(["# RegimeV2 Phase 7W Micro-State Robustness", "", f"- Asset/timeframe: {summary.get('asset')}|{summary.get('timeframe')}", f"- Supported windows: {summary.get('supported_window_count')}/{summary.get('window_count')}", f"- Supported breakout-better windows: {summary.get('supported_breakout_better_count')}", f"- Runtime-enabled: {summary.get('runtime_enabled_count')}", f"- Recommendation: {summary.get('recommendation')}", ""])


def _window_summary(spec: Mapping[str, Any], frame: pd.DataFrame, ohlcv: pd.DataFrame, min_state_active: int, horizons: Sequence[int], fees_bps: Sequence[float]) -> dict[str, Any]:
    breakout = frame[frame.get("breakout_transition_micro_state", "") == MICRO_STATE_BREAKOUT_SETUP]
    compression = frame[frame.get("breakout_transition_micro_state", "") == MICRO_STATE_COMPRESSION_OBSERVE]
    b = _state_stats(breakout, ohlcv, horizons, fees_bps)
    c = _state_stats(compression, ohlcv, horizons, fees_bps)
    support_ok = int(b["active_count"]) >= int(min_state_active) and int(c["active_count"]) >= int(min_state_active)
    b_avg = b.get("avg_directional_net_return")
    c_avg = c.get("avg_directional_net_return")
    breakout_better = b_avg is not None and c_avg is not None and float(b_avg) > float(c_avg)
    return {
        **dict(spec),
        "breakout_setup_active": b["active_count"],
        "breakout_setup_avg_return": b_avg,
        "breakout_setup_worst_return": b.get("worst_directional_net_return"),
        "compression_active": c["active_count"],
        "compression_avg_return": c_avg,
        "compression_worst_return": c.get("worst_directional_net_return"),
        "support_ok": bool(support_ok),
        "breakout_better": bool(breakout_better),
    }


def _state_stats(frame: pd.DataFrame, ohlcv: pd.DataFrame, horizons: Sequence[int], fees_bps: Sequence[float]) -> dict[str, Any]:
    values: list[float] = []
    for horizon in horizons:
        for fee in fees_bps:
            records = label_breakout_transition_outcomes(frame, ohlcv, horizon_bars=int(horizon), fee_bps=float(fee))
            values.extend(float(row["directional_net_return"]) for row in records if row.get("outcome_label") == "labeled")
    return {
        "active_count": int(len(frame)),
        "labeled_count": len(values),
        "avg_directional_net_return": sum(values) / len(values) if values else None,
        "worst_directional_net_return": min(values) if values else None,
    }


def _variant_row(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = dict(report.get("summary", {}))
    return {
        "asset": summary.get("asset"),
        "timeframe": summary.get("timeframe"),
        "window_count": summary.get("window_count"),
        "supported_window_count": summary.get("supported_window_count"),
        "breakout_better_count": summary.get("breakout_better_count"),
        "supported_breakout_better_count": summary.get("supported_breakout_better_count"),
        "support_ready": summary.get("support_ready"),
        "runtime_enabled_count": summary.get("runtime_enabled_count"),
        "worst_breakout_return": summary.get("worst_breakout_return"),
        "worst_compression_return": summary.get("worst_compression_return"),
        "recommendation": summary.get("recommendation"),
    }


def _recommendation(windows: Sequence[Mapping[str, Any]], supported: Sequence[Mapping[str, Any]]) -> str:
    if not supported:
        return "insufficient_window_support"
    if all(row.get("breakout_better") for row in supported):
        return "micro_state_split_window_supported"
    return "micro_state_split_window_mixed"


def _best_variant(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return dict(sorted(rows, key=lambda row: (int(row.get("supported_breakout_better_count") or 0), int(row.get("supported_window_count") or 0)), reverse=True)[0])


def _min_value(values) -> float | None:
    nums = [float(value) for value in values if value is not None]
    return min(nums) if nums else None


def _render_matrix(report: Mapping[str, Any]) -> str:
    s = dict(report.get("summary", {}))
    lines = ["# RegimeV2 Phase 7W Micro-State Robustness Matrix", "", f"- Assets: {s.get('assets')}", f"- Supported windows: {s.get('supported_window_count')}", f"- Supported breakout-better windows: {s.get('supported_breakout_better_count')}", f"- Runtime-enabled: {s.get('runtime_enabled_count')}", f"- Recommendation: {s.get('recommendation')}", "", "| Asset | Supported | Supported better | Ready | Worst breakout | Worst compression |", "|---|---:|---:|---|---:|---:|"]
    for row in report.get("variants", []):
        lines.append(f"| {row.get('asset')} | {row.get('supported_window_count')} | {row.get('supported_breakout_better_count')} | {row.get('support_ready')} | {row.get('worst_breakout_return')} | {row.get('worst_compression_return')} |")
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "build_micro_state_window_specs",
    "build_transition_micro_state_robust_matrix_report",
    "build_transition_micro_state_robust_report",
    "build_transition_micro_state_robust_retest_report",
    "render_transition_micro_state_robust_markdown",
]
