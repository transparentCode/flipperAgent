"""Drift/streak gate simulation for PA paper suppression.

Phase 6U tests non-live pause rules for the PA suppress-to-flat action. The
simulation uses only prior active-changed rows to decide whether suppression
would be paused on the current row.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

_DEFAULT_GATES = (
    {"name": "missed_streak_2", "kind": "missed_streak", "missed_streak": 2},
    {"name": "missed_streak_3", "kind": "missed_streak", "missed_streak": 3},
    {"name": "rolling_avg_neg_3", "kind": "rolling_avg_neg", "window": 3},
    {"name": "rolling_avg_neg_5", "kind": "rolling_avg_neg", "window": 5},
    {"name": "rolling_avg_neg_10", "kind": "rolling_avg_neg", "window": 10},
    {"name": "miss_gt_avoid_3", "kind": "miss_gt_avoid", "window": 3},
    {"name": "miss_gt_avoid_5", "kind": "miss_gt_avoid", "window": 5},
    {"name": "miss_gt_avoid_10", "kind": "miss_gt_avoid", "window": 10},
)


def build_pa_paper_drift_gate_report(
    labeled_records: Iterable[Mapping[str, Any]],
    *,
    failure_window: Mapping[str, Any] | None = None,
    gate_specs: Sequence[Mapping[str, Any]] = _DEFAULT_GATES,
    min_paused_rows: int = 1,
) -> dict[str, Any]:
    """Build a non-live report ranking candidate drift/streak pause gates."""
    rows = _active_changed_rows(labeled_records)
    rows = _with_failure_window(rows, failure_window or {})
    baseline = _current_suppress_metrics(rows, name="current_suppress_to_paper")
    gates = [_simulate_gate(rows, spec) for spec in gate_specs]
    ranked = [row for row in gates if row.get("paused_count", 0) >= int(min_paused_rows)]
    ranked.sort(
        key=lambda row: (
            _float(row.get("gate_minus_current_suppress_avg"), 0.0),
            _float(row.get("failure_window_pause_rate"), 0.0),
            -_float(row.get("lost_avoided_loss_count"), 0.0),
        ),
        reverse=True,
    )
    best = ranked[0] if ranked else None
    return {
        "phase": "phase_6u_pa_paper_drift_gate_simulation",
        "summary": {
            "active_changed_count": len(rows),
            "candidate_gate_count": len(gates),
            "ranked_gate_count": len(ranked),
            "min_paused_rows": int(min_paused_rows),
            "current_avg_paper_minus_baseline": baseline.get("avg_paper_minus_baseline"),
            "best_gate": best,
            "recommendation": _recommendation(best),
        },
        "current_suppress_to_paper": baseline,
        "candidate_gates": ranked,
    }


def render_pa_paper_drift_gate_markdown(report: Mapping[str, Any]) -> str:
    """Render compact Markdown for drift/streak gate simulation."""
    summary = dict(report.get("summary", {}))
    current = dict(report.get("current_suppress_to_paper", {}))
    lines = [
        "# RegimeV2 Phase 6U PA Paper Drift Gate Simulation",
        "",
        "## Summary",
        "",
        f"- Active changed rows: {summary.get('active_changed_count', 0)}",
        f"- Candidate gates: {summary.get('candidate_gate_count', 0)}",
        f"- Ranked gates: {summary.get('ranked_gate_count', 0)}",
        f"- Current avg paper-minus-baseline: {summary.get('current_avg_paper_minus_baseline')}",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Best gate: {summary.get('best_gate')}",
        "",
        "## Current Suppression",
        "",
        f"- Count: {current.get('count', 0)}",
        f"- Avg lift: {current.get('avg_paper_minus_baseline')}",
        f"- Positive lift rate: {current.get('positive_paper_lift_rate')}",
        f"- Outcomes: {current.get('outcome_labels', {})}",
        "",
        "## Candidate Gates",
        "",
        "| Gate | Paused | Gate avg lift | Gate-current avg | Recovered missed | Lost avoided | Failure pause rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report.get("candidate_gates", []):
        lines.append(
            "| {name} | {paused} | {gate_lift} | {delta} | {recovered} | {lost} | {failure_rate} |".format(
                name=row.get("name"),
                paused=row.get("paused_count"),
                gate_lift=row.get("avg_gate_minus_baseline"),
                delta=row.get("gate_minus_current_suppress_avg"),
                recovered=row.get("recovered_missed_win_count"),
                lost=row.get("lost_avoided_loss_count"),
                failure_rate=row.get("failure_window_pause_rate"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _simulate_gate(rows: list[dict[str, Any]], spec: Mapping[str, Any]) -> dict[str, Any]:
    name = str(spec.get("name") or spec.get("kind") or "gate")
    actions = []
    prior: list[dict[str, Any]] = []
    for row in rows:
        paused = _gate_paused(prior, spec)
        baseline_net = _float(row.get("baseline_net_return"), 0.0)
        paper_net = _float(row.get("paper_net_return"), 0.0)
        gate_net = baseline_net if paused else paper_net
        actions.append(
            {
                "timestamp": row.get("timestamp"),
                "paused": paused,
                "outcome_label": row.get("outcome_label"),
                "in_failure_window": bool(row.get("in_failure_window", False)),
                "baseline_net_return": baseline_net,
                "paper_net_return": paper_net,
                "paper_minus_baseline": _float(row.get("paper_minus_baseline"), 0.0),
                "gate_net_return": gate_net,
                "gate_minus_baseline": gate_net - baseline_net,
                "gate_minus_current_suppress": gate_net - paper_net,
            }
        )
        prior.append(row)
    return _gate_metrics(name, spec, actions)


def _gate_paused(prior: list[dict[str, Any]], spec: Mapping[str, Any]) -> bool:
    kind = str(spec.get("kind") or "")
    if kind == "missed_streak":
        streak = int(spec.get("missed_streak") or 2)
        if len(prior) < streak:
            return False
        return all(str(row.get("outcome_label")) == "missed_win" for row in prior[-streak:])
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
    return False


def _gate_metrics(name: str, spec: Mapping[str, Any], actions: list[dict[str, Any]]) -> dict[str, Any]:
    paused = [row for row in actions if bool(row.get("paused", False))]
    failure_rows = [row for row in actions if bool(row.get("in_failure_window", False))]
    failure_paused = [row for row in paused if bool(row.get("in_failure_window", False))]
    return {
        "name": name,
        "spec": dict(spec),
        "count": len(actions),
        "paused_count": len(paused),
        "active_count": len(actions) - len(paused),
        "avg_gate_net_return": _mean(row.get("gate_net_return") for row in actions),
        "avg_gate_minus_baseline": _mean(row.get("gate_minus_baseline") for row in actions),
        "avg_current_suppress_minus_baseline": _mean(row.get("paper_minus_baseline") for row in actions),
        "gate_minus_current_suppress_avg": _mean(row.get("gate_minus_current_suppress") for row in actions),
        "positive_gate_lift_rate": _positive_rate(row.get("gate_minus_baseline") for row in actions),
        "recovered_missed_win_count": sum(1 for row in paused if str(row.get("outcome_label")) == "missed_win"),
        "lost_avoided_loss_count": sum(1 for row in paused if str(row.get("outcome_label")) == "avoided_loss"),
        "failure_window_count": len(failure_rows),
        "failure_window_paused_count": len(failure_paused),
        "failure_window_pause_rate": _rate(len(failure_paused), len(failure_rows)),
        "paused_outcome_labels": dict(sorted(Counter(str(row.get("outcome_label")) for row in paused).items())),
    }


def _current_suppress_metrics(rows: list[dict[str, Any]], *, name: str) -> dict[str, Any]:
    labels = Counter(str(row.get("outcome_label")) for row in rows)
    return {
        "name": name,
        "count": len(rows),
        "avg_baseline_net_return": _mean(row.get("baseline_net_return") for row in rows),
        "avg_paper_net_return": _mean(row.get("paper_net_return") for row in rows),
        "avg_paper_minus_baseline": _mean(row.get("paper_minus_baseline") for row in rows),
        "positive_paper_lift_rate": _positive_rate(row.get("paper_minus_baseline") for row in rows),
        "outcome_labels": dict(sorted(labels.items())),
    }


def _recommendation(best: Mapping[str, Any] | None) -> str:
    if not best:
        return "no_candidate_gate_found"
    if _float(best.get("gate_minus_current_suppress_avg"), 0.0) > 0.0:
        return "candidate_drift_gate_found"
    return "hold_off_no_improving_gate"


def _active_changed_rows(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        dict(record)
        for record in records
        if record.get("outcome_label") != "unlabeled"
        and bool(record.get("paper_active", False))
        and bool(record.get("selection_changed", False))
    ]
    return sorted(rows, key=lambda row: _float(row.get("timestamp"), 0.0))


def _with_failure_window(rows: list[dict[str, Any]], failure_window: Mapping[str, Any]) -> list[dict[str, Any]]:
    start_ts = _maybe_float(failure_window.get("start_timestamp"))
    end_ts = _maybe_float(failure_window.get("end_timestamp"))
    out = []
    for row in rows:
        item = dict(row)
        ts = _maybe_float(item.get("timestamp"))
        item["in_failure_window"] = ts is not None and (start_ts is None or ts >= start_ts) and (end_ts is None or ts <= end_ts)
        out.append(item)
    return out


def _mean(values: Iterable[Any]) -> float | None:
    nums = [_maybe_float(value) for value in values]
    nums = [value for value in nums if value is not None]
    return sum(nums) / len(nums) if nums else None


def _positive_rate(values: Iterable[Any]) -> float | None:
    nums = [_maybe_float(value) for value in values]
    nums = [value for value in nums if value is not None]
    return sum(1 for value in nums if value > 0.0) / len(nums) if nums else None


def _float(value: Any, default: float) -> float:
    parsed = _maybe_float(value)
    return default if parsed is None else parsed


def _maybe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _rate(numerator: int, denominator: int) -> float | None:
    return float(numerator) / float(denominator) if denominator > 0 else None


__all__ = ["build_pa_paper_drift_gate_report", "render_pa_paper_drift_gate_markdown"]
