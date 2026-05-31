"""TFI — Taker Flow Imbalance indicator."""

from __future__ import annotations

from collections import deque
from typing import Any, Sequence

import numpy as np
import pandas as pd

from libs.features.indicators.base import Indicator
from libs.features.indicators.registry import IndicatorRegistry


@IndicatorRegistry.register("TFI")
class TFI(Indicator):
    """Exponentially-smoothed taker buy ratio with z-score normalisation.

    Parameters
    ----------
    smooth : int
        EWM span for the raw taker-buy ratio.
    zscore_window : int
        Rolling window for z-score normalisation.
    """

    def __init__(self, smooth: int = 5, zscore_window: int = 100) -> None:
        super().__init__()
        self.smooth = smooth
        self.zscore_window = zscore_window

        # Live streaming state
        self._tfi_buf: deque[float] = deque(maxlen=zscore_window)
        self._ewm_state: float | None = None
        self._alpha: float = 2.0 / (smooth + 1)

    @property
    def lookback_required(self) -> int:
        return self.zscore_window + self.smooth

    # ------------------------------------------------------------------
    # Batch (vectorised)
    # ------------------------------------------------------------------

    def batch(self, data: pd.DataFrame) -> dict[str, Any]:
        """Compute TFI over a DataFrame.

        Expected columns: volume, taker_buy_base.
        """
        volume = data["volume"].values.astype(np.float64)
        taker_buy_base = data["taker_buy_base"].values.astype(np.float64)

        tfi_raw = taker_buy_base / np.maximum(volume, 1e-12)
        tfi = pd.Series(tfi_raw).ewm(span=self.smooth, adjust=False).mean().values

        tfi_series = pd.Series(tfi)
        roll_mean = tfi_series.rolling(self.zscore_window, min_periods=1).mean().values
        roll_std = tfi_series.rolling(self.zscore_window, min_periods=1).std(ddof=0).values
        roll_std = np.where(roll_std < 1e-12, 1e-12, roll_std)
        tfi_zscore = (tfi - roll_mean) / roll_std

        return {
            "tfi": tfi,
            "tfi_zscore": tfi_zscore,
        }

    # ------------------------------------------------------------------
    # Prime
    # ------------------------------------------------------------------

    def prime(self, historical_data: Sequence[dict[str, float]]) -> None:
        self._tfi_buf.clear()
        self._ewm_state = None

        for tick in historical_data:
            self._push_tick(tick)

        self._is_primed = True

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, new_value: dict[str, float]) -> dict[str, Any]:
        if not self.is_primed:
            raise RuntimeError("Indicator must be primed before update() can be called.")
        return self._push_tick(new_value)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _push_tick(self, tick: dict[str, float]) -> dict[str, Any]:
        volume = float(tick["volume"])
        taker_buy_base = float(tick["taker_buy_base"])

        raw = taker_buy_base / max(volume, 1e-12)

        # EWM update
        if self._ewm_state is None:
            self._ewm_state = raw
        else:
            self._ewm_state = self._alpha * raw + (1 - self._alpha) * self._ewm_state

        tfi = self._ewm_state
        self._tfi_buf.append(tfi)

        buf_arr = np.array(self._tfi_buf)
        mean = float(np.mean(buf_arr))
        std = float(np.std(buf_arr))
        if std < 1e-12:
            std = 1e-12
        tfi_zscore = (tfi - mean) / std

        return {
            "tfi": tfi,
            "tfi_zscore": tfi_zscore,
        }
