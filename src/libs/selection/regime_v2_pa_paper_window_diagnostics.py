"""Failure-window diagnostics for PA paper robustness.

Phase 6S explains the worst rolling window instead of changing rollout state.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping


def build_pa_paper_window_diagnostic_report(
    labeled_records: Iterable[Mapping[str, Any]],
    *,
    window: Mapping[str, Any],
    min_changed_rows: int = 10,
    include_rows: int = 25,
) -> dict[str, Any]:
    """Explain the worst active-changed PA paper window."""
    rows = [dict(record) for record in labeled_records if record.get("outcome_label") != "unlabeled"]
    active_changed = [row for row in rows if bool(row.get("paper_active", False)) and bool(row.get("selection_changed", False))]
    start_ts = _float(window.get("start_timestamp"), None)
    end_ts = _float(window.get("end_timestamp"), None)
    failure_rows = [row for row in active_changed if _in_window(row, start_ts=start_ts, end_ts=end_ts)]
    before_rows = [row for row in active_changed if start_ts is not None and _float(row.get("timestamp"), 0.0) < start_ts]
    after_rows = [row for row in active_changed if end_ts is not None and _float(row.get("timestamp"), 0.0) > end_ts]
    all_metrics = _segment_metrics(active_changed, name="all_active_changed")
    failure_metrics = _segment_metrics(failure_rows, name="failure_window")
    before_metrics = _segment_metrics(before_rows, name="before_failure_window")
    after_metrics = _segment_metrics(after_rows, name="after_failure_window")
    diagnosis = _diagnosis(
        failure_metrics,
        failure_rows=failure_rows,
        min_changed_rows=int(min_changed_rows),
    )
    return {
        "phase": "phase_6s_pa_paper_failure_window_diagnostics",
        "summary": {
            "window_start_timestamp": start_ts,
            "window_end_timestamp": end_ts,
            "horizon_bars": window.get("horizon_bars"),
            "fee_bps": window.get("fee_bps"),
            "rolling_window": window.get("rolling_window"),
            "total_labeled_records": len(rows),
            "active_changed_count": len(active_changed),
            "failure_window_count": len(failure_rows),
            "min_changed_rows": int(min_changed_rows),
            "failure_avg_paper_minus_baseline": failure_metrics.get("avg_paper_minus_baseline"),
            "failure_positive_lift_rate": failure_metrics.get("positive_paper_lift_rate"),
            "failure_avoided_loss_count": failure_metrics.get("avoided_loss_count"),
            "failure_missed_win_count": failure_metrics.get("missed_win_count"),
            "diagnosis": diagnosis,
            "recommendation": _recommendation(diagnosis),
        },
        "window": dict(window),
        "segments": {
            "all_active_changed": all_metrics,
            "before_failure_window": before_metrics,
            "failure_window": failure_metrics,
            "after_failure_window": after_metrics,
        },
        "failure_rows": _row_summaries(failure_rows, limit=int(include_rows)),
    }


def render_pa_paper_window_diagnostic_markdown(report: Mapping[str, Any]) -> str:
    """Render compact Markdown for failure-window diagnostics."""
    summary = dict(report.get("summary", {}))
    segments = dict(report.get("segments", {}))
    lines = [
        "# RegimeV2 Phase 6S PA Paper Failure Window Diagnostics",
        "",
        "## Summary",
        "",
        f"- Window: {summary.get('window_start_timestamp')} → {summary.get('window_end_timestamp')}",
        f"- Horizon bars: {summary.get('horizon_bars')}",
        f"- Fee bps: {summary.get('fee_bps')}",
        f"- Rolling window: {summary.get('rolling_window')}",
        f"- Failure rows: {summary.get('failure_window_count')}",
        f"- Failure avg lift: {summary.get('failure_avg_paper_minus_baseline')}",
        f"- Failure positive lift rate: {summary.get('failure_positive_lift_rate')}",
        f"- Failure avoided/missed: {summary.get('failure_avoided_loss_count')} / {summary.get('failure_missed_win_count')}",
        f"- Diagnosis: {summary.get('diagnosis')}",
        f"- Recommendation: {summary.get('recommendation')}",
        "",
        "## Segments",
        "",
        "| Segment | Count | Avg lift | Positive rate | Avoided | Missed | Avg baseline score | Avg edge | Avg conviction |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("before_failure_window", "failure_window", "after_failure_window", "all_active_changed"):
        row = dict(segments.get(name, {}))
        lines.append(
            "| {name} | {count} | {lift} | {positive} | {avoided} | {missed} | {score} | {edge} | {conviction} |".format(
                name=name,
                count=row.get("count"),
                lift=row.get("avg_paper_minus_baseline"),
                positive=row.get("positive_paper_lift_rate"),
                avoided=row.get("avoided_loss_count"),
                missed=row.get("missed_win_count"),
                score=row.get("avg_baseline_selection_score"),
                edge=row.get("avg_baseline_edge_score"),
                conviction=row.get("avg_baseline_conviction"),
            )
        )
    lines.extend(["", "## Failure Rows", "", "| Timestamp | Label | Baseline net | Paper net | Lift | Score | Edge | Conviction |", "|---:|---|---:|---:|---:|---:|---:|---:|"])
    for row in report.get("failure_rows", []):
        lines.append(
            "| {timestamp} | {label} | {baseline} | {paper} | {lift} | {score} | {edge} | {conviction} |".format(
                timestamp=row.get("timestamp"),
                label=row.get("outcome_label"),
                baseline=row.get("baseline_net_return"),
                paper=row.get("paper_net_return"),
                lift=row.get("paper_minus_baseline"),
                score=row.get("baseline_selection_score"),
                edge=row.get("baseline_edge_score"),
                conviction=row.get("baseline_conviction"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def worst_window_from_robustness(robustness_report: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the worst rolling window from a robustness report."""
    summary = dict(robustness_report.get("summary", {}))
    window = dict(summary.get("worst_rolling_window") or {})
    if not window:
        return {}
    return window


