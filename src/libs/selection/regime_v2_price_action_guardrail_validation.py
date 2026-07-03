"""Offline rolling validation for PriceAction direction-aware guardrails.

Phase 6F found that PriceAction long removals were the strongest candidate.
This module validates that candidate across horizons, fee assumptions, assets,
and rolling windows. It does not change live selection behaviour.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from libs.selection.regime_v2_price_action_matrix import is_price_action_subset_removal
from libs.selection.regime_v2_shadow_outcomes import label_shadow_decision_outcomes

_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES_BPS = (2.0, 5.0, 10.0)
_DEFAULT_ROLLING_WINDOW = 30
_DEFAULT_MIN_WINDOW = 10


def is_price_action_direction_guardrail(record: Mapping[str, Any], *, direction: int = 1) -> bool:
    """Return True for PriceAction subset removals matching baseline direction."""
    if not is_price_action_subset_removal(record):
        return False
    try:
        return int(record.get("baseline_selected_direction")) == int(direction)
    except (TypeError, ValueError):
        return False


def build_price_action_guardrail_validation(
    records: Iterable[Mapping[str, Any]],
    ohlcv_by_pair: Mapping[tuple[str, str], pd.DataFrame],
    *,
    direction: int = 1,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES_BPS,
    rolling_window: int = _DEFAULT_ROLLING_WINDOW,
    min_window: int = _DEFAULT_MIN_WINDOW,
) -> dict[str, Any]:
    """Build a multi-horizon/fee rolling validation report for a guardrail."""
    raw_records = [dict(record) for record in records]
    candidate_records = [record for record in raw_records if is_price_action_direction_guardrail(record, direction=direction)]
    cells: list[dict[str, Any]] = []
    for horizon in horizons:
        for fee_bps in fees_bps:
            labeled = label_shadow_decision_outcomes(
                raw_records,
                ohlcv_by_pair,
                horizon_bars=int(horizon),
                fee_bps=float(fee_bps),
            )
            candidate = [record for record in labeled if is_price_action_direction_guardrail(record, direction=direction)]
            cells.append(
                _validation_cell(
                    candidate,
                    horizon_bars=int(horizon),
                    fee_bps=float(fee_bps),
                    rolling_window=int(rolling_window),
                    min_window=int(min_window),
                )
            )
    return {
        "phase": "phase_6g_price_action_direction_guardrail_validation",
        "summary": {
            "total_records": len(raw_records),
            "direction": int(direction),
            "candidate_count": len(candidate_records),
            "candidate_rate": _rate(len(candidate_records), len(raw_records)),
            "cell_count": len(cells),
            "horizons": sorted({cell["horizon_bars"] for cell in cells}),
            "fees_bps": sorted({cell["fee_bps"] for cell in cells}),
            "rolling_window": int(rolling_window),
            "min_window": int(min_window),
            "stable_positive_cell_count": sum(1 for cell in cells if _stable_positive(cell)),
            "rolling_stable_cell_count": sum(1 for cell in cells if _rolling_stable(cell)),
            "best_cell": _best_cell(cells),
            "worst_cell": _worst_cell(cells),
        },
        "cells": cells,
    }


def render_price_action_guardrail_validation_markdown(report: Mapping[str, Any]) -> str:
    """Render compact Markdown for the validation report."""
    summary = dict(report.get("summary", {}))
    cells = list(report.get("cells", []))
    lines = [
        "# RegimeV2 Phase 6G PriceAction Direction Guardrail Validation",
        "",
        "## Summary",
        "",
        f"- Total records: {summary.get('total_records', 0)}",
        f"- Direction: {summary.get('direction')}",
        f"- Candidate rows: {summary.get('candidate_count', 0)} ({summary.get('candidate_rate')})",
        f"- Cells: {summary.get('cell_count', 0)}",
        f"- Horizons: {summary.get('horizons', [])}",
        f"- Fees bps: {summary.get('fees_bps', [])}",
        f"- Rolling window: {summary.get('rolling_window')}",
        f"- Stable positive cells: {summary.get('stable_positive_cell_count', 0)}",
        f"- Rolling-stable cells: {summary.get('rolling_stable_cell_count', 0)}",
        f"- Best cell: {summary.get('best_cell')}",
        f"- Worst cell: {summary.get('worst_cell')}",
        "",
        "## Matrix",
        "",
        "| Horizon | Fee bps | Count | Avg lift | Bad rate | Positive rate | Min rolling lift | Rolling positive windows | Windows |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cell in cells:
        rolling = dict(cell.get("rolling", {}))
        lines.append(
            "| {horizon} | {fee} | {count} | {lift} | {bad_rate} | {positive} | {min_lift} | {positive_windows} | {windows} |".format(
                horizon=cell.get("horizon_bars"),
                fee=cell.get("fee_bps"),
                count=cell.get("count"),
                lift=cell.get("avg_shadow_minus_baseline"),
                bad_rate=cell.get("bad_rate"),
                positive=cell.get("positive_shadow_lift_rate"),
                min_lift=rolling.get("min_avg_shadow_minus_baseline"),
                positive_windows=rolling.get("positive_window_rate"),
                windows=rolling.get("window_count"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _validation_cell(
    records: list[dict[str, Any]],
    *,
    horizon_bars: int,
    fee_bps: float,
    rolling_window: int,
    min_window: int,
) -> dict[str, Any]:
    labeled = [record for record in records if record.get("outcome_label") != "unlabeled"]
    return {
        "horizon_bars": int(horizon_bars),
        "fee_bps": float(fee_bps),
        "count": len(labeled),
        "avg_baseline_net_return": _mean(record.get("baseline_net_return") for record in labeled),
        "avg_shadow_minus_baseline": _mean(record.get("shadow_minus_baseline") for record in labeled),
        "median_shadow_minus_baseline": _median(record.get("shadow_minus_baseline") for record in labeled),
        "bad_count": sum(1 for record in labeled if _is_bad_price_action(record)),
        "bad_rate": _rate(sum(1 for record in labeled if _is_bad_price_action(record)), len(labeled)),
        "positive_shadow_lift_rate": _positive_rate(record.get("shadow_minus_baseline") for record in labeled),
        "outcome_labels": dict(sorted(Counter(str(record.get("outcome_label")) for record in labeled).items())),
        "asset_timeframe": _asset_timeframe_metrics(labeled),
        "rolling": _rolling_metrics(labeled, rolling_window=rolling_window, min_window=min_window),
    }


def _asset_timeframe_metrics(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        key = f"{record.get('asset') or 'none'}|{record.get('timeframe') or 'none'}"
        grouped.setdefault(key, []).append(record)
    return {key: _basic_metrics(items) for key, items in sorted(grouped.items())}


def _rolling_metrics(records: list[dict[str, Any]], *, rolling_window: int, min_window: int) -> dict[str, Any]:
    ordered = sorted(records, key=lambda record: (float(record.get("timestamp") or 0.0), str(record.get("asset") or "")))
    windows: list[dict[str, Any]] = []
    if not ordered:
        return {
            "window_count": 0,
            "positive_window_count": 0,
            "positive_window_rate": None,
            "min_avg_shadow_minus_baseline": None,
            "max_avg_shadow_minus_baseline": None,
            "windows": windows,
        }
    step = max(1, int(rolling_window))
    for start in range(0, len(ordered), step):
        items = ordered[start : start + int(rolling_window)]
        if len(items) < int(min_window):
            continue
        metrics = _basic_metrics(items)
        metrics["start_timestamp"] = items[0].get("timestamp")
        metrics["end_timestamp"] = items[-1].get("timestamp")
        windows.append(metrics)
    lifts = [float(window["avg_shadow_minus_baseline"]) for window in windows if window.get("avg_shadow_minus_baseline") is not None]
    return {
        "window_count": len(windows),
        "positive_window_count": sum(1 for lift in lifts if lift > 0.0),
        "positive_window_rate": _rate(sum(1 for lift in lifts if lift > 0.0), len(lifts)),
        "min_avg_shadow_minus_baseline": min(lifts) if lifts else None,
        "max_avg_shadow_minus_baseline": max(lifts) if lifts else None,
        "windows": windows,
    }


def _basic_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    bad_count = sum(1 for record in records if _is_bad_price_action(record))
    return {
        "count": len(records),
        "bad_count": bad_count,
        "bad_rate": _rate(bad_count, len(records)),
        "avg_shadow_minus_baseline": _mean(record.get("shadow_minus_baseline") for record in records),
        "positive_shadow_lift_rate": _positive_rate(record.get("shadow_minus_baseline") for record in records),
        "outcome_labels": dict(sorted(Counter(str(record.get("outcome_label")) for record in records).items())),
    }


def _is_bad_price_action(record: Mapping[str, Any]) -> bool:
    return _float(record.get("baseline_net_return"), 0.0) < 0.0


def _stable_positive(cell: Mapping[str, Any]) -> bool:
    return (
        _float(cell.get("avg_shadow_minus_baseline"), 0.0) > 0.0
        and _float(cell.get("positive_shadow_lift_rate"), 0.0) >= 0.55
        and int(cell.get("count") or 0) >= 10
    )


def _rolling_stable(cell: Mapping[str, Any]) -> bool:
    rolling = dict(cell.get("rolling", {}))
    return (
        _stable_positive(cell)
        and int(rolling.get("window_count") or 0) > 0
        and _float(rolling.get("min_avg_shadow_minus_baseline"), 0.0) > 0.0
        and _float(rolling.get("positive_window_rate"), 0.0) >= 0.75
    )


def _best_cell(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    ranked = _ranked_cells(cells)
    return ranked[0] if ranked else None


def _worst_cell(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    ranked = _ranked_cells(cells)
    return ranked[-1] if ranked else None


def _ranked_cells(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for cell in cells:
        lift = cell.get("avg_shadow_minus_baseline")
        if lift is None:
            continue
        rows.append(
            {
                "horizon_bars": cell.get("horizon_bars"),
                "fee_bps": cell.get("fee_bps"),
                "count": cell.get("count"),
                "avg_shadow_minus_baseline": lift,
                "bad_rate": cell.get("bad_rate"),
                "positive_shadow_lift_rate": cell.get("positive_shadow_lift_rate"),
            }
        )
    return sorted(rows, key=lambda row: float(row["avg_shadow_minus_baseline"]), reverse=True)


def _mean(values: Iterable[Any]) -> float | None:
    nums = _numbers(values)
    if not nums:
        return None
    return sum(nums) / len(nums)


def _median(values: Iterable[Any]) -> float | None:
    nums = sorted(_numbers(values))
    if not nums:
        return None
    midpoint = len(nums) // 2
    if len(nums) % 2:
        return nums[midpoint]
    return (nums[midpoint - 1] + nums[midpoint]) / 2.0


def _positive_rate(values: Iterable[Any]) -> float | None:
    nums = _numbers(values)
    if not nums:
        return None
    return sum(1 for value in nums if value > 0.0) / len(nums)


def _numbers(values: Iterable[Any]) -> list[float]:
    nums: list[float] = []
    for value in values:
        if value is None:
            continue
        try:
            nums.append(float(value))
        except (TypeError, ValueError):
            continue
    return nums


def _float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


__all__ = [
    "build_price_action_guardrail_validation",
    "is_price_action_direction_guardrail",
    "render_price_action_guardrail_validation_markdown",
]
