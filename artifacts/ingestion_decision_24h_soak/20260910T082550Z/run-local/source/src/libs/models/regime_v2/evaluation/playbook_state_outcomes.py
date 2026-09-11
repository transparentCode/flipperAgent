"""Offline outcome validation for Phase 7B playbook states."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES = (2.0, 5.0, 10.0)
_DEFAULT_SEGMENTS = (
    "all",
    "risk",
    "wait",
    "executable",
    "no_trade_risk",
    "wait_compression",
    "breakout_setup",
    "trend_continuation",
    "breakout_confirmation",
    "range_reversion",
    "scalp_only",
    "observe_only",
)


def build_playbook_state_outcome_matrix(
    state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES,
    large_move_bps: float = 20.0,
) -> dict[str, Any]:
    """Build a horizon/fee outcome matrix for 7B state-machine rows."""
    cells = []
    for horizon in horizons:
        for fee in fees_bps:
            labeled = label_playbook_state_outcomes(
                state_df,
                ohlcv,
                horizon_bars=int(horizon),
                fee_bps=float(fee),
                large_move_bps=float(large_move_bps),
            )
            cells.append(_cell(labeled, horizon_bars=int(horizon), fee_bps=float(fee)))
    return {
        "phase": "phase_7c_playbook_state_outcome_matrix",
        "summary": _summary(cells),
        "cells": cells,
    }


def label_playbook_state_outcomes(
    state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    horizon_bars: int,
    fee_bps: float = 0.0,
    large_move_bps: float = 20.0,
) -> list[dict[str, Any]]:
    """Attach forward-return outcomes to each playbook-state row."""
    prepared = _prepare_ohlcv(ohlcv)
    fee = float(fee_bps) / 10000.0
    large_threshold = float(large_move_bps) / 10000.0
    records: list[dict[str, Any]] = []
    for ts, row in state_df.iterrows():
        if ts not in prepared.index:
            records.append(_unlabeled(ts, row, "timestamp_not_in_ohlcv", horizon_bars, fee_bps))
            continue
        loc = prepared.index.get_loc(ts)
        if isinstance(loc, slice) or isinstance(loc, np.ndarray):
            records.append(_unlabeled(ts, row, "non_unique_timestamp", horizon_bars, fee_bps))
            continue
        future_loc = int(loc) + int(horizon_bars)
        if future_loc >= len(prepared):
            records.append(_unlabeled(ts, row, "missing_future_bar", horizon_bars, fee_bps))
            continue
        close_now = float(prepared["close"].iloc[int(loc)])
        close_future = float(prepared["close"].iloc[future_loc])
        if close_now <= 0.0 or close_future <= 0.0:
            records.append(_unlabeled(ts, row, "invalid_close", horizon_bars, fee_bps))
            continue
        forward = float(np.log(close_future / close_now))
        side = _implied_side(row)
        directional = side * forward - fee if side != 0 else None
        records.append(
            {
                **_base_record(ts, row, horizon_bars, fee_bps),
                "outcome_label": "labeled",
                "outcome_reason": "ok",
                "future_timestamp": str(prepared.index[future_loc]),
                "forward_log_return": forward,
                "abs_forward_log_return": abs(forward),
                "forward_return_positive": forward > 0.0,
                "forward_return_negative": forward < 0.0,
                "large_move": abs(forward) >= large_threshold,
                "implied_side": side,
                "directional_net_return": directional,
                "directional_positive": directional is not None and directional > 0.0,
            }
        )
    return records


def render_playbook_state_outcome_matrix_markdown(matrix: Mapping[str, Any]) -> str:
    """Render compact Markdown for a 7C state-outcome matrix."""
    summary = dict(matrix.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7C Playbook State Outcome Matrix",
        "",
        "## Summary",
        "",
        f"- Cells: {summary.get('cell_count', 0)}",
        f"- Horizons: {summary.get('horizons', [])}",
        f"- Fees bps: {summary.get('fees_bps', [])}",
        f"- Best executable cell: {summary.get('best_executable_cell')}",
        f"- Worst executable cell: {summary.get('worst_executable_cell')}",
        f"- Risk state worst positive-rate cell: {summary.get('risk_worst_positive_rate_cell')}",
        f"- Wait state highest large-move cell: {summary.get('wait_highest_large_move_cell')}",
        "",
        "## Cells",
        "",
        "| Horizon | Fee | Labeled | Risk avg | Wait abs | Exec avg | Exec pos | Scalp avg | Range avg |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cell in matrix.get("cells", []):
        seg = dict(cell.get("segments", {}))
        risk = dict(seg.get("risk", {}))
        wait = dict(seg.get("wait", {}))
        executable = dict(seg.get("executable", {}))
        scalp = dict(seg.get("scalp_only", {}))
        range_rev = dict(seg.get("range_reversion", {}))
        lines.append(
            "| {h} | {f} | {n} | {risk_avg} | {wait_abs} | {exec_avg} | {exec_pos} | {scalp_avg} | {range_avg} |".format(
                h=cell.get("horizon_bars"),
                f=cell.get("fee_bps"),
                n=cell.get("labeled_count"),
                risk_avg=risk.get("avg_forward_log_return"),
                wait_abs=wait.get("avg_abs_forward_log_return"),
                exec_avg=executable.get("avg_forward_log_return"),
                exec_pos=executable.get("positive_return_rate"),
                scalp_avg=scalp.get("avg_forward_log_return"),
                range_avg=range_rev.get("avg_forward_log_return"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _cell(records: list[dict[str, Any]], *, horizon_bars: int, fee_bps: float) -> dict[str, Any]:
    labeled = [row for row in records if row.get("outcome_label") == "labeled"]
    unlabeled = [row for row in records if row.get("outcome_label") != "labeled"]
    return {
        "horizon_bars": int(horizon_bars),
        "fee_bps": float(fee_bps),
        "total_records": len(records),
        "labeled_count": len(labeled),
        "unlabeled_count": len(unlabeled),
        "unlabeled_reasons": dict(sorted(Counter(str(row.get("outcome_reason")) for row in unlabeled).items())),
        "state_distribution": dict(sorted(Counter(str(row.get("playbook_state")) for row in labeled).items())),
        "state_group_distribution": dict(sorted(Counter(str(row.get("state_group")) for row in labeled).items())),
        "segments": {segment: _segment_metrics(_segment(labeled, segment)) for segment in _DEFAULT_SEGMENTS},
    }


def _summary(cells: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cell_count": len(cells),
        "horizons": sorted({int(cell.get("horizon_bars")) for cell in cells}),
        "fees_bps": sorted({float(cell.get("fee_bps")) for cell in cells}),
        "best_executable_cell": _best_segment_cell(cells, "executable", "avg_forward_log_return"),
        "worst_executable_cell": _worst_segment_cell(cells, "executable", "avg_forward_log_return"),
        "risk_worst_positive_rate_cell": _best_segment_cell(cells, "risk", "positive_return_rate"),
        "wait_highest_large_move_cell": _best_segment_cell(cells, "wait", "large_move_rate"),
        "scalp_best_cell": _best_segment_cell(cells, "scalp_only", "avg_forward_log_return"),
        "range_reversion_best_cell": _best_segment_cell(cells, "range_reversion", "avg_forward_log_return"),
    }


def _segment(records: list[dict[str, Any]], segment: str) -> list[dict[str, Any]]:
    if segment == "all":
        return records
    if segment in {"risk", "wait", "executable"}:
        return [row for row in records if row.get("state_group") == segment]
    state = {
        "no_trade_risk": "NO_TRADE_RISK",
        "wait_compression": "WAIT_COMPRESSION",
        "breakout_setup": "BREAKOUT_SETUP",
        "trend_continuation": "TREND_CONTINUATION",
        "breakout_confirmation": "BREAKOUT_CONFIRMATION",
        "range_reversion": "RANGE_REVERSION",
        "scalp_only": "SCALP_ONLY",
        "observe_only": "OBSERVE_ONLY",
    }.get(segment)
    return [row for row in records if row.get("playbook_state") == state]


def _segment_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    directional = [row for row in records if row.get("directional_net_return") is not None]
    return {
        "count": len(records),
        "avg_forward_log_return": _mean(row.get("forward_log_return") for row in records),
        "avg_abs_forward_log_return": _mean(row.get("abs_forward_log_return") for row in records),
        "positive_return_rate": _rate(sum(1 for row in records if bool(row.get("forward_return_positive"))), len(records)),
        "negative_return_rate": _rate(sum(1 for row in records if bool(row.get("forward_return_negative"))), len(records)),
        "large_move_rate": _rate(sum(1 for row in records if bool(row.get("large_move"))), len(records)),
        "directional_count": len(directional),
        "avg_directional_net_return": _mean(row.get("directional_net_return") for row in directional),
        "directional_positive_rate": _rate(sum(1 for row in directional if bool(row.get("directional_positive"))), len(directional)),
        "state_distribution": dict(sorted(Counter(str(row.get("playbook_state")) for row in records).items())),
    }


def _best_segment_cell(cells: list[dict[str, Any]], segment: str, metric: str) -> dict[str, Any] | None:
    return _ranked_segment_cell(cells, segment, metric, reverse=True)


def _worst_segment_cell(cells: list[dict[str, Any]], segment: str, metric: str) -> dict[str, Any] | None:
    return _ranked_segment_cell(cells, segment, metric, reverse=False)


def _ranked_segment_cell(cells: list[dict[str, Any]], segment: str, metric: str, *, reverse: bool) -> dict[str, Any] | None:
    rows = []
    for cell in cells:
        metrics = dict(dict(cell.get("segments", {})).get(segment, {}))
        value = metrics.get(metric)
        if value is None:
            continue
        rows.append(
            {
                "horizon_bars": cell.get("horizon_bars"),
                "fee_bps": cell.get("fee_bps"),
                "segment": segment,
                "metric": metric,
                "value": value,
                "count": metrics.get("count"),
            }
        )
    if not rows:
        return None
    return sorted(rows, key=lambda row: float(row.get("value") or 0.0), reverse=reverse)[0]


def _prepare_ohlcv(ohlcv: pd.DataFrame) -> pd.DataFrame:
    frame = ohlcv.copy()
    if "timestamp" in frame.columns:
        frame = frame.set_index("timestamp")
    frame = frame.sort_index()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame


def _base_record(ts: Any, row: Mapping[str, Any], horizon_bars: int, fee_bps: float) -> dict[str, Any]:
    return {
        "timestamp": str(ts),
        "horizon_bars": int(horizon_bars),
        "fee_bps": float(fee_bps),
        "playbook_state": row.get("playbook_state"),
        "state_group": row.get("playbook_state_group"),
        "state_reason": row.get("playbook_state_reason"),
        "dominant_playbook": row.get("playbook_state_dominant_playbook"),
        "market_phase": row.get("playbook_state_market_phase"),
        "horizon_bias": row.get("playbook_state_horizon_bias"),
        "conflict_tags": row.get("playbook_state_conflict_tags"),
    }


def _unlabeled(ts: Any, row: Mapping[str, Any], reason: str, horizon_bars: int, fee_bps: float) -> dict[str, Any]:
    return {
        **_base_record(ts, row, horizon_bars, fee_bps),
        "outcome_label": "unlabeled",
        "outcome_reason": reason,
    }


def _implied_side(row: Mapping[str, Any]) -> int:
    phase = str(row.get("playbook_state_market_phase") or "")
    state = str(row.get("playbook_state") or "")
    if state != "TREND_CONTINUATION":
        return 0
    if phase == "bull_trend":
        return 1
    if phase == "bear_trend":
        return -1
    return 0


def _mean(values) -> float | None:
    nums = []
    for value in values:
        try:
            if value is not None:
                nums.append(float(value))
        except (TypeError, ValueError):
            continue
    return sum(nums) / len(nums) if nums else None


def _rate(numerator: int, denominator: int) -> float | None:
    return float(numerator) / float(denominator) if denominator > 0 else None


__all__ = [
    "build_playbook_state_outcome_matrix",
    "label_playbook_state_outcomes",
    "render_playbook_state_outcome_matrix_markdown",
]