def _segment_metrics(records: list[dict[str, Any]], *, name: str) -> dict[str, Any]:
    labels = Counter(str(row.get("outcome_label")) for row in records)
    paper_top = Counter(_paper_top_model(row) for row in records)
    return {
        "name": name,
        "count": len(records),
        "avg_baseline_net_return": _mean(row.get("baseline_net_return") for row in records),
        "avg_paper_net_return": _mean(row.get("paper_net_return") for row in records),
        "avg_paper_minus_baseline": _mean(row.get("paper_minus_baseline") for row in records),
        "positive_paper_lift_rate": _positive_rate(row.get("paper_minus_baseline") for row in records),
        "avoided_loss_count": int(labels.get("avoided_loss", 0)),
        "missed_win_count": int(labels.get("missed_win", 0)),
        "outcome_labels": dict(sorted(labels.items())),
        "paper_top_models": dict(sorted(paper_top.items())),
        "avg_baseline_selection_score": _mean(row.get("baseline_selection_score") for row in records),
        "avg_baseline_edge_score": _mean(row.get("baseline_edge_score") for row in records),
        "avg_baseline_conviction": _mean(row.get("baseline_conviction") for row in records),
        "avg_forward_log_return": _mean(row.get("forward_log_return") for row in records),
    }


def _diagnosis(segment: Mapping[str, Any], *, failure_rows: list[dict[str, Any]], min_changed_rows: int) -> list[str]:
    reasons: list[str] = []
    count = int(segment.get("count") or 0)
    avg_lift = _float(segment.get("avg_paper_minus_baseline"), None)
    avoided = int(segment.get("avoided_loss_count") or 0)
    missed = int(segment.get("missed_win_count") or 0)
    if count < int(min_changed_rows):
        reasons.append("insufficient_window_sample")
    if avg_lift is not None and avg_lift < 0.0:
        reasons.append("negative_window_lift")
    if missed > avoided:
        reasons.append("missed_wins_dominate")
    if failure_rows and all(_paper_top_model(row) == "None" for row in failure_rows):
        reasons.append("flat_after_suppression")
    if failure_rows and _positive_rate(row.get("baseline_net_return") for row in failure_rows) and _positive_rate(row.get("baseline_net_return") for row in failure_rows) > 0.5:
        reasons.append("baseline_price_action_worked_in_window")
    return reasons or ["no_failure_detected"]


def _recommendation(diagnosis: list[str]) -> str:
    hard = {"negative_window_lift", "missed_wins_dominate", "baseline_price_action_worked_in_window"}
    if hard.intersection(diagnosis) and "insufficient_window_sample" not in diagnosis:
        return "hold_off_and_investigate_window"
    if hard.intersection(diagnosis):
        return "continue_monitoring_insufficient_window_sample"
    return "continue_monitoring"


def _row_summaries(records: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    rows = sorted(records, key=lambda row: _float(row.get("timestamp"), 0.0) or 0.0)
    return [
        {
            "timestamp": row.get("timestamp"),
            "outcome_label": row.get("outcome_label"),
            "baseline_net_return": row.get("baseline_net_return"),
            "paper_net_return": row.get("paper_net_return"),
            "paper_minus_baseline": row.get("paper_minus_baseline"),
            "forward_log_return": row.get("forward_log_return"),
            "baseline_selection_score": row.get("baseline_selection_score"),
            "baseline_edge_score": row.get("baseline_edge_score"),
            "baseline_conviction": row.get("baseline_conviction"),
            "paper_top_model": _paper_top_model(row),
        }
        for row in rows[:limit]
    ]


def _paper_top_model(row: Mapping[str, Any]) -> str:
    ranked = row.get("paper_ranked_candidates")
    if isinstance(ranked, list) and ranked and isinstance(ranked[0], dict):
        return str(ranked[0].get("model_name"))
    model = row.get("paper_selected_model")
    return str(model) if model is not None else "None"


def _in_window(row: Mapping[str, Any], *, start_ts: float | None, end_ts: float | None) -> bool:
    ts = _float(row.get("timestamp"), None)
    if ts is None:
        return False
    if start_ts is not None and ts < start_ts:
        return False
    if end_ts is not None and ts > end_ts:
        return False
    return True


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


__all__ = [
    "build_pa_paper_window_diagnostic_report",
    "render_pa_paper_window_diagnostic_markdown",
    "worst_window_from_robustness",
]
