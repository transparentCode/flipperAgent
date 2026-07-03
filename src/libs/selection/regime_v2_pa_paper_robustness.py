"""Multi-cell robustness report for PA paper guardrail outcomes."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from libs.selection.regime_v2_pa_paper_report import label_pa_paper_outcomes

_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES = (2.0, 5.0, 10.0)
_DEFAULT_ROLLING_WINDOWS = (20, 30, 50)


def build_pa_paper_robustness_report(
    records: Iterable[Mapping[str, Any]],
    ohlcv_by_pair: Mapping[tuple[str, str], pd.DataFrame],
    *,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES,
    rolling_windows: Sequence[int] = _DEFAULT_ROLLING_WINDOWS,
    min_window: int = 10,
    min_support: int = 30,
    min_positive_rate: float = 0.60,
    passing_cell_floor: int = 10,
    max_negative_cells: int = 1,
    rolling_stable_floor: int = 8,
) -> dict[str, Any]:
    """Build a horizon/fee/rolling robustness report for PA paper records."""
    raw = [dict(record) for record in records]
    cells: list[dict[str, Any]] = []
    for horizon in horizons:
        for fee_bps in fees_bps:
            labeled = label_pa_paper_outcomes(
                raw,
                ohlcv_by_pair,
                horizon_bars=int(horizon),
                fee_bps=float(fee_bps),
            )
            cells.append(
                _cell(
                    labeled,
                    horizon_bars=int(horizon),
                    fee_bps=float(fee_bps),
                    rolling_windows=tuple(int(window) for window in rolling_windows),
                    min_window=int(min_window),
                    min_positive_rate=float(min_positive_rate),
                )
            )

    active_changed_counts = [int(cell.get("active_changed", {}).get("count") or 0) for cell in cells]
    candidate_count = max(active_changed_counts) if active_changed_counts else 0
    passing_cells = sum(1 for cell in cells if cell.get("status") == "pass")
    negative_cells = sum(
        1
        for cell in cells
        if _float(cell.get("active_changed", {}).get("avg_paper_minus_baseline"), 0.0) <= 0.0
    )
    rolling_stable_cells = sum(1 for cell in cells if bool(cell.get("rolling_stable", False)))
    promote_ready = (
        candidate_count >= int(min_support)
        and passing_cells >= int(passing_cell_floor)
        and negative_cells <= int(max_negative_cells)
        and rolling_stable_cells >= int(rolling_stable_floor)
    )
    return {
        "phase": "phase_6m_pa_paper_robustness",
        "summary": {
            "total_records": len(raw),
            "candidate_count": candidate_count,
            "cell_count": len(cells),
            "passing_cell_count": passing_cells,
            "negative_cell_count": negative_cells,
            "rolling_stable_cell_count": rolling_stable_cells,
            "min_support": int(min_support),
            "min_positive_rate": float(min_positive_rate),
            "passing_cell_floor": int(passing_cell_floor),
            "max_negative_cells": int(max_negative_cells),
            "rolling_stable_floor": int(rolling_stable_floor),
            "paper_ready": promote_ready,
            "recommendation": "paper_rollout_candidate" if promote_ready else "hold_off",
            "best_cell": _best_cell(cells),
            "worst_cell": _worst_cell(cells),
            "worst_rolling_window": _worst_rolling_window(cells),
        },
        "cells": cells,
    }


def render_pa_paper_robustness_markdown(report: Mapping[str, Any]) -> str:
    """Render compact Markdown for PA paper robustness."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 6M PA Paper Robustness Report",
        "",
        "## Summary",
        "",
        f"- Total records: {summary.get('total_records', 0)}",
        f"- Candidate rows: {summary.get('candidate_count', 0)}",
        f"- Passing cells: {summary.get('passing_cell_count', 0)} / {summary.get('cell_count', 0)}",
        f"- Negative cells: {summary.get('negative_cell_count', 0)}",
        f"- Rolling-stable cells: {summary.get('rolling_stable_cell_count', 0)}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Paper-ready: {summary.get('paper_ready')}",
        f"- Best cell: {summary.get('best_cell')}",
        f"- Worst cell: {summary.get('worst_cell')}",
        f"- Worst rolling window: {summary.get('worst_rolling_window')}",
        "",
        "## Cells",
        "",
        "| Horizon | Fee bps | Active changed | Avg lift | Positive rate | Bad rate | Rolling stable | Status | Reasons |",
        "|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for cell in report.get("cells", []):
        segment = dict(cell.get("active_changed", {}))
        lines.append(
            "| {horizon} | {fee} | {count} | {lift} | {positive} | {bad} | {stable} | {status} | {reasons} |".format(
                horizon=cell.get("horizon_bars"),
                fee=cell.get("fee_bps"),
                count=segment.get("count"),
                lift=segment.get("avg_paper_minus_baseline"),
                positive=segment.get("positive_paper_lift_rate"),
                bad=segment.get("bad_rate"),
                stable=cell.get("rolling_stable"),
                status=cell.get("status"),
                reasons=", ".join(cell.get("failure_reasons", [])),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _cell(
    labeled: list[dict[str, Any]],
    *,
    horizon_bars: int,
    fee_bps: float,
    rolling_windows: Sequence[int],
    min_window: int,
    min_positive_rate: float,
) -> dict[str, Any]:
    rows = [row for row in labeled if row.get("outcome_label") != "unlabeled"]
    active = [row for row in rows if bool(row.get("paper_active", False))]
    changed = [row for row in rows if bool(row.get("selection_changed", False))]
    active_changed = [row for row in active if bool(row.get("selection_changed", False))]
    rolling = {
        str(window): _rolling(active_changed, rolling_window=int(window), min_window=int(min_window))
        for window in rolling_windows
    }
    active_changed_metrics = _metrics(active_changed)
    rolling_stable = all(
        _float(item.get("min_avg_paper_minus_baseline"), 0.0) > 0.0
        and _float(item.get("positive_window_rate"), 0.0) >= min_positive_rate
        for item in rolling.values()
    )
    reasons = _failure_reasons(
        active_changed_metrics,
        rolling_stable=rolling_stable,
        min_positive_rate=min_positive_rate,
    )
    return {
        "horizon_bars": int(horizon_bars),
        "fee_bps": float(fee_bps),
        "labeled_count": len(rows),
        "paper_active": _metrics(active),
        "changed": _metrics(changed),
        "active_changed": active_changed_metrics,
        "rolling": rolling,
        "rolling_stable": rolling_stable,
        "failure_reasons": reasons,
        "status": "pass" if not reasons else "fail",
    }


def _failure_reasons(segment: Mapping[str, Any], *, rolling_stable: bool, min_positive_rate: float) -> list[str]:
    reasons: list[str] = []
    if int(segment.get("count") or 0) <= 0:
        return ["no_active_changed_rows"]
    if _float(segment.get("avg_paper_minus_baseline"), 0.0) <= 0.0:
        reasons.append("avg_lift_below_zero")
    if _float(segment.get("positive_paper_lift_rate"), 0.0) < min_positive_rate:
        reasons.append("positive_rate_below_floor")
    if not rolling_stable:
        reasons.append("rolling_not_stable")
    return reasons


def _rolling(records: list[dict[str, Any]], *, rolling_window: int, min_window: int) -> dict[str, Any]:
    ordered = sorted(records, key=lambda row: float(row.get("timestamp") or 0.0))
    windows: list[dict[str, Any]] = []
    for start in range(0, len(ordered), max(1, int(rolling_window))):
        items = ordered[start : start + int(rolling_window)]
        if len(items) < int(min_window):
            continue
        metrics = _metrics(items)
        metrics["start_timestamp"] = items[0].get("timestamp")
        metrics["end_timestamp"] = items[-1].get("timestamp")
        windows.append(metrics)
    lifts = [float(row["avg_paper_minus_baseline"]) for row in windows if row.get("avg_paper_minus_baseline") is not None]
    positive = sum(1 for lift in lifts if lift > 0.0)
    return {
        "window_count": len(windows),
        "positive_window_count": positive,
        "positive_window_rate": _rate(positive, len(lifts)),
        "min_avg_paper_minus_baseline": min(lifts) if lifts else None,
        "max_avg_paper_minus_baseline": max(lifts) if lifts else None,
        "windows": windows,
    }


def _metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    bad_count = sum(1 for row in records if _float(row.get("baseline_net_return"), 0.0) < 0.0)
    return {
        "count": len(records),
        "bad_count": bad_count,
        "bad_rate": _rate(bad_count, len(records)),
        "avg_baseline_net_return": _mean(row.get("baseline_net_return") for row in records),
        "avg_paper_net_return": _mean(row.get("paper_net_return") for row in records),
        "avg_paper_minus_baseline": _mean(row.get("paper_minus_baseline") for row in records),
        "positive_paper_lift_rate": _positive_rate(row.get("paper_minus_baseline") for row in records),
        "outcome_labels": dict(sorted(Counter(str(row.get("outcome_label")) for row in records).items())),
    }


def _best_cell(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    rows = _rank_cells(cells)
    return rows[0] if rows else None


def _worst_cell(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    rows = _rank_cells(cells)
    return rows[-1] if rows else None


def _rank_cells(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for cell in cells:
        segment = dict(cell.get("active_changed", {}))
        lift = segment.get("avg_paper_minus_baseline")
        if lift is None:
            continue
        rows.append(
            {
                "horizon_bars": cell.get("horizon_bars"),
                "fee_bps": cell.get("fee_bps"),
                "count": segment.get("count"),
                "avg_paper_minus_baseline": lift,
                "positive_paper_lift_rate": segment.get("positive_paper_lift_rate"),
                "bad_rate": segment.get("bad_rate"),
            }
        )
    return sorted(rows, key=lambda row: float(row["avg_paper_minus_baseline"]), reverse=True)


def _worst_rolling_window(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    rows = []
    for cell in cells:
        for window_name, rolling in dict(cell.get("rolling", {})).items():
            for window in dict(rolling).get("windows", []):
                lift = window.get("avg_paper_minus_baseline")
                if lift is None:
                    continue
                row = dict(window)
                row["horizon_bars"] = cell.get("horizon_bars")
                row["fee_bps"] = cell.get("fee_bps")
                row["rolling_window"] = int(window_name)
                rows.append(row)
    if not rows:
        return None
    return sorted(rows, key=lambda row: float(row["avg_paper_minus_baseline"]))[0]


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


__all__ = ["build_pa_paper_robustness_report", "render_pa_paper_robustness_markdown"]
