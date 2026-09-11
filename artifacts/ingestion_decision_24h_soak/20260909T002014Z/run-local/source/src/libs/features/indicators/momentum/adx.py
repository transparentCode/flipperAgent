"""ADX — Average Directional Index with +DI / -DI."""

from typing import Any, Sequence, Tuple
from collections import deque
import numpy as np
from numba import njit

from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry


@njit(cache=True)
def _compute_adx_batch(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(high)
    adx_out = np.full(n, np.nan)
    plus_di = np.full(n, np.nan)
    minus_di = np.full(n, np.nan)
    if n < 2 * period + 1:
        return adx_out, plus_di, minus_di

    tr = np.zeros(n)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i] = max(hl, max(hc, lc))
        up = high[i] - high[i - 1]
        dn = low[i - 1] - low[i]
        plus_dm[i] = up if (up > dn and up > 0) else 0.0
        minus_dm[i] = dn if (dn > up and dn > 0) else 0.0

    atr_s = 0.0
    pdm_s = 0.0
    mdm_s = 0.0
    for i in range(1, period + 1):
        atr_s += tr[i]
        pdm_s += plus_dm[i]
        mdm_s += minus_dm[i]

    for i in range(period + 1, n):
        atr_s = atr_s - atr_s / period + tr[i]
        pdm_s = pdm_s - pdm_s / period + plus_dm[i]
        mdm_s = mdm_s - mdm_s / period + minus_dm[i]
        pdi = 100.0 * pdm_s / atr_s if atr_s != 0.0 else 0.0
        mdi = 100.0 * mdm_s / atr_s if atr_s != 0.0 else 0.0
        plus_di[i] = pdi
        minus_di[i] = mdi
        dx_denom = pdi + mdi
        dx = 100.0 * abs(pdi - mdi) / dx_denom if dx_denom != 0.0 else 0.0
        if i == 2 * period:
            adx_out[i] = dx
        elif i > 2 * period and not np.isnan(adx_out[i - 1]):
            adx_out[i] = (adx_out[i - 1] * (period - 1) + dx) / period

    return adx_out, plus_di, minus_di


@IndicatorRegistry.register("ADX")
class ADX(Indicator):
    def __init__(self, period: int = 14):
        super().__init__()
        self.period = period
        # Wilder smoothed accumulators
        self._atr_s: float = 0.0
        self._pdm_s: float = 0.0
        self._mdm_s: float = 0.0
        self._adx: float = 0.0
        self._adx_ready: bool = False
        self._tick_count: int = 0
        self._prev_high: float = 0.0
        self._prev_low: float = 0.0
        self._prev_close: float = 0.0
        # Initial sums for first period
        self._init_tr: list = []
        self._init_pdm: list = []
        self._init_mdm: list = []

    @property
    def lookback_required(self) -> int:
        return 2 * self.period + 1

    def batch(self, data: Sequence[Tuple[float, float, float]]) -> list[dict]:
        if not data:
            return []
        arr = np.array(data, dtype=np.float64)
        high = arr[:, 0]
        low = arr[:, 1]
        close = arr[:, 2]
        adx_arr, pdi_arr, mdi_arr = _compute_adx_batch(high, low, close, self.period)
        results = []
        for i in range(len(data)):
            if np.isnan(adx_arr[i]):
                results.append(None)
            else:
                results.append({
                    "adx": adx_arr[i],
                    "plus_di": pdi_arr[i],
                    "minus_di": mdi_arr[i],
                })
        return results

    def prime(self, historical_data: Sequence[Tuple[float, float, float]]) -> None:
        needed = 2 * self.period + 1
        if len(historical_data) < needed:
            raise ValueError(
                f"ADX requires at least {needed} elements to prime."
            )
        # Run batch and reconstruct internal state from the tail
        arr = np.array(historical_data, dtype=np.float64)
        high = arr[:, 0]
        low = arr[:, 1]
        close = arr[:, 2]
        n = len(high)

        # Recompute TR, +DM, -DM
        tr = np.zeros(n)
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        for i in range(1, n):
            hl = high[i] - low[i]
            hc = abs(high[i] - close[i - 1])
            lc = abs(low[i] - close[i - 1])
            tr[i] = max(hl, hc, lc)
            up = high[i] - high[i - 1]
            dn = low[i - 1] - low[i]
            plus_dm[i] = up if (up > dn and up > 0) else 0.0
            minus_dm[i] = dn if (dn > up and dn > 0) else 0.0

        atr_s = sum(tr[1 : self.period + 1])
        pdm_s = sum(plus_dm[1 : self.period + 1])
        mdm_s = sum(minus_dm[1 : self.period + 1])

        adx_val = 0.0
        adx_ready = False
        for i in range(self.period + 1, n):
            atr_s = atr_s - atr_s / self.period + tr[i]
            pdm_s = pdm_s - pdm_s / self.period + plus_dm[i]
            mdm_s = mdm_s - mdm_s / self.period + minus_dm[i]
            pdi = 100.0 * pdm_s / atr_s if atr_s != 0.0 else 0.0
            mdi = 100.0 * mdm_s / atr_s if atr_s != 0.0 else 0.0
            dx_denom = pdi + mdi
            dx = 100.0 * abs(pdi - mdi) / dx_denom if dx_denom != 0.0 else 0.0
            if i == 2 * self.period:
                adx_val = dx
                adx_ready = True
            elif i > 2 * self.period and adx_ready:
                adx_val = (adx_val * (self.period - 1) + dx) / self.period

        self._atr_s = atr_s
        self._pdm_s = pdm_s
        self._mdm_s = mdm_s
        self._adx = adx_val
        self._adx_ready = adx_ready
        self._prev_high = high[-1]
        self._prev_low = low[-1]
        self._prev_close = close[-1]
        self._tick_count = n
        self._is_primed = True

    def update(self, new_value: Tuple[float, float, float]) -> dict:
        if not self.is_primed:
            raise RuntimeError(
                "Indicator must be primed before update() can be called."
            )
        h, l, c = new_value

        # True Range
        hl = h - l
        hc = abs(h - self._prev_close)
        lc = abs(l - self._prev_close)
        tr = max(hl, hc, lc)

        # Directional Movement
        up = h - self._prev_high
        dn = self._prev_low - l
        pdm = up if (up > dn and up > 0) else 0.0
        mdm = dn if (dn > up and dn > 0) else 0.0

        # Wilder smooth
        self._atr_s = self._atr_s - self._atr_s / self.period + tr
        self._pdm_s = self._pdm_s - self._pdm_s / self.period + pdm
        self._mdm_s = self._mdm_s - self._mdm_s / self.period + mdm

        pdi = 100.0 * self._pdm_s / self._atr_s if self._atr_s != 0.0 else 0.0
        mdi = 100.0 * self._mdm_s / self._atr_s if self._atr_s != 0.0 else 0.0
        dx_denom = pdi + mdi
        dx = 100.0 * abs(pdi - mdi) / dx_denom if dx_denom != 0.0 else 0.0

        self._tick_count += 1
        if self._adx_ready:
            self._adx = (self._adx * (self.period - 1) + dx) / self.period
        else:
            if self._tick_count >= 2 * self.period + 1:
                self._adx = dx
                self._adx_ready = True

        self._prev_high = h
        self._prev_low = l
        self._prev_close = c

        return {"adx": self._adx, "plus_di": pdi, "minus_di": mdi}
