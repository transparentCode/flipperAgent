from typing import Sequence, Any, Tuple
import numpy as np
from numba import njit
from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry

@njit(cache=True)
def _compute_vwap_batch(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray, timestamp: np.ndarray, anchor_offset: int) -> np.ndarray:
    n = len(high)
    vwap = np.full(n, np.nan)
    
    if n == 0:
        return vwap
        
    cum_pv = 0.0
    cum_v = 0.0
    
    # We will anchor on calendar day change (UTC) with optional anchor_offset
    # Assuming timestamp is UNIX epoch in seconds
    current_day = int((timestamp[0] - anchor_offset) / 86400)
    
    for i in range(n):
        day = int((timestamp[i] - anchor_offset) / 86400)
        if day != current_day:
            cum_pv = 0.0
            cum_v = 0.0
            current_day = day
            
        tp = (high[i] + low[i] + close[i]) / 3.0
        pv = tp * volume[i]
        
        cum_pv += pv
        cum_v += volume[i]
        
        if cum_v > 0:
            vwap[i] = cum_pv / cum_v
        else:
            vwap[i] = tp # fallback if no volume but that's rare
            
    return vwap

@IndicatorRegistry.register("VWAP")
class VWAP(Indicator[Tuple[float, float, float, float, float], float]):
    def __init__(self, anchor_offset: int = 0):
        super().__init__()
        self.anchor_offset = anchor_offset
        self.cum_pv = 0.0
        self.cum_v = 0.0
        self.current_day = None

    @property
    def lookback_required(self) -> int:
        return 1

    def batch(self, data: Sequence[Tuple[float, float, float, float, float]]) -> list[Any]:
        if not data:
            return []
            
        arr = np.array(data, dtype=np.float64)
        if len(arr.shape) != 2 or arr.shape[1] != 5:
            raise ValueError("VWAP requires (high, low, close, volume, timestamp) tuples.")
            
        high = arr[:, 0]
        low = arr[:, 1]
        close = arr[:, 2]
        volume = arr[:, 3]
        timestamp = arr[:, 4]
        
        numba_res = _compute_vwap_batch(high, low, close, volume, timestamp, self.anchor_offset)
        
        return [None if np.isnan(x) else x for x in numba_res.tolist()]

    def prime(self, historical_data: Sequence[Tuple[float, float, float, float, float]]) -> None:
        if len(historical_data) < self.lookback_required:
            raise ValueError(f"VWAP requires at least {self.lookback_required} elements to prime.")
            
        # We need the accumulation from the current session
        # Find start of current session from the end
        arr = np.array(historical_data, dtype=np.float64)
        timestamp = arr[:, 4]
        
        last_day = int((timestamp[-1] - self.anchor_offset) / 86400)
        
        cum_pv = 0.0
        cum_v = 0.0
        
        session_start_idx = len(historical_data) - 1
        while session_start_idx >= 0 and int((timestamp[session_start_idx] - self.anchor_offset) / 86400) == last_day:
            session_start_idx -= 1
            
        session_start_idx += 1
        
        for i in range(session_start_idx, len(historical_data)):
            high, low, close, volume, _ = historical_data[i]
            tp = (high + low + close) / 3.0
            cum_pv += tp * volume
            cum_v += volume
            
        self.cum_pv = cum_pv
        self.cum_v = cum_v
        self.current_day = last_day
        self._is_primed = True

    def update(self, new_value: Tuple[float, float, float, float, float]) -> float:
        if not self._is_primed:
            raise RuntimeError("Indicator must be primed before update() can be called.")
            
        high, low, close, volume, timestamp = new_value
        day = int((timestamp - self.anchor_offset) / 86400)
        
        if day != self.current_day:
            self.cum_pv = 0.0
            self.cum_v = 0.0
            self.current_day = day
            
        tp = (high + low + close) / 3.0
        self.cum_pv += tp * volume
        self.cum_v += volume
        
        if self.cum_v > 0:
            return self.cum_pv / self.cum_v
        return tp
