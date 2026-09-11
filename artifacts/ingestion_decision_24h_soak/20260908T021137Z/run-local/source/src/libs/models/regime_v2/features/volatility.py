"""Volatility evidence features for RegimeV2."""

from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_v2.config import VolatilityConfig
from libs.models.regime_v2.features.utils import clip01, rolling_percentile, rolling_zscore, true_range


def compute_volatility_features(df: pd.DataFrame, config: VolatilityConfig) -> pd.DataFrame:
    close = df["close"].astype(float)
    lr = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    realized = lr.rolling(config.realized_window, min_periods=2).std(ddof=0).fillna(0.0)
    atr_pct = (true_range(df) / close.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    vol_blend = (
        config.realized_weight * realized
        + config.atr_weight * atr_pct.rolling(config.realized_window, min_periods=2).mean().fillna(0.0)
    )

    percentile = rolling_percentile(vol_blend, config.percentile_window)
    vol_min = vol_blend.rolling(config.compression_window, min_periods=5).quantile(config.compression_low_quantile)
    vol_max = vol_blend.rolling(config.compression_window, min_periods=5).quantile(config.compression_high_quantile)
    compression = 1.0 - ((vol_blend - vol_min) / (vol_max - vol_min).replace(0.0, np.nan))
    compression = compression.replace([np.inf, -np.inf], np.nan).fillna(0.5).clip(0.0, 1.0)

    shock_z = rolling_zscore(lr.abs(), config.realized_window * 2)
    shock_risk = clip01((shock_z / config.shock_z).clip(lower=0.0))

    state = np.select(
        [
            shock_risk >= config.shock_state_threshold,
            percentile >= config.expanding_percentile_threshold,
            compression >= config.compressed_threshold,
            percentile <= config.quiet_percentile_threshold,
        ],
        ["shock", "expanding", "compressed", "quiet"],
        default="normal",
    )

    return pd.DataFrame(
        {
            "realized_vol": vol_blend.astype(float),
            "volatility_percentile": percentile.astype(float).clip(0.0, 100.0),
            "volatility_state": state,
            "compression_score": compression.astype(float),
            "shock_risk": shock_risk.astype(float),
            "return_abs_z": shock_z.astype(float),
        },
        index=df.index,
    )


__all__ = ["compute_volatility_features"]
