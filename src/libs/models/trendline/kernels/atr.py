"""Numba-compatible true-range kernel over validated NumPy arrays."""

from __future__ import annotations

import numpy as np
from numba import njit


@njit(cache=True, nogil=True)
def true_range_mean(high: np.ndarray, low: np.ndarray, close: np.ndarray, window: int) -> float:
    """Return the trailing simple mean of true range in stable operation order."""

    start = high.size - window
    total = 0.0
    for index in range(start, high.size):
        value = high[index] - low[index]
        if index > 0:
            high_gap = abs(high[index] - close[index - 1])
            low_gap = abs(low[index] - close[index - 1])
            if high_gap > value:
                value = high_gap
            if low_gap > value:
                value = low_gap
        total += value
    return total / window


__all__ = ["true_range_mean"]
