"""Tests for Phase 6V PA paper drift-gate matrix validation."""

from __future__ import annotations

from libs.models.regime_v2.scripts.pa_paper_dg_matrix import _parse_args
from libs.selection import regime_v2_pa_paper_dg_matrix as matrix
from libs.selection.regime_v2_pa_paper_dg_matrix import (
    build_pa_paper_dg_matrix_report,
    render_pa_paper_dg_matrix_markdown,
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


def test_dg_matrix_passes_when_gate_improves_without_lost_avoided(monkeypatch):
    rows = [
        _row(1.0, lift=-0.01, label="missed_win"),
        _row(2.0, lift=-0.02, label="missed_win"),
        _row(3.0, lift=-0.03, label="missed_win"),
    ]
    monkeypatch.setattr(matrix, "label_pa_paper_outcomes", lambda raw, _ohlcv, horizon_bars, fee_bps: [dict(row) for row in raw])

    report = build_pa_paper_dg_matrix_report(
        rows,
        {},
        horizons=(24,),
        fees_bps=(2.0,),
        rolling_windows=(3,),
        min_window=1,
        gate_spec={"name": "rolling_avg_neg_2", "kind": "rolling_avg_neg", "window": 2},
    )

    assert report["summary"]["passing_cell_count"] == 1
    assert report["summary"]["recommendation"] == "gate_validation_candidate"
    gate = report["cells"][0]["gate"]
    assert gate["recovered_missed_win_count"] == 1
    assert gate["lost_avoided_loss_count"] == 0
    assert gate["gate_minus_current_suppress_avg"] > 0.0


def test_dg_matrix_fails_when_gate_loses_avoided_loss(monkeypatch):
    rows = [
        _row(1.0, lift=-0.01, label="missed_win"),
        _row(2.0, lift=-0.02, label="missed_win"),
        _row(3.0, lift=0.03, label="avoided_loss"),
    ]
    monkeypatch.setattr(matrix, "label_pa_paper_outcomes", lambda raw, _ohlcv, horizon_bars, fee_bps: [dict(row) for row in raw])

    report = build_pa_paper_dg_matrix_report(
        rows,
        {},
        horizons=(24,),
        fees_bps=(2.0,),
        rolling_windows=(3,),
        min_window=1,
        gate_spec={"name": "rolling_avg_neg_2", "kind": "rolling_avg_neg", "window": 2},
    )

    assert report["summary"]["passing_cell_count"] == 0
    assert report["summary"]["recommendation"] == "hold_off"
    assert "lost_avoided_losses" in report["cells"][0]["failure_reasons"]


def test_dg_matrix_markdown_and_cli_args(monkeypatch):
    rows = [_row(1.0, lift=-0.01, label="missed_win")]
    monkeypatch.setattr(matrix, "label_pa_paper_outcomes", lambda raw, _ohlcv, horizon_bars, fee_bps: [dict(row) for row in raw])
    report = build_pa_paper_dg_matrix_report(rows, {}, horizons=(3,), fees_bps=(2.0,), rolling_windows=(1,), min_window=1)
    md = render_pa_paper_dg_matrix_markdown(report)
    assert "# RegimeV2 Phase 6V PA Paper Drift Gate Matrix" in md
    assert "## Cells" in md

    args = _parse_args(
        [
            "--log",
            "custom.jsonl",
            "--limit",
            "100",
            "--horizon",
            "3",
            "--horizon",
            "6",
            "--fee-bps",
            "2",
            "--rolling-window",
            "20",
            "--min-window",
            "5",
            "--min-cell-improvement",
            "0.001",
            "--max-lost-avoided",
            "1",
            "--min-rolling-positive-rate",
            "0.75",
            "--output-json",
            "out.json",
            "--output-md",
            "out.md",
        ]
    )
    assert args.log == "custom.jsonl"
    assert args.limit == 100
    assert args.horizon == [3, 6]
    assert args.fee_bps == [2.0]
    assert args.rolling_window == [20]
    assert args.min_window == 5
    assert args.min_cell_improvement == 0.001
    assert args.max_lost_avoided == 1
    assert args.min_rolling_positive_rate == 0.75

    defaults = _parse_args([])
    assert defaults.horizon == [3, 6, 12, 24]
    assert defaults.fee_bps == [2.0, 5.0, 10.0]
    assert defaults.rolling_window == [20, 30, 50]
