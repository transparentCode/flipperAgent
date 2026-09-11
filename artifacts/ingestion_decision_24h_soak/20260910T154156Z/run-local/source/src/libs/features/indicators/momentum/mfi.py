"""MFI — Money Flow Index indicator."""

from typing import Sequence, Tuple
from collections import deque
import numpy as np
from numba import njit

from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry


@njit(cache=True)
def _compute_mfi_batch(
    high: np.ndarray, low: np.ndarray, close: np.ndarray,
    volume: np.ndarray, period: int
) -> np.ndarray:
    n = len(high)
    out = np.full(n, np.nan)
    if n < period + 1:
        return out
    tp = (high + low + close) / 3.0
    raw_mf = tp * volume
    for i in range(period, n):
        pos_flow = 0.0
        neg_flow = 0.0
        for j in range(i - period + 1, i + 1):
            if tp[j] > tp[j - 1]:
                pos_flow += raw_mf[j]
            elif tp[j] < tp[j - 1]:
                neg_flow += raw_mf[j]
        ratio = pos_flow / neg_flow if neg_flow != 0.0 else 1e9
        out[i] = 100.0 - 100.0 / (1.0 + ratio)
    return out


@IndicatorRegistry.register("MFI")
class MFI(Indicator):
    def __init__(self, period: int = 14):
        super().__init__()
        self.period = period
        # Store (tp, raw_mf) pairs; need period+1 to compare tp direction
        self._buffer: deque = deque(maxlen=period + 1)

    @property
    def lookback_required(self) -> int:
        return self.period + 1

    def batch(self, data: Sequence[Tuple[float, float, float, float]]) -> list[float]:
        if not data:
            return []
        arr = np.array(data, dtype=np.float64)
        high = arr[:, 0]
        low = arr[:, 1]
        close = arr[:, 2]
        volume = arr[:, 3]
        result = _compute_mfi_batch(high, low, close, volume, self.period)
        return [None if np.isnan(x) else x for x in result.tolist()]

    def prime(self, historical_data: Sequence[Tuple[float, float, float, float]]) -> None:
        needed = self.period + 1
        if len(historical_data) < needed:
            raise ValueError(
                f"MFI requires at least {needed} elements to prime."
            )
        self._buffer.clear()
        for h, l, c, v in historical_data[-needed :]:
            tp = (h + l + c) / 3.0
            self._buffer.append((tp, tp * v))
        self._is_primed = True

    def update(self, new_value: Tuple[float, float, float, float]) -> float:
        if not self.is_primed:
            raise RuntimeError(
                "Indicator must be primed before update() can be called."
            )
        h, l, c, v = new_value
        tp = (h + l + c) / 3.0
        raw_mf = tp * v
        self._buffer.append((tp, raw_mf))

        pos_flow = 0.0
        neg_flow = 0.0
        buf = list(self._buffer)
        for i in range(1, len(buf)):
            if buf[i][0] > buf[i - 1][0]:
                pos_flow += buf[i][1]
            elif buf[i][0] < buf[i - 1][0]:
                neg_flow += buf[i][1]

        ratio = pos_flow / neg_flow if neg_flow != 0.0 else 1e9
        return 100.0 - 100.0 / (1.0 + ratio)
