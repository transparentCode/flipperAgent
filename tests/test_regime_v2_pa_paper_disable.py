"""Tests for Phase 6P PA paper disable recommendations."""

from __future__ import annotations

from libs.models.regime_v2.scripts.pa_paper_disable import _parse_args
from libs.selection.regime_v2_pa_paper_disable import (
    build_pa_paper_disable_report,
    render_pa_paper_disable_markdown,
)


def _monitor(*, all_lift: float = 0.02, window_lift: float = 0.01, window_count: int = 12, missed: int = 2) -> dict:
    return {
        "summary": {"min_changed_rows": 10, "overall_status": "ok"},
        "all_time": {
            "name": "all_time",
            "active_changed_count": 40,
            "avg_paper_minus_baseline": all_lift,
            "avoided_loss_count": 30,
            "missed_win_count": 10,
            "monitor_flags": [],
        },
        "windows": [
            {
                "name": "last_24h",
                "window_hours": 24,
                "active_changed_count": window_count,
                "avg_paper_minus_baseline": window_lift,
                "avoided_loss_count": max(0, window_count - missed),
                "missed_win_count": missed,
                "monitor_flags": [],
            },
            {
                "name": "last_720h",
                "window_hours": 720,
                "active_changed_count": 40,
                "avg_paper_minus_baseline": all_lift,
                "avoided_loss_count": 30,
                "missed_win_count": 10,
                "monitor_flags": [],
            },
        ],
    }


def test_disable_report_continue_monitoring_when_clean():
    report = build_pa_paper_disable_report(_monitor())

    assert report["summary"]["recommendation"] == "continue_monitoring"
    assert report["summary"]["disable_recommended"] is False
    assert report["summary"]["pause_recommended"] is False
    assert report["summary"]["actionable_failure_count"] == 0


def test_disable_report_insufficient_sample_does_not_pause():
    report = build_pa_paper_disable_report(_monitor(window_lift=-0.01, window_count=3, missed=3))

    assert report["summary"]["recommendation"] == "continue_monitoring_insufficient_sample"
    assert report["summary"]["pause_recommended"] is False
    assert report["summary"]["disable_recommended"] is False
    assert report["summary"]["insufficient_failure_count"] == 1
    last_24h = [row for row in report["segments"] if row["name"] == "last_24h"][0]
    assert last_24h["action"] == "continue_monitoring_insufficient_sample"


def test_disable_report_pauses_when_action_window_has_sufficient_failure():
    report = build_pa_paper_disable_report(_monitor(window_lift=-0.01, window_count=12, missed=8))

    assert report["summary"]["recommendation"] == "pause_for_review"
    assert report["summary"]["pause_recommended"] is True
    assert report["summary"]["disable_recommended"] is False
    assert report["summary"]["actionable_failure_count"] == 1


def test_disable_report_disables_when_all_time_fails():
    report = build_pa_paper_disable_report(_monitor(all_lift=-0.01, window_lift=0.01, window_count=12))

    assert report["summary"]["recommendation"] == "disable_paper_observation"
    assert report["summary"]["disable_recommended"] is True
    all_time = [row for row in report["segments"] if row["role"] == "all_time"][0]
    assert all_time["action"] == "disable_paper_observation"


def test_disable_report_can_exclude_all_time_from_disable():
    report = build_pa_paper_disable_report(
        _monitor(all_lift=-0.01, window_lift=0.01, window_count=12),
        include_all_time_for_disable=False,
    )

    assert report["summary"]["recommendation"] == "continue_monitoring"
    assert all(row["role"] != "all_time" for row in report["segments"])


def test_disable_markdown_and_cli_args():
    report = build_pa_paper_disable_report(_monitor(window_lift=-0.01, window_count=3, missed=3))
    md = render_pa_paper_disable_markdown(report)
    assert "# RegimeV2 Phase 6P PA Paper Disable Recommendation" in md
    assert "continue_monitoring_insufficient_sample" in md

    args = _parse_args(
        [
            "--monitor",
            "monitor.json",
            "--min-changed-rows",
            "5",
            "--action-window-hours",
            "24",
            "--action-window-hours",
            "168",
            "--exclude-all-time",
            "--output-json",
            "out.json",
            "--output-md",
            "out.md",
        ]
    )
    assert args.monitor == "monitor.json"
    assert args.min_changed_rows == 5
    assert args.action_window_hours == [24, 168]
    assert args.exclude_all_time is True
    assert args.output_json == "out.json"
    assert args.output_md == "out.md"

    defaults = _parse_args([])
    assert defaults.action_window_hours == [24, 168]
