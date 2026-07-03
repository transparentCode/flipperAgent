"""Tests for Phase 6S PA paper failure-window diagnostics."""

from __future__ import annotations

from libs.models.regime_v2.scripts.pa_paper_window_diag import _parse_args
from libs.selection.regime_v2_pa_paper_window_diagnostics import (
    build_pa_paper_window_diagnostic_report,
    render_pa_paper_window_diagnostic_markdown,
    worst_window_from_robustness,
)


def _row(timestamp: float, *, lift: float, label: str) -> dict:
    return {
        "timestamp": timestamp,
        "paper_active": True,
        "selection_changed": True,
        "outcome_label": label,
        "baseline_net_return": -lift,
        "paper_net_return": 0.0,
        "paper_minus_baseline": lift,
        "forward_log_return": lift,
        "baseline_selection_score": 0.5,
        "baseline_edge_score": 0.7,
        "baseline_conviction": 0.8,
        "paper_selected_model": None,
        "paper_ranked_candidates": [],
    }


def test_window_diagnostic_detects_negative_failure_window():
    rows = [
        _row(1000.0, lift=0.02, label="avoided_loss"),
        _row(2000.0, lift=-0.01, label="missed_win"),
        _row(2001.0, lift=-0.02, label="missed_win"),
        _row(3000.0, lift=0.03, label="avoided_loss"),
    ]
    window = {"start_timestamp": 1999.0, "end_timestamp": 2002.0, "horizon_bars": 24, "fee_bps": 2.0, "rolling_window": 30}

    report = build_pa_paper_window_diagnostic_report(rows, window=window, min_changed_rows=2)

    assert report["summary"]["failure_window_count"] == 2
    assert report["summary"]["failure_avg_paper_minus_baseline"] < 0.0
    assert "negative_window_lift" in report["summary"]["diagnosis"]
    assert "missed_wins_dominate" in report["summary"]["diagnosis"]
    assert "flat_after_suppression" in report["summary"]["diagnosis"]
    assert report["summary"]["recommendation"] == "hold_off_and_investigate_window"


def test_window_diagnostic_insufficient_window_sample():
    report = build_pa_paper_window_diagnostic_report(
        [_row(2000.0, lift=-0.01, label="missed_win")],
        window={"start_timestamp": 1999.0, "end_timestamp": 2001.0},
        min_changed_rows=2,
    )

    assert "insufficient_window_sample" in report["summary"]["diagnosis"]
    assert report["summary"]["recommendation"] == "continue_monitoring_insufficient_window_sample"


def test_worst_window_extraction_markdown_and_cli_args():
    robustness = {"summary": {"worst_rolling_window": {"start_timestamp": 1.0, "end_timestamp": 2.0}}}
    assert worst_window_from_robustness(robustness) == {"start_timestamp": 1.0, "end_timestamp": 2.0}

    report = build_pa_paper_window_diagnostic_report(
        [_row(1000.0, lift=0.01, label="avoided_loss")],
        window={"start_timestamp": 999.0, "end_timestamp": 1001.0},
        min_changed_rows=1,
    )
    md = render_pa_paper_window_diagnostic_markdown(report)
    assert "# RegimeV2 Phase 6S PA Paper Failure Window Diagnostics" in md
    assert "## Failure Rows" in md

    args = _parse_args(
        [
            "--log",
            "custom.jsonl",
            "--robustness",
            "robust.json",
            "--limit",
            "100",
            "--start-timestamp",
            "1",
            "--end-timestamp",
            "2",
            "--horizon-bars",
            "24",
            "--fee-bps",
            "2",
            "--min-changed-rows",
            "5",
            "--include-rows",
            "7",
            "--output-json",
            "out.json",
            "--output-md",
            "out.md",
        ]
    )
    assert args.log == "custom.jsonl"
    assert args.robustness == "robust.json"
    assert args.limit == 100
    assert args.start_timestamp == 1.0
    assert args.end_timestamp == 2.0
    assert args.horizon_bars == 24
    assert args.fee_bps == 2.0
    assert args.min_changed_rows == 5
    assert args.include_rows == 7
