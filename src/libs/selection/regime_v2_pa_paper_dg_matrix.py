"""Horizon/fee/rolling validation for PA paper drift gates.

Phase 6V validates the best Phase 6U gate beyond one diagnostic cell.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from libs.selection.regime_v2_pa_paper_report import label_pa_paper_outcomes

_DEFAULT_HORIZONS = (3, 6, 12, 24)
_DEFAULT_FEES = (2.0, 5.0, 10.0)
_DEFAULT_ROLLING_WINDOWS = (20, 30, 50)
_DEFAULT_GATE = {"name": "rolling_avg_neg_3", "kind": "rolling_avg_neg", "window": 3}


def build_pa_paper_dg_matrix_report(
    records: Iterable[Mapping[str, Any]],
    ohlcv_by_pair: Mapping[tuple[str, str], pd.DataFrame],
    *,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    fees_bps: Sequence[float] = _DEFAULT_FEES,
    rolling_windows: Sequence[int] = _DEFAULT_ROLLING_WINDOWS,
    min_window: int = 10,
    gate_spec: Mapping[str, Any] = _DEFAULT_GATE,
    min_cell_improvement: float = 0.0,
    max_lost_avoided: int = 0,
    min_rolling_positive_rate: float = 0.50,
) -> dict[str, Any]:
    """Validate a candidate PA paper drift gate across horizon/fee cells."""
    raw = [dict(record) for record in records]
    cells: list[dict[str, Any]] = []
    for horizon in horizons:
        for fee_bps in fees_bps:
            labeled = label_pa_paper_outcomes(raw, ohlcv_by_pair, horizon_bars=int(horizon), fee_bps=float(fee_bps))
            cells.append(
                _cell(
                    labeled,
                    horizon_bars=int(horizon),
                    fee_bps=float(fee_bps),
                    rolling_windows=tuple(int(window) for window in rolling_windows),
                    min_window=int(min_window),
                    gate_spec=gate_spec,
                    min_cell_improvement=float(min_cell_improvement),
                    max_lost_avoided=int(max_lost_avoided),
                    min_rolling_positive_rate=float(min_rolling_positive_rate),
                )
            )
    passing = sum(1 for cell in cells if cell.get("status") == "pass")
    improved = sum(1 for cell in cells if _float(cell.get("gate", {}).get("gate_minus_current_suppress_avg"), 0.0) > 0.0)
    no_lost_avoided = sum(1 for cell in cells if int(cell.get("gate", {}).get("lost_avoided_loss_count") or 0) <= int(max_lost_avoided))
    rolling_stable = sum(1 for cell in cells if bool(cell.get("rolling_stable", False)))
    cell_count = len(cells)
    ready = cell_count > 0 and passing == cell_count
    return {
        "phase": "phase_6v_pa_paper_drift_gate_matrix",
        "summary": {
            "total_records": len(raw),
            "gate_name": str(gate_spec.get("name") or "gate"),
            "cell_count": cell_count,
            "passing_cell_count": passing,
            "improved_cell_count": improved,
            "no_lost_avoided_cell_count": no_lost_avoided,
            "rolling_stable_cell_count": rolling_stable,
            "min_cell_improvement": float(min_cell_improvement),
            "max_lost_avoided": int(max_lost_avoided),
            "min_rolling_positive_rate": float(min_rolling_positive_rate),
            "matrix_ready": ready,
            "recommendation": "gate_validation_candidate" if ready else "hold_off",
            "best_cell": _best_cell(cells),
            "worst_cell": _worst_cell(cells),
            "worst_rolling_window": _worst_rolling_window(cells),
        },
        "cells": cells,
    }


def render_pa_paper_dg_matrix_markdown(report: Mapping[str, Any]) -> str:
    """Render compact Markdown for drift-gate matrix validation."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 6V PA Paper Drift Gate Matrix",
        "",
        "## Summary",
        "",
        f"- Gate: {summary.get('gate_name')}",
        f"- Cells: {summary.get('passing_cell_count', 0)} / {summary.get('cell_count', 0)} passing",
        f"- Improved cells: {summary.get('improved_cell_count', 0)}",
        f"- No-lost-avoided cells: {summary.get('no_lost_avoided_cell_count', 0)}",
        f"- Rolling-stable cells: {summary.get('rolling_stable_cell_count', 0)}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Matrix-ready: {summary.get('matrix_ready')}",
        f"- Best cell: {summary.get('best_cell')}",
        f"- Worst cell: {summary.get('worst_cell')}",
        f"- Worst rolling window: {summary.get('worst_rolling_window')}",
        "",
        "## Cells",
        "",
        "| Horizon | Fee | Count | Gate-current avg | Recovered | Lost avoided | Failure pause | Rolling stable | Status | Reasons |",
        "|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for cell in report.get("cells", []):
        gate = dict(cell.get("gate", {}))
        lines.append(
            "| {horizon} | {fee} | {count} | {delta} | {recovered} | {lost} | {failure} | {stable} | {status} | {reasons} |".format(
                horizon=cell.get("horizon_bars"),
                fee=cell.get("fee_bps"),
                count=gate.get("count"),
                delta=gate.get("gate_minus_current_suppress_avg"),
                recovered=gate.get("recovered_missed_win_count"),
                lost=gate.get("lost_avoided_loss_count"),
                failure=gate.get("failure_window_pause_rate"),
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
    gate_spec: Mapping[str, Any],
    min_cell_improvement: float,
    max_lost_avoided: int,
    min_rolling_positive_rate: float,
) -> dict[str, Any]:
    rows = _active_changed_rows(labeled)
    actions = _simulate_gate(rows, gate_spec)
    gate = _gate_metrics(actions)
    rolling = {str(window): _rolling(actions, rolling_window=int(window), min_window=int(min_window)) for window in rolling_windows}
    rolling_stable = all(
        _float(row.get("min_gate_minus_current_suppress_avg"), 0.0) >= 0.0
        and _float(row.get("positive_improvement_window_rate"), 0.0) >= float(min_rolling_positive_rate)
        for row in rolling.values()
        if int(row.get("window_count") or 0) > 0
    )
    reasons = _failure_reasons(
        gate,
        rolling_stable=rolling_stable,
        min_cell_improvement=float(min_cell_improvement),
        max_lost_avoided=int(max_lost_avoided),
    )
    return {
        "horizon_bars": int(horizon_bars),
        "fee_bps": float(fee_bps),
        "gate": gate,
        "current_suppress": _current_metrics(rows),
        "rolling": rolling,
        "rolling_stable": rolling_stable,
        "failure_reasons": reasons,
        "status": "pass" if not reasons else "fail",
    }


def _simulate_gate(rows: list[dict[str, Any]], gate_spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    prior: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    for row in rows:
        paused = _gate_paused(prior, gate_spec)
        baseline = _float(row.get("baseline_net_return"), 0.0)
        paper = _float(row.get("paper_net_return"), 0.0)
        gate_net = baseline if paused else paper
        actions.append(
            {
                "timestamp": row.get("timestamp"),
                "paused": paused,
                "outcome_label": row.get("outcome_label"),
                "baseline_net_return": baseline,
                "paper_net_return": paper,
                "paper_minus_baseline": _float(row.get("paper_minus_baseline"), 0.0),
                "gate_net_return": gate_net,
                "gate_minus_baseline": gate_net - baseline,
                "gate_minus_current_suppress": gate_net - paper,
            }
        )
        prior.append(row)
    return actions


def _gate_paused(prior: list[dict[str, Any]], spec: Mapping[str, Any]) -> bool:
    kind = str(spec.get("kind") or "")
    if kind == "rolling_avg_neg":
        window = int(spec.get("window") or 3)
        if len(prior) < window:
            return False
        values = [_float(row.get("paper_minus_baseline"), 0.0) for row in prior[-window:]]
        return (sum(values) / len(values)) < 0.0
    if kind == "miss_gt_avoid":
        window = int(spec.get("window") or 3)
        if len(prior) < window:
            return False
        labels = Counter(str(row.get("outcome_label")) for row in prior[-window:])
        return int(labels.get("missed_win", 0)) > int(labels.get("avoided_loss", 0))
    if kind == "missed_streak":
        streak = int(spec.get("missed_streak") or 2)
        if len(prior) < streak:
            return False
        return all(str(row.get("outcome_label")) == "missed_win" for row in prior[-streak:])
    return False


def _gate_metrics(actions: list[dict[str, Any]]) -> dict[str, Any]:
    paused = [row for row in actions if bool(row.get("paused", False))]
    return {
        "count": len(actions),
        "paused_count": len(paused),
        "active_count": len(actions) - len(paused),
        "avg_gate_minus_baseline": _mean(row.get("gate_minus_baseline") for row in actions),
        "avg_current_suppress_minus_baseline": _mean(row.get("paper_minus_baseline") for row in actions),
        "gate_minus_current_suppress_avg": _mean(row.get("gate_minus_current_suppress") for row in actions),
        "positive_gate_lift_rate": _positive_rate(row.get("gate_minus_baseline") for row in actions),
        "recovered_missed_win_count": sum(1 for row in paused if str(row.get("outcome_label")) == "missed_win"),
        "lost_avoided_loss_count": sum(1 for row in paused if str(row.get("outcome_label")) == "avoided_loss"),
        "paused_outcome_labels": dict(sorted(Counter(str(row.get("outcome_label")) for row in paused).items())),
    }


def _current_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "avg_paper_minus_baseline": _mean(row.get("paper_minus_baseline") for row in rows),
        "positive_paper_lift_rate": _positive_rate(row.get("paper_minus_baseline") for row in rows),
        "outcome_labels": dict(sorted(Counter(str(row.get("outcome_label")) for row in rows).items())),
    }


def _rolling(actions: list[dict[str, Any]], *, rolling_window: int, min_window: int) -> dict[str, Any]:
    ordered = sorted(actions, key=lambda row: _float(row.get("timestamp"), 0.0))
    windows: list[dict[str, Any]] = []
    for start in range(0, len(ordered), max(1, int(rolling_window))):
        items = ordered[start : start + int(rolling_window)]
        if len(items) < int(min_window):
            continue
        windows.append(_rolling_window_metrics(items))
    deltas = [row["gate_minus_current_suppress_avg"] for row in windows if row.get("gate_minus_current_suppress_avg") is not None]
    positive = sum(1 for value in deltas if value >= 0.0)
    return {
        "window_count": len(windows),
        "positive_improvement_window_count": positive,
        "positive_improvement_window_rate": _rate(positive, len(deltas)),
        "min_gate_minus_current_suppress_avg": min(deltas) if deltas else None,
        "max_gate_minus_current_suppress_avg": max(deltas) if deltas else None,
        "windows": windows,
    }


def _rolling_window_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(items),
        "start_timestamp": items[0].get("timestamp"),
        "end_timestamp": items[-1].get("timestamp"),
        "gate_minus_current_suppress_avg": _mean(row.get("gate_minus_current_suppress") for row in items),
        "avg_gate_minus_baseline": _mean(row.get("gate_minus_baseline") for row in items),
        "recovered_missed_win_count": sum(1 for row in items if bool(row.get("paused", False)) and str(row.get("outcome_label")) == "missed_win"),
        "lost_avoided_loss_count": sum(1 for row in items if bool(row.get("paused", False)) and str(row.get("outcome_label")) == "avoided_loss"),
    }


