from typing import Sequence
import numpy as np
from numba import njit

from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry

@njit(cache=True)
def _compute_ema_batch(data: np.ndarray, period: int, alpha: float) -> np.ndarray:
    n = len(data)
    result = np.full(n, np.nan)
    if n < period:
        return result
    
    current = np.sum(data[:period]) / period
    result[period - 1] = current
    
    for i in range(period, n):
        current = (data[i] - current) * alpha + current
        result[i] = current
        
    return result

@IndicatorRegistry.register("EMA")
class EMA(Indicator):
    def __init__(self, period: int):
        super().__init__()
        self.period = period
        self.alpha = 2.0 / (period + 1)
        self.current_ema = None

    @property
    def lookback_required(self) -> int:
        return self.period

    def batch(self, data: Sequence[float]) -> list[float]:
        if not data:
            return []
        
        arr = np.array(data, dtype=np.float64)
        numba_res = _compute_ema_batch(arr, self.period, self.alpha)
        
        return [None if np.isnan(x) else x for x in numba_res.tolist()]

    def prime(self, historical_data: Sequence[float]) -> None:
        if len(historical_data) < self.period:
            raise ValueError(f"EMA requires at least {self.period} elements to prime.")
            
        # Prime using the exact batch logic logic to keep parity
        batch_result = self.batch(historical_data)
        self.current_ema = batch_result[-1]
        self._is_primed = True

    def update(self, new_value: float) -> float:
        if not self.is_primed:
            raise RuntimeError("Indicator must be primed before update() can be called.")
            
        self.current_ema = (new_value - self.current_ema) * self.alpha + self.current_ema
        return self.current_ema
