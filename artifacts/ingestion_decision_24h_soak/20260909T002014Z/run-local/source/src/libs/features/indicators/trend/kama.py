"""KAMA — Kaufman Adaptive Moving Average indicator."""

import collections
from typing import Sequence
import numpy as np
from numba import njit

from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry


@njit(cache=True)
def _compute_kama_batch(
    data: np.ndarray, period: int, fast_period: int, slow_period: int
) -> np.ndarray:
    n = len(data)
    result = np.full(n, np.nan)
    if n < period:
        return result

    fast_sc = 2.0 / (fast_period + 1)
    slow_sc = 2.0 / (slow_period + 1)

    # First KAMA value is the close at index period-1
    result[period - 1] = data[period - 1]

    for i in range(period, n):
        direction = abs(data[i] - data[i - period])
        volatility = 0.0
        for j in range(i - period + 1, i + 1):
            volatility += abs(data[j] - data[j - 1])

        if volatility == 0.0:
            er = 0.0
        else:
            er = direction / volatility

        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        result[i] = result[i - 1] + sc * (data[i] - result[i - 1])

    return result


@IndicatorRegistry.register("KAMA")
class KAMA(Indicator):
    def __init__(
        self, period: int = 10, fast_period: int = 2, slow_period: int = 30
    ):
        super().__init__()
        self.period = period
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.fast_sc = 2.0 / (fast_period + 1)
        self.slow_sc = 2.0 / (slow_period + 1)
        self.current_kama = None
        self._window: collections.deque = collections.deque(maxlen=self.period + 1)
        self._running_volatility: float = 0.0

    @property
    def lookback_required(self) -> int:
        return self.period

    def batch(self, data: Sequence[float]) -> list[float]:
        if not data:
            return []
        arr = np.array(data, dtype=np.float64)
        numba_res = _compute_kama_batch(
            arr, self.period, self.fast_period, self.slow_period
        )
        return [None if np.isnan(x) else x for x in numba_res.tolist()]

    def prime(self, historical_data: Sequence[float]) -> None:
        if len(historical_data) < self.period:
            raise ValueError(
                f"KAMA requires at least {self.period} elements to prime."
            )
        batch_result = self.batch(historical_data)
        self.current_kama = batch_result[-1]
        # Keep the last `period` values for volatility computation on update
        self._window = collections.deque(
            historical_data[-self.period :], maxlen=self.period + 1
        )
        # Initialize running volatility from the primed window
        self._running_volatility = 0.0
        for j in range(1, len(self._window)):
            self._running_volatility += abs(self._window[j] - self._window[j - 1])
        self._is_primed = True

    def update(self, new_value: float) -> float:
        if not self.is_primed:
            raise RuntimeError(
                "Indicator must be primed before update() can be called."
            )

        # O(1) running volatility update
        prev_value = self._window[-1]
        new_diff = abs(new_value - prev_value)
        if len(self._window) == self._window.maxlen:
            # The oldest diff will be evicted by the deque append
            old_diff = abs(self._window[1] - self._window[0])
            self._running_volatility += new_diff - old_diff
        else:
            self._running_volatility += new_diff

        self._window.append(new_value)

        direction = abs(new_value - self._window[0])
        volatility = self._running_volatility

        if volatility == 0.0:
            er = 0.0
        else:
            er = direction / volatility

        sc = (er * (self.fast_sc - self.slow_sc) + self.slow_sc) ** 2
        self.current_kama = self.current_kama + sc * (new_value - self.current_kama)

        return self.current_kama
