"""Tests for Phase 6K PA paper reports and outcomes."""

from __future__ import annotations

import json

import pandas as pd

from libs.models.regime_v2.scripts.pa_paper_label import _parse_args as _parse_label_args
from libs.models.regime_v2.scripts.pa_paper_report import _parse_args as _parse_report_args
from libs.selection.regime_v2_pa_paper_report import (
    build_pa_paper_outcome_report,
    build_pa_paper_report,
    label_pa_paper_outcomes,
    load_pa_paper_decisions,
    render_pa_paper_outcome_report_markdown,
    render_pa_paper_report_markdown,
    write_labeled_pa_paper_outcomes,
)


def _record(timestamp: float = 1000.0, *, paper_direction: int | None = None) -> dict:
    return {
        "schema_version": 1,
        "record_type": "regime_v2_pa_asset_paper_decision",
        "asset": "BNBUSDT",
        "timeframe": "1h",
        "timestamp": timestamp,
        "paper_active": True,
        "paper_reason": "price_action_asset_direction_suppressed",
        "target_model": "PriceAction",
        "target_asset": "BNBUSDT",
        "target_timeframe": "1h",
        "target_direction": 1,
        "suppressed_count": 1,
        "suppressed_models": ["PriceAction"],
        "baseline_selected_model": "PriceAction",
        "paper_selected_model": "Momentum" if paper_direction else None,
        "baseline_selected_direction": 1,
        "paper_selected_direction": paper_direction,
        "baseline_selection_score": 0.9,
        "paper_selection_score": 0.5 if paper_direction else None,
        "edge_delta": -0.4 if paper_direction else None,
        "selection_changed": True,
        "paper_selected_count": 1 if paper_direction else 0,
        "candidate_count": 2,
    }


def _ohlcv() -> pd.DataFrame:
    index = pd.to_datetime([1000.0, 1001.0, 1002.0, 1003.0], unit="s", utc=True)
    return pd.DataFrame(
        {
            "open": [100.0, 90.0, 80.0, 70.0],
            "high": [101.0, 91.0, 81.0, 71.0],
            "low": [99.0, 89.0, 79.0, 69.0],
            "close": [100.0, 90.0, 80.0, 70.0],
            "volume": [1.0, 1.0, 1.0, 1.0],
        },
        index=index,
    )


def test_load_pa_paper_decisions_handles_missing_and_invalid(tmp_path):
    missing, invalid = load_pa_paper_decisions(tmp_path / "missing.jsonl")
    assert missing == []
    assert invalid == 0

    path = tmp_path / "paper.jsonl"
    path.write_text(json.dumps(_record()) + "\nnot-json\n", encoding="utf-8")
    records, invalid = load_pa_paper_decisions(path)
    assert len(records) == 1
    assert invalid == 1


def test_build_pa_paper_report_and_markdown():
    report = build_pa_paper_report([_record(), {**_record(), "paper_active": False, "selection_changed": False}])

    assert report["summary"]["records_after_filter"] == 2
    assert report["summary"]["paper_active_count"] == 1
    assert report["summary"]["selection_changed_count"] == 1
    assert report["distributions"]["baseline_model"] == {"PriceAction": 2}
    md = render_pa_paper_report_markdown(report)
    assert "# RegimeV2 Phase 6K PA Paper Decision Report" in md
    assert "## Model Pair Summary" in md


def test_label_pa_paper_outcomes_maps_paper_fields():
    labeled = label_pa_paper_outcomes(
        [_record(timestamp=1000.0, paper_direction=None), _record(timestamp=1001.0, paper_direction=1)],
        {("BNBUSDT", "1h"): _ohlcv()},
        horizon_bars=1,
        fee_bps=0.0,
    )

    assert labeled[0]["outcome_label"] == "avoided_loss"
    assert labeled[0]["paper_net_return"] == 0.0
    assert labeled[0]["paper_minus_baseline"] > 0.0
    assert labeled[1]["paper_selected_model"] == "Momentum"
    assert "shadow_net_return" not in labeled[0]


def test_write_and_build_pa_paper_outcome_report(tmp_path):
    labeled = label_pa_paper_outcomes(
        [_record(timestamp=1000.0, paper_direction=None)],
        {("BNBUSDT", "1h"): _ohlcv()},
        horizon_bars=1,
        fee_bps=0.0,
    )
    out = tmp_path / "outcomes.jsonl"
    result = write_labeled_pa_paper_outcomes(labeled, out)
    assert result == out
    assert len(out.read_text().splitlines()) == 1

    report = build_pa_paper_outcome_report(labeled, source_path=str(out))
    assert report["summary"]["labeled_count"] == 1
    assert report["summary"]["avg_paper_minus_baseline"] > 0.0
    md = render_pa_paper_outcome_report_markdown(report)
    assert "# RegimeV2 Phase 6K PA Paper Outcome Report" in md


def test_pa_paper_report_cli_defaults_and_args():
    args = _parse_report_args(["--log", "custom.jsonl", "--asset", "BNBUSDT", "--timeframe", "1h"])
    assert args.log == "custom.jsonl"
    assert args.asset == "BNBUSDT"
    assert args.timeframe == "1h"

    defaults = _parse_report_args([])
    assert defaults.output_json.endswith("pa_paper_report.json")
    assert defaults.output_md.endswith("pa_paper_report.md")


def test_pa_paper_label_cli_defaults_and_args():
    args = _parse_label_args(["--log", "custom.jsonl", "--limit", "900", "--horizon-bars", "6", "--fee-bps", "2"])
    assert args.log == "custom.jsonl"
    assert args.limit == 900
    assert args.horizon_bars == 6
    assert args.fee_bps == 2.0

    defaults = _parse_label_args([])
    assert defaults.horizon_bars == 12
    assert defaults.fee_bps == 5.0