def _failure_reasons(gate: Mapping[str, Any], *, rolling_stable: bool, min_cell_improvement: float, max_lost_avoided: int) -> list[str]:
    reasons: list[str] = []
    if int(gate.get("count") or 0) <= 0:
        return ["no_active_changed_rows"]
    if _float(gate.get("gate_minus_current_suppress_avg"), 0.0) <= float(min_cell_improvement):
        reasons.append("no_positive_gate_improvement")
    if int(gate.get("lost_avoided_loss_count") or 0) > int(max_lost_avoided):
        reasons.append("lost_avoided_losses")
    if int(gate.get("recovered_missed_win_count") or 0) <= 0:
        reasons.append("no_recovered_missed_wins")
    if not rolling_stable:
        reasons.append("rolling_not_stable")
    return reasons


def _active_changed_rows(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [
            dict(record)
            for record in records
            if record.get("outcome_label") != "unlabeled"
            and bool(record.get("paper_active", False))
            and bool(record.get("selection_changed", False))
        ],
        key=lambda row: _float(row.get("timestamp"), 0.0),
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
        gate = dict(cell.get("gate", {}))
        rows.append(
            {
                "horizon_bars": cell.get("horizon_bars"),
                "fee_bps": cell.get("fee_bps"),
                "count": gate.get("count"),
                "gate_minus_current_suppress_avg": gate.get("gate_minus_current_suppress_avg"),
                "avg_gate_minus_baseline": gate.get("avg_gate_minus_baseline"),
                "recovered_missed_win_count": gate.get("recovered_missed_win_count"),
                "lost_avoided_loss_count": gate.get("lost_avoided_loss_count"),
            }
        )
    return sorted(rows, key=lambda row: _float(row.get("gate_minus_current_suppress_avg"), 0.0), reverse=True)


def _worst_rolling_window(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    rows = []
    for cell in cells:
        for window_name, rolling in dict(cell.get("rolling", {})).items():
            for window in dict(rolling).get("windows", []):
                row = dict(window)
                row["horizon_bars"] = cell.get("horizon_bars")
                row["fee_bps"] = cell.get("fee_bps")
                row["rolling_window"] = int(window_name)
                rows.append(row)
    if not rows:
        return None
    return sorted(rows, key=lambda row: _float(row.get("gate_minus_current_suppress_avg"), 0.0))[0]


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


__all__ = ["build_pa_paper_dg_matrix_report", "render_pa_paper_dg_matrix_markdown"]
