"""Tests for Phase 6T PA paper context-filter discovery."""

from __future__ import annotations

from libs.models.regime_v2.scripts.pa_paper_filter_discovery import _parse_args
from libs.selection.regime_v2_pa_paper_filter_discovery import (
    build_pa_paper_filter_discovery_report,
    render_pa_paper_filter_discovery_markdown,
)


def _row(timestamp: float, *, score: float, lift: float, label: str) -> dict:
    return {
        "timestamp": timestamp,
        "paper_active": True,
        "selection_changed": True,
        "outcome_label": label,
        "baseline_selection_score": score,
        "baseline_edge_score": score ** 0.5 if score >= 0 else score,
        "baseline_conviction": score ** 0.5 if score >= 0 else score,
        "paper_minus_baseline": lift,
        "forward_log_return": lift,
    }


def test_filter_discovery_finds_score_filter_for_failure_window():
    rows = [
        _row(1000.0, score=0.08, lift=0.03, label="avoided_loss"),
        _row(1001.0, score=0.09, lift=0.02, label="avoided_loss"),
        _row(1002.0, score=0.10, lift=0.02, label="avoided_loss"),
        _row(2000.0, score=0.001, lift=-0.01, label="missed_win"),
        _row(2001.0, score=0.002, lift=-0.02, label="missed_win"),
        _row(2002.0, score=0.003, lift=-0.01, label="missed_win"),
    ]

    report = build_pa_paper_filter_discovery_report(
        rows,
        failure_window={"start_timestamp": 1999.0, "end_timestamp": 2003.0},
        min_support=3,
        min_rejected_bad_rate=0.6,
        max_kept_bad_rate=0.1,
    )

    assert report["summary"]["candidate_filter_count"] >= 1
    assert report["summary"]["recommendation"] == "candidate_filter_found"
    assert report["summary"]["best_filter"]["rejected_bad_rate"] >= 0.6
    assert report["summary"]["best_filter"]["kept_bad_rate"] == 0.0


def test_filter_discovery_no_filter_when_failures_are_mixed():
    rows = [
        _row(1000.0, score=0.01, lift=0.02, label="avoided_loss"),
        _row(1001.0, score=0.02, lift=-0.02, label="missed_win"),
        _row(1002.0, score=0.03, lift=0.02, label="avoided_loss"),
        _row(1003.0, score=0.04, lift=-0.02, label="missed_win"),
    ]

    report = build_pa_paper_filter_discovery_report(
        rows,
        failure_window={"start_timestamp": 1000.0, "end_timestamp": 1003.0},
        min_support=2,
        min_rejected_bad_rate=0.9,
        max_kept_bad_rate=0.1,
    )

    assert report["summary"]["candidate_filter_count"] == 0
    assert report["summary"]["recommendation"] == "no_simple_filter_found"


def test_filter_discovery_markdown_and_cli_args():
    report = build_pa_paper_filter_discovery_report(
        [_row(1000.0, score=0.01, lift=0.01, label="avoided_loss")],
        failure_window={"start_timestamp": 999.0, "end_timestamp": 1001.0},
        min_support=1,
    )
    md = render_pa_paper_filter_discovery_markdown(report)
    assert "# RegimeV2 Phase 6T PA Paper Context Filter Discovery" in md
    assert "## Candidate Filters" in md

    args = _parse_args(
        [
            "--log",
            "custom.jsonl",
            "--robustness",
            "robust.json",
            "--limit",
            "100",
            "--default-horizon-bars",
            "24",
            "--default-fee-bps",
            "2",
            "--min-support",
            "3",
            "--min-rejected-bad-rate",
            "0.7",
            "--max-kept-bad-rate",
            "0.2",
            "--output-json",
            "out.json",
            "--output-md",
            "out.md",
        ]
    )
    assert args.log == "custom.jsonl"
    assert args.robustness == "robust.json"
    assert args.limit == 100
    assert args.default_horizon_bars == 24
    assert args.default_fee_bps == 2.0
    assert args.min_support == 3
    assert args.min_rejected_bad_rate == 0.7
    assert args.max_kept_bad_rate == 0.2
