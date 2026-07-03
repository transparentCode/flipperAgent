"""Multi-horizon/fee outcome matrix for RegimeV2 shadow decisions."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from libs.selection.regime_v2_shadow_outcomes import label_shadow_decision_outcomes

_DEFAULT_SEGMENTS = (
    "all",
    "changed",
    "gate_active",
    "gate_active_changed",
    "subset_only_changed",
    "non_subset_changed",
)


def build_shadow_outcome_matrix(
    records: Iterable[Mapping[str, Any]],
    ohlcv_by_pair: Mapping[tuple[str, str], pd.DataFrame],
    *,
    horizons: Sequence[int] = (3, 6, 12, 24),
    fees_bps: Sequence[float] = (2.0, 5.0, 10.0),
) -> dict[str, Any]:
    """Build a RegimeV2 shadow outcome matrix across horizons and fees."""
    raw_records = [dict(record) for record in records]
    cells: list[dict[str, Any]] = []
    for horizon in horizons:
        for fee_bps in fees_bps:
            labeled = label_shadow_decision_outcomes(
                raw_records,
                ohlcv_by_pair,
                horizon_bars=int(horizon),
                fee_bps=float(fee_bps),
            )
            cells.append(_matrix_cell(labeled, horizon_bars=int(horizon), fee_bps=float(fee_bps)))
    return {
        "phase": "phase_6_shadow_outcome_matrix",
        "summary": _matrix_summary(cells),
        "cells": cells,
    }


def render_shadow_outcome_matrix_markdown(matrix: Mapping[str, Any]) -> str:
    """Render a compact Markdown matrix report."""
    summary = dict(matrix.get("summary", {}))
    cells = list(matrix.get("cells", []))
    lines = [
        "# RegimeV2 Phase 6B Shadow Outcome Matrix",
        "",
        "## Summary",
        "",
        f"- Cells: {summary.get('cell_count', 0)}",
        f"- Horizons: {summary.get('horizons', [])}",
        f"- Fees bps: {summary.get('fees_bps', [])}",
        f"- Best changed cell: {summary.get('best_changed_cell')}",
        f"- Worst changed cell: {summary.get('worst_changed_cell')}",
        f"- Best gate-active-changed cell: {summary.get('best_gate_active_changed_cell')}",
        "",
        "## Matrix Cells",
        "",
        "| Horizon | Fee bps | Labeled | Changed lift | Changed positive | Gate-active changed lift | Gate-active positive | Subset-only lift |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cell in cells:
        segments = dict(cell.get("segments", {}))
        changed = dict(segments.get("changed", {}))
        gate_active_changed = dict(segments.get("gate_active_changed", {}))
        subset_only = dict(segments.get("subset_only_changed", {}))
        lines.append(
            "| {horizon} | {fee} | {labeled} | {changed_lift} | {changed_positive} | {active_lift} | {active_positive} | {subset_lift} |".format(
                horizon=cell.get("horizon_bars"),
                fee=cell.get("fee_bps"),
                labeled=cell.get("labeled_count"),
                changed_lift=changed.get("avg_shadow_minus_baseline"),
                changed_positive=changed.get("positive_shadow_lift_rate"),
                active_lift=gate_active_changed.get("avg_shadow_minus_baseline"),
                active_positive=gate_active_changed.get("positive_shadow_lift_rate"),
                subset_lift=subset_only.get("avg_shadow_minus_baseline"),
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
        "total_records": len(records),
        "labeled_count": len(labeled),
        "unlabeled_count": len(unlabeled),
        "outcome_labels": dict(sorted(Counter(str(record.get("outcome_label")) for record in labeled).items())),
        "unlabeled_reasons": dict(sorted(Counter(str(record.get("outcome_reason")) for record in unlabeled).items())),
        "segments": {segment: _segment_metrics(_segment_records(labeled, segment)) for segment in _DEFAULT_SEGMENTS},
        "asset_timeframe": _asset_timeframe_metrics(labeled),
    }


def _segment_records(records: list[dict[str, Any]], segment: str) -> list[dict[str, Any]]:
    if segment == "all":
        return records
    if segment == "changed":
        return [record for record in records if bool(record.get("selection_changed", False))]
    if segment == "gate_active":
        return [record for record in records if bool(record.get("gate_active", False))]
    if segment == "gate_active_changed":
        return [
            record
            for record in records
            if bool(record.get("gate_active", False)) and bool(record.get("selection_changed", False))
        ]
    if segment == "subset_only_changed":
        return [record for record in records if bool(record.get("subset_only_changed", False))]
    if segment == "non_subset_changed":
        return [
            record
            for record in records
            if bool(record.get("selection_changed", False)) and not bool(record.get("subset_only_changed", False))
        ]
    return []


def _segment_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(records),
        "avg_baseline_net_return": _mean(record.get("baseline_net_return") for record in records),
        "avg_shadow_net_return": _mean(record.get("shadow_net_return") for record in records),
        "avg_shadow_minus_baseline": _mean(record.get("shadow_minus_baseline") for record in records),
        "median_shadow_minus_baseline": _median(record.get("shadow_minus_baseline") for record in records),
        "positive_shadow_lift_rate": _positive_rate(record.get("shadow_minus_baseline") for record in records),
        "outcome_labels": dict(sorted(Counter(str(record.get("outcome_label")) for record in records).items())),
    }


def _asset_timeframe_metrics(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        key = f"{record.get('asset') or 'none'}|{record.get('timeframe') or 'none'}"
        grouped.setdefault(key, []).append(record)
    return {key: _segment_metrics(items) for key, items in sorted(grouped.items())}


def _matrix_summary(cells: list[dict[str, Any]]) -> dict[str, Any]:
    changed_rank = _rank_cells(cells, segment="changed")
    gate_rank = _rank_cells(cells, segment="gate_active_changed")
    return {
        "cell_count": len(cells),
        "horizons": sorted({cell["horizon_bars"] for cell in cells}),
        "fees_bps": sorted({cell["fee_bps"] for cell in cells}),
        "best_changed_cell": changed_rank[0] if changed_rank else None,
        "worst_changed_cell": changed_rank[-1] if changed_rank else None,
        "best_gate_active_changed_cell": gate_rank[0] if gate_rank else None,
        "worst_gate_active_changed_cell": gate_rank[-1] if gate_rank else None,
    }


def _rank_cells(cells: list[dict[str, Any]], *, segment: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cell in cells:
        metrics = dict(dict(cell.get("segments", {})).get(segment, {}))
        lift = metrics.get("avg_shadow_minus_baseline")
        if lift is None:
            continue
        rows.append(
            {
                "horizon_bars": cell.get("horizon_bars"),
                "fee_bps": cell.get("fee_bps"),
                "count": metrics.get("count"),
                "avg_shadow_minus_baseline": lift,
                "positive_shadow_lift_rate": metrics.get("positive_shadow_lift_rate"),
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


__all__ = ["build_shadow_outcome_matrix", "render_shadow_outcome_matrix_markdown"]
