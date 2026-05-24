from typing import Sequence, Any, Tuple
import numpy as np
from numba import njit
from collections import deque
import math
from src.libs.features.indicators.base import Indicator
from src.libs.features.indicators.registry import IndicatorRegistry

@njit(cache=True)
def _compute_bb_batch(data: np.ndarray, period: int, num_std: float) -> tuple:
    n = len(data)
    sma = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    
    if n < period:
        return sma, upper, lower
        
    for i in range(period - 1, n):
        window = data[i - period + 1 : i + 1]
        mean_val = np.mean(window)
        std_val = np.std(window)
        sma[i] = mean_val
        upper[i] = mean_val + num_std * std_val
        lower[i] = mean_val - num_std * std_val
        
    return sma, upper, lower

@IndicatorRegistry.register("BollingerBands")
class BollingerBands(Indicator[float, Tuple[float, float, float]]):
    def __init__(self, period: int = 20, num_std: float = 2.0):
        super().__init__()
        self.period = period
        self.num_std = num_std
        self.buffer = deque(maxlen=period)
        self.rolling_sum = 0.0
        self.rolling_sum_sq = 0.0

    @property
    def lookback_required(self) -> int:
        return self.period

    def batch(self, data: Sequence[float]) -> list[Any]:
        if not data:
            return []
            
        arr = np.array(data, dtype=np.float64)
        sma, upper, lower = _compute_bb_batch(arr, self.period, self.num_std)
        
        result = []
        for i in range(len(arr)):
            if np.isnan(sma[i]):
                result.append(None)
            else:
                result.append((sma[i], upper[i], lower[i]))
        return result

    def prime(self, historical_data: Sequence[float]) -> None:
        if len(historical_data) < self.lookback_required:
            raise ValueError(f"BollingerBands requires at least {self.lookback_required} elements to prime.")
            
        window = historical_data[-self.period:]
        self.buffer.extend(window)
        
        self.rolling_sum = sum(window)
        self.rolling_sum_sq = sum(x * x for x in window)
        
        self._is_primed = True

    def update(self, new_value: float) -> Tuple[float, float, float]:
        if not self.is_primed:
            raise RuntimeError("Indicator must be primed before update() can be called.")
            
        old_value = self.buffer[0] if len(self.buffer) == self.period else 0.0
        
        self.buffer.append(new_value)
        
        self.rolling_sum += new_value - old_value
        self.rolling_sum_sq += (new_value * new_value) - (old_value * old_value)
        
        mean_val = self.rolling_sum / self.period
        
        # Avoid negative variance due to floating point drift
        variance = max(0.0, (self.rolling_sum_sq / self.period) - (mean_val * mean_val))
        std_val = math.sqrt(variance)
        
        upper = mean_val + self.num_std * std_val
        lower = mean_val - self.num_std * std_val
        
        return mean_val, upper, lower
