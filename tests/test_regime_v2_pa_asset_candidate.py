"""Tests for asset-specific PriceAction candidate validation."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.scripts.validate_pa_asset_candidate_binance import _parse_args
from libs.selection.regime_v2_pa_asset_candidate import (
    build_pa_asset_candidate_report,
    is_pa_asset_candidate,
    render_pa_asset_candidate_markdown,
)


def _record(
    *,
    timestamp: float,
    asset: str = "BNBUSDT",
    timeframe: str = "1h",
    direction: int = 1,
    baseline_model: str = "PriceAction",
    shadow_model: str | None = None,
    changed: bool = True,
    subset_only: bool = True,
) -> dict:
    return {
        "asset": asset,
        "timeframe": timeframe,
        "timestamp": timestamp,
        "baseline_selected_model": baseline_model,
        "shadow_selected_model": shadow_model,
        "baseline_selected_direction": direction,
        "shadow_selected_direction": None,
        "selection_changed": changed,
        "shadow_subset_only": subset_only,
        "include_non_target_models": False,
        "target_models": ["Momentum", "TrendFollowing", "RegimePullbackScorer", "SqueezeBreakout"],
    }


def _ohlcv(symbol: str = "BNBUSDT") -> pd.DataFrame:
    index = pd.to_datetime([1000.0, 1001.0, 1002.0, 1003.0, 1004.0, 1005.0], unit="s", utc=True)
    if symbol == "BNBUSDT":
        close = [100.0, 90.0, 80.0, 70.0, 60.0, 50.0]
    else:
        close = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
    return pd.DataFrame(
        {
            "open": close,
            "high": [value + 1.0 for value in close],
            "low": [value - 1.0 for value in close],
            "close": close,
            "volume": [1.0] * len(close),
        },
        index=index,
    )


def test_is_pa_asset_candidate_requires_exact_asset_timeframe_direction():
    assert is_pa_asset_candidate(_record(timestamp=1000.0), asset="BNBUSDT", timeframe="1h", direction=1) is True
    assert is_pa_asset_candidate(_record(timestamp=1000.0, asset="BTCUSDT"), asset="BNBUSDT", timeframe="1h", direction=1) is False
    assert is_pa_asset_candidate(_record(timestamp=1000.0, timeframe="4h"), asset="BNBUSDT", timeframe="1h", direction=1) is False
    assert is_pa_asset_candidate(_record(timestamp=1000.0, direction=-1), asset="BNBUSDT", timeframe="1h", direction=1) is False
    assert is_pa_asset_candidate(_record(timestamp=1000.0, baseline_model="Momentum"), asset="BNBUSDT", timeframe="1h", direction=1) is False


def test_pa_asset_candidate_report_can_be_paper_candidate_when_strict_gates_pass():
    records = [
        _record(timestamp=1000.0),
        _record(timestamp=1001.0),
        _record(timestamp=1002.0),
        _record(timestamp=1003.0),
        _record(timestamp=1004.0),
        _record(timestamp=1000.0, asset="BTCUSDT", timeframe="4h"),
    ]

    report = build_pa_asset_candidate_report(
        records,
        {("BNBUSDT", "1h"): _ohlcv("BNBUSDT"), ("BTCUSDT", "4h"): _ohlcv("BTCUSDT")},
        asset="BNBUSDT",
        timeframe="1h",
        direction=1,
        horizons=(1,),
        fees_bps=(0.0,),
        rolling_windows=(2,),
        min_window=1,
        min_support=3,
        passing_cell_floor=1,
        max_negative_cells=0,
        rolling_stable_floor=1,
        min_positive_rate=0.6,
    )

    assert report["summary"]["candidate_count"] == 5
    assert report["summary"]["passing_cell_count"] == 1
    assert report["summary"]["negative_cell_count"] == 0
    assert report["summary"]["rolling_stable_cell_count"] == 1
    assert report["summary"]["promote_ready"] is True
    assert report["summary"]["recommendation"] == "paper_candidate"
    assert report["comparison"][0]["asset_timeframe"] == "BNBUSDT|1h"


def test_pa_asset_candidate_report_holds_off_when_rolling_fails():
    records = [
        _record(timestamp=1000.0),
        _record(timestamp=1001.0),
        _record(timestamp=1002.0),
    ]

    report = build_pa_asset_candidate_report(
        records,
        {("BNBUSDT", "1h"): _ohlcv("BTCUSDT")},
        asset="BNBUSDT",
        timeframe="1h",
        direction=1,
        horizons=(1,),
        fees_bps=(0.0,),
        rolling_windows=(2,),
        min_window=1,
        min_support=1,
        passing_cell_floor=1,
        max_negative_cells=0,
        rolling_stable_floor=1,
        min_positive_rate=0.6,
    )

    assert report["summary"]["promote_ready"] is False
    assert report["summary"]["recommendation"] == "hold_off"
    assert report["cells"][0]["status"] == "fail"
    assert "avg_lift_below_zero" in report["cells"][0]["failure_reasons"]


def test_render_pa_asset_candidate_markdown_contains_sections():
    report = build_pa_asset_candidate_report(
        [_record(timestamp=1000.0)],
        {("BNBUSDT", "1h"): _ohlcv("BNBUSDT")},
        horizons=(1,),
        fees_bps=(0.0,),
        rolling_windows=(1,),
        min_window=1,
    )

    md = render_pa_asset_candidate_markdown(report)

    assert "# RegimeV2 Phase 6I PriceAction Asset Candidate" in md
    assert "## Horizon/Fee Cells" in md
    assert "## Comparison Across Assets" in md


def test_validate_pa_asset_candidate_cli_parse_args():
    args = _parse_args(
        [
            "--log",
            "logs/custom.jsonl",
            "--asset",
            "ETHUSDT",
            "--timeframe",
            "4h",
            "--direction",
            "-1",
            "--limit",
            "900",
            "--horizon",
            "3",
            "--fee-bps",
            "5",
            "--rolling-window",
            "20",
            "--min-window",
            "8",
            "--min-support",
            "12",
            "--passing-cell-floor",
            "2",
            "--max-negative-cells",
            "1",
            "--rolling-stable-floor",
            "2",
            "--min-positive-rate",
            "0.65",
            "--output-json",
            "research/asset.json",
            "--output-md",
            "research/asset.md",
        ]
    )

    assert args.log == "logs/custom.jsonl"
    assert args.asset == "ETHUSDT"
    assert args.timeframe == "4h"
    assert args.direction == -1
    assert args.limit == 900
    assert args.horizon == [3]
    assert args.fee_bps == [5.0]
    assert args.rolling_window == [20]
    assert args.min_window == 8
    assert args.min_support == 12
    assert args.passing_cell_floor == 2
    assert args.max_negative_cells == 1
    assert args.rolling_stable_floor == 2
    assert args.min_positive_rate == 0.65
    assert args.output_json == "research/asset.json"
    assert args.output_md == "research/asset.md"


def test_validate_pa_asset_candidate_cli_defaults():
    args = _parse_args([])

    assert args.asset == "BNBUSDT"
    assert args.timeframe == "1h"
    assert args.direction == 1
    assert args.limit == 1200
    assert args.horizon == [3, 6, 12, 24]
    assert args.fee_bps == [2.0, 5.0, 10.0]
    assert args.rolling_window == [20, 30, 50]
