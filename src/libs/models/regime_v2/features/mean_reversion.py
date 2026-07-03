"""Mean-reversion and chop evidence features for RegimeV2."""

from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_v2.config import MeanReversionConfig
from libs.models.regime_v2.features.utils import clip01, rolling_zscore, true_range


def compute_mean_reversion_features(df: pd.DataFrame, config: MeanReversionConfig) -> pd.DataFrame:
    close = df["close"].astype(float)
    center = close.rolling(config.center_window, min_periods=5).mean()
    band = close.rolling(config.band_window, min_periods=5).std(ddof=0).replace(0.0, np.nan)
    z = ((close - center) / band).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    z = z.clip(-config.z_clip, config.z_clip)

    # Distance from center gives MR opportunity, but too much break risk is handled elsewhere.
    mean_reversion_score = clip01((z.abs() / config.z_clip).fillna(0.0))

    tr = true_range(df)
    rolling_range = (df["high"].rolling(config.chop_window, min_periods=3).max() - df["low"].rolling(config.chop_window, min_periods=3).min()).replace(0.0, np.nan)
    path = tr.rolling(config.chop_window, min_periods=3).sum()
    path_to_range = (path / rolling_range).replace([np.inf, -np.inf], np.nan).fillna(1.0).clip(lower=1.0)
    # Choppiness-index style normalization.  The previous linear ratio
    # normalization saturated on 1h crypto because intrabar true range can be
    # large versus the rolling high-low span.  Log normalization preserves the
    # ordering while avoiding "everything is chop" behavior.
    chop_ci = (np.log10(path_to_range) / np.log10(max(config.chop_window, 2))).clip(0.0, 1.0)
    chop_norm = clip01(((chop_ci - 0.45) / 0.35).clip(lower=0.0))

    # Range quality is high when price repeatedly mean-reverts and realized path is not explosively directional.
    z_cross = (np.sign(z) != np.sign(z.shift(1))).astype(float)
    cross_rate = z_cross.rolling(config.chop_window, min_periods=3).mean().fillna(0.0)
    range_quality = clip01(0.55 * chop_norm + 0.45 * cross_rate.clip(0.0, 1.0))

    # Chop risk combines path inefficiency and low directional follow-through.
    abs_ret_z = rolling_zscore(close.pct_change().abs().fillna(0.0), config.chop_window)
    chop_risk = clip01(0.70 * chop_norm + 0.30 * (1.0 - (abs_ret_z / 3.0).clip(0.0, 1.0)))

    return pd.DataFrame(
        {
            "mr_zscore": z.astype(float),
            "mean_reversion_score": mean_reversion_score.astype(float),
            "range_quality": range_quality.astype(float),
            "chop_risk": chop_risk.astype(float),
            "chop_index_proxy": chop_norm.astype(float),
            "chop_ci": chop_ci.astype(float),
        },
        index=df.index,
    )


__all__ = ["compute_mean_reversion_features"]
