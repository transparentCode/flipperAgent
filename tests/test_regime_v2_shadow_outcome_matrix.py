"""Tests for RegimeV2 shadow outcome matrix reports."""

from __future__ import annotations

import pandas as pd

from libs.models.regime_v2.scripts.shadow_outcome_matrix_binance import _parse_args
from libs.selection.regime_v2_shadow_outcome_matrix import (
    build_shadow_outcome_matrix,
    render_shadow_outcome_matrix_markdown,
)


def _record(
    *,
    timestamp: float,
    baseline_model: str = "PriceAction",
    shadow_model: str | None = None,
    baseline_direction: int = 1,
    shadow_direction: int | None = None,
    gate_active: bool = False,
    subset_only: bool = True,
) -> dict:
    return {
        "asset": "BTCUSDT",
        "timeframe": "4h",
        "timestamp": timestamp,
        "baseline_selected_model": baseline_model,
        "shadow_selected_model": shadow_model,
        "baseline_selected_direction": baseline_direction,
        "shadow_selected_direction": shadow_direction,
        "selection_changed": baseline_model != shadow_model,
        "gate_active": gate_active,
        "shadow_subset_only": subset_only,
        "include_non_target_models": False,
        "target_models": ["Momentum", "TrendFollowing", "RegimePullbackScorer", "SqueezeBreakout"],
    }


def _ohlcv() -> pd.DataFrame:
    index = pd.to_datetime([1000.0, 1001.0, 1002.0, 1003.0, 1004.0], unit="s", utc=True)
    return pd.DataFrame(
        {
            "open": [100.0, 90.0, 95.0, 101.0, 104.0],
            "high": [101.0, 91.0, 96.0, 102.0, 105.0],
            "low": [99.0, 89.0, 94.0, 100.0, 103.0],
            "close": [100.0, 90.0, 95.0, 101.0, 104.0],
            "volume": [1.0, 1.0, 1.0, 1.0, 1.0],
        },
        index=index,
    )


def test_build_shadow_outcome_matrix_builds_horizon_fee_cells_and_segments():
    records = [
        _record(timestamp=1000.0, baseline_direction=1, shadow_direction=None, gate_active=False, subset_only=True),
        _record(
            timestamp=1000.0,
            baseline_model="Momentum",
            shadow_model="SqueezeBreakout",
            baseline_direction=1,
            shadow_direction=-1,
            gate_active=True,
            subset_only=False,
        ),
        _record(
            timestamp=1001.0,
            baseline_model="Momentum",
            shadow_model="Momentum",
            baseline_direction=1,
            shadow_direction=1,
            gate_active=False,
            subset_only=False,
        ),
    ]

    matrix = build_shadow_outcome_matrix(
        records,
        {("BTCUSDT", "4h"): _ohlcv()},
        horizons=(1, 2),
        fees_bps=(0.0, 5.0),
    )

    assert matrix["summary"]["cell_count"] == 4
    assert matrix["summary"]["horizons"] == [1, 2]
    assert matrix["summary"]["fees_bps"] == [0.0, 5.0]
    first = matrix["cells"][0]
    assert first["horizon_bars"] == 1
    assert first["fee_bps"] == 0.0
    assert first["labeled_count"] == 3
    assert first["segments"]["changed"]["count"] == 2
    assert first["segments"]["gate_active_changed"]["count"] == 1
    assert first["segments"]["subset_only_changed"]["count"] == 1
    assert first["segments"]["non_subset_changed"]["count"] == 1
    assert "BTCUSDT|4h" in first["asset_timeframe"]


def test_shadow_outcome_matrix_handles_unlabeled_rows():
    matrix = build_shadow_outcome_matrix(
        [_record(timestamp=9999.0)],
        {("BTCUSDT", "4h"): _ohlcv()},
        horizons=(1,),
        fees_bps=(0.0,),
    )

    cell = matrix["cells"][0]
    assert cell["labeled_count"] == 0
    assert cell["unlabeled_count"] == 1
    assert cell["unlabeled_reasons"] == {"timestamp_not_found": 1}
    assert cell["segments"]["all"]["avg_shadow_minus_baseline"] is None


def test_render_shadow_outcome_matrix_markdown_contains_table():
    matrix = build_shadow_outcome_matrix(
        [_record(timestamp=1000.0)],
        {("BTCUSDT", "4h"): _ohlcv()},
        horizons=(1,),
        fees_bps=(0.0,),
    )

    md = render_shadow_outcome_matrix_markdown(matrix)

    assert "# RegimeV2 Phase 6B Shadow Outcome Matrix" in md
    assert "| Horizon | Fee bps |" in md
    assert "| 1 | 0.0 |" in md


def test_shadow_outcome_matrix_cli_parse_args():
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
            "research/matrix.json",
            "--output-md",
            "research/matrix.md",
        ]
    )

    assert args.log == "logs/custom.jsonl"
    assert args.limit == 900
    assert args.horizon == [3, 12]
    assert args.fee_bps == [2.0, 10.0]
    assert args.output_json == "research/matrix.json"
    assert args.output_md == "research/matrix.md"


def test_shadow_outcome_matrix_cli_defaults():
    args = _parse_args([])

    assert args.horizon == [3, 6, 12, 24]
    assert args.fee_bps == [2.0, 5.0, 10.0]
