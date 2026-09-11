"""Momentum — Price change over N periods."""

from typing import Sequence, Tuple
from collections import deque
import numpy as np
from numba import njit

from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry


@njit(cache=True)
def _compute_momentum_batch(data: np.ndarray, period: int) -> np.ndarray:
    n = len(data)
    out = np.full(n, np.nan)
    for i in range(period, n):
        out[i] = data[i] - data[i - period]
    return out


@IndicatorRegistry.register("Momentum")
class Momentum(Indicator):
    def __init__(self, period: int = 10):
        super().__init__()
        self.period = period
        self._buffer: deque = deque(maxlen=period + 1)

    @property
    def lookback_required(self) -> int:
        return self.period

    def batch(self, data: Sequence[float]) -> list[float]:
        if not data:
            return []
        arr = np.array(data, dtype=np.float64)
        result = _compute_momentum_batch(arr, self.period)
        return [None if np.isnan(x) else x for x in result.tolist()]

    def prime(self, historical_data: Sequence[float]) -> None:
        if len(historical_data) < self.period + 1:
            raise ValueError(
                f"Momentum requires at least {self.period + 1} elements to prime."
            )
        self._buffer.clear()
        self._buffer.extend(historical_data[-(self.period + 1) :])
        self._is_primed = True

    def update(self, new_value: float) -> float:
        if not self.is_primed:
            raise RuntimeError(
                "Indicator must be primed before update() can be called."
            )
        self._buffer.append(new_value)
        return self._buffer[-1] - self._buffer[0]
