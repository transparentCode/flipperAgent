"""
Rolling Volatility Percentile Rank.

Computes rolling vol (std of log-returns) and its percentile rank
within a historical window. Emits continuous values only — no
discrete HIGH/LOW classification.

Adapted from libs/regime/vol_overlay.py — zero imports from old module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from libs.models.regime_classification.contracts import VolStateLocal


@dataclass(frozen=True)
class VolPercentileConfig:
    lookback: int = 168  # 1 week of 1h bars for rolling vol estimate
    rank_window: int = 1000  # history for percentile ranking


class VolPercentile:
    """
    Computes rolling volatility and its percentile rank.

    Usage
    -----
    vp = VolPercentile()
    state = vp.compute(df)             # single-bar output
    df_out = vp.compute_series(df)     # full series output
    """

    def __init__(self, config: Optional[VolPercentileConfig] = None):
        self.config = config or VolPercentileConfig()

    def compute(self, df: pd.DataFrame) -> VolStateLocal:
        """Compute volatility state at the last bar of df."""
        series = self._rolling_vol_series(df)
        if series is None or series.empty:
            return VolStateLocal(vol_percentile=50.0, rolling_vol=0.0)

        rolling_vol = float(series.iloc[-1])
        percentile = self._percentile_rank(series)

        return VolStateLocal(
            vol_percentile=percentile,
            rolling_vol=rolling_vol,
        )

    def compute_series(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute volatility state at every bar.

        Adds columns: vol_rolling, vol_percentile.
        """
        series = self._rolling_vol_series(df)
        result = df.copy()

        if series is None or series.empty:
            result["vol_rolling"] = 0.0
            result["vol_percentile"] = 50.0
            return result

        pct = (
            series.rolling(self.config.rank_window, min_periods=1)
            .rank(pct=True)
            * 100.0
        )

        result["vol_rolling"] = series
        result["vol_percentile"] = pct
        return result

    def _rolling_vol_series(self, df: pd.DataFrame) -> Optional[pd.Series]:
        if "close" not in df.columns or len(df) < 2:
            return None
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
