"""Tests for Phase 6O PA paper monitor."""

from __future__ import annotations

from libs.models.regime_v2.scripts.pa_paper_monitor import _parse_args
from libs.selection.regime_v2_pa_paper_monitor import (
    build_pa_paper_monitor_report,
    render_pa_paper_monitor_markdown,
)


def _row(timestamp: float, *, lift: float, label: str, changed: bool = True) -> dict:
    return {
        "asset": "BNBUSDT",
        "timeframe": "1h",
        "timestamp": timestamp,
        "paper_active": True,
        "selection_changed": changed,
        "outcome_label": label,
        "baseline_net_return": -lift,
        "paper_net_return": 0.0,
        "paper_minus_baseline": lift,
    }


def test_pa_paper_monitor_reports_all_time_and_windows():
    rows = [
        _row(1000.0, lift=0.02, label="avoided_loss"),
        _row(2000.0, lift=0.01, label="avoided_loss"),
        _row(3000.0, lift=-0.005, label="missed_win"),
        {**_row(3001.0, lift=0.0, label="unchanged", changed=False), "paper_active": False},
    ]

    report = build_pa_paper_monitor_report(rows, windows_hours=(1,), min_changed_rows=2)

    assert report["summary"]["total_records"] == 4
    assert report["summary"]["labeled_count"] == 4
    assert report["summary"]["latest_timestamp"] == 3001.0
    assert report["all_time"]["active_changed_count"] == 3
    assert report["all_time"]["avoided_loss_count"] == 2
    assert report["all_time"]["missed_win_count"] == 1
    assert report["all_time"]["avg_paper_minus_baseline"] > 0.0
    assert report["windows"][0]["window_hours"] == 1
    assert report["windows"][0]["active_changed_count"] == 3


def test_pa_paper_monitor_flags_bad_recent_window():
    rows = [
        _row(1000.0, lift=-0.01, label="missed_win"),
        _row(1001.0, lift=-0.02, label="missed_win"),
    ]

    report = build_pa_paper_monitor_report(rows, windows_hours=(24,), min_changed_rows=2)

    assert report["summary"]["overall_status"] == "watch"
    assert "negative_avg_lift" in report["all_time"]["monitor_flags"]
    assert "missed_wins_exceed_avoided_losses" in report["all_time"]["monitor_flags"]
    assert report["windows"][0]["status"] == "watch"


def test_pa_paper_monitor_low_sample_flag_and_markdown():
    report = build_pa_paper_monitor_report(
        [_row(1000.0, lift=0.01, label="avoided_loss")],
        windows_hours=(24,),
        min_changed_rows=3,
    )

    assert "low_changed_sample" in report["all_time"]["monitor_flags"]
    md = render_pa_paper_monitor_markdown(report)
    assert "# RegimeV2 Phase 6O PA Paper Monitor" in md
    assert "## Windows" in md


def test_pa_paper_monitor_cli_args():
    args = _parse_args(
        [
            "--outcomes",
            "custom.jsonl",
            "--window-hours",
            "12",
            "--window-hours",
            "24",
            "--min-changed-rows",
            "5",
            "--output-json",
            "out.json",
            "--output-md",
            "out.md",
        ]
    )

    assert args.outcomes == "custom.jsonl"
    assert args.window_hours == [12, 24]
    assert args.min_changed_rows == 5
    assert args.output_json == "out.json"
    assert args.output_md == "out.md"

    defaults = _parse_args([])
    assert defaults.window_hours == [24, 168, 720]
    assert defaults.min_changed_rows == 10
