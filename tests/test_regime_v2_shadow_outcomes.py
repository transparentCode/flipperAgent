"""Tests for RegimeV2 shadow outcome labeling."""

from __future__ import annotations

import json

import pandas as pd

from libs.models.regime_v2.scripts.label_shadow_outcomes_binance import _parse_args, _pairs_from_records
from libs.selection.regime_v2_shadow_outcomes import (
    build_shadow_outcome_report,
    label_shadow_decision_outcomes,
    load_labeled_shadow_outcomes,
    render_shadow_outcome_report_markdown,
    write_labeled_shadow_outcomes,
)


def _record(
    *,
    asset: str = "BTCUSDT",
    timeframe: str = "4h",
    timestamp: float = 1000.0,
    baseline_model: str = "PriceAction",
    shadow_model: str | None = None,
    baseline_direction: int | None = 1,
    shadow_direction: int | None = None,
    changed: bool = True,
    gate_active: bool = False,
    shadow_subset_only: bool = True,
    include_non_target_models: bool = False,
) -> dict:
    return {
        "schema_version": 1,
        "record_type": "regime_v2_shadow_decision",
        "asset": asset,
        "timeframe": timeframe,
        "timestamp": timestamp,
        "baseline_selected_model": baseline_model,
        "shadow_selected_model": shadow_model,
        "baseline_selected_direction": baseline_direction,
        "shadow_selected_direction": shadow_direction,
        "selection_changed": changed,
        "gate_active": gate_active,
        "gate_reason": "active" if gate_active else "inactive_playbook_policy",
        "shadow_subset_only": shadow_subset_only,
        "include_non_target_models": include_non_target_models,
        "target_models": ["Momentum", "TrendFollowing", "RegimePullbackScorer", "SqueezeBreakout"],
    }


def _ohlcv() -> pd.DataFrame:
    index = pd.to_datetime([1000.0, 1001.0, 1002.0, 1003.0], unit="s", utc=True)
    return pd.DataFrame(
        {
            "open": [100.0, 90.0, 95.0, 101.0],
            "high": [101.0, 91.0, 96.0, 102.0],
            "low": [99.0, 89.0, 94.0, 100.0],
            "close": [100.0, 90.0, 95.0, 101.0],
            "volume": [1.0, 1.0, 1.0, 1.0],
        },
        index=index,
    )


def test_label_shadow_decision_outcomes_marks_avoided_loss_when_shadow_flats_bad_long():
    labeled = label_shadow_decision_outcomes(
        [_record(timestamp=1000.0, baseline_direction=1, shadow_direction=None)],
        {("BTCUSDT", "4h"): _ohlcv()},
        horizon_bars=1,
    )

    row = labeled[0]
    assert row["outcome_label"] == "avoided_loss"
    assert row["baseline_net_return"] < 0.0
    assert row["shadow_net_return"] == 0.0
    assert row["shadow_minus_baseline"] > 0.0
    assert row["subset_only_changed"] is True


def test_label_shadow_decision_outcomes_marks_missed_win_when_shadow_flats_good_long():
    labeled = label_shadow_decision_outcomes(
        [_record(timestamp=1001.0, baseline_direction=1, shadow_direction=None)],
        {("BTCUSDT", "4h"): _ohlcv()},
        horizon_bars=2,
    )

    row = labeled[0]
    assert row["outcome_label"] == "missed_win"
    assert row["baseline_net_return"] > 0.0
    assert row["shadow_minus_baseline"] < 0.0


def test_label_shadow_decision_outcomes_marks_improved_pick_when_shadow_direction_better():
    labeled = label_shadow_decision_outcomes(
        [
            _record(
                timestamp=1000.0,
                baseline_model="Momentum",
                shadow_model="SqueezeBreakout",
                baseline_direction=1,
                shadow_direction=-1,
                gate_active=True,
                shadow_subset_only=True,
                include_non_target_models=False,
            )
        ],
        {("BTCUSDT", "4h"): _ohlcv()},
        horizon_bars=1,
    )

    row = labeled[0]
    assert row["outcome_label"] == "avoided_loss"
    assert row["shadow_net_return"] > row["baseline_net_return"]
    assert row["subset_only_changed"] is False


def test_build_shadow_outcome_report_aggregates_labeled_rows():
    labeled = label_shadow_decision_outcomes(
        [
            _record(timestamp=1000.0, baseline_direction=1, shadow_direction=None),
            _record(timestamp=1001.0, baseline_direction=1, shadow_direction=None),
        ],
        {("BTCUSDT", "4h"): _ohlcv()},
        horizon_bars=1,
    )

    report = build_shadow_outcome_report(labeled, source_path="outcomes.jsonl")

    assert report["summary"]["total_records_read"] == 2
    assert report["summary"]["labeled_count"] == 2
    assert report["summary"]["selection_changed_count"] == 2
    assert report["summary"]["subset_only_changed_count"] == 2
    assert report["distributions"]["outcome_label"] == {"avoided_loss": 1, "missed_win": 1}
    assert report["model_pair_outcomes"][0]["baseline_selected_model"] == "PriceAction"


def test_write_and_load_labeled_shadow_outcomes(tmp_path):
    path = tmp_path / "outcomes.jsonl"
    rows = [{"outcome_label": "avoided_loss"}]

    write_labeled_shadow_outcomes(rows, path)
    loaded, invalid = load_labeled_shadow_outcomes(path)

    assert invalid == 0
    assert loaded == rows


def test_load_labeled_shadow_outcomes_counts_invalid_rows(tmp_path):
    path = tmp_path / "outcomes.jsonl"
    path.write_text(json.dumps({"ok": True}) + "\nnot-json\n[]\n", encoding="utf-8")

    loaded, invalid = load_labeled_shadow_outcomes(path)

    assert loaded == [{"ok": True}]
    assert invalid == 2


def test_render_shadow_outcome_report_markdown_contains_core_sections():
    report = build_shadow_outcome_report(
        label_shadow_decision_outcomes([_record(timestamp=1000.0)], {("BTCUSDT", "4h"): _ohlcv()}, horizon_bars=1),
        source_path="outcomes.jsonl",
    )

    md = render_shadow_outcome_report_markdown(report)

    assert "# RegimeV2 Phase 6 Shadow Outcome Report" in md
    assert "avoided_loss: 1" in md
    assert "| PriceAction | none | 1 |" in md


def test_label_shadow_outcomes_cli_parse_args():
    args = _parse_args(
        [
            "--log",
            "logs/custom.jsonl",
            "--limit",
            "500",
            "--horizon-bars",
            "6",
            "--fee-bps",
            "5",
            "--output-jsonl",
            "research/outcomes.jsonl",
            "--report-json",
            "research/outcomes.json",
            "--report-md",
            "research/outcomes.md",
        ]
    )

    assert args.log == "logs/custom.jsonl"
    assert args.limit == 500
    assert args.horizon_bars == 6
    assert args.fee_bps == 5.0
    assert args.output_jsonl == "research/outcomes.jsonl"
    assert args.report_json == "research/outcomes.json"
    assert args.report_md == "research/outcomes.md"


def test_pairs_from_records_deduplicates_and_sorts():
    records = [
        {"asset": "ethusdt", "timeframe": "4h"},
        {"asset": "BTCUSDT", "timeframe": "4h"},
        {"asset": "ETHUSDT", "timeframe": "4h"},
    ]

    assert _pairs_from_records(records) == (("BTCUSDT", "4h"), ("ETHUSDT", "4h"))
