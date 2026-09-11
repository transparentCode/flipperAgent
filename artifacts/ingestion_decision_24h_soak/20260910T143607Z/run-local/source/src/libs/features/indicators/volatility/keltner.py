"""KeltnerChannel — EMA midline with ATR-based bands."""

from typing import Any, Sequence, Tuple
from collections import deque
import numpy as np
from numba import njit

from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry
from libs.features.indicators.volatility.atr import _compute_atr_batch


@njit(cache=True)
def _compute_keltner_batch(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int,
    multiplier: float,
    atr_period: int,
) -> tuple:
    n = len(high)
    middle = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)

    if n < max(period, atr_period + 1):
        return middle, upper, lower

    # EMA of close
    alpha = 2.0 / (period + 1)
    ema = np.sum(close[:period]) / period
    middle[period - 1] = ema
    for i in range(period, n):
        ema = (close[i] - ema) * alpha + ema
        middle[i] = ema

    # ATR
    atr = _compute_atr_batch(high, low, close, atr_period)

    # Combine
    for i in range(n):
        if not np.isnan(middle[i]) and not np.isnan(atr[i]):
            upper[i] = middle[i] + multiplier * atr[i]
            lower[i] = middle[i] - multiplier * atr[i]

    return middle, upper, lower


@IndicatorRegistry.register("KeltnerChannel")
class KeltnerChannel(Indicator[Tuple[float, float, float], Tuple[float, float, float]]):
    def __init__(
        self, period: int = 20, multiplier: float = 1.5, atr_period: int = 14
    ):
        super().__init__()
        self.period = period
        self.multiplier = multiplier
        self.atr_period = atr_period
        self.alpha = 2.0 / (period + 1)
        self.current_ema = None
        self.current_atr = None
        self.prev_close = None

    @property
    def lookback_required(self) -> int:
        return max(self.period, self.atr_period + 1)

    def batch(self, data: Sequence[Tuple[float, float, float]]) -> list[Any]:
        if not data:
            return []

        arr = np.array(data, dtype=np.float64)
        if len(arr.shape) != 2 or arr.shape[1] != 3:
            raise ValueError("KeltnerChannel requires (high, low, close) tuples.")

        high = arr[:, 0]
        low = arr[:, 1]
        close = arr[:, 2]

        mid, up, lo = _compute_keltner_batch(
            high, low, close, self.period, self.multiplier, self.atr_period
        )

        result = []
        for i in range(len(arr)):
            if np.isnan(mid[i]) or np.isnan(up[i]):
                result.append(None)
            else:
                result.append((mid[i], up[i], lo[i]))
        return result

    def prime(self, historical_data: Sequence[Tuple[float, float, float]]) -> None:
        if len(historical_data) < self.lookback_required:
            raise ValueError(
                f"KeltnerChannel requires at least {self.lookback_required} elements to prime."
            )
        batch_result = self.batch(historical_data)
        last_valid = batch_result[-1]
        if last_valid is not None:
            self.current_ema = last_valid[0]

        # Prime ATR state
        arr = np.array(historical_data, dtype=np.float64)
        atr_arr = _compute_atr_batch(
            arr[:, 0], arr[:, 1], arr[:, 2], self.atr_period
        )
        for i in range(len(atr_arr) - 1, -1, -1):
            if not np.isnan(atr_arr[i]):
                self.current_atr = float(atr_arr[i])
                break

        self.prev_close = historical_data[-1][2]
        self._is_primed = True

    def update(
        self, new_value: Tuple[float, float, float]
    ) -> Tuple[float, float, float]:
        if not self.is_primed:
            raise RuntimeError(
                "Indicator must be primed before update() can be called."
            )

        high, low, close = new_value

        # Update EMA
        self.current_ema = (close - self.current_ema) * self.alpha + self.current_ema

        # Update ATR
        hl = high - low
        hc = abs(high - self.prev_close) if self.prev_close is not None else hl
        lc = abs(low - self.prev_close) if self.prev_close is not None else hl
        tr = max(hl, hc, lc)
        self.current_atr = (
            self.current_atr * (self.atr_period - 1) + tr
        ) / self.atr_period

        self.prev_close = close

        upper = self.current_ema + self.multiplier * self.current_atr
        lower = self.current_ema - self.multiplier * self.current_atr

        return self.current_ema, upper, lower
