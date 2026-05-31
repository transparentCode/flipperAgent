"""
Volatility Overlay
==================
Rolling volatility percentile rank — fully orthogonal to the HMM.

Output: vol_percentile (0–100) + vol_regime (LOW_VOL | HIGH_VOL).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app.regime.models import VolState

_EPS = 1e-10
_LOW_VOL = "LOW_VOL"
_HIGH_VOL = "HIGH_VOL"


@dataclass(frozen=True)
class VolConfig:
    lookback: int = 168             # 1 week of 1H bars for rolling vol estimate
    high_percentile: float = 70.0   # Percentile above which = HIGH_VOL
    rank_window: int = 1000         # History for percentile ranking
    hysteresis_band: float = 2.0    # ± band around threshold (enter at 72, exit at 68)


class VolOverlay:
    """
    Computes rolling volatility and its percentile rank.

    Usage
    -----
    overlay = VolOverlay()
    state   = overlay.compute(df)          # single-bar output
    df_out  = overlay.compute_series(df)   # full series output
    """

    def __init__(self, config: Optional[VolConfig] = None):
        self.config = config or VolConfig()
        self._current_vol_regime: str = _LOW_VOL  # for hysteresis tracking

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(self, df: pd.DataFrame) -> VolState:
        """
        Compute volatility state at the last bar of df.

        Parameters
        ----------
        df : DataFrame with 'close' column.
        """
        series = self._rolling_vol_series(df)
        if series is None or series.empty:
            return VolState(vol_percentile=50.0, vol_regime=_LOW_VOL, rolling_vol=0.0)

        rolling_vol = float(series.iloc[-1])
        percentile = self._percentile_rank(series)

        # Apply hysteresis: different enter/exit thresholds
        enter_thresh = self.config.high_percentile + self.config.hysteresis_band
        exit_thresh = self.config.high_percentile - self.config.hysteresis_band
        if self._current_vol_regime == _LOW_VOL:
            vol_regime = _HIGH_VOL if percentile >= enter_thresh else _LOW_VOL
        else:
            vol_regime = _LOW_VOL if percentile < exit_thresh else _HIGH_VOL
        self._current_vol_regime = vol_regime

        return VolState(
            vol_percentile=percentile,
            vol_regime=vol_regime,
            rolling_vol=rolling_vol,
        )

    def compute_series(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute volatility state at every bar.

        Adds columns: vol_rolling, vol_percentile, vol_regime.
        """
        series = self._rolling_vol_series(df)
        result = df.copy()

        if series is None or series.empty:
            result["vol_rolling"] = 0.0
            result["vol_percentile"] = 50.0
            result["vol_regime"] = _LOW_VOL
            return result

        # Percentile rank (expanding then capped to rank_window)
        pct = (
            series.rolling(self.config.rank_window, min_periods=1)
            .rank(pct=True) * 100.0
        )

        # Apply hysteresis band to vol_regime series
        enter_thresh = self.config.high_percentile + self.config.hysteresis_band
        exit_thresh = self.config.high_percentile - self.config.hysteresis_band
        vol_regimes = np.empty(len(pct), dtype=object)
        current = _LOW_VOL
        pct_vals = pct.values
        for i in range(len(pct_vals)):
            p = pct_vals[i]
            if np.isnan(p):
                vol_regimes[i] = current
                continue
            if current == _LOW_VOL:
                current = _HIGH_VOL if p >= enter_thresh else _LOW_VOL
            else:
                current = _LOW_VOL if p < exit_thresh else _HIGH_VOL
            vol_regimes[i] = current

        result["vol_rolling"] = series
        result["vol_percentile"] = pct
        result["vol_regime"] = vol_regimes
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rolling_vol_series(self, df: pd.DataFrame) -> Optional[pd.Series]:
        if "close" not in df.columns or len(df) < 2:
            return None
        # Use pct_change so index is preserved (NaN at bar 0)
        log_ret = np.log(df["close"] / df["close"].shift(1))
        return log_ret.rolling(self.config.lookback, min_periods=1).std()

    def _percentile_rank(self, series: pd.Series) -> float:
        """Percentile rank of the last value within rank_window history."""
        history = series.dropna().values
        history = history[-self.config.rank_window :]
        if len(history) == 0:
            return 50.0
        last_val = history[-1]
        rank = (history <= last_val).sum() / len(history) * 100.0
        return float(rank)
