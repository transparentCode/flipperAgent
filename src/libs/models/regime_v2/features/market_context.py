"""Market-context and liquidity evidence for RegimeV2."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from libs.models.regime_v2.config import MarketContextConfig


def compute_market_context_features(df: pd.DataFrame, config: MarketContextConfig) -> pd.DataFrame:
    """Read optional context columns already produced elsewhere.

    The function is deliberately neutral when columns are absent so RegimeV2 can
    run on plain OHLCV during tests/backfills.
    """
    index = df.index
    alignment = _series_or_default(df, config.alignment_column, 0.0).clip(-1.0, 1.0)
    breadth_raw = _series_or_default(df, config.breadth_column, 0.0)
    breadth_confirmation = pd.Series(np.tanh(breadth_raw.astype(float) * 10.0), index=index).clip(-1.0, 1.0)

    regime_state = _series_or_default(df, config.regime_state_column, 2.0)
    broad_selloff = (regime_state == 3).astype(float)
    risk_off = (regime_state == 0).astype(float)
    alt_season = (regime_state == 1).astype(float)

    market_context_score = (0.65 * alignment + 0.35 * breadth_confirmation).clip(-1.0, 1.0)

    liquidity_stress = pd.Series(0.0, index=index)
    if "spread_bps" in df.columns:
        spread = pd.to_numeric(df["spread_bps"], errors="coerce").fillna(0.0)
        liquidity_stress = liquidity_stress + (spread / 20.0).clip(0.0, 1.0) * 0.45
    if "bid_ask_imbalance" in df.columns:
        imbalance = pd.to_numeric(df["bid_ask_imbalance"], errors="coerce").fillna(0.0).abs()
        liquidity_stress = liquidity_stress + imbalance.clip(0.0, 1.0) * 0.25
    if "depth_ratio" in df.columns:
        depth = pd.to_numeric(df["depth_ratio"], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(1.0)
        depth_stress = pd.Series([abs(math.log(max(float(x), 1e-6))) for x in depth], index=index)
        liquidity_stress = liquidity_stress + (depth_stress / 2.0).clip(0.0, 1.0) * 0.30
    liquidity_stress = liquidity_stress.clip(0.0, 1.0)

    return pd.DataFrame(
        {
            "market_context_score": market_context_score.astype(float),
            "breadth_confirmation": breadth_confirmation.astype(float),
            "liquidity_stress": liquidity_stress.astype(float),
            "cross_asset_regime_state": regime_state.astype(float),
            "context_risk_off": risk_off.astype(float),
            "context_alt_season": alt_season.astype(float),
            "context_broad_selloff": broad_selloff.astype(float),
        },
        index=index,
    )


def _series_or_default(df: pd.DataFrame, column: str, default: float) -> pd.Series:
    if column not in df.columns:
        return pd.Series(default, index=df.index, dtype=float)
    return pd.to_numeric(df[column], errors="coerce").fillna(default).astype(float)


__all__ = ["compute_market_context_features"]
