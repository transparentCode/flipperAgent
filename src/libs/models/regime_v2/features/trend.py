"""Trend evidence features for RegimeV2."""

from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_v2.config import TrendConfig
from libs.models.regime_v2.features.utils import EPS, clip01, clip11, true_range


def compute_trend_features(df: pd.DataFrame, config: TrendConfig) -> pd.DataFrame:
    """Compute deterministic trend evidence.

    The kernel uses independent, cheap signals: EMA spread, directional
    efficiency, and sign persistence.  It intentionally avoids HMM-style hidden
    state in Phase 1.
    """
    close = df["close"].astype(float)
    lr = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    ema_fast = close.ewm(span=max(config.fast_ema, 2), adjust=False, min_periods=1).mean()
    ema_slow = close.ewm(span=max(config.slow_ema, config.fast_ema + 1), adjust=False, min_periods=1).mean()
    atr = true_range(df).rolling(config.efficiency_lookback, min_periods=2).mean().replace(0.0, np.nan)

    ema_spread_norm = ((ema_fast - ema_slow) / (atr * config.slope_atr_scale + EPS)).replace(
        [np.inf, -np.inf], np.nan
    ).fillna(0.0)
    ema_score = pd.Series(np.tanh(ema_spread_norm), index=df.index)

    net_move = close - close.shift(config.efficiency_lookback)
    path = close.diff().abs().rolling(config.efficiency_lookback, min_periods=2).sum()
    efficiency = (net_move.abs() / path.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    signed_efficiency = efficiency * np.sign(net_move.fillna(0.0))

    sign = np.sign(lr)
    signed_persistence = sign.rolling(config.persistence_lookback, min_periods=2).mean().fillna(0.0)
    persistence = signed_persistence.abs().clip(0.0, 1.0)

    direction_score = clip11(
        config.ema_score_weight * ema_score
        + config.efficiency_score_weight * signed_efficiency
        + config.persistence_score_weight * signed_persistence
    )
    trend_strength = clip01(
        config.ema_score_weight * ema_score.abs()
        + config.efficiency_score_weight * efficiency
        + config.persistence_score_weight * persistence
    )
    trend_confidence = clip01(
        config.confidence_strength_weight * trend_strength
        + config.confidence_persistence_weight * persistence
    )

    direction = np.where(
        direction_score > config.direction_deadzone,
        "bull",
        np.where(direction_score < -config.direction_deadzone, "bear", "neutral"),
    )

    return pd.DataFrame(
        {
            "trend_direction_score": direction_score.astype(float),
            "trend_direction": direction,
            "trend_strength": trend_strength.astype(float),
            "trend_persistence": persistence.astype(float),
            "trend_confidence": trend_confidence.astype(float),
            "trend_ema_spread_norm": ema_spread_norm.astype(float),
            "trend_efficiency": efficiency.astype(float),
        },
        index=df.index,
    )


__all__ = ["compute_trend_features"]
