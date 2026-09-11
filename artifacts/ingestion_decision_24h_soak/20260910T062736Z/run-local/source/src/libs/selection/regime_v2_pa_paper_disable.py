"""Disable recommendation layer for PA paper monitoring.

Phase 6P turns monitor metrics into explicit recommendations. It never edits
configuration and never disables anything by itself.
"""

from __future__ import annotations

from typing import Any, Mapping

_HARD_FLAGS = {"negative_avg_lift", "missed_wins_exceed_avoided_losses"}
_DEFAULT_ACTION_WINDOWS = (24, 168)


def build_pa_paper_disable_report(
    monitor_report: Mapping[str, Any],
    *,
    min_changed_rows: int | None = None,
    action_windows_hours: tuple[int, ...] = _DEFAULT_ACTION_WINDOWS,
    include_all_time_for_disable: bool = True,
) -> dict[str, Any]:
    """Build a non-mutating disable/pause recommendation from a monitor report."""
    monitor_summary = dict(monitor_report.get("summary", {}))
    floor = int(min_changed_rows if min_changed_rows is not None else monitor_summary.get("min_changed_rows", 10) or 10)
    all_time = dict(monitor_report.get("all_time", {}))
    windows = [dict(row) for row in monitor_report.get("windows", [])]
    segments = []
    if include_all_time_for_disable:
        segments.append(_evaluate_segment(all_time, floor=floor, role="all_time"))
    for row in windows:
        role = "action_window" if int(row.get("window_hours") or 0) in set(action_windows_hours) else "observation_window"
        segments.append(_evaluate_segment(row, floor=floor, role=role))

    hard_failures = [row for row in segments if row["hard_failure"]]
    actionable_failures = [row for row in hard_failures if row["enough_sample"] and row["role"] in {"all_time", "action_window"}]
    insufficient_failures = [row for row in hard_failures if not row["enough_sample"]]
    low_sample_segments = [row for row in segments if not row["enough_sample"]]
    recommendation = _recommendation(actionable_failures, insufficient_failures)
    return {
        "phase": "phase_6p_pa_paper_disable_recommendation",
        "summary": {
            "recommendation": recommendation,
            "disable_recommended": recommendation == "disable_paper_observation",
            "pause_recommended": recommendation == "pause_for_review",
            "min_changed_rows": floor,
            "action_windows_hours": list(action_windows_hours),
            "include_all_time_for_disable": bool(include_all_time_for_disable),
            "segment_count": len(segments),
            "hard_failure_count": len(hard_failures),
            "actionable_failure_count": len(actionable_failures),
            "insufficient_failure_count": len(insufficient_failures),
            "low_sample_segment_count": len(low_sample_segments),
            "monitor_overall_status": monitor_summary.get("overall_status"),
        },
        "segments": segments,
        "actionable_failures": actionable_failures,
        "insufficient_failures": insufficient_failures,
    }


def render_pa_paper_disable_markdown(report: Mapping[str, Any]) -> str:
    """Render compact Markdown for PA paper disable recommendations."""
    summary = dict(report.get("summary", {}))
    lines = [
        "# RegimeV2 Phase 6P PA Paper Disable Recommendation",
        "",
        "## Summary",
        "",
        f"- Recommendation: {summary.get('recommendation')}",
        f"- Disable recommended: {summary.get('disable_recommended')}",
        f"- Pause recommended: {summary.get('pause_recommended')}",
        f"- Actionable failures: {summary.get('actionable_failure_count', 0)}",
        f"- Insufficient failures: {summary.get('insufficient_failure_count', 0)}",
        f"- Low-sample segments: {summary.get('low_sample_segment_count', 0)}",
        "",
        "## Segments",
        "",
        "| Name | Role | Changed | Enough sample | Avg lift | Avoided | Missed | Action | Reasons |",
        "|---|---|---:|---|---:|---:|---:|---|---|",
    ]
    for row in report.get("segments", []):
        lines.append(
            "| {name} | {role} | {count} | {enough} | {lift} | {avoided} | {missed} | {action} | {reasons} |".format(
                name=row.get("name"),
                role=row.get("role"),
                count=row.get("active_changed_count"),
                enough=row.get("enough_sample"),
                lift=row.get("avg_paper_minus_baseline"),
                avoided=row.get("avoided_loss_count"),
                missed=row.get("missed_win_count"),
                action=row.get("action"),
                reasons=", ".join(row.get("reasons", [])),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _evaluate_segment(segment: Mapping[str, Any], *, floor: int, role: str) -> dict[str, Any]:
    active_changed_count = _int_value(segment.get("active_changed_count"), 0)
    avg_lift = _float(segment.get("avg_paper_minus_baseline"), None)
    avoided = _int_value(segment.get("avoided_loss_count"), 0)
    missed = _int_value(segment.get("missed_win_count"), 0)
    enough = active_changed_count >= int(floor)
    reasons = []
    if not enough:
        reasons.append("insufficient_changed_sample")
    if avg_lift is not None and avg_lift < 0.0:
        reasons.append("negative_avg_lift")
    if missed > avoided:
        reasons.append("missed_wins_exceed_avoided_losses")
    hard_failure = bool(set(reasons).intersection(_HARD_FLAGS))
    if hard_failure and enough and role in {"all_time", "action_window"}:
        action = "disable_paper_observation" if role == "all_time" else "pause_for_review"
    elif hard_failure and not enough:
        action = "continue_monitoring_insufficient_sample"
    else:
        action = "continue_monitoring"
    return {
        "name": segment.get("name") or _name_for_segment(segment, role),
        "role": role,
        "window_hours": segment.get("window_hours"),
        "active_changed_count": active_changed_count,
        "enough_sample": enough,
        "avg_paper_minus_baseline": avg_lift,
        "avoided_loss_count": avoided,
        "missed_win_count": missed,
        "monitor_flags": list(segment.get("monitor_flags", [])),
        "reasons": reasons,
        "hard_failure": hard_failure,
        "action": action,
    }


def _recommendation(actionable_failures: list[dict[str, Any]], insufficient_failures: list[dict[str, Any]]) -> str:
    if any(row.get("action") == "disable_paper_observation" for row in actionable_failures):
        return "disable_paper_observation"
    if any(row.get("action") == "pause_for_review" for row in actionable_failures):
        return "pause_for_review"
    if insufficient_failures:
        return "continue_monitoring_insufficient_sample"
    return "continue_monitoring"


def _name_for_segment(segment: Mapping[str, Any], role: str) -> str:
    if segment.get("window_hours") is not None:
        return f"last_{segment.get('window_hours')}h"
    return role


def _int_value(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float | None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = ["build_pa_paper_disable_report", "render_pa_paper_disable_markdown"]
