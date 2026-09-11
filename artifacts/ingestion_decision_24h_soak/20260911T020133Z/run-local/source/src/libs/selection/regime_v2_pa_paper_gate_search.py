"""Offline search over PA paper pause-rule variants."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from libs.selection.regime_v2_pa_paper_report import label_pa_paper_outcomes

HORIZONS = (3, 6, 12, 24)
FEES = (2.0, 5.0, 10.0)
ROLLING_WINDOWS = (20, 30, 50)
GATES = (
    {"name": "rolling_avg_neg_3", "kind": "rolling_avg_neg", "window": 3},
    {"name": "miss_gt_avoid_3", "kind": "miss_gt_avoid", "window": 3},
    {"name": "missed_streak_2", "kind": "missed_streak", "missed_streak": 2},
    {"name": "rolling_avg_neg_3_and_miss_gt_avoid_3", "kind": "and", "rules": ("rolling_avg_neg_3", "miss_gt_avoid_3")},
    {"name": "rolling_avg_neg_3_and_missed_streak_2", "kind": "and", "rules": ("rolling_avg_neg_3", "missed_streak_2")},
    {"name": "rolling_avg_below_002_3", "kind": "rolling_avg_below", "window": 3, "threshold": -0.002},
    {"name": "rolling_avg_below_005_3", "kind": "rolling_avg_below", "window": 3, "threshold": -0.005},
    {"name": "rolling_avg_below_002_5", "kind": "rolling_avg_below", "window": 5, "threshold": -0.002},
)
ALIASES = {
    "rolling_avg_neg_3": {"kind": "rolling_avg_neg", "window": 3},
    "miss_gt_avoid_3": {"kind": "miss_gt_avoid", "window": 3},
    "missed_streak_2": {"kind": "missed_streak", "missed_streak": 2},
}


def build_pa_paper_gate_search_report(
    records: Iterable[Mapping[str, Any]],
    ohlcv_by_pair: Mapping[tuple[str, str], pd.DataFrame],
    *,
    horizons: Sequence[int] = HORIZONS,
    fees_bps: Sequence[float] = FEES,
    rolling_windows: Sequence[int] = ROLLING_WINDOWS,
    min_window: int = 10,
    gate_specs: Sequence[Mapping[str, Any]] = GATES,
    max_lost_avoided: int = 0,
) -> dict[str, Any]:
    raw = [dict(r) for r in records]
    cells = {
        (int(h), float(f)): label_pa_paper_outcomes(raw, ohlcv_by_pair, horizon_bars=int(h), fee_bps=float(f))
        for h in horizons
        for f in fees_bps
    }
    variants = [_variant(spec, cells, rolling_windows=rolling_windows, min_window=min_window, max_lost_avoided=max_lost_avoided) for spec in gate_specs]
    variants.sort(key=lambda r: (r["passing_cell_count"], r["no_lost_avoided_cell_count"], r["avg_improvement"], r["total_recovered"], -r["total_lost_avoided"]), reverse=True)
    best = variants[0] if variants else None
    return {
        "phase": "phase_6w_pa_paper_gate_search",
        "summary": {
            "total_records": len(raw),
            "variant_count": len(variants),
            "cell_count": len(cells),
            "max_lost_avoided": int(max_lost_avoided),
            "best_variant": _summary(best),
            "ready_variant_count": sum(1 for v in variants if v["matrix_ready"]),
            "recommendation": "gate_variant_ready" if best and best["matrix_ready"] else "hold_off_refine_more",
        },
        "variants": variants,
    }


def render_pa_paper_gate_search_markdown(report: Mapping[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 6W PA Paper Gate Search",
        "",
        "## Summary",
        "",
        f"- Variants: {summary.get('variant_count', 0)}",
        f"- Cells per variant: {summary.get('cell_count', 0)}",
        f"- Ready variants: {summary.get('ready_variant_count', 0)}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Best variant: {summary.get('best_variant')}",
        "",
        "## Variants",
        "",
        "| Variant | Pass | Improved | No lost | Rolling stable | Avg improvement | Recovered | Lost avoided | Ready |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("variants", []):
        lines.append(
            f"| {row.get('name')} | {row.get('passing_cell_count')}/{row.get('cell_count')} | {row.get('improved_cell_count')} | {row.get('no_lost_avoided_cell_count')} | {row.get('rolling_stable_cell_count')} | {row.get('avg_improvement')} | {row.get('total_recovered')} | {row.get('total_lost_avoided')} | {row.get('matrix_ready')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _variant(spec: Mapping[str, Any], labeled_cells: Mapping[tuple[int, float], list[dict[str, Any]]], *, rolling_windows: Sequence[int], min_window: int, max_lost_avoided: int) -> dict[str, Any]:
    cells = [_cell(rows, h, f, spec, rolling_windows=rolling_windows, min_window=min_window, max_lost_avoided=max_lost_avoided) for (h, f), rows in sorted(labeled_cells.items())]
    cell_count = len(cells)
    passing = sum(1 for c in cells if c["status"] == "pass")
    return {
        "name": str(spec.get("name")),
        "spec": dict(spec),
        "cell_count": cell_count,
        "passing_cell_count": passing,
        "improved_cell_count": sum(1 for c in cells if c["gate"]["improvement"] > 0.0),
        "no_lost_avoided_cell_count": sum(1 for c in cells if c["gate"]["lost_avoided"] <= max_lost_avoided),
        "rolling_stable_cell_count": sum(1 for c in cells if c["rolling_stable"]),
        "avg_improvement": _mean(c["gate"]["improvement"] for c in cells),
        "total_recovered": sum(c["gate"]["recovered"] for c in cells),
        "total_lost_avoided": sum(c["gate"]["lost_avoided"] for c in cells),
        "matrix_ready": cell_count > 0 and passing == cell_count,
        "best_cell": _best(cells),
        "worst_cell": _worst(cells),
        "cells": cells,
    }


def _cell(rows: list[dict[str, Any]], horizon: int, fee: float, spec: Mapping[str, Any], *, rolling_windows: Sequence[int], min_window: int, max_lost_avoided: int) -> dict[str, Any]:
    data = _active_changed(rows)
    actions = _actions(data, spec)
    gate = _gate_metrics(actions)
    rolling = {str(w): _rolling(actions, int(w), min_window) for w in rolling_windows}
    rolling_stable = all((r["min_improvement"] or 0.0) >= 0.0 for r in rolling.values() if r["window_count"] > 0)
    reasons = []
    if gate["improvement"] <= 0.0:
        reasons.append("no_positive_improvement")
    if gate["lost_avoided"] > max_lost_avoided:
        reasons.append("lost_avoided_losses")
    if gate["recovered"] <= 0:
        reasons.append("no_recovered_missed_wins")
    if not rolling_stable:
        reasons.append("rolling_not_stable")
    return {"horizon_bars": int(horizon), "fee_bps": float(fee), "gate": gate, "rolling": rolling, "rolling_stable": rolling_stable, "failure_reasons": reasons, "status": "pass" if not reasons else "fail"}


def _actions(rows: list[dict[str, Any]], spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    prior: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    for row in rows:
        paused = _paused(prior, spec)
        base = _float(row.get("baseline_net_return"), 0.0)
        paper = _float(row.get("paper_net_return"), 0.0)
        gate_net = base if paused else paper
        out.append({"timestamp": row.get("timestamp"), "paused": paused, "label": row.get("outcome_label"), "paper_lift": _float(row.get("paper_minus_baseline"), 0.0), "gate_lift": gate_net - base, "improvement": gate_net - paper})
        prior.append(row)
    return out


def _paused(prior: list[dict[str, Any]], spec: Mapping[str, Any]) -> bool:
    kind = str(spec.get("kind"))
    if kind == "rolling_avg_neg":
        window = int(spec.get("window") or 3)
        return len(prior) >= window and _roll_avg(prior, window) < 0.0
    if kind == "rolling_avg_below":
        window = int(spec.get("window") or 3)
        return len(prior) >= window and _roll_avg(prior, window) <= _float(spec.get("threshold"), -0.002)
    if kind == "miss_gt_avoid":
        window = int(spec.get("window") or 3)
        if len(prior) < window:
            return False
        labels = Counter(str(r.get("outcome_label")) for r in prior[-window:])
        return labels.get("missed_win", 0) > labels.get("avoided_loss", 0)
    if kind == "missed_streak":
        streak = int(spec.get("missed_streak") or 2)
        return len(prior) >= streak and all(str(r.get("outcome_label")) == "missed_win" for r in prior[-streak:])
    if kind == "and":
        return all(_paused(prior, ALIASES.get(str(rule), {"kind": rule})) for rule in spec.get("rules", ()))
    return False


def _gate_metrics(actions: list[dict[str, Any]]) -> dict[str, Any]:
    paused = [a for a in actions if a["paused"]]
    return {"count": len(actions), "paused": len(paused), "gate_lift": _mean(a["gate_lift"] for a in actions), "current_lift": _mean(a["paper_lift"] for a in actions), "improvement": _mean(a["improvement"] for a in actions) or 0.0, "recovered": sum(1 for a in paused if str(a["label"]) == "missed_win"), "lost_avoided": sum(1 for a in paused if str(a["label"]) == "avoided_loss"), "paused_labels": dict(sorted(Counter(str(a["label"]) for a in paused).items()))}


def _rolling(actions: list[dict[str, Any]], window: int, min_window: int) -> dict[str, Any]:
    ordered = sorted(actions, key=lambda a: _float(a.get("timestamp"), 0.0))
    chunks = []
    for start in range(0, len(ordered), max(1, window)):
        items = ordered[start : start + window]
        if len(items) >= min_window:
            chunks.append({"count": len(items), "start_timestamp": items[0].get("timestamp"), "end_timestamp": items[-1].get("timestamp"), "improvement": _mean(a["improvement"] for a in items), "recovered": sum(1 for a in items if a["paused"] and str(a["label"]) == "missed_win"), "lost_avoided": sum(1 for a in items if a["paused"] and str(a["label"]) == "avoided_loss")})
    vals = [c["improvement"] for c in chunks if c["improvement"] is not None]
    return {"window_count": len(chunks), "min_improvement": min(vals) if vals else None, "max_improvement": max(vals) if vals else None, "windows": chunks}


def _active_changed(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return sorted([dict(r) for r in rows if r.get("outcome_label") != "unlabeled" and bool(r.get("paper_active", False)) and bool(r.get("selection_changed", False))], key=lambda r: _float(r.get("timestamp"), 0.0))


def _roll_avg(rows: list[dict[str, Any]], window: int) -> float:
    vals = [_float(r.get("paper_minus_baseline"), 0.0) for r in rows[-window:]]
    return sum(vals) / len(vals) if vals else 0.0


def _summary(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {"name": row.get("name"), "passing_cell_count": row.get("passing_cell_count"), "cell_count": row.get("cell_count"), "avg_improvement": row.get("avg_improvement"), "total_recovered": row.get("total_recovered"), "total_lost_avoided": row.get("total_lost_avoided"), "matrix_ready": row.get("matrix_ready")}


def _best(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    return _rank(cells)[0] if cells else None


def _worst(cells: list[dict[str, Any]]) -> dict[str, Any] | None:
    return _rank(cells)[-1] if cells else None


def _rank(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted([{"horizon_bars": c["horizon_bars"], "fee_bps": c["fee_bps"], "improvement": c["gate"]["improvement"], "recovered": c["gate"]["recovered"], "lost_avoided": c["gate"]["lost_avoided"], "status": c["status"]} for c in cells], key=lambda r: _float(r.get("improvement"), 0.0), reverse=True)


def _mean(values: Iterable[Any]) -> float | None:
    vals = []
    for value in values:
        try:
            if value is not None:
                vals.append(float(value))
        except (TypeError, ValueError):
            continue
    return sum(vals) / len(vals) if vals else None


def _float(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = ["build_pa_paper_gate_search_report", "render_pa_paper_gate_search_markdown"]
