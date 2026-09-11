"""Offline drift report for the PriceAction direction candidate.

The report explains why a candidate that looked good on a smaller sample failed
on a larger rolling validation. It is analysis-only and changes no live logic.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from libs.selection.regime_v2_price_action_guardrail_validation import is_price_action_direction_guardrail
from libs.selection.regime_v2_price_action_matrix import is_price_action_subset_removal
from libs.selection.regime_v2_shadow_outcomes import label_shadow_decision_outcomes


def build_pa_drift_report(
    records: Iterable[Mapping[str, Any]],
    ohlcv_by_pair: Mapping[tuple[str, str], pd.DataFrame],
    *,
    direction: int = 1,
    horizons: Sequence[int] = (3, 6, 12, 24),
    fees_bps: Sequence[float] = (2.0, 5.0, 10.0),
    rolling_window: int = 30,
    min_window: int = 10,
    min_bad_rate: float = 0.55,
    min_avg_lift: float = 0.0,
    min_rolling_positive_rate: float = 0.75,
) -> dict[str, Any]:
    """Build drift/failure diagnostics for a PriceAction direction candidate."""
    raw = [dict(record) for record in records]
    pa_rows = [record for record in raw if is_price_action_subset_removal(record)]
    candidate_rows = [record for record in raw if is_price_action_direction_guardrail(record, direction=direction)]
    cells: list[dict[str, Any]] = []
    direction_cells: list[dict[str, Any]] = []

    for horizon in horizons:
        for fee_bps in fees_bps:
            labeled = label_shadow_decision_outcomes(
                raw,
                ohlcv_by_pair,
                horizon_bars=int(horizon),
                fee_bps=float(fee_bps),
            )
            candidate = [record for record in labeled if is_price_action_direction_guardrail(record, direction=direction)]
            cell = _build_cell(
                candidate,
                horizon_bars=int(horizon),
                fee_bps=float(fee_bps),
                rolling_window=int(rolling_window),
                min_window=int(min_window),
                min_bad_rate=float(min_bad_rate),
                min_avg_lift=float(min_avg_lift),
                min_rolling_positive_rate=float(min_rolling_positive_rate),
            )
            cells.append(cell)
            for split_direction in (-1, 1):
                split = [
                    record for record in labeled if is_price_action_direction_guardrail(record, direction=split_direction)
                ]
                row = _metrics(split)
                row.update({"direction": split_direction, "horizon_bars": int(horizon), "fee_bps": float(fee_bps)})
                direction_cells.append(row)

    failure_windows = _failure_windows(cells)
    return {
        "phase": "phase_6h_pa_drift_report",
        "summary": {
            "total_records": len(raw),
            "price_action_subset_removal_count": len(pa_rows),
            "price_action_subset_removal_rate": _rate(len(pa_rows), len(raw)),
            "direction": int(direction),
            "candidate_count": len(candidate_rows),
            "candidate_rate": _rate(len(candidate_rows), len(raw)),
            "cell_count": len(cells),
            "passing_cell_count": sum(1 for cell in cells if cell.get("status") == "pass"),
            "failing_cell_count": sum(1 for cell in cells if cell.get("status") != "pass"),
            "negative_cell_count": sum(1 for cell in cells if _float(cell.get("avg_shadow_minus_baseline"), 0.0) <= min_avg_lift),
            "rolling_failure_window_count": len(failure_windows),
            "min_bad_rate": float(min_bad_rate),
            "min_avg_lift": float(min_avg_lift),
            "min_rolling_positive_rate": float(min_rolling_positive_rate),
            "rolling_window": int(rolling_window),
            "min_window": int(min_window),
        },
        "cells": cells,
        "failure_windows": failure_windows[:20],
        "asset_timeframe_summary": _asset_summary(cells),
        "direction_comparison": _direction_summary(direction_cells),
    }


def render_pa_drift_report_markdown(report: Mapping[str, Any]) -> str:
    """Render compact Markdown for the drift report."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 6H PriceAction Drift Report",
        "",
        "## Summary",
        "",
        f"- Total records: {summary.get('total_records', 0)}",
        f"- PriceAction subset removals: {summary.get('price_action_subset_removal_count', 0)} ({summary.get('price_action_subset_removal_rate')})",
        f"- Direction tested: {summary.get('direction')}",
        f"- Candidate rows: {summary.get('candidate_count', 0)} ({summary.get('candidate_rate')})",
        f"- Passing cells: {summary.get('passing_cell_count', 0)} / {summary.get('cell_count', 0)}",
        f"- Negative cells: {summary.get('negative_cell_count', 0)}",
        f"- Rolling failure windows: {summary.get('rolling_failure_window_count', 0)}",
        "",
        "## Cell Status",
        "",
        "| Horizon | Fee bps | Count | Avg lift | Bad rate | Rolling min lift | Rolling positive rate | Status | Reasons |",
        "|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for cell in report.get("cells", []):
        rolling = dict(cell.get("rolling", {}))
        lines.append(
            "| {horizon} | {fee} | {count} | {lift} | {bad_rate} | {min_lift} | {roll_rate} | {status} | {reasons} |".format(
                horizon=cell.get("horizon_bars"),
                fee=cell.get("fee_bps"),
                count=cell.get("count"),
                lift=cell.get("avg_shadow_minus_baseline"),
                bad_rate=cell.get("bad_rate"),
                min_lift=rolling.get("min_avg_shadow_minus_baseline"),
                roll_rate=rolling.get("positive_window_rate"),
                status=cell.get("status"),
                reasons=", ".join(cell.get("failure_reasons", [])),
            )
        )
    lines.extend([
        "",
        "## Worst Failure Windows",
        "",
        "| Horizon | Fee bps | Start | End | Count | Avg lift | Bad rate | Labels |",
        "|---:|---:|---|---|---:|---:|---:|---|",
    ])
    for row in list(report.get("failure_windows", []))[:10]:
        lines.append(
            "| {horizon} | {fee} | {start} | {end} | {count} | {lift} | {bad_rate} | {labels} |".format(
                horizon=row.get("horizon_bars"),
                fee=row.get("fee_bps"),
                start=row.get("start_timestamp"),
                end=row.get("end_timestamp"),
                count=row.get("count"),
                lift=row.get("avg_shadow_minus_baseline"),
                bad_rate=row.get("bad_rate"),
                labels=row.get("outcome_labels"),
            )
        )
    lines.extend([
        "",
        "## Asset / Timeframe Summary",
        "",
        "| Asset/TF | Cells | Negative cells | Avg lift | Bad rate |",
        "|---|---:|---:|---:|---:|",
    ])
    for row in report.get("asset_timeframe_summary", []):
        lines.append(
            "| {key} | {cells} | {negative} | {lift} | {bad_rate} |".format(
                key=row.get("asset_timeframe"),
                cells=row.get("cell_count"),
                negative=row.get("negative_cell_count"),
                lift=row.get("avg_shadow_minus_baseline"),
                bad_rate=row.get("bad_rate"),
            )
        )
    lines.extend([
        "",
        "## Direction Comparison",
        "",
        "| Direction | Cells | Count | Avg lift | Bad rate |",
        "|---:|---:|---:|---:|---:|",
    ])
    for row in report.get("direction_comparison", []):
        lines.append(
            "| {direction} | {cells} | {count} | {lift} | {bad_rate} |".format(
                direction=row.get("direction"),
                cells=row.get("cell_count"),
                count=row.get("count"),
                lift=row.get("avg_shadow_minus_baseline"),
                bad_rate=row.get("bad_rate"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _build_cell(
    records: list[dict[str, Any]],
    *,
    horizon_bars: int,
    fee_bps: float,
    rolling_window: int,
    min_window: int,
    min_bad_rate: float,
    min_avg_lift: float,
    min_rolling_positive_rate: float,
) -> dict[str, Any]:
    labeled = [record for record in records if record.get("outcome_label") != "unlabeled"]
    metrics = _metrics(labeled)
    metrics.update(
        {
            "horizon_bars": int(horizon_bars),
            "fee_bps": float(fee_bps),
            "asset_timeframe": _asset_metrics(labeled),
            "rolling": _rolling(labeled, rolling_window=rolling_window, min_window=min_window),
        }
    )
    reasons = _failure_reasons(
        metrics,
        min_bad_rate=min_bad_rate,
        min_avg_lift=min_avg_lift,
        min_rolling_positive_rate=min_rolling_positive_rate,
    )
    metrics["failure_reasons"] = reasons
    metrics["status"] = "pass" if not reasons else "fail"
    return metrics


def _failure_reasons(
    cell: Mapping[str, Any], *, min_bad_rate: float, min_avg_lift: float, min_rolling_positive_rate: float) -> list[str]:
    reasons: list[str] = []
    if int(cell.get("count") or 0) <= 0:
        return ["no_candidate_rows"]
    if _float(cell.get("avg_shadow_minus_baseline"), 0.0) <= min_avg_lift:
        reasons.append("avg_lift_below_floor")
    if _float(cell.get("bad_rate"), 0.0) < min_bad_rate:
        reasons.append("bad_rate_below_floor")
    rolling = dict(cell.get("rolling", {}))
    if int(rolling.get("window_count") or 0) <= 0:
        reasons.append("no_rolling_windows")
    if _float(rolling.get("min_avg_shadow_minus_baseline"), 0.0) <= min_avg_lift:
        reasons.append("rolling_min_lift_below_floor")
    if _float(rolling.get("positive_window_rate"), 0.0) < min_rolling_positive_rate:
        reasons.append("rolling_positive_rate_below_floor")
    return reasons


def _rolling(records: list[dict[str, Any]], *, rolling_window: int, min_window: int) -> dict[str, Any]:
    ordered = sorted(records, key=lambda record: (float(record.get("timestamp") or 0.0), str(record.get("asset") or "")))
    windows: list[dict[str, Any]] = []
    for start in range(0, len(ordered), max(1, rolling_window)):
        items = ordered[start : start + rolling_window]
        if len(items) < min_window:
            continue
        row = _metrics(items)
        row["start_timestamp"] = items[0].get("timestamp")
        row["end_timestamp"] = items[-1].get("timestamp")
        windows.append(row)
    lifts = [float(row["avg_shadow_minus_baseline"]) for row in windows if row.get("avg_shadow_minus_baseline") is not None]
    return {
        "window_count": len(windows),
        "positive_window_count": sum(1 for lift in lifts if lift > 0.0),
        "positive_window_rate": _rate(sum(1 for lift in lifts if lift > 0.0), len(lifts)),
        "min_avg_shadow_minus_baseline": min(lifts) if lifts else None,
        "max_avg_shadow_minus_baseline": max(lifts) if lifts else None,
        "windows": windows,
    }


def _failure_windows(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cell in cells:
        for window in dict(cell.get("rolling", {})).get("windows", []):
            if _float(window.get("avg_shadow_minus_baseline"), 0.0) > 0.0:
                continue
            row = dict(window)
            row["horizon_bars"] = cell.get("horizon_bars")
            row["fee_bps"] = cell.get("fee_bps")
            rows.append(row)
    return sorted(rows, key=lambda row: float(row.get("avg_shadow_minus_baseline") or 0.0))


def _asset_summary(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for cell in cells:
        for key, metrics in dict(cell.get("asset_timeframe", {})).items():
            grouped.setdefault(str(key), []).append(dict(metrics))
    rows = []
    for key, items in grouped.items():
        rows.append(
            {
                "asset_timeframe": key,
                "cell_count": len(items),
                "negative_cell_count": sum(1 for item in items if _float(item.get("avg_shadow_minus_baseline"), 0.0) <= 0.0),
                "count": sum(int(item.get("count") or 0) for item in items),
                "avg_shadow_minus_baseline": _weighted_mean(items, "avg_shadow_minus_baseline", "count"),
                "bad_rate": _weighted_mean(items, "bad_rate", "count"),
            }
        )
    return sorted(rows, key=lambda row: (-int(row["negative_cell_count"]), float(row.get("avg_shadow_minus_baseline") or 0.0)))


def _direction_summary(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for cell in cells:
        grouped.setdefault(int(cell.get("direction") or 0), []).append(cell)
    rows = []
    for direction, items in sorted(grouped.items()):
        rows.append(
            {
                "direction": direction,
                "cell_count": len(items),
                "count": sum(int(item.get("count") or 0) for item in items),
                "avg_shadow_minus_baseline": _weighted_mean(items, "avg_shadow_minus_baseline", "count"),
                "bad_rate": _weighted_mean(items, "bad_rate", "count"),
            }
        )
    return rows


def _asset_metrics(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        key = f"{record.get('asset') or 'none'}|{record.get('timeframe') or 'none'}"
        grouped.setdefault(key, []).append(record)
    return {key: _metrics(items) for key, items in sorted(grouped.items())}


def _metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    bad_count = sum(1 for record in records if _float(record.get("baseline_net_return"), 0.0) < 0.0)
    return {
        "count": len(records),
        "bad_count": bad_count,
        "bad_rate": _rate(bad_count, len(records)),
        "avg_baseline_net_return": _mean(record.get("baseline_net_return") for record in records),
        "avg_shadow_minus_baseline": _mean(record.get("shadow_minus_baseline") for record in records),
        "positive_shadow_lift_rate": _positive_rate(record.get("shadow_minus_baseline") for record in records),
        "outcome_labels": dict(sorted(Counter(str(record.get("outcome_label")) for record in records).items())),
    }


def _weighted_mean(rows: list[dict[str, Any]], value_key: str, weight_key: str) -> float | None:
    numerator = 0.0
    denominator = 0.0
    for row in rows:
        value = row.get(value_key)
        weight = row.get(weight_key)
        if value is None or weight is None:
            continue
        weight_f = float(weight)
        numerator += float(value) * weight_f
        denominator += weight_f
    return numerator / denominator if denominator > 0.0 else None


def _mean(values: Iterable[Any]) -> float | None:
    nums = _numbers(values)
    return sum(nums) / len(nums) if nums else None


def _positive_rate(values: Iterable[Any]) -> float | None:
    nums = _numbers(values)
    return sum(1 for value in nums if value > 0.0) / len(nums) if nums else None


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
    return float(numerator) / float(denominator) if denominator > 0 else None


__all__ = ["build_pa_drift_report", "render_pa_drift_report_markdown"]
