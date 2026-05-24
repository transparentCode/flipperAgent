from typing import Sequence, Any, Tuple
import numpy as np
from numba import njit
from src.libs.features.indicators.base import Indicator
from src.libs.features.indicators.registry import IndicatorRegistry
from src.libs.features.indicators.trend.ema import _compute_ema_batch, EMA

@njit(cache=True)
def _compute_macd_batch(data: np.ndarray, fast_period: int, slow_period: int, signal_period: int) -> tuple:
    n = len(data)
    macd_line = np.full(n, np.nan)
    signal_line = np.full(n, np.nan)
    histogram = np.full(n, np.nan)

    if n < slow_period:
        return macd_line, signal_line, histogram

    fast_alpha = 2.0 / (fast_period + 1)
    slow_alpha = 2.0 / (slow_period + 1)
    signal_alpha = 2.0 / (signal_period + 1)

    fast_ema = np.sum(data[:fast_period]) / fast_period
    slow_ema = np.sum(data[:slow_period]) / slow_period

    # Fast EMA needs to progress to slow_period
    for i in range(fast_period, slow_period):
        fast_ema = (data[i] - fast_ema) * fast_alpha + fast_ema

    macd_line[slow_period - 1] = fast_ema - slow_ema

    macd_history = np.zeros(n)
    macd_history[slow_period - 1] = fast_ema - slow_ema

    # Calculate MACD line
    count = 1
    for i in range(slow_period, n):
        fast_ema = (data[i] - fast_ema) * fast_alpha + fast_ema
        slow_ema = (data[i] - slow_ema) * slow_alpha + slow_ema
        mac_val = fast_ema - slow_ema
        macd_line[i] = mac_val
        macd_history[i] = mac_val
        count += 1

    # Signal line is EMA of MACD line. Starts after we have signal_period values of MACD line
    signal_start = slow_period - 1 + signal_period
    if n < signal_start:
        return macd_line, signal_line, histogram

    curr_signal = np.sum(macd_history[slow_period-1:signal_start]) / signal_period
    signal_line[signal_start - 1] = curr_signal
    histogram[signal_start - 1] = macd_history[signal_start - 1] - curr_signal

    for i in range(signal_start, n):
        curr_signal = (macd_history[i] - curr_signal) * signal_alpha + curr_signal
        signal_line[i] = curr_signal
        histogram[i] = macd_history[i] - curr_signal

    return macd_line, signal_line, histogram

@IndicatorRegistry.register("MACD")
class MACD(Indicator):
    def __init__(self, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
        super().__init__()
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        
        self.fast_ema = EMA(fast_period)
        self.slow_ema = EMA(slow_period)
        self.signal_ema = EMA(signal_period)

    @property
    def lookback_required(self) -> int:
        return self.slow_period + self.signal_period - 1

    def batch(self, data: Sequence[float]) -> list[Any]:
        if not data:
            return []
            
        arr = np.array(data, dtype=np.float64)
        m_line, s_line, hist = _compute_macd_batch(arr, self.fast_period, self.slow_period, self.signal_period)
        
        result = []
        for i in range(len(arr)):
            m = None if np.isnan(m_line[i]) else m_line[i]
            s = None if np.isnan(s_line[i]) else s_line[i]
            h = None if np.isnan(hist[i]) else hist[i]
            if m is None and s is None and h is None:
                result.append(None)
            else:
                result.append((m, s, h))
        return result

    def prime(self, historical_data: Sequence[float]) -> None:
        if len(historical_data) < self.lookback_required:
            raise ValueError(f"MACD requires at least {self.lookback_required} elements to prime.")
            
        res = self.batch(historical_data)
        
        # Determine internal states
        # The easiest way is to fully prime the EMAs sequentially or recreate them
        fast_ema_val = np.sum(historical_data[:self.fast_period]) / self.fast_period
        for val in historical_data[self.fast_period:]:
            fast_ema_val = (val - fast_ema_val) * self.fast_ema.alpha + fast_ema_val
            
        slow_ema_val = np.sum(historical_data[:self.slow_period]) / self.slow_period
        macd_history = [fast_ema_val - slow_ema_val] # NOT purely accurate for the first elements but the loop below does it right
        
        # Actually, let's just let the internal EMAs handle it by priming them
        self.fast_ema.prime(historical_data)
        self.slow_ema.prime(historical_data)
        
        # For the signal_ema, its history is the macd line
        arr = np.array(historical_data, dtype=np.float64)
        m_line, _, _ = _compute_macd_batch(arr, self.fast_period, self.slow_period, self.signal_period)
        
        # m_line has nans. We need the actual valid values
        valid_macd = m_line[~np.isnan(m_line)]
        self.signal_ema.prime(valid_macd.tolist())
        
        self._is_primed = True

    def update(self, new_value: float) -> Tuple[float, float, float]:
        if not self.is_primed:
            raise RuntimeError("Indicator must be primed before update() can be called.")
            
        fast_val = self.fast_ema.update(new_value)
        slow_val = self.slow_ema.update(new_value)
        
        macd_val = fast_val - slow_val
        signal_val = self.signal_ema.update(macd_val)
        hist_val = macd_val - signal_val
        
        return macd_val, signal_val, hist_val
