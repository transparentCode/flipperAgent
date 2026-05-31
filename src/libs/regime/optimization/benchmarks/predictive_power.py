"""
Tier 2: Predictive Power Benchmark (40% of objective).

Measures how well the regime label predicts future returns and volatility.

Metrics:
  forward_return_ic  — Spearman IC between regime rank and 4-bar forward return
  vol_forecast_error — regime-conditional vol vs. realized vol RMSE (lower = better)
  ic_decay_score     — weighted IC across [1, 4, 12, 24] horizons

Note on regime rank: The ordinal ranking (CLEAN_TREND > VOLATILE_TREND > QUIET_MR > CHOPPY)
represents a prior belief about risk-adjusted return expectation, not a guarantee. In
persistent bull markets (e.g. BTC 2023-2025), VOLATILE_TREND may outperform CLEAN_TREND
in absolute terms, producing negative IC. This doesn't mean the ranking is wrong — it means
the regime classifier's value comes from vol-conditional sizing, not return prediction.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


_HORIZONS = [1, 4, 12, 24]
_HORIZON_WEIGHTS = [0.4, 0.3, 0.2, 0.1]   # IC decays with horizon; weight more recent

# Ordinal rank for regimes (higher = more desirable for long-only trading).
# Reflects a prior: low-vol trending > high-vol trending > MR > chop.
# In persistent bull markets, actual returns may not follow this ordering.
# Maps all 9 aggregator labels (direction + squeeze variants).
_REGIME_RANK = {
    "CLEAN_TREND_BULL":    4,
    "CLEAN_TREND_BEAR":    2,
    "CLEAN_TREND_FLAT":    3,
    "VOLATILE_TREND_BULL": 3,
    "VOLATILE_TREND_BEAR": 1,
    "VOLATILE_TREND_FLAT": 2,
    "QUIET_MR_RANGE":      1,
    "QUIET_MR_SQUEEZE":    1,
    "CHOPPY":              0,
}


def compute(
    features_df: pd.DataFrame,
    returns: np.ndarray,
    primary_horizon: int = 4,
) -> dict:
    """
    Compute Tier-2 benchmark metrics.

    Parameters
    ----------
    features_df    : output of analyze_series(), must have 'regime' column
    returns        : 1-D array of log-returns aligned with features_df
    primary_horizon: forward return horizon for main IC (bars)

    Returns
    -------
    dict with: forward_return_ic, vol_forecast_error, ic_decay_score
    """
    if len(returns) < max(_HORIZONS) + 5 or "regime" not in features_df.columns:
        return _empty()

    n = min(len(returns), len(features_df))
    ret = returns[-n:]
    regime_col = features_df["regime"].values[-n:]
    regime_rank = np.array([_REGIME_RANK.get(r, 0) for r in regime_col], dtype=float)

    # Forward return IC at primary horizon
    fwd_ret = _forward_returns(ret, primary_horizon)
    valid = np.isfinite(fwd_ret) & np.isfinite(regime_rank)
    if valid.sum() < 10:
        return _empty()
    ic, _ = stats.spearmanr(regime_rank[valid], fwd_ret[valid])
    forward_return_ic = float(ic) if np.isfinite(ic) else 0.0

    # IC decay score
    ic_decay = []
    for h, w in zip(_HORIZONS, _HORIZON_WEIGHTS):
        fwd = _forward_returns(ret, h)
        valid_h = np.isfinite(fwd) & np.isfinite(regime_rank)
        if valid_h.sum() < 10:
            ic_decay.append(0.0)
            continue
        ic_h, _ = stats.spearmanr(regime_rank[valid_h], fwd[valid_h])
        ic_decay.append(float(ic_h) * w if np.isfinite(ic_h) else 0.0)
    ic_decay_score = float(sum(ic_decay))

    # Vol forecast error
    vol_forecast_error = _vol_forecast_rmse(regime_col, ret)

    return {
        "forward_return_ic": forward_return_ic,
        "vol_forecast_error": vol_forecast_error,
        "ic_decay_score": ic_decay_score,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _forward_returns(returns: np.ndarray, horizon: int) -> np.ndarray:
    """Sum of returns over next `horizon` bars. NaN for last `horizon` bars."""
    n = len(returns)
    fwd = np.full(n, np.nan)
    for i in range(n - horizon):
        fwd[i] = returns[i + 1 : i + horizon + 1].sum()
    return fwd


def _vol_forecast_rmse(regime_col: np.ndarray, returns: np.ndarray) -> float:
    """
    Measure how well regime-conditional vol forecasts realized vol.

    Forecast: regime → expected vol level (parametric).
    Realized: rolling 24-bar std of returns.
    Error: RMSE between forecast and realized.
    """
    # Parametric vol scale per regime (all 9 aggregator labels)
    vol_scale = {
        "CLEAN_TREND_BULL":    0.8,
        "CLEAN_TREND_BEAR":    0.8,
        "CLEAN_TREND_FLAT":    0.8,
        "VOLATILE_TREND_BULL": 1.5,
        "VOLATILE_TREND_BEAR": 1.5,
        "VOLATILE_TREND_FLAT": 1.5,
        "QUIET_MR_RANGE":      0.6,
        "QUIET_MR_SQUEEZE":    0.5,
        "CHOPPY":              1.2,
    }
    realized_vol = pd.Series(returns).rolling(24, min_periods=5).std().values
    global_vol = np.nanstd(returns) + 1e-10

    forecast_vol = np.array([
        global_vol * vol_scale.get(r, 1.0) for r in regime_col
    ])
    valid = np.isfinite(realized_vol) & np.isfinite(forecast_vol)
    if valid.sum() < 10:
        return 1.0
    rmse = float(np.sqrt(np.mean((forecast_vol[valid] - realized_vol[valid]) ** 2)))
    # Normalise by mean realized vol so RMSE is unitless
    return float(rmse / (np.nanmean(realized_vol[valid]) + 1e-10))


def _empty() -> dict:
    return {
        "forward_return_ic": 0.0,
        "vol_forecast_error": 1.0,
        "ic_decay_score": 0.0,
    }
