"""Runtime monitoring report for PA paper outcome streams.

Phase 6O monitors the paper-only PriceAction guardrail after observation has
started. It does not disable anything; automatic disable rules are deferred to
Phase 6P.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping, Sequence

_DEFAULT_WINDOWS_HOURS = (24, 168, 720)


def build_pa_paper_monitor_report(
    records: Iterable[Mapping[str, Any]],
    *,
    windows_hours: Sequence[int] = _DEFAULT_WINDOWS_HOURS,
    min_changed_rows: int = 10,
) -> dict[str, Any]:
    """Build all-time and recent-window monitoring metrics for PA paper outcomes."""
    rows = [dict(record) for record in records]
    labeled = [row for row in rows if row.get("outcome_label") != "unlabeled"]
    timestamps = [_float(row.get("timestamp"), None) for row in labeled]
    timestamps = [ts for ts in timestamps if ts is not None]
    latest_ts = max(timestamps) if timestamps else None
    windows = [
        _window_report(
            labeled,
            latest_ts=latest_ts,
            hours=int(hours),
            min_changed_rows=int(min_changed_rows),
        )
        for hours in windows_hours
    ]
    all_time = _segment_metrics(labeled, name="all_time", min_changed_rows=int(min_changed_rows))
    return {
        "phase": "phase_6o_pa_paper_monitor",
        "summary": {
            "total_records": len(rows),
            "labeled_count": len(labeled),
            "unlabeled_count": len(rows) - len(labeled),
            "latest_timestamp": latest_ts,
            "window_count": len(windows),
            "min_changed_rows": int(min_changed_rows),
            "overall_status": _overall_status(all_time, windows),
            "all_time_changed_count": all_time["changed_count"],
            "all_time_active_changed_count": all_time["active_changed_count"],
            "all_time_avg_paper_minus_baseline": all_time["avg_paper_minus_baseline"],
            "all_time_changed_positive_rate": all_time["changed_positive_paper_lift_rate"],
        },
        "all_time": all_time,
        "windows": windows,
    }


def render_pa_paper_monitor_markdown(report: Mapping[str, Any]) -> str:
    """Render compact Markdown for PA paper monitoring."""
    summary = dict(report.get("summary", {}))
    all_time = dict(report.get("all_time", {}))
    lines = [
        "# RegimeV2 Phase 6O PA Paper Monitor",
        "",
        "## Summary",
        "",
        f"- Total records: {summary.get('total_records', 0)}",
        f"- Labeled: {summary.get('labeled_count', 0)}",
        f"- Unlabeled: {summary.get('unlabeled_count', 0)}",
        f"- Latest timestamp: {summary.get('latest_timestamp')}",
        f"- Overall status: {summary.get('overall_status')}",
        f"- All-time changed rows: {summary.get('all_time_changed_count', 0)}",
        f"- All-time avg paper-minus-baseline: {summary.get('all_time_avg_paper_minus_baseline')}",
        f"- All-time changed positive rate: {summary.get('all_time_changed_positive_rate')}",
        "",
        "## All Time",
        "",
        f"- Paper active: {all_time.get('paper_active_count', 0)}",
        f"- Selection changed: {all_time.get('changed_count', 0)}",
        f"- Active changed: {all_time.get('active_changed_count', 0)}",
        f"- Avoided losses: {all_time.get('avoided_loss_count', 0)}",
        f"- Missed wins: {all_time.get('missed_win_count', 0)}",
        f"- Monitor flags: {all_time.get('monitor_flags', [])}",
        "",
        "## Windows",
        "",
        "| Window | Rows | Changed | Active changed | Avg lift | Positive rate | Avoided | Missed | Status | Flags |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in report.get("windows", []):
        lines.append(
            "| {hours}h | {rows} | {changed} | {active_changed} | {lift} | {positive} | {avoided} | {missed} | {status} | {flags} |".format(
                hours=row.get("window_hours"),
                rows=row.get("count"),
                changed=row.get("changed_count"),
                active_changed=row.get("active_changed_count"),
                lift=row.get("avg_paper_minus_baseline"),
                positive=row.get("changed_positive_paper_lift_rate"),
                avoided=row.get("avoided_loss_count"),
                missed=row.get("missed_win_count"),
                status=row.get("status"),
                flags=", ".join(row.get("monitor_flags", [])),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _window_report(
    records: list[dict[str, Any]],
    *,
    latest_ts: float | None,
    hours: int,
    min_changed_rows: int,
) -> dict[str, Any]:
    if latest_ts is None:
        rows: list[dict[str, Any]] = []
        start_ts = None
    else:
        start_ts = latest_ts - float(hours) * 3600.0
        rows = [row for row in records if _float(row.get("timestamp"), -1.0) >= start_ts]
    metrics = _segment_metrics(rows, name=f"last_{hours}h", min_changed_rows=min_changed_rows)
    metrics["window_hours"] = int(hours)
    metrics["start_timestamp"] = start_ts
    metrics["end_timestamp"] = latest_ts
    return metrics


def _segment_metrics(records: list[dict[str, Any]], *, name: str, min_changed_rows: int) -> dict[str, Any]:
    paper_active = [row for row in records if bool(row.get("paper_active", False))]
    changed = [row for row in records if bool(row.get("selection_changed", False))]
    active_changed = [row for row in paper_active if bool(row.get("selection_changed", False))]
    labels = Counter(str(row.get("outcome_label")) for row in active_changed)
    avg_lift = _mean(row.get("paper_minus_baseline") for row in active_changed)
    positive_rate = _positive_rate(row.get("paper_minus_baseline") for row in active_changed)
    flags = _monitor_flags(
        active_changed_count=len(active_changed),
        avoided_loss_count=int(labels.get("avoided_loss", 0)),
        missed_win_count=int(labels.get("missed_win", 0)),
        avg_lift=avg_lift,
        min_changed_rows=int(min_changed_rows),
    )
    return {
        "name": name,
        "count": len(records),
        "paper_active_count": len(paper_active),
        "changed_count": len(changed),
        "active_changed_count": len(active_changed),
        "avg_baseline_net_return": _mean(row.get("baseline_net_return") for row in active_changed),
        "avg_paper_net_return": _mean(row.get("paper_net_return") for row in active_changed),
        "avg_paper_minus_baseline": avg_lift,
        "changed_positive_paper_lift_rate": positive_rate,
        "avoided_loss_count": int(labels.get("avoided_loss", 0)),
        "missed_win_count": int(labels.get("missed_win", 0)),
        "outcome_labels": dict(sorted(labels.items())),
        "monitor_flags": flags,
        "status": "watch" if flags else "ok",
    }


def _monitor_flags(
    *,
    active_changed_count: int,
    avoided_loss_count: int,
    missed_win_count: int,
    avg_lift: float | None,
    min_changed_rows: int,
) -> list[str]:
    flags: list[str] = []
    if active_changed_count < min_changed_rows:
        flags.append("low_changed_sample")
    if avg_lift is not None and avg_lift < 0.0:
        flags.append("negative_avg_lift")
    if missed_win_count > avoided_loss_count:
        flags.append("missed_wins_exceed_avoided_losses")
    return flags


def _overall_status(all_time: Mapping[str, Any], windows: list[Mapping[str, Any]]) -> str:
    hard_flags = {"negative_avg_lift", "missed_wins_exceed_avoided_losses"}
    for segment in [all_time, *windows]:
        if hard_flags.intersection(set(segment.get("monitor_flags", []))):
            return "watch"
    return "ok"


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


__all__ = ["build_pa_paper_monitor_report", "render_pa_paper_monitor_markdown"]
