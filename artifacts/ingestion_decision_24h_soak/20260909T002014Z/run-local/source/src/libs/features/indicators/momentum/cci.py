"""CCI — Commodity Channel Index indicator."""

from typing import Sequence, Tuple
from collections import deque
import numpy as np
from numba import njit

from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry


@njit(cache=True)
def _compute_cci_batch(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int
) -> np.ndarray:
    n = len(high)
    out = np.full(n, np.nan)
    tp = (high + low + close) / 3.0
    for i in range(period - 1, n):
        s = 0.0
        for j in range(i - period + 1, i + 1):
            s += tp[j]
        mean_tp = s / period
        mad = 0.0
        for j in range(i - period + 1, i + 1):
            mad += abs(tp[j] - mean_tp)
        mad /= period
        out[i] = (tp[i] - mean_tp) / (0.015 * mad) if mad != 0.0 else 0.0
    return out


@IndicatorRegistry.register("CCI")
class CCI(Indicator):
    def __init__(self, period: int = 5):
        super().__init__()
        self.period = period
        self._tp_buffer: deque = deque(maxlen=period)

    @property
    def lookback_required(self) -> int:
        return self.period

    def batch(self, data: Sequence[Tuple[float, float, float]]) -> list[float]:
        if not data:
            return []
        arr = np.array(data, dtype=np.float64)
        high = arr[:, 0]
        low = arr[:, 1]
        close = arr[:, 2]
        result = _compute_cci_batch(high, low, close, self.period)
        return [None if np.isnan(x) else x for x in result.tolist()]

    def prime(self, historical_data: Sequence[Tuple[float, float, float]]) -> None:
        if len(historical_data) < self.period:
            raise ValueError(
                f"CCI requires at least {self.period} elements to prime."
            )
        self._tp_buffer.clear()
        for h, l, c in historical_data[-self.period :]:
            self._tp_buffer.append((h + l + c) / 3.0)
        self._is_primed = True

    def update(self, new_value: Tuple[float, float, float]) -> float:
        if not self.is_primed:
            raise RuntimeError(
                "Indicator must be primed before update() can be called."
            )
        h, l, c = new_value
        tp = (h + l + c) / 3.0
        self._tp_buffer.append(tp)

        mean_tp = sum(self._tp_buffer) / len(self._tp_buffer)
        mad = sum(abs(v - mean_tp) for v in self._tp_buffer) / len(self._tp_buffer)
        if mad == 0.0:
            return 0.0
        return (tp - mean_tp) / (0.015 * mad)
