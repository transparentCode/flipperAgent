"""ADLine — Accumulation / Distribution Line indicator."""

from typing import Sequence, Tuple
import numpy as np
from numba import njit

from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry


@njit(cache=True)
def _compute_ad_line_batch(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray
) -> np.ndarray:
    n = len(high)
    out = np.zeros(n)
    for i in range(n):
        hl = high[i] - low[i]
        if hl == 0.0:
            clv = 0.0
        else:
            clv = ((close[i] - low[i]) - (high[i] - close[i])) / hl
        ad_val = clv * volume[i]
        out[i] = out[i - 1] + ad_val if i > 0 else ad_val
    return out


@IndicatorRegistry.register("ADLine")
class ADLine(Indicator):
    def __init__(self):
        super().__init__()
        self._accumulator: float = 0.0

    @property
    def lookback_required(self) -> int:
        return 0

    def batch(self, data: Sequence[Tuple[float, float, float, float]]) -> list[float]:
        if not data:
            return []
        arr = np.array(data, dtype=np.float64)
        high = arr[:, 0]
        low = arr[:, 1]
        close = arr[:, 2]
        volume = arr[:, 3]
        result = _compute_ad_line_batch(high, low, close, volume)
        return result.tolist()

    def prime(self, historical_data: Sequence[Tuple[float, float, float, float]]) -> None:
        self._accumulator = 0.0
        for h, l, c, v in historical_data:
            hl = h - l
            if hl == 0.0:
                clv = 0.0
            else:
                clv = ((c - l) - (h - c)) / hl
            self._accumulator += clv * v
        self._is_primed = True

    def update(self, new_value: Tuple[float, float, float, float]) -> float:
        if not self.is_primed:
            raise RuntimeError(
                "Indicator must be primed before update() can be called."
            )
        h, l, c, v = new_value
        hl = h - l
        if hl == 0.0:
            clv = 0.0
        else:
            clv = ((c - l) - (h - c)) / hl
        self._accumulator += clv * v
        return self._accumulator
