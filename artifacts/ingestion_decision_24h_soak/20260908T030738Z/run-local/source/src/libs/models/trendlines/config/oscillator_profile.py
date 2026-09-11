"""Oscillator-space profile computed from synthetic OHLCV data.

OscillatorProfile is the oscillator counterpart of AssetProfile. It captures
statistical properties specific to oscillator-space trendlines (RSI, MACD, etc.)
without using price-scale ratios like ``mean_atr / mean_price`` that produce
meaningless values on oscillator data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd


_TF_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480,
    "12h": 720, "1d": 1440,
    "1w": 10080,
}

_MIN_BARS = 20


def _tf_to_minutes(timeframe: str) -> int:
    minutes = _TF_MINUTES.get(timeframe)
    if minutes is not None:
        return minutes
    tf = timeframe.strip().lower()
    if tf.endswith("m") and tf[:-1].isdigit():
        return int(tf[:-1])
    if tf.endswith("h") and tf[:-1].isdigit():
        return int(tf[:-1]) * 60
    if tf.endswith("d") and tf[:-1].isdigit():
        return int(tf[:-1]) * 1440
    raise ValueError(f"Cannot parse timeframe: {timeframe!r}")


@dataclass(frozen=True)
class OscillatorProfile:
    """Statistical summary of oscillator-space data for config derivation.

    Unlike AssetProfile, this does NOT compute price-scale ratios like
    ``mean_atr / mean_price``. Instead it captures:
    - TF info (for time-based derivation: hold_bars, atr_window, etc.)
    - Oscillator volatility (rolling std, not true-range ratio)
    - Bounded vs unbounded metadata
    """

    oscillator_type: str
    is_bounded: bool
    value_range: Optional[Tuple[float, float]]
    mean_value: float
    mean_atr: float
    rolling_std: float
    n_bars: int
    tf_minutes: int
    bar_duration_hours: float

    @classmethod
    def from_dataframe(
        cls,
        df: pd.DataFrame,
        timeframe: str,
        oscillator_type: str,
        *,
        is_bounded: bool = False,
        value_range: Optional[Tuple[float, float]] = None,
    ) -> "OscillatorProfile":
        """Build profile from synthetic OHLCV DataFrame.

        The ``df`` should already be the output of ``prepare_oscillator_df()``.
        """
        required_cols = {"open", "high", "low", "close"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"OscillatorProfile requires columns {sorted(required_cols)}; missing {sorted(missing)}")
        if len(df) < _MIN_BARS:
            raise ValueError(f"OscillatorProfile requires >= {_MIN_BARS} bars, got {len(df)}")

        close = df["close"].to_numpy(dtype=float)
        tf_minutes = _tf_to_minutes(timeframe)

        # ATR on synthetic OHLCV (same calculation as boundary adapter uses)
        high = df["high"].to_numpy(dtype=float)
        low = df["low"].to_numpy(dtype=float)
        prev_close = np.concatenate(([close[0]], close[:-1]))
        tr = np.maximum.reduce([high - low, np.abs(high - prev_close), np.abs(low - prev_close)])
        mean_atr = float(np.nanmean(pd.Series(tr).rolling(14, min_periods=1).mean().to_numpy()))

        # Rolling std captures oscillator volatility better than pure ATR
        rolling_std = float(pd.Series(close).rolling(14, min_periods=1).std().mean())

        return cls(
            oscillator_type=oscillator_type.lower(),
            is_bounded=is_bounded,
            value_range=value_range,
            mean_value=float(np.nanmean(close)),
            mean_atr=mean_atr,
            rolling_std=rolling_std,
            n_bars=len(df),
            tf_minutes=tf_minutes,
            bar_duration_hours=tf_minutes / 60.0,
        )
