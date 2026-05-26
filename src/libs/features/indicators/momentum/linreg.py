"""LinReg — Rolling linear regression value indicator."""

from typing import Sequence
from collections import deque
import numpy as np
from numba import njit

from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry


@njit(cache=True)
def _compute_linreg_batch(data: np.ndarray, period: int) -> np.ndarray:
    n = len(data)
    result = np.full(n, np.nan)
    if n < period:
        return result

    # Precompute fixed sums for x = 0..period-1
    sum_x = 0.0
    sum_x2 = 0.0
    for k in range(period):
        sum_x += k
        sum_x2 += k * k

    N = float(period)
    denom = N * sum_x2 - sum_x * sum_x

    for i in range(period - 1, n):
        sum_y = 0.0
        sum_xy = 0.0
        for j in range(period):
            y = data[i - period + 1 + j]
            sum_y += y
            sum_xy += j * y

        slope = (N * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / N
        result[i] = intercept + slope * (period - 1)

    return result


@IndicatorRegistry.register("LinReg")
class LinReg(Indicator):
    def __init__(self, period: int = 12):
        super().__init__()
        self.period = period
        self._buffer: deque = deque(maxlen=period)

        # Precompute fixed sums
        self._sum_x = sum(range(period))
        self._sum_x2 = sum(k * k for k in range(period))
        self._N = float(period)
        self._denom = self._N * self._sum_x2 - self._sum_x * self._sum_x

    @property
    def lookback_required(self) -> int:
        return self.period

    def batch(self, data: Sequence[float]) -> list[float]:
        if not data:
            return []
        arr = np.array(data, dtype=np.float64)
        numba_res = _compute_linreg_batch(arr, self.period)
        return [None if np.isnan(x) else x for x in numba_res.tolist()]

    def prime(self, historical_data: Sequence[float]) -> None:
        if len(historical_data) < self.period:
            raise ValueError(
                f"LinReg requires at least {self.period} elements to prime."
            )
        self._buffer.clear()
        self._buffer.extend(historical_data[-self.period :])
        self._is_primed = True

    def update(self, new_value: float) -> float:
        if not self.is_primed:
            raise RuntimeError(
                "Indicator must be primed before update() can be called."
            )
        self._buffer.append(new_value)

        sum_y = 0.0
        sum_xy = 0.0
        for j, y in enumerate(self._buffer):
            sum_y += y
            sum_xy += j * y

        slope = (self._N * sum_xy - self._sum_x * sum_y) / self._denom
        intercept = (sum_y - slope * self._sum_x) / self._N
        return intercept + slope * (self.period - 1)
