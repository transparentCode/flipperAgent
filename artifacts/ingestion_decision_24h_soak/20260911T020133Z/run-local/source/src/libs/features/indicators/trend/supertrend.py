from typing import Sequence, Any, Tuple
import numpy as np
from numba import njit
from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry
from libs.features.indicators.volatility.atr import _compute_atr_batch, ATR

@njit(cache=True)
def _compute_supertrend_batch(high: np.ndarray, low: np.ndarray, close: np.ndarray, atr: np.ndarray, multiplier: float) -> tuple:
    n = len(high)
    st = np.full(n, np.nan)
    direction = np.zeros(n, dtype=np.int32)
    final_ub = np.full(n, np.nan)
    final_lb = np.full(n, np.nan)
    
    # We need the first valid ATR
    start_idx = 0
    while start_idx < n and np.isnan(atr[start_idx]):
        start_idx += 1
        
    if start_idx >= n:
        return st, direction, final_ub, final_lb
        
    # Initialize basic bands for start_idx
    hl2 = (high[start_idx] + low[start_idx]) / 2.0
    matr = multiplier * atr[start_idx]
    
    final_ub[start_idx] = hl2 + matr
    final_lb[start_idx] = hl2 - matr
    
    direction[start_idx] = 1 # Initial assume up
    st[start_idx] = final_lb[start_idx]
    
    for i in range(start_idx + 1, n):
        hl2 = (high[i] + low[i]) / 2.0
        matr = multiplier * atr[i]
        basic_ub = hl2 + matr
        basic_lb = hl2 - matr
        
        # update final UB
        if basic_ub < final_ub[i-1] or close[i-1] > final_ub[i-1]:
            final_ub[i] = basic_ub
        else:
            final_ub[i] = final_ub[i-1]
            
        # update final LB
        if basic_lb > final_lb[i-1] or close[i-1] < final_lb[i-1]:
            final_lb[i] = basic_lb
        else:
            final_lb[i] = final_lb[i-1]
            
        # determine Supertrend and direction
        if st[i-1] == final_ub[i-1]:
            if close[i] <= final_ub[i]:
                direction[i] = -1
                st[i] = final_ub[i]
            else:
                direction[i] = 1
                st[i] = final_lb[i]
        elif st[i-1] == final_lb[i-1]:
            if close[i] >= final_lb[i]:
                direction[i] = 1
                st[i] = final_lb[i]
            else:
                direction[i] = -1
                st[i] = final_ub[i]
                
    return st, direction, final_ub, final_lb

@IndicatorRegistry.register("Supertrend")
class Supertrend(Indicator):
    def __init__(self, period: int = 10, multiplier: float = 3.0):
        super().__init__()
        self.period = period
        self.multiplier = multiplier
        self.atr_ind = ATR(period)
        
        self.prev_close = None
        self.prev_final_ub = None
        self.prev_final_lb = None
        self.prev_st = None
        self.direction = 1

    @property
    def lookback_required(self) -> int:
        return self.period + 1

    def batch(self, data: Sequence[Tuple[float, float, float]]) -> list[Any]:
        if not data:
            return []
            
        arr = np.array(data, dtype=np.float64)
        if len(arr.shape) != 2 or arr.shape[1] != 3:
            raise ValueError("Supertrend requires (high, low, close) tuples.")
            
        high = arr[:, 0]
        low = arr[:, 1]
        close = arr[:, 2]
        
        atr = _compute_atr_batch(high, low, close, self.period)
        st, direction, _, _ = _compute_supertrend_batch(high, low, close, atr, self.multiplier)
        
        result = []
        for i in range(len(arr)):
            if np.isnan(st[i]):
                result.append(None)
            else:
                result.append((st[i], int(direction[i])))
        return result

    def prime(self, historical_data: Sequence[Tuple[float, float, float]]) -> None:
        if len(historical_data) < self.lookback_required:
            raise ValueError(f"Supertrend requires at least {self.lookback_required} elements to prime.")
            
        self.atr_ind.prime(historical_data)
        
        arr = np.array(historical_data, dtype=np.float64)
        high = arr[:, 0]
        low = arr[:, 1]
        close = arr[:, 2]
        atr = _compute_atr_batch(high, low, close, self.period)
        st, direction, final_ub, final_lb = _compute_supertrend_batch(high, low, close, atr, self.multiplier)
        
        self.prev_final_ub = final_ub[-1]
        self.prev_final_lb = final_lb[-1]
        self.prev_st = st[-1]
        self.direction = int(direction[-1])
        self.prev_close = close[-1]
        
        self._is_primed = True

    def update(self, new_value: Tuple[float, float, float]) -> Tuple[float, int]:
        if not self._is_primed:
            raise RuntimeError("Indicator must be primed before update() can be called.")
            
        high, low, close = new_value
        current_atr = self.atr_ind.update(new_value)
        
        hl2 = (high + low) / 2.0
        matr = self.multiplier * current_atr
        basic_ub = hl2 + matr
        basic_lb = hl2 - matr
        
        # update final UB
        if basic_ub < self.prev_final_ub or self.prev_close > self.prev_final_ub:
            final_ub = basic_ub
        else:
            final_ub = self.prev_final_ub
            
        # update final LB
        if basic_lb > self.prev_final_lb or self.prev_close < self.prev_final_lb:
            final_lb = basic_lb
        else:
            final_lb = self.prev_final_lb
            
        # determine Supertrend and direction
        if self.prev_st == self.prev_final_ub:
            if close <= final_ub:
                self.direction = -1
                current_st = final_ub
            else:
                self.direction = 1
                current_st = final_lb
        else: # prev_st == prev_final_lb
            if close >= final_lb:
                self.direction = 1
                current_st = final_lb
            else:
                self.direction = -1
                current_st = final_ub
                
        self.prev_final_ub = final_ub
        self.prev_final_lb = final_lb
        self.prev_st = current_st
        self.prev_close = close
        
        return current_st, self.direction
