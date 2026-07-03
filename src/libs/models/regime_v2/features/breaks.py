"""Structural-break and breakout evidence for RegimeV2."""

from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_v2.config import BreakConfig
from libs.models.regime_v2.features.utils import EPS, clip01, rolling_percentile, rolling_zscore, true_range


def compute_break_features(df: pd.DataFrame, config: BreakConfig) -> pd.DataFrame:
    """Compute three distinct breakout concepts.

    ``pre_breakout_setup_score`` captures compression near a channel boundary.
    ``displacement_breakout_score`` captures confirmed close beyond the channel.
    ``post_breakout_retest_score`` captures a recent breakout retesting the
    broken boundary.  ``breakout_quality`` is a backward-compatible composite
    used by the current policy layer.
    """
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    open_ = df["open"].astype(float)
    volume = df["volume"].astype(float)

    lr = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    ret_z = rolling_zscore(lr.abs(), config.range_window * 2)
    tr = true_range(df)
    range_z = rolling_zscore(tr, config.range_window * 2)
    vol_z = rolling_zscore(np.log1p(volume), config.range_window * 2)

    prior_high = high.shift(1).rolling(config.breakout_window, min_periods=5).max()
    prior_low = low.shift(1).rolling(config.breakout_window, min_periods=5).min()
    rolling_range = (prior_high - prior_low).replace(0.0, np.nan)

    upside_break = ((close - prior_high) / rolling_range).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    downside_break = ((prior_low - close) / rolling_range).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    breakout_magnitude = pd.concat([upside_break, downside_break], axis=1).max(axis=1)

    volume_confirm = clip01((vol_z / max(config.confirmation_volume_z, EPS)).clip(lower=0.0))
    displacement_breakout_score = clip01((breakout_magnitude * 3.0).clip(0.0, 1.0) * (0.60 + 0.40 * volume_confirm))

    channel_width_pct = (rolling_range / close.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    width_percentile = rolling_percentile(channel_width_pct, config.breakout_window * 2)
    setup_compression = (1.0 - width_percentile / 100.0).clip(0.0, 1.0)
    channel_position = ((close - prior_low) / rolling_range).replace([np.inf, -np.inf], np.nan).fillna(0.5).clip(0.0, 1.0)
    edge_pressure = pd.concat([channel_position, 1.0 - channel_position], axis=1).max(axis=1)
    near_edge = ((edge_pressure - 0.55) / 0.35).clip(0.0, 1.0)
    quiet_enough = (1.0 - (ret_z / max(config.shock_z, EPS)).clip(0.0, 1.0)).clip(0.0, 1.0)
    pre_breakout_setup_score = clip01(setup_compression * near_edge * (0.60 + 0.40 * quiet_enough))

    retest_lookback = max(3, min(config.range_window, config.breakout_window // 3))
    recent_up_break = upside_break.rolling(retest_lookback, min_periods=1).max().shift(1).fillna(0.0).clip(0.0, 1.0)
    recent_down_break = downside_break.rolling(retest_lookback, min_periods=1).max().shift(1).fillna(0.0).clip(0.0, 1.0)
    upper_distance = ((close - prior_high).abs() / rolling_range).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    lower_distance = ((close - prior_low).abs() / rolling_range).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    near_upper_retest = (1.0 - upper_distance / 0.18).clip(0.0, 1.0)
    near_lower_retest = (1.0 - lower_distance / 0.18).clip(0.0, 1.0)
    retest_up = recent_up_break * near_upper_retest * (close >= prior_high * 0.995).astype(float)
    retest_down = recent_down_break * near_lower_retest * (close <= prior_low * 1.005).astype(float)
    post_breakout_retest_score = clip01(pd.concat([retest_up, retest_down], axis=1).max(axis=1) * (0.70 + 0.30 * quiet_enough))

    candle_range = (high - low).replace(0.0, np.nan)
    close_location = ((close - low) / candle_range).replace([np.inf, -np.inf], np.nan).fillna(0.5).clip(0.0, 1.0)
    upper_rejection = ((upside_break > 0).astype(float) * (1.0 - close_location)).clip(0.0, 1.0)
    lower_rejection = ((downside_break > 0).astype(float) * close_location).clip(0.0, 1.0)
    rejection_risk = pd.concat([upper_rejection, lower_rejection], axis=1).max(axis=1)

    false_breakout_risk = clip01(
        0.50 * displacement_breakout_score * (1.0 - volume_confirm)
        + 0.30 * rejection_risk
        + 0.20 * (ret_z < 1.0).astype(float)
    )

    structural_break_risk = clip01(
        0.45 * (ret_z / max(config.shock_z, EPS)).clip(0.0, 1.0)
        + 0.35 * (range_z / max(config.shock_z, EPS)).clip(0.0, 1.0)
        + 0.20 * displacement_breakout_score
    )

    breakout_quality = pd.concat(
        [
            0.75 * pre_breakout_setup_score,
            displacement_breakout_score,
            0.85 * post_breakout_retest_score,
        ],
        axis=1,
    ).max(axis=1).clip(0.0, 1.0)

    setup_direction = np.where(channel_position >= 0.5, "up", "down")
    displacement_direction = np.where(upside_break > downside_break, "up", np.where(downside_break > upside_break, "down", "none"))
    retest_direction = np.where(retest_up > retest_down, "up", np.where(retest_down > retest_up, "down", "none"))
    direction = np.where(
        displacement_direction != "none",
        displacement_direction,
        np.where(post_breakout_retest_score > pre_breakout_setup_score, retest_direction, setup_direction),
    )
    direction = np.where(breakout_quality > 0.05, direction, "none")

    return pd.DataFrame(
        {
            "structural_break_risk": structural_break_risk.astype(float),
            "breakout_quality": breakout_quality.astype(float),
            "pre_breakout_setup_score": pre_breakout_setup_score.astype(float),
            "displacement_breakout_score": displacement_breakout_score.astype(float),
            "post_breakout_retest_score": post_breakout_retest_score.astype(float),
            "false_breakout_risk": false_breakout_risk.astype(float),
            "breakout_direction": direction,
            "range_expansion_z": range_z.astype(float),
            "volume_confirmation": volume_confirm.astype(float),
            "channel_width_percentile": width_percentile.astype(float),
            "channel_position": channel_position.astype(float),
        },
        index=df.index,
    )


__all__ = ["compute_break_features"]
