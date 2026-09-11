"""Shared math utilities for squeeze_breakout model and scorer."""

from __future__ import annotations

import numpy as np

from libs.features.indicators.momentum.linreg import _compute_linreg_batch


def sma_series(arr: np.ndarray, period: int) -> np.ndarray:
    """Simple moving average over a 1-D array, returns NaN for warmup."""
    out = np.full(len(arr), np.nan)
    if len(arr) < period:
        return out
    cs = np.cumsum(arr)
    cs = np.insert(cs, 0, 0.0)
    out[period - 1:] = (cs[period:] - cs[:-period]) / period
    return out


def rolling_linreg(data: np.ndarray, period: int) -> np.ndarray:
    """Rolling linear-regression value, delegates to the njit kernel."""
    return _compute_linreg_batch(data, period)
