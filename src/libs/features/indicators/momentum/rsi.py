from typing import Sequence
import numpy as np
from numba import njit

from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry

@njit(cache=True)
def _compute_rsi_batch(data: np.ndarray, period: int) -> np.ndarray:
    n = len(data)
    result = np.full(n, np.nan)
    if n < period + 1:
        return result
        
    sum_gain = 0.0
    sum_loss = 0.0
    for i in range(1, period + 1):
        change = data[i] - data[i-1]
        if change > 0:
            sum_gain += change
        else:
            sum_loss += abs(change)
            
    avg_gain = sum_gain / period
    avg_loss = sum_loss / period
    
    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))
        
    for i in range(period + 1, n):
        change = data[i] - data[i-1]
        gain = change if change > 0 else 0.0
        loss = abs(change) if change < 0 else 0.0
        
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        
        if avg_loss == 0:
            result[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i] = 100.0 - (100.0 / (1.0 + rs))
            
    return result


@IndicatorRegistry.register("RSI")
class RSI(Indicator):
    def __init__(self, period: int = 14):
        super().__init__()
        self.period = period
        self.avg_gain = 0.0
        self.avg_loss = 0.0
        self.last_value = None

    @property
    def lookback_required(self) -> int:
        return self.period + 1

    def batch(self, data: Sequence[float]) -> list[float]:
        if not data:
            return []
        
        arr = np.array(data, dtype=np.float64)
        numba_res = _compute_rsi_batch(arr, self.period)
        
        return [None if np.isnan(x) else x for x in numba_res.tolist()]

    def prime(self, historical_data: Sequence[float]) -> None:
        if len(historical_data) < self.period + 1:
            raise ValueError(f"RSI requires at least {self.period + 1} elements to prime.")
            
        # Initialize running averages using historical data
        gains = []
        losses = []
        
        for i in range(1, self.period + 1):
            change = historical_data[i] - historical_data[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))
                
        avg_g = sum(gains) / self.period
        avg_l = sum(losses) / self.period
        
        for i in range(self.period + 1, len(historical_data)):
            change = historical_data[i] - historical_data[i-1]
            gain = change if change > 0 else 0.0
            loss = abs(change) if change < 0 else 0.0
            avg_g = (avg_g * (self.period - 1) + gain) / self.period
            avg_l = (avg_l * (self.period - 1) + loss) / self.period
            
        self.avg_gain = avg_g
        self.avg_loss = avg_l
        self.last_value = historical_data[-1]
        self._is_primed = True

    def update(self, new_value: float) -> float:
        if not self.is_primed:
            raise RuntimeError("Indicator must be primed before update() can be called.")
            
        change = new_value - self.last_value
        gain = change if change > 0 else 0.0
        loss = abs(change) if change < 0 else 0.0
        
        self.avg_gain = (self.avg_gain * (self.period - 1) + gain) / self.period
        self.avg_loss = (self.avg_loss * (self.period - 1) + loss) / self.period
        
        self.last_value = new_value
        
        if self.avg_loss == 0:
            return 100.0
            
        rs = self.avg_gain / self.avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
