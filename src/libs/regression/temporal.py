"""Pure temporal helpers shared by legacy and structural regression paths."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from libs.common.timeframes import timeframe_to_seconds


def normalize_timestamps(index: pd.Index) -> np.ndarray:
    """Validate and normalize candle-open timestamps to UTC ``datetime64[ns]``."""
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("regression dataframe index must be a DatetimeIndex")
    if index.hasnans:
        raise ValueError("regression dataframe index must not contain NaT")
    if not index.is_unique:
        raise ValueError("regression dataframe index must be unique")
    if not index.is_monotonic_increasing:
        raise ValueError("regression dataframe index must be monotonic increasing")

    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    return index.tz_localize(None).to_numpy(dtype="datetime64[ns]", copy=False)


def timeframe_seconds(timeframe: str) -> int:
    """Return the strict fixed duration for a supported regression timeframe."""
    seconds = timeframe_to_seconds(timeframe, default=0)
    if seconds <= 0:
        raise ValueError(f"unsupported regression timeframe: {timeframe!r}")
    return seconds


def _utc_datetime(timestamp: np.datetime64 | pd.Timestamp) -> datetime:
    value = pd.Timestamp(timestamp)
    if value.tz is None:
        value = value.tz_localize("UTC")
    else:
        value = value.tz_convert("UTC")
    return value.to_pydatetime()


def market_times(
    timestamps: np.ndarray, timeframe_seconds_value: int
) -> tuple[datetime, datetime]:
    """Return the final candle open and deterministic close times."""
    if len(timestamps) == 0:
        raise ValueError("cannot create a regression result without market time")

    opened_at = _utc_datetime(timestamps[-1])
    return opened_at, opened_at + timedelta(seconds=timeframe_seconds_value)


def market_time_bounds(
    timestamps: np.ndarray, timeframe_seconds_value: int
) -> tuple[datetime, datetime, datetime]:
    """Return first open, final open, and final close for a selected window."""
    if len(timestamps) == 0:
        raise ValueError("cannot create a regression result without market time")

    timestamp, observed_through = market_times(timestamps, timeframe_seconds_value)
    return _utc_datetime(timestamps[0]), timestamp, observed_through
