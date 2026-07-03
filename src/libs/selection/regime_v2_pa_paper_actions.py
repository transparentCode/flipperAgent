"""Compare PA paper guardrail action variants.

Phase 6Q compares the current suppress/reselect paper action with simpler
position-size alternatives. It uses already labeled paper outcomes and does not
change runtime behavior.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

_DEFAULT_SCALES = (0.25, 0.5, 0.75)


def build_pa_paper_action_report(
    records: Iterable[Mapping[str, Any]],
    *,
    scales: Sequence[float] = _DEFAULT_SCALES,
    changed_only: bool = True,
) -> dict[str, Any]:
    """Compare action variants on labeled PA paper rows."""
    rows = [dict(record) for record in records if record.get("outcome_label") != "unlabeled"]
    cohort = [row for row in rows if _in_action_cohort(row, changed_only=changed_only)]
    actions = [_action_metrics("keep_baseline", cohort, _baseline_net)]
    actions.append(_action_metrics("suppress_to_paper", cohort, _paper_net))
    for scale in scales:
        actions.append(_action_metrics(f"scale_baseline_{scale:g}", cohort, lambda row, s=float(scale): _scaled_baseline_net(row, s)))
    ranked = sorted(actions, key=lambda row: _float(row.get("avg_action_minus_baseline"), float("-inf")), reverse=True)
    best = ranked[0] if ranked else None
    current = next((row for row in actions if row.get("action") == "suppress_to_paper"), None)
    return {
        "phase": "phase_6q_pa_paper_action_comparison",
        "summary": {
            "total_records": len(rows),
            "cohort_count": len(cohort),
            "changed_only": bool(changed_only),
            "action_count": len(actions),
            "best_action": best.get("action") if best else None,
            "best_avg_action_minus_baseline": best.get("avg_action_minus_baseline") if best else None,
            "current_action": "suppress_to_paper",
            "current_avg_action_minus_baseline": current.get("avg_action_minus_baseline") if current else None,
            "current_rank": _rank_for_action(ranked, "suppress_to_paper"),
            "recommendation": _recommendation(best, current),
        },
        "actions": ranked,
    }


def render_pa_paper_action_markdown(report: Mapping[str, Any]) -> str:
    """Render compact Markdown for the action comparison report."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 6Q PA Paper Action Comparison",
        "",
        "## Summary",
        "",
        f"- Cohort rows: {summary.get('cohort_count', 0)}",
        f"- Best action: {summary.get('best_action')}",
        f"- Best avg lift: {summary.get('best_avg_action_minus_baseline')}",
        f"- Current action: {summary.get('current_action')}",
        f"- Current avg lift: {summary.get('current_avg_action_minus_baseline')}",
        f"- Current rank: {summary.get('current_rank')}",
        f"- Recommendation: {summary.get('recommendation')}",
        "",
        "## Actions",
        "",
        "| Action | Count | Avg action return | Avg lift | Positive lift rate | Avoided | Missed | Labels |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("actions", []):
        lines.append(
            "| {action} | {count} | {avg_return} | {avg_lift} | {positive} | {avoided} | {missed} | {labels} |".format(
                action=row.get("action"),
                count=row.get("count"),
                avg_return=row.get("avg_action_net_return"),
                avg_lift=row.get("avg_action_minus_baseline"),
                positive=row.get("positive_action_lift_rate"),
                avoided=row.get("avoided_loss_count"),
                missed=row.get("missed_win_count"),
                labels=row.get("action_labels"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _in_action_cohort(row: Mapping[str, Any], *, changed_only: bool) -> bool:
    if changed_only:
        return bool(row.get("paper_active", False)) and bool(row.get("selection_changed", False))
    return bool(row.get("paper_active", False))


def _action_metrics(action: str, records: list[dict[str, Any]], action_fn) -> dict[str, Any]:
    rows = []
    labels = Counter()
    for row in records:
        baseline = _float(row.get("baseline_net_return"), None)
        if baseline is None:
            continue
        action_net = action_fn(row)
        if action_net is None:
            continue
        lift = action_net - baseline
        label = _action_label(baseline, action_net, lift)
        labels[label] += 1
        rows.append({"baseline": baseline, "action_net": action_net, "lift": lift, "label": label})
    return {
        "action": action,
        "count": len(rows),
        "avg_baseline_net_return": _mean(item["baseline"] for item in rows),
        "avg_action_net_return": _mean(item["action_net"] for item in rows),
        "avg_action_minus_baseline": _mean(item["lift"] for item in rows),
        "positive_action_lift_rate": _positive_rate(item["lift"] for item in rows),
        "avoided_loss_count": int(labels.get("avoided_loss", 0)),
        "missed_win_count": int(labels.get("missed_win", 0)),
        "action_labels": dict(sorted(labels.items())),
    }


def _action_label(baseline_net: float, action_net: float, lift: float) -> str:
    if abs(lift) <= 1e-15:
        return "unchanged"
    if lift > 0.0 and baseline_net < 0.0:
        return "avoided_loss"
    if lift < 0.0 and baseline_net > 0.0:
        return "missed_win"
    if lift > 0.0:
        return "improved_pick"
    return "worsened_pick"


def _baseline_net(row: Mapping[str, Any]) -> float | None:
    return _float(row.get("baseline_net_return"), None)


def _paper_net(row: Mapping[str, Any]) -> float | None:
    return _float(row.get("paper_net_return"), None)


def _scaled_baseline_net(row: Mapping[str, Any], scale: float) -> float | None:
    baseline = _float(row.get("baseline_net_return"), None)
    return None if baseline is None else baseline * float(scale)


def _recommendation(best: Mapping[str, Any] | None, current: Mapping[str, Any] | None) -> str:
    if not best or not current:
        return "insufficient_data"
    if best.get("action") == current.get("action"):
        return "keep_suppress_to_paper"
    best_lift = _float(best.get("avg_action_minus_baseline"), 0.0)
    current_lift = _float(current.get("avg_action_minus_baseline"), 0.0)
    if best_lift > current_lift:
        return f"consider_{best.get('action')}"
    return "keep_suppress_to_paper"


def _rank_for_action(ranked: list[Mapping[str, Any]], action: str) -> int | None:
    for idx, row in enumerate(ranked, start=1):
        if row.get("action") == action:
            return idx
    return None


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


def _float(value: Any, default: float | None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = ["build_pa_paper_action_report", "render_pa_paper_action_markdown"]
