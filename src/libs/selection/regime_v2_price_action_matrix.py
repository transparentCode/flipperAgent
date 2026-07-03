"""PriceAction-specific evidence matrix for RegimeV2 shadow logs.

This module is intentionally offline-only. It isolates the one sizeable effect
seen so far: PriceAction being removed by the validated shadow subset. The
output should be used to decide whether PriceAction needs its own playbook,
not to promote generic RegimeV2 gating.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from libs.selection.regime_v2_shadow_outcomes import label_shadow_decision_outcomes

_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES_BPS = (2.0, 5.0, 10.0)


def is_price_action_subset_removal(record: Mapping[str, Any]) -> bool:
    """Return True when a shadow row represents PriceAction subset removal."""
    if str(record.get("baseline_selected_model") or "") != "PriceAction":
        return False
    if record.get("shadow_selected_model") is not None:
        return False
    if not bool(record.get("selection_changed", False)):
        return False
    if not bool(record.get("shadow_subset_only", False)):
        return False
    if bool(record.get("include_non_target_models", True)):
        return False
    target_models = {str(model) for model in (record.get("target_models") or [])}
    return "PriceAction" not in target_models


def build_price_action_subset_matrix(
    records: Iterable[Mapping[str, Any]],
    ohlcv_by_pair: Mapping[tuple[str, str], pd.DataFrame],
    *,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES_BPS,
) -> dict[str, Any]:
    """Build multi-horizon outcome evidence for PriceAction subset removals."""
    raw_records = [dict(record) for record in records]
    price_action_records = [record for record in raw_records if is_price_action_subset_removal(record)]
    cells: list[dict[str, Any]] = []
    for horizon in horizons:
        for fee_bps in fees_bps:
            labeled_all = label_shadow_decision_outcomes(
                raw_records,
                ohlcv_by_pair,
                horizon_bars=int(horizon),
                fee_bps=float(fee_bps),
            )
            labeled_pa = [record for record in labeled_all if is_price_action_subset_removal(record)]
            cells.append(_matrix_cell(labeled_pa, horizon_bars=int(horizon), fee_bps=float(fee_bps)))
    return {
        "phase": "phase_6e_price_action_subset_matrix",
        "summary": {
            "total_records": len(raw_records),
            "price_action_subset_removal_count": len(price_action_records),
            "price_action_subset_removal_rate": _rate(len(price_action_records), len(raw_records)),
            "cell_count": len(cells),
            "horizons": sorted({cell["horizon_bars"] for cell in cells}),
            "fees_bps": sorted({cell["fee_bps"] for cell in cells}),
            "best_cell": _best_cell(cells),
            "worst_cell": _worst_cell(cells),
            "stable_positive_cell_count": sum(
                1
                for cell in cells
                if _float(cell.get("avg_shadow_minus_baseline"), 0.0) > 0.0
                and _float(cell.get("positive_shadow_lift_rate"), 0.0) >= 0.55
            ),
        },
        "cells": cells,
    }


def render_price_action_subset_matrix_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact Markdown PriceAction evidence report."""
    summary = dict(report.get("summary", {}))
    cells = list(report.get("cells", []))
    lines = [
        "# RegimeV2 Phase 6E PriceAction Subset Matrix",
        "",
        "## Summary",
        "",
        f"- Total records: {summary.get('total_records', 0)}",
        f"- PriceAction subset removals: {summary.get('price_action_subset_removal_count', 0)} ({summary.get('price_action_subset_removal_rate')})",
        f"- Cells: {summary.get('cell_count', 0)}",
        f"- Horizons: {summary.get('horizons', [])}",
        f"- Fees bps: {summary.get('fees_bps', [])}",
        f"- Stable positive cells: {summary.get('stable_positive_cell_count', 0)}",
        f"- Best cell: {summary.get('best_cell')}",
        f"- Worst cell: {summary.get('worst_cell')}",
        "",
        "## Matrix",
        "",
        "| Horizon | Fee bps | Count | Avg lift | Positive rate | Avoided loss | Missed win |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cell in cells:
        labels = dict(cell.get("outcome_labels", {}))
        lines.append(
            "| {horizon} | {fee} | {count} | {lift} | {positive} | {avoided} | {missed} |".format(
                horizon=cell.get("horizon_bars"),
                fee=cell.get("fee_bps"),
                count=cell.get("count"),
                lift=cell.get("avg_shadow_minus_baseline"),
                positive=cell.get("positive_shadow_lift_rate"),
                avoided=labels.get("avoided_loss", 0),
                missed=labels.get("missed_win", 0),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _matrix_cell(records: list[dict[str, Any]], *, horizon_bars: int, fee_bps: float) -> dict[str, Any]:
    labeled = [record for record in records if record.get("outcome_label") != "unlabeled"]
    unlabeled = [record for record in records if record.get("outcome_label") == "unlabeled"]
    return {
        "horizon_bars": int(horizon_bars),
        "fee_bps": float(fee_bps),
        "count": len(labeled),
        "unlabeled_count": len(unlabeled),
        "avg_baseline_net_return": _mean(record.get("baseline_net_return") for record in labeled),
        "avg_shadow_net_return": _mean(record.get("shadow_net_return") for record in labeled),
        "avg_shadow_minus_baseline": _mean(record.get("shadow_minus_baseline") for record in labeled),
        "median_shadow_minus_baseline": _median(record.get("shadow_minus_baseline") for record in labeled),
        "positive_shadow_lift_rate": _positive_rate(record.get("shadow_minus_baseline") for record in labeled),
        "outcome_labels": dict(sorted(Counter(str(record.get("outcome_label")) for record in labeled).items())),
        "asset_timeframe": _asset_timeframe_metrics(labeled),
    }


def _asset_timeframe_metrics(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        key = f"{record.get('asset') or 'none'}|{record.get('timeframe') or 'none'}"
        grouped.setdefault(key, []).append(record)
    return {key: _pair_metrics(items) for key, items in sorted(grouped.items())}


def _pair_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(records),
        "avg_shadow_minus_baseline": _mean(record.get("shadow_minus_baseline") for record in records),
        "positive_shadow_lift_rate": _positive_rate(record.get("shadow_minus_baseline") for record in records),
        "outcome_labels": dict(sorted(Counter(str(record.get("outcome_label")) for record in records).items())),
    }


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
    "build_price_action_subset_matrix",
    "is_price_action_subset_removal",
    "render_price_action_subset_matrix_markdown",
]
