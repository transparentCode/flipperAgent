"""Asset-specific PriceAction candidate validation.

Phase 6H showed global PriceAction direction suppression is invalid, while
BNBUSDT|1h remained positive. This module validates one asset/timeframe
candidate offline and produces a strict pass/fail report. It changes no live
selection behaviour.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from libs.selection.regime_v2_price_action_guardrail_validation import is_price_action_direction_guardrail
from libs.selection.regime_v2_shadow_outcomes import label_shadow_decision_outcomes

_DEFAULT_PASSING_CELL_FLOOR = 10
_DEFAULT_MAX_NEGATIVE_CELLS = 1
_DEFAULT_ROLLING_STABLE_FLOOR = 8
_DEFAULT_MIN_POSITIVE_RATE = 0.60
_DEFAULT_MIN_SUPPORT = 30


def is_pa_asset_candidate(
    record: Mapping[str, Any],
    *,
    asset: str,
    timeframe: str,
    direction: int = 1,
) -> bool:
    """Return True for the exact asset/timeframe/direction candidate."""
    if str(record.get("asset") or "") != str(asset):
        return False
    if str(record.get("timeframe") or "") != str(timeframe):
        return False
    return is_price_action_direction_guardrail(record, direction=direction)


def build_pa_asset_candidate_report(
    records: Iterable[Mapping[str, Any]],
    ohlcv_by_pair: Mapping[tuple[str, str], pd.DataFrame],
    *,
    asset: str = "BNBUSDT",
    timeframe: str = "1h",
    direction: int = 1,
    horizons: Sequence[int] = (3, 6, 12, 24),
    fees_bps: Sequence[float] = (2.0, 5.0, 10.0),
    rolling_windows: Sequence[int] = (20, 30, 50),
    min_window: int = 10,
    min_support: int = _DEFAULT_MIN_SUPPORT,
    passing_cell_floor: int = _DEFAULT_PASSING_CELL_FLOOR,
    max_negative_cells: int = _DEFAULT_MAX_NEGATIVE_CELLS,
    rolling_stable_floor: int = _DEFAULT_ROLLING_STABLE_FLOOR,
    min_positive_rate: float = _DEFAULT_MIN_POSITIVE_RATE,
) -> dict[str, Any]:
    """Build strict asset-specific validation for a PA guardrail candidate."""
    raw = [dict(record) for record in records]
    candidate_rows = [
        record
        for record in raw
        if is_pa_asset_candidate(record, asset=asset, timeframe=timeframe, direction=direction)
    ]
    cells: list[dict[str, Any]] = []
    for horizon in horizons:
        for fee_bps in fees_bps:
            labeled = label_shadow_decision_outcomes(
                raw,
                ohlcv_by_pair,
                horizon_bars=int(horizon),
                fee_bps=float(fee_bps),
            )
            candidate = [
                record
                for record in labeled
                if is_pa_asset_candidate(record, asset=asset, timeframe=timeframe, direction=direction)
            ]
            cells.append(
                _cell(
                    candidate,
                    horizon_bars=int(horizon),
                    fee_bps=float(fee_bps),
                    rolling_windows=tuple(int(window) for window in rolling_windows),
                    min_window=int(min_window),
                    min_positive_rate=float(min_positive_rate),
                )
            )

    passing_cell_count = sum(1 for cell in cells if cell.get("status") == "pass")
    negative_cell_count = sum(1 for cell in cells if _float(cell.get("avg_shadow_minus_baseline"), 0.0) <= 0.0)
    rolling_stable_cell_count = sum(1 for cell in cells if bool(cell.get("rolling_stable", False)))
    promote_ready = (
        len(candidate_rows) >= int(min_support)
        and passing_cell_count >= int(passing_cell_floor)
        and negative_cell_count <= int(max_negative_cells)
        and rolling_stable_cell_count >= int(rolling_stable_floor)
    )
    return {
        "phase": "phase_6i_pa_asset_candidate_validation",
        "summary": {
            "asset": asset,
            "timeframe": timeframe,
            "direction": int(direction),
            "total_records": len(raw),
            "candidate_count": len(candidate_rows),
            "candidate_rate": _rate(len(candidate_rows), len(raw)),
            "cell_count": len(cells),
            "passing_cell_count": passing_cell_count,
            "negative_cell_count": negative_cell_count,
            "rolling_stable_cell_count": rolling_stable_cell_count,
            "min_support": int(min_support),
            "passing_cell_floor": int(passing_cell_floor),
            "max_negative_cells": int(max_negative_cells),
            "rolling_stable_floor": int(rolling_stable_floor),
            "min_positive_rate": float(min_positive_rate),
            "promote_ready": promote_ready,
            "recommendation": "paper_candidate" if promote_ready else "hold_off",
            "best_cell": _best_cell(cells),
            "worst_cell": _worst_cell(cells),
            "worst_rolling_window": _worst_rolling_window(cells),
        },
        "cells": cells,
        "comparison": _comparison(raw, ohlcv_by_pair, horizons=horizons, fees_bps=fees_bps, direction=direction),
    }


def render_pa_asset_candidate_markdown(report: Mapping[str, Any]) -> str:
    """Render compact Markdown for the asset candidate report."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 6I PriceAction Asset Candidate",
        "",
        "## Summary",
        "",
        f"- Candidate: {summary.get('asset')}|{summary.get('timeframe')} direction={summary.get('direction')}",
        f"- Total records: {summary.get('total_records', 0)}",
        f"- Candidate rows: {summary.get('candidate_count', 0)} ({summary.get('candidate_rate')})",
        f"- Passing cells: {summary.get('passing_cell_count', 0)} / {summary.get('cell_count', 0)}",
        f"- Negative cells: {summary.get('negative_cell_count', 0)}",
        f"- Rolling-stable cells: {summary.get('rolling_stable_cell_count', 0)}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Promote ready: {summary.get('promote_ready')}",
        f"- Best cell: {summary.get('best_cell')}",
        f"- Worst cell: {summary.get('worst_cell')}",
        f"- Worst rolling window: {summary.get('worst_rolling_window')}",
        "",
        "## Horizon/Fee Cells",
        "",
        "| Horizon | Fee bps | Count | Avg lift | Positive rate | Bad rate | Rolling stable | Status | Reasons |",
        "|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for cell in report.get("cells", []):
        lines.append(
            "| {horizon} | {fee} | {count} | {lift} | {positive} | {bad_rate} | {rolling_stable} | {status} | {reasons} |".format(
                horizon=cell.get("horizon_bars"),
                fee=cell.get("fee_bps"),
                count=cell.get("count"),
                lift=cell.get("avg_shadow_minus_baseline"),
                positive=cell.get("positive_shadow_lift_rate"),
                bad_rate=cell.get("bad_rate"),
                rolling_stable=cell.get("rolling_stable"),
                status=cell.get("status"),
                reasons=", ".join(cell.get("failure_reasons", [])),
            )
        )
    lines.extend([
        "",
        "## Comparison Across Assets",
        "",
        "| Asset/TF | Count | Avg lift | Positive rate | Bad rate |",
        "|---|---:|---:|---:|---:|",
    ])
    for row in report.get("comparison", []):
        lines.append(
            "| {key} | {count} | {lift} | {positive} | {bad_rate} |".format(
                key=row.get("asset_timeframe"),
                count=row.get("count"),
                lift=row.get("avg_shadow_minus_baseline"),
                positive=row.get("positive_shadow_lift_rate"),
                bad_rate=row.get("bad_rate"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _cell(
    records: list[dict[str, Any]],
    *,
    horizon_bars: int,
    fee_bps: float,
    rolling_windows: Sequence[int],
    min_window: int,
    min_positive_rate: float,
) -> dict[str, Any]:
    labeled = [record for record in records if record.get("outcome_label") != "unlabeled"]
    metrics = _metrics(labeled)
    rolling = {
        str(window): _rolling(labeled, rolling_window=int(window), min_window=int(min_window))
        for window in rolling_windows
    }
    metrics.update(
        {
            "horizon_bars": int(horizon_bars),
            "fee_bps": float(fee_bps),
            "rolling": rolling,
        }
    )
    rolling_stable = all(
        _float(row.get("min_avg_shadow_minus_baseline"), 0.0) > 0.0
        and _float(row.get("positive_window_rate"), 0.0) >= float(min_positive_rate)
        for row in rolling.values()
    )
    reasons = _failure_reasons(metrics, rolling_stable=rolling_stable, min_positive_rate=min_positive_rate)
    metrics["rolling_stable"] = rolling_stable
    metrics["failure_reasons"] = reasons
    metrics["status"] = "pass" if not reasons else "fail"
    return metrics


def _failure_reasons(cell: Mapping[str, Any], *, rolling_stable: bool, min_positive_rate: float) -> list[str]:
    reasons: list[str] = []
    if int(cell.get("count") or 0) <= 0:
        return ["no_candidate_rows"]
    if _float(cell.get("avg_shadow_minus_baseline"), 0.0) <= 0.0:
        reasons.append("avg_lift_below_zero")
    if _float(cell.get("positive_shadow_lift_rate"), 0.0) < float(min_positive_rate):
        reasons.append("positive_rate_below_floor")
    if not rolling_stable:
        reasons.append("rolling_not_stable")
    return reasons


def _rolling(records: list[dict[str, Any]], *, rolling_window: int, min_window: int) -> dict[str, Any]:
    ordered = sorted(records, key=lambda record: float(record.get("timestamp") or 0.0))
    windows: list[dict[str, Any]] = []
    for start in range(0, len(ordered), max(1, int(rolling_window))):
        items = ordered[start : start + int(rolling_window)]
        if len(items) < int(min_window):
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


def _comparison(
    records: list[dict[str, Any]],
    ohlcv_by_pair: Mapping[tuple[str, str], pd.DataFrame],
    *,
    horizons: Sequence[int],
    fees_bps: Sequence[float],
    direction: int,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for horizon in horizons:
        for fee_bps in fees_bps:
            labeled = label_shadow_decision_outcomes(
                records,
                ohlcv_by_pair,
                horizon_bars=int(horizon),
                fee_bps=float(fee_bps),
            )
            for record in labeled:
                if not is_price_action_direction_guardrail(record, direction=direction):
                    continue
                key = f"{record.get('asset') or 'none'}|{record.get('timeframe') or 'none'}"
                grouped.setdefault(key, []).append(record)
    rows = []
    for key, items in sorted(grouped.items()):
        row = _metrics(items)
        row["asset_timeframe"] = key
        rows.append(row)
    return sorted(rows, key=lambda row: float(row.get("avg_shadow_minus_baseline") or 0.0), reverse=True)


def _best_cell(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    ranked = _rank_cells(cells)
    return ranked[0] if ranked else None


def _worst_cell(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    ranked = _rank_cells(cells)
    return ranked[-1] if ranked else None


def _rank_cells(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for cell in cells:
        if cell.get("avg_shadow_minus_baseline") is None:
            continue
        rows.append(
            {
                "horizon_bars": cell.get("horizon_bars"),
                "fee_bps": cell.get("fee_bps"),
                "count": cell.get("count"),
                "avg_shadow_minus_baseline": cell.get("avg_shadow_minus_baseline"),
                "positive_shadow_lift_rate": cell.get("positive_shadow_lift_rate"),
                "bad_rate": cell.get("bad_rate"),
            }
        )
    return sorted(rows, key=lambda row: float(row["avg_shadow_minus_baseline"]), reverse=True)


def _worst_rolling_window(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    rows = []
    for cell in cells:
        for window_name, rolling in dict(cell.get("rolling", {})).items():
            for window in dict(rolling).get("windows", []):
                if window.get("avg_shadow_minus_baseline") is None:
                    continue
                row = dict(window)
                row["horizon_bars"] = cell.get("horizon_bars")
                row["fee_bps"] = cell.get("fee_bps")
                row["rolling_window"] = int(window_name)
                rows.append(row)
    if not rows:
        return None
    return sorted(rows, key=lambda row: float(row["avg_shadow_minus_baseline"]))[0]


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


__all__ = [
    "build_pa_asset_candidate_report",
    "is_pa_asset_candidate",
    "render_pa_asset_candidate_markdown",
]
