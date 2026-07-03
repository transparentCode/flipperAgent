"""Tests for PriceAction direction-aware guardrail validation."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.scripts.validate_price_action_guardrail_binance import _parse_args
from libs.selection.regime_v2_price_action_guardrail_validation import (
    build_price_action_guardrail_validation,
    is_price_action_direction_guardrail,
    render_price_action_guardrail_validation_markdown,
)


def _record(
    *,
    timestamp: float,
    direction: int = 1,
    baseline_model: str = "PriceAction",
    shadow_model: str | None = None,
    changed: bool = True,
    subset_only: bool = True,
    include_non_target_models: bool = False,
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
        "target_models": ["Momentum", "TrendFollowing", "RegimePullbackScorer", "SqueezeBreakout"],
    }


def _ohlcv() -> pd.DataFrame:
    index = pd.to_datetime([1000.0, 1001.0, 1002.0, 1003.0, 1004.0, 1005.0], unit="s", utc=True)
    return pd.DataFrame(
        {
            "open": [100.0, 90.0, 95.0, 88.0, 92.0, 89.0],
            "high": [101.0, 91.0, 96.0, 89.0, 93.0, 90.0],
            "low": [99.0, 89.0, 94.0, 87.0, 91.0, 88.0],
            "close": [100.0, 90.0, 95.0, 88.0, 92.0, 89.0],
            "volume": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        },
        index=index,
    )


def test_is_price_action_direction_guardrail_requires_matching_direction():
    assert is_price_action_direction_guardrail(_record(timestamp=1000.0, direction=1), direction=1) is True
    assert is_price_action_direction_guardrail(_record(timestamp=1000.0, direction=-1), direction=1) is False
    assert is_price_action_direction_guardrail(_record(timestamp=1000.0, baseline_model="Momentum"), direction=1) is False
    assert is_price_action_direction_guardrail(_record(timestamp=1000.0, shadow_model="Momentum"), direction=1) is False


def test_guardrail_validation_builds_cells_and_rolling_windows():
    records = [
        _record(timestamp=1000.0, direction=1),
        _record(timestamp=1001.0, direction=1),
        _record(timestamp=1002.0, direction=1),
        _record(timestamp=1003.0, direction=-1),
        _record(timestamp=1000.0, baseline_model="Momentum", shadow_model="Momentum", changed=False, subset_only=False),
    ]

    report = build_price_action_guardrail_validation(
        records,
        {("BTCUSDT", "4h"): _ohlcv()},
        direction=1,
        horizons=(1,),
        fees_bps=(0.0,),
        rolling_window=2,
        min_window=1,
    )

    assert report["summary"]["total_records"] == 5
    assert report["summary"]["candidate_count"] == 3
    assert report["summary"]["candidate_rate"] == 3 / 5
    cell = report["cells"][0]
    assert cell["count"] == 3
    assert cell["rolling"]["window_count"] == 2
    assert cell["outcome_labels"] == {"avoided_loss": 2, "missed_win": 1}
    assert "BTCUSDT|4h" in cell["asset_timeframe"]


def test_guardrail_validation_handles_no_candidates():
    report = build_price_action_guardrail_validation(
        [_record(timestamp=1000.0, direction=-1)],
        {("BTCUSDT", "4h"): _ohlcv()},
        direction=1,
        horizons=(1,),
        fees_bps=(0.0,),
    )

    assert report["summary"]["candidate_count"] == 0
    assert report["cells"][0]["count"] == 0
    assert report["cells"][0]["avg_shadow_minus_baseline"] is None


def test_render_guardrail_validation_markdown_contains_matrix():
    report = build_price_action_guardrail_validation(
        [_record(timestamp=1000.0, direction=1)],
        {("BTCUSDT", "4h"): _ohlcv()},
        direction=1,
        horizons=(1,),
        fees_bps=(0.0,),
    )

    md = render_price_action_guardrail_validation_markdown(report)

    assert "# RegimeV2 Phase 6G PriceAction Direction Guardrail Validation" in md
    assert "| Horizon | Fee bps |" in md
    assert "| 1 | 0.0 |" in md


def test_validate_price_action_guardrail_cli_parse_args():
    args = _parse_args(
        [
            "--log",
            "logs/custom.jsonl",
            "--direction",
            "-1",
            "--limit",
            "1200",
            "--horizon",
            "3",
            "--horizon",
            "12",
            "--fee-bps",
            "2",
            "--fee-bps",
            "10",
            "--rolling-window",
            "25",
            "--min-window",
            "8",
            "--output-json",
            "research/validation.json",
            "--output-md",
            "research/validation.md",
        ]
    )

    assert args.log == "logs/custom.jsonl"
    assert args.direction == -1
    assert args.limit == 1200
    assert args.horizon == [3, 12]
    assert args.fee_bps == [2.0, 10.0]
    assert args.rolling_window == 25
    assert args.min_window == 8
    assert args.output_json == "research/validation.json"
    assert args.output_md == "research/validation.md"


def test_validate_price_action_guardrail_cli_defaults():
    args = _parse_args([])

    assert args.direction == 1
    assert args.limit == 1000
    assert args.horizon == [3, 6, 12, 24]
    assert args.fee_bps == [2.0, 5.0, 10.0]
    assert args.rolling_window == 30
    assert args.min_window == 10
