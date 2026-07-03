"""Tests for RegimeV2 PriceAction subset-removal matrix."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.scripts.price_action_subset_matrix_binance import _parse_args
from libs.selection.regime_v2_price_action_matrix import (
    build_price_action_subset_matrix,
    is_price_action_subset_removal,
    render_price_action_subset_matrix_markdown,
)


def _record(
    *,
    timestamp: float = 1000.0,
    baseline_model: str = "PriceAction",
    shadow_model: str | None = None,
    changed: bool = True,
    subset_only: bool = True,
    include_non_target_models: bool = False,
    target_models: list[str] | None = None,
    direction: int = 1,
) -> dict:
    return {
        "asset": "BTCUSDT",
        "timeframe": "4h",
        "timestamp": timestamp,
        "baseline_selected_model": baseline_model,
        "shadow_selected_model": shadow_model,
        "baseline_selected_direction": direction,
        "shadow_selected_direction": None,
        "selection_changed": changed,
        "shadow_subset_only": subset_only,
        "include_non_target_models": include_non_target_models,
        "target_models": target_models or ["Momentum", "TrendFollowing", "RegimePullbackScorer", "SqueezeBreakout"],
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


def test_is_price_action_subset_removal_requires_all_conditions():
    assert is_price_action_subset_removal(_record()) is True
    assert is_price_action_subset_removal(_record(baseline_model="Momentum")) is False
    assert is_price_action_subset_removal(_record(shadow_model="Momentum")) is False
    assert is_price_action_subset_removal(_record(changed=False)) is False
    assert is_price_action_subset_removal(_record(subset_only=False)) is False
    assert is_price_action_subset_removal(_record(include_non_target_models=True)) is False
    assert is_price_action_subset_removal(_record(target_models=["PriceAction"])) is False


def test_price_action_subset_matrix_filters_and_labels_rows():
    records = [
        _record(timestamp=1000.0, direction=1),
        _record(timestamp=1001.0, direction=1),
        _record(timestamp=1000.0, baseline_model="Momentum", shadow_model="Momentum", changed=False, subset_only=False),
    ]

    report = build_price_action_subset_matrix(
        records,
        {("BTCUSDT", "4h"): _ohlcv()},
        horizons=(1,),
        fees_bps=(0.0,),
    )

    assert report["summary"]["total_records"] == 3
    assert report["summary"]["price_action_subset_removal_count"] == 2
    assert report["summary"]["price_action_subset_removal_rate"] == 2 / 3
    assert report["summary"]["cell_count"] == 1
    cell = report["cells"][0]
    assert cell["count"] == 2
    assert cell["outcome_labels"] == {"avoided_loss": 1, "missed_win": 1}
    assert cell["positive_shadow_lift_rate"] == 0.5
    assert "BTCUSDT|4h" in cell["asset_timeframe"]


def test_price_action_subset_matrix_handles_no_price_action_rows():
    report = build_price_action_subset_matrix(
        [_record(baseline_model="Momentum", shadow_model="Momentum", changed=False, subset_only=False)],
        {("BTCUSDT", "4h"): _ohlcv()},
        horizons=(1,),
        fees_bps=(0.0,),
    )

    assert report["summary"]["price_action_subset_removal_count"] == 0
    assert report["cells"][0]["count"] == 0
    assert report["cells"][0]["avg_shadow_minus_baseline"] is None


def test_render_price_action_subset_matrix_markdown_contains_table():
    report = build_price_action_subset_matrix(
        [_record(timestamp=1000.0)],
        {("BTCUSDT", "4h"): _ohlcv()},
        horizons=(1,),
        fees_bps=(0.0,),
    )

    md = render_price_action_subset_matrix_markdown(report)

    assert "# RegimeV2 Phase 6E PriceAction Subset Matrix" in md
    assert "| Horizon | Fee bps |" in md
    assert "| 1 | 0.0 |" in md


def test_price_action_subset_matrix_cli_parse_args():
    args = _parse_args(
        [
            "--log",
            "logs/custom.jsonl",
            "--limit",
            "900",
            "--horizon",
            "3",
            "--horizon",
            "12",
            "--fee-bps",
            "2",
            "--fee-bps",
            "10",
            "--output-json",
            "research/pa.json",
            "--output-md",
            "research/pa.md",
        ]
    )

    assert args.log == "logs/custom.jsonl"
    assert args.limit == 900
    assert args.horizon == [3, 12]
    assert args.fee_bps == [2.0, 10.0]
    assert args.output_json == "research/pa.json"
    assert args.output_md == "research/pa.md"


def test_price_action_subset_matrix_cli_defaults():
    args = _parse_args([])

    assert args.horizon == [3, 6, 12, 24]
    assert args.fee_bps == [2.0, 5.0, 10.0]
