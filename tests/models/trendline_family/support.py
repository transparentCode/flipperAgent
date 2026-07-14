"""Deterministic OHLCV and resolved-config fixtures for Phase-B tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pandas as pd

from libs.models.trendline_family.config import ResolvedTrendlineFamilyConfig
from libs.models.trendline_family.config_resolver import TrendlineFamilyConfigResolver


def candidate_ohlcv() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=24, freq="h", tz="UTC")
    lows = [10, 9, 8, 9, 10, 11, 10, 9, 7, 8, 9, 10, 11, 10, 9, 6, 7, 8, 9, 10, 11, 12, 11, 10]
    return pd.DataFrame(
        {
            "open": [value + 2.2 for value in lows],
            "high": [value + 4.0 for value in lows],
            "low": lows,
            "close": [value + 2.0 for value in lows],
        },
        index=index,
    )


def monotonic_ohlcv() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=12, freq="h", tz="UTC")
    lows = list(range(10, 22))
    return pd.DataFrame(
        {
            "open": [value + 1.2 for value in lows],
            "high": [value + 2.0 for value in lows],
            "low": lows,
            "close": [value + 1.0 for value in lows],
        },
        index=index,
    )


def resolved_config(
    *,
    asset: str = "BTCUSDT",
    timeframe: str = "1h",
    **candidate_overrides: Any,
) -> ResolvedTrendlineFamilyConfig:
    candidate = {
        "lookback_bars": 24,
        "min_bars": 8,
        "fractal_left_bars": 1,
        "fractal_right_bars": 1,
        "min_pivots_per_side": 2,
        "min_candidate_quality": 0.0,
    }
    candidate.update(deepcopy(candidate_overrides))
    candidate["birth_quality_threshold"] = max(
        float(candidate.get("birth_quality_threshold", 0.45)),
        float(candidate["min_candidate_quality"]),
    )
    raw = {"version": 1, "defaults": {"candidate": candidate}}
    return TrendlineFamilyConfigResolver(raw).resolve(asset=asset, timeframe=timeframe)
