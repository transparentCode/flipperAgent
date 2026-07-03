"""Tests for the PriceAction drift report."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.scripts.report_pa_drift_binance import _parse_args
from libs.selection.regime_v2_pa_drift_report import build_pa_drift_report, render_pa_drift_report_markdown


def _record(
    *,
    timestamp: float,
    asset: str = "BTCUSDT",
    direction: int = 1,
    baseline_model: str = "PriceAction",
    shadow_model: str | None = None,
    changed: bool = True,
    subset_only: bool = True,
) -> dict:
    return {
        "asset": asset,
        "timeframe": "4h",
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


def _ohlcv() -> pd.DataFrame:
    index = pd.to_datetime([1000.0, 1001.0, 1002.0, 1003.0, 1004.0, 1005.0], unit="s", utc=True)
    return pd.DataFrame(
        {
            "open": [100.0, 90.0, 95.0, 105.0, 92.0, 110.0],
            "high": [101.0, 91.0, 96.0, 106.0, 93.0, 111.0],
            "low": [99.0, 89.0, 94.0, 104.0, 91.0, 109.0],
            "close": [100.0, 90.0, 95.0, 105.0, 92.0, 110.0],
            "volume": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        },
        index=index,
    )


def test_pa_drift_report_flags_failed_cells_and_windows():
    records = [
        _record(timestamp=1000.0, direction=1),
        _record(timestamp=1001.0, direction=1),
        _record(timestamp=1002.0, direction=1),
        _record(timestamp=1003.0, direction=-1),
    ]

    report = build_pa_drift_report(
        records,
        {("BTCUSDT", "4h"): _ohlcv()},
        direction=1,
        horizons=(1,),
        fees_bps=(0.0,),
        rolling_window=2,
        min_window=1,
        min_bad_rate=0.8,
    )

    assert report["summary"]["total_records"] == 4
    assert report["summary"]["candidate_count"] == 3
    assert report["summary"]["cell_count"] == 1
    assert report["summary"]["failing_cell_count"] == 1
    assert report["cells"][0]["status"] == "fail"
    assert "bad_rate_below_floor" in report["cells"][0]["failure_reasons"]
    assert report["failure_windows"]


def test_pa_drift_report_asset_and_direction_summaries():
    records = [
        _record(timestamp=1000.0, asset="BTCUSDT", direction=1),
        _record(timestamp=1001.0, asset="ETHUSDT", direction=1),
        _record(timestamp=1002.0, asset="BTCUSDT", direction=-1),
    ]

    report = build_pa_drift_report(
        records,
        {("BTCUSDT", "4h"): _ohlcv(), ("ETHUSDT", "4h"): _ohlcv()},
        direction=1,
        horizons=(1,),
        fees_bps=(0.0,),
        rolling_window=2,
        min_window=1,
    )

    assets = {row["asset_timeframe"]: row for row in report["asset_timeframe_summary"]}
    assert "BTCUSDT|4h" in assets
    assert "ETHUSDT|4h" in assets
    directions = {row["direction"]: row for row in report["direction_comparison"]}
    assert 1 in directions
    assert -1 in directions


def test_pa_drift_report_handles_no_candidates():
    report = build_pa_drift_report(
        [_record(timestamp=1000.0, direction=-1)],
        {("BTCUSDT", "4h"): _ohlcv()},
        direction=1,
        horizons=(1,),
        fees_bps=(0.0,),
    )

    assert report["summary"]["candidate_count"] == 0
    assert report["cells"][0]["status"] == "fail"
    assert report["cells"][0]["failure_reasons"] == ["no_candidate_rows"]


def test_render_pa_drift_report_markdown_contains_sections():
    report = build_pa_drift_report(
        [_record(timestamp=1000.0, direction=1)],
        {("BTCUSDT", "4h"): _ohlcv()},
        direction=1,
        horizons=(1,),
        fees_bps=(0.0,),
    )

    md = render_pa_drift_report_markdown(report)

    assert "# RegimeV2 Phase 6H PriceAction Drift Report" in md
    assert "## Cell Status" in md
    assert "## Direction Comparison" in md


def test_report_pa_drift_cli_parse_args():
    args = _parse_args(
        [
            "--log",
            "logs/custom.jsonl",
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
            "--min-bad-rate",
            "0.6",
            "--min-avg-lift",
            "0.001",
            "--min-rolling-positive-rate",
            "0.8",
            "--output-json",
            "research/drift.json",
            "--output-md",
            "research/drift.md",
        ]
    )

    assert args.log == "logs/custom.jsonl"
    assert args.direction == -1
    assert args.limit == 900
    assert args.horizon == [3]
    assert args.fee_bps == [5.0]
    assert args.rolling_window == 20
    assert args.min_window == 8
    assert args.min_bad_rate == 0.6
    assert args.min_avg_lift == 0.001
    assert args.min_rolling_positive_rate == 0.8
    assert args.output_json == "research/drift.json"
    assert args.output_md == "research/drift.md"


def test_report_pa_drift_cli_defaults():
    args = _parse_args([])

    assert args.direction == 1
    assert args.limit == 1200
    assert args.horizon == [3, 6, 12, 24]
    assert args.fee_bps == [2.0, 5.0, 10.0]
    assert args.rolling_window == 30
    assert args.min_window == 10
