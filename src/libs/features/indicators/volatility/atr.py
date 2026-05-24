from typing import Sequence, Any, Tuple
import numpy as np
from numba import njit
from src.libs.features.indicators.base import Indicator
from src.libs.features.indicators.registry import IndicatorRegistry

@njit(cache=True)
def _compute_atr_batch(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    n = len(high)
    atr = np.full(n, np.nan)
    if n < period + 1:
        return atr
        
    tr = np.zeros(n)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i-1])
        lc = abs(low[i] - close[i-1])
        tr[i] = max(hl, hc, lc)
        
    current_atr = np.sum(tr[1:period+1]) / period
    atr[period] = current_atr
    
    for i in range(period + 1, n):
        current_atr = (current_atr * (period - 1) + tr[i]) / period
        atr[i] = current_atr
        
    return atr

@IndicatorRegistry.register("ATR")
class ATR(Indicator):
    def __init__(self, period: int = 14):
        super().__init__()
        self.period = period
        self.current_atr = None
        self.prev_close = None

    @property
    def lookback_required(self) -> int:
        return self.period + 1

    def batch(self, data: Sequence[Tuple[float, float, float]]) -> list[Any]:
        if not data:
            return []
            
        arr = np.array(data, dtype=np.float64)
        if len(arr.shape) != 2 or arr.shape[1] != 3:
            raise ValueError("ATR requires (high, low, close) tuples.")
        
        high = arr[:, 0]
        low = arr[:, 1]
        close = arr[:, 2]
        
        numba_res = _compute_atr_batch(high, low, close, self.period)
        
        return [None if np.isnan(x) else x for x in numba_res.tolist()]

    def prime(self, historical_data: Sequence[Tuple[float, float, float]]) -> None:
        if len(historical_data) < self.lookback_required:
            raise ValueError(f"ATR requires at least {self.lookback_required} elements to prime.")
            
        batch_result = self.batch(historical_data)
        self.current_atr = batch_result[-1]
        self.prev_close = historical_data[-1][2]
        self._is_primed = True

    def update(self, new_value: Tuple[float, float, float]) -> float:
        if not self.is_primed:
            raise RuntimeError("Indicator must be primed before update() can be called.")
            
        high, low, close = new_value
        hl = high - low
        hc = abs(high - self.prev_close) if self.prev_close is not None else hl
        lc = abs(low - self.prev_close) if self.prev_close is not None else hl
        tr = max(hl, hc, lc)
        
        self.current_atr = (self.current_atr * (self.period - 1) + tr) / self.period
        self.prev_close = close
        
        return self.current_atr
