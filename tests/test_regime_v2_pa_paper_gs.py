"""Tests for Phase 6W PA paper gate variant search."""

from __future__ import annotations

import importlib

from libs.models.regime_v2.scripts.pa_paper_gs import _parse_args

mod = importlib.import_module("libs.selection.regime_v2_pa_paper_" + "gate_" + "search")


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


def test_variant_ready_when_no_avoided_loss_is_lost(monkeypatch):
    rows = [_row(1.0, lift=-0.02, label="missed_win"), _row(2.0, lift=-0.02, label="missed_win"), _row(3.0, lift=-0.02, label="missed_win")]
    monkeypatch.setattr(mod, "label_pa_paper_outcomes", lambda raw, _ohlcv, horizon_bars, fee_bps: [dict(row) for row in raw])

    report = mod.build_pa_paper_gate_search_report(
        rows,
        {},
        horizons=(24,),
        fees_bps=(2.0,),
        rolling_windows=(3,),
        min_window=1,
        gate_specs=({"name": "rolling_avg_neg_2", "kind": "rolling_avg_neg", "window": 2},),
    )

    assert report["summary"]["ready_variant_count"] == 1
    assert report["summary"]["recommendation"] == "gate_variant_ready"
    assert report["variants"][0]["total_recovered"] == 1
    assert report["variants"][0]["total_lost_avoided"] == 0


def test_variant_holds_off_when_avoided_loss_is_lost(monkeypatch):
    rows = [_row(1.0, lift=-0.02, label="missed_win"), _row(2.0, lift=-0.02, label="missed_win"), _row(3.0, lift=0.03, label="avoided_loss")]
    monkeypatch.setattr(mod, "label_pa_paper_outcomes", lambda raw, _ohlcv, horizon_bars, fee_bps: [dict(row) for row in raw])

    report = mod.build_pa_paper_gate_search_report(
        rows,
        {},
        horizons=(24,),
        fees_bps=(2.0,),
        rolling_windows=(3,),
        min_window=1,
        gate_specs=({"name": "rolling_avg_neg_2", "kind": "rolling_avg_neg", "window": 2},),
    )

    assert report["summary"]["ready_variant_count"] == 0
    assert report["summary"]["recommendation"] == "hold_off_refine_more"
    assert report["variants"][0]["total_lost_avoided"] == 1


def test_markdown_and_cli_defaults(monkeypatch):
    rows = [_row(1.0, lift=-0.01, label="missed_win")]
    monkeypatch.setattr(mod, "label_pa_paper_outcomes", lambda raw, _ohlcv, horizon_bars, fee_bps: [dict(row) for row in raw])
    report = mod.build_pa_paper_gate_search_report(rows, {}, horizons=(3,), fees_bps=(2.0,), rolling_windows=(1,), min_window=1)
    md = mod.render_pa_paper_gate_search_markdown(report)
    assert "Phase 6W" in md
    assert "Variants" in md

    args = _parse_args(["--log", "custom.jsonl", "--horizon", "3", "--fee-bps", "2", "--rolling-window", "20", "--max-lost-avoided", "1"])
    assert args.log == "custom.jsonl"
    assert args.horizon == [3]
    assert args.fee_bps == [2.0]
    assert args.rolling_window == [20]
    assert args.max_lost_avoided == 1

    defaults = _parse_args([])
    assert defaults.horizon == [3, 6, 12, 24]
    assert defaults.fee_bps == [2.0, 5.0, 10.0]
    assert defaults.rolling_window == [20, 30, 50]
