"""Tests for Phase 6U PA paper drift/streak gate simulation."""

from __future__ import annotations

from libs.models.regime_v2.scripts.pa_paper_drift_gate import _parse_args
from libs.selection.regime_v2_pa_paper_drift_gate import (
    build_pa_paper_drift_gate_report,
    render_pa_paper_drift_gate_markdown,
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
    }


def test_missed_streak_gate_recovers_next_missed_win():
    rows = [
        _row(1.0, lift=-0.01, label="missed_win"),
        _row(2.0, lift=-0.02, label="missed_win"),
        _row(3.0, lift=-0.03, label="missed_win"),
    ]

    report = build_pa_paper_drift_gate_report(
        rows,
        gate_specs=({"name": "missed_streak_2", "kind": "missed_streak", "missed_streak": 2},),
    )

    gate = report["candidate_gates"][0]
    assert gate["paused_count"] == 1
    assert gate["recovered_missed_win_count"] == 1
    assert gate["gate_minus_current_suppress_avg"] > 0.0
    assert report["summary"]["recommendation"] == "candidate_drift_gate_found"


def test_rolling_avg_gate_can_pause_failure_window():
    rows = [
        _row(1.0, lift=0.02, label="avoided_loss"),
        _row(2.0, lift=-0.02, label="missed_win"),
        _row(3.0, lift=-0.02, label="missed_win"),
        _row(4.0, lift=-0.02, label="missed_win"),
    ]

    report = build_pa_paper_drift_gate_report(
        rows,
        failure_window={"start_timestamp": 3.0, "end_timestamp": 4.0},
        gate_specs=({"name": "rolling_avg_neg_2", "kind": "rolling_avg_neg", "window": 2},),
    )

    gate = report["candidate_gates"][0]
    assert gate["paused_count"] >= 1
    assert gate["failure_window_pause_rate"] is not None
    assert gate["recovered_missed_win_count"] >= 1


def test_drift_gate_markdown_and_cli_args():
    report = build_pa_paper_drift_gate_report(
        [_row(1.0, lift=0.01, label="avoided_loss")],
        gate_specs=({"name": "missed_streak_2", "kind": "missed_streak", "missed_streak": 2},),
    )
    md = render_pa_paper_drift_gate_markdown(report)
    assert "# RegimeV2 Phase 6U PA Paper Drift Gate Simulation" in md
    assert "## Candidate Gates" in md

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
            "--min-paused-rows",
            "2",
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
    assert args.min_paused_rows == 2
