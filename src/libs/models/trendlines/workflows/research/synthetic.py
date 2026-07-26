"""Deterministic, network-free research smoke data."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from libs.models.trendlines.signals.context import (
    BarAvailabilitySource,
    BarTimestampSemantics,
)
from libs.models.trendlines.workflows.research.contracts import (
    SYNTHETIC_GENERATOR_SEMANTICS_VERSION,
    TrendlineResearchSpec,
)


SYNTHETIC_BASE_PRICE = 100.0
SYNTHETIC_VOLATILITY = 0.8


def strict_timeframe_seconds(timeframe: str) -> int:
    """Parse fixed-duration timeframe strings without a fallback."""

    match = re.fullmatch(r"([1-9][0-9]*)([smhdwSMHDW])", str(timeframe).strip())
    if match is None:
        raise ValueError(f"Unsupported fixed timeframe: {timeframe!r}")
    value = int(match.group(1))
    unit_seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    return value * unit_seconds[match.group(2).lower()]


def _timeframe_seed(seed: int, timeframe: str, ordinal: int) -> int:
    stable_offset = sum((index + 1) * ord(char) for index, char in enumerate(timeframe))
    return int(seed + stable_offset + ordinal * 100_003)


def generate_synthetic_frames(spec: TrendlineResearchSpec) -> dict[str, pd.DataFrame]:
    """Generate one deterministic OHLCV frame per requested timeframe."""

    data = spec.data
    if data.mode.value != "synthetic":
        raise ValueError("generate_synthetic_frames requires synthetic data mode")
    assert data.start_time is not None
    frames: dict[str, pd.DataFrame] = {}
    for ordinal, timeframe in enumerate(spec.timeframes):
        count = data.bar_counts[timeframe]
        seconds = strict_timeframe_seconds(timeframe)
        index = pd.date_range(
            data.start_time,
            periods=count,
            freq=pd.Timedelta(seconds=seconds),
            tz="UTC",
        )
        rng = np.random.default_rng(_timeframe_seed(data.seed or 0, timeframe, ordinal))
        drift = np.linspace(0.0, 1.5, count)
        cycle = np.sin(np.linspace(0.0, 8.0 * np.pi, count)) * 1.8
        close = SYNTHETIC_BASE_PRICE + drift + cycle + rng.normal(0.0, SYNTHETIC_VOLATILITY, count)
        open_values = close + rng.normal(0.0, 0.25, count)
        spread = np.abs(rng.normal(0.8, 0.15, count))
        high = np.maximum(open_values, close) + spread
        low = np.minimum(open_values, close) - spread
        volume = np.abs(rng.normal(1_000.0, 180.0, count))
        frame = pd.DataFrame(
            {
                "open": open_values,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            },
            index=index,
        )
        frame["bar_available_at"] = index + pd.Timedelta(seconds=seconds)
        frame.attrs["bar_timestamp_semantics"] = BarTimestampSemantics.OPEN_TIME.value
        frame.attrs["bar_availability_source"] = BarAvailabilitySource.FIXED_INTERVAL_DERIVED.value
        frame.attrs["research_generator_semantics_version"] = SYNTHETIC_GENERATOR_SEMANTICS_VERSION
        frames[timeframe] = frame
    return frames


__all__ = [
    "SYNTHETIC_BASE_PRICE",
    "SYNTHETIC_GENERATOR_SEMANTICS_VERSION",
    "SYNTHETIC_VOLATILITY",
    "generate_synthetic_frames",
    "strict_timeframe_seconds",
]
