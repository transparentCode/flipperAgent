"""Offline transition validation for RegimeV2 Phase 7D playbook states."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

_DEFAULT_TRANSITION_BARS = (1, 3, 6)
_DEFAULT_OUTCOME_HORIZONS = (3, 6, 12, 24)


def build_playbook_state_transition_matrix(
    state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    transition_bars: Sequence[int] = _DEFAULT_TRANSITION_BARS,
    outcome_horizons: Sequence[int] = _DEFAULT_OUTCOME_HORIZONS,
    large_move_bps: float = 20.0,
) -> dict[str, Any]:
    """Build a transition/outcome validation matrix for 7B states."""
    cells = []
    for step in transition_bars:
        for horizon in outcome_horizons:
            labeled = label_playbook_state_transitions(
                state_df,
                ohlcv,
                transition_bars=int(step),
                outcome_horizon_bars=int(horizon),
                large_move_bps=float(large_move_bps),
            )
            cells.append(_cell(labeled, transition_bars=int(step), outcome_horizon_bars=int(horizon)))
    return {
        "phase": "phase_7d_playbook_state_transition_matrix",
        "summary": _summary(cells),
        "cells": cells,
    }


def label_playbook_state_transitions(
    state_df: pd.DataFrame,
    ohlcv: pd.DataFrame,
    *,
    transition_bars: int,
    outcome_horizon_bars: int,
    large_move_bps: float = 20.0,
) -> list[dict[str, Any]]:
    """Attach future state and forward-return outcomes to each state row."""
    states = state_df.sort_index()
    prepared = _prepare_ohlcv(ohlcv)
    large_threshold = float(large_move_bps) / 10000.0
    records: list[dict[str, Any]] = []
    for pos, (ts, row) in enumerate(states.iterrows()):
        transition_pos = pos + int(transition_bars)
        outcome_pos = pos + int(outcome_horizon_bars)
        if transition_pos >= len(states):
            records.append(_unlabeled(ts, row, "missing_transition_state", transition_bars, outcome_horizon_bars))
            continue
        if outcome_pos >= len(states):
            records.append(_unlabeled(ts, row, "missing_outcome_state", transition_bars, outcome_horizon_bars))
            continue
        if ts not in prepared.index:
            records.append(_unlabeled(ts, row, "timestamp_not_in_ohlcv", transition_bars, outcome_horizon_bars))
            continue
        loc = prepared.index.get_loc(ts)
        if isinstance(loc, slice) or isinstance(loc, np.ndarray):
            records.append(_unlabeled(ts, row, "non_unique_timestamp", transition_bars, outcome_horizon_bars))
            continue
        future_loc = int(loc) + int(outcome_horizon_bars)
        if future_loc >= len(prepared):
            records.append(_unlabeled(ts, row, "missing_future_bar", transition_bars, outcome_horizon_bars))
            continue
        next_ts, next_row = states.iloc[transition_pos].name, states.iloc[transition_pos]
        close_now = float(prepared["close"].iloc[int(loc)])
        close_future = float(prepared["close"].iloc[future_loc])
        if close_now <= 0.0 or close_future <= 0.0:
            records.append(_unlabeled(ts, row, "invalid_close", transition_bars, outcome_horizon_bars))
            continue
        forward = float(np.log(close_future / close_now))
        current_state = _text(row.get("playbook_state"))
        next_state = _text(next_row.get("playbook_state"))
        transition = f"{current_state}->{next_state}"
        intent = _transition_intent(current_state, next_state)
        records.append(
            {
                **_base_record(ts, row, transition_bars, outcome_horizon_bars),
                "outcome_label": "labeled",
                "outcome_reason": "ok",
                "next_timestamp": str(next_ts),
                "next_state": next_state,
                "next_state_group": _text(next_row.get("playbook_state_group")),
                "transition": transition,
                "transition_intent": intent,
                "state_changed": current_state != next_state,
                "future_timestamp": str(prepared.index[future_loc]),
                "forward_log_return": forward,
                "abs_forward_log_return": abs(forward),
                "forward_return_positive": forward > 0.0,
                "forward_return_negative": forward < 0.0,
                "large_move": abs(forward) >= large_threshold,
            }
        )
    return records


def render_playbook_state_transition_matrix_markdown(matrix: Mapping[str, Any]) -> str:
    """Render compact Markdown for transition validation."""
    summary = dict(matrix.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 7D Playbook State Transition Matrix",
        "",
        "## Summary",
        "",
        f"- Cells: {summary.get('cell_count', 0)}",
        f"- Transition bars: {summary.get('transition_bars', [])}",
        f"- Outcome horizons: {summary.get('outcome_horizons', [])}",
        f"- Best transition intent cell: {summary.get('best_intent_cell')}",
        f"- Highest wait large-move cell: {summary.get('wait_large_move_cell')}",
        f"- Worst scalp exit cell: {summary.get('worst_scalp_exit_cell')}",
        f"- Best risk recovery cell: {summary.get('best_risk_recovery_cell')}",
        "",
        "## Cells",
        "",
        "| Step | Horizon | Labeled | Changed | Wait large move | Risk recovery avg | Scalp exit avg | Setup avg |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cell in matrix.get("cells", []):
        segments = dict(cell.get("segments", {}))
        wait = dict(segments.get("wait_to_any", {}))
        recovery = dict(segments.get("risk_recovery", {}))
        scalp_exit = dict(segments.get("scalp_exit", {}))
        setup = dict(segments.get("setup_to_any", {}))
        lines.append(
            "| {step} | {horizon} | {n} | {changed} | {wait_move} | {recovery_avg} | {scalp_avg} | {setup_avg} |".format(
                step=cell.get("transition_bars"),
                horizon=cell.get("outcome_horizon_bars"),
                n=cell.get("labeled_count"),
                changed=cell.get("state_changed_rate"),
                wait_move=wait.get("large_move_rate"),
                recovery_avg=recovery.get("avg_forward_log_return"),
                scalp_avg=scalp_exit.get("avg_forward_log_return"),
                setup_avg=setup.get("avg_forward_log_return"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _cell(records: list[dict[str, Any]], *, transition_bars: int, outcome_horizon_bars: int) -> dict[str, Any]:
    labeled = [row for row in records if row.get("outcome_label") == "labeled"]
    unlabeled = [row for row in records if row.get("outcome_label") != "labeled"]
    return {
        "transition_bars": int(transition_bars),
        "outcome_horizon_bars": int(outcome_horizon_bars),
        "total_records": len(records),
        "labeled_count": len(labeled),
        "unlabeled_count": len(unlabeled),
        "unlabeled_reasons": dict(sorted(Counter(str(row.get("outcome_reason")) for row in unlabeled).items())),
        "state_changed_rate": _rate(sum(1 for row in labeled if bool(row.get("state_changed"))), len(labeled)),
        "transition_distribution": dict(Counter(str(row.get("transition")) for row in labeled).most_common(20)),
        "transition_intent_distribution": dict(Counter(str(row.get("transition_intent")) for row in labeled).most_common()),
        "segments": {name: _segment_metrics(_segment(labeled, name)) for name in _segment_names()},
    }


def _summary(cells: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cell_count": len(cells),
        "transition_bars": sorted({int(cell.get("transition_bars")) for cell in cells}),
        "outcome_horizons": sorted({int(cell.get("outcome_horizon_bars")) for cell in cells}),
        "best_intent_cell": _best_segment_cell(cells, "intentful", "avg_forward_log_return"),
        "wait_large_move_cell": _best_segment_cell(cells, "wait_to_any", "large_move_rate"),
        "worst_scalp_exit_cell": _worst_segment_cell(cells, "scalp_exit", "avg_forward_log_return"),
        "best_risk_recovery_cell": _best_segment_cell(cells, "risk_recovery", "avg_forward_log_return"),
        "best_setup_cell": _best_segment_cell(cells, "setup_to_any", "avg_forward_log_return"),
    }


def _segment_names() -> tuple[str, ...]:
    return (
        "all",
        "changed",
        "unchanged",
        "intentful",
        "wait_to_any",
        "wait_to_setup",
        "setup_to_any",
        "setup_to_confirmation",
        "risk_to_any",
        "risk_recovery",
        "scalp_to_any",
        "scalp_exit",
        "range_to_any",
    )


def _segment(records: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    if name == "all":
        return records
    if name == "changed":
        return [row for row in records if bool(row.get("state_changed"))]
    if name == "unchanged":
        return [row for row in records if not bool(row.get("state_changed"))]
    if name == "intentful":
        return [row for row in records if row.get("transition_intent") != "other"]
    if name == "wait_to_any":
        return [row for row in records if row.get("playbook_state") in {"WAIT_COMPRESSION", "BREAKOUT_SETUP", "OBSERVE_ONLY"}]
    if name == "wait_to_setup":
        return [row for row in records if row.get("transition_intent") == "compression_to_setup"]
    if name == "setup_to_any":
        return [row for row in records if row.get("playbook_state") == "BREAKOUT_SETUP"]
    if name == "setup_to_confirmation":
        return [row for row in records if row.get("transition_intent") == "setup_to_confirmation"]
    if name == "risk_to_any":
        return [row for row in records if row.get("playbook_state") == "NO_TRADE_RISK"]
    if name == "risk_recovery":
        return [row for row in records if row.get("transition_intent") == "risk_recovery"]
    if name == "scalp_to_any":
        return [row for row in records if row.get("playbook_state") == "SCALP_ONLY"]
    if name == "scalp_exit":
        return [row for row in records if row.get("transition_intent") == "scalp_exit"]
    if name == "range_to_any":
        return [row for row in records if row.get("playbook_state") == "RANGE_REVERSION"]
    return []


def _segment_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(records),
        "avg_forward_log_return": _mean(row.get("forward_log_return") for row in records),
        "avg_abs_forward_log_return": _mean(row.get("abs_forward_log_return") for row in records),
        "positive_return_rate": _rate(sum(1 for row in records if bool(row.get("forward_return_positive"))), len(records)),
        "negative_return_rate": _rate(sum(1 for row in records if bool(row.get("forward_return_negative"))), len(records)),
        "large_move_rate": _rate(sum(1 for row in records if bool(row.get("large_move"))), len(records)),
        "changed_rate": _rate(sum(1 for row in records if bool(row.get("state_changed"))), len(records)),
        "transition_distribution": dict(Counter(str(row.get("transition")) for row in records).most_common(12)),
        "intent_distribution": dict(Counter(str(row.get("transition_intent")) for row in records).most_common()),
    }


def _transition_intent(current_state: str, next_state: str) -> str:
    if current_state == "WAIT_COMPRESSION" and next_state == "BREAKOUT_SETUP":
        return "compression_to_setup"
    if current_state == "BREAKOUT_SETUP" and next_state == "BREAKOUT_CONFIRMATION":
        return "setup_to_confirmation"
    if current_state == "NO_TRADE_RISK" and next_state != "NO_TRADE_RISK":
        return "risk_recovery"
    if current_state == "SCALP_ONLY" and next_state != "SCALP_ONLY":
        return "scalp_exit"
    if current_state == "RANGE_REVERSION" and next_state in {"NO_TRADE_RISK", "BREAKOUT_SETUP", "WAIT_COMPRESSION"}:
        return "range_invalidated"
    return "other"


def _base_record(ts: Any, row: Mapping[str, Any], transition_bars: int, outcome_horizon_bars: int) -> dict[str, Any]:
    return {
        "timestamp": str(ts),
        "transition_bars": int(transition_bars),
        "outcome_horizon_bars": int(outcome_horizon_bars),
        "playbook_state": row.get("playbook_state"),
        "state_group": row.get("playbook_state_group"),
        "state_reason": row.get("playbook_state_reason"),
        "dominant_playbook": row.get("playbook_state_dominant_playbook"),
        "market_phase": row.get("playbook_state_market_phase"),
        "horizon_bias": row.get("playbook_state_horizon_bias"),
        "conflict_tags": row.get("playbook_state_conflict_tags"),
    }


def _unlabeled(ts: Any, row: Mapping[str, Any], reason: str, transition_bars: int, outcome_horizon_bars: int) -> dict[str, Any]:
    return {
        **_base_record(ts, row, transition_bars, outcome_horizon_bars),
        "outcome_label": "unlabeled",
        "outcome_reason": reason,
    }


def _prepare_ohlcv(ohlcv: pd.DataFrame) -> pd.DataFrame:
    frame = ohlcv.copy()
    if "timestamp" in frame.columns:
        frame = frame.set_index("timestamp")
    frame = frame.sort_index()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame


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
                "transition_bars": cell.get("transition_bars"),
                "outcome_horizon_bars": cell.get("outcome_horizon_bars"),
                "segment": segment,
                "metric": metric,
                "value": value,
                "count": metrics.get("count"),
            }
        )
    if not rows:
        return None
    return sorted(rows, key=lambda row: float(row.get("value") or 0.0), reverse=reverse)[0]


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value)
    return default if text.lower() == "nan" else text


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
    "build_playbook_state_transition_matrix",
    "label_playbook_state_transitions",
    "render_playbook_state_transition_matrix_markdown",
]
