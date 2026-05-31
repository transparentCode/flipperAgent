"""
Tier 1: Strategy Utility Benchmark (50% of objective).

Simulates the regime-gated long-short strategy vs. buy-and-hold.

Uses the `position_scale` column from features_df — the same continuous
p_trending-blended weights that the live bot uses for sizing. Negative
weights indicate short positions.

Fallback regime mapping (when position_scale column is absent):
  CLEAN_TREND_BULL → +1.0x, BEAR → -1.0x, FLAT → 0.0x
  VOLATILE_TREND_BULL → +0.6x, BEAR → -0.6x, FLAT → 0.0x
  QUIET_MR_RANGE → +0.3x, SQUEEZE → 0.0x
  CHOPPY → flat (0x)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute(
    features_df: pd.DataFrame,
    returns: np.ndarray,
    risk_free_rate: float = 0.0,
) -> dict:
    """
    Compute Tier-1 benchmark metrics.

    Parameters
    ----------
    features_df : output of RegimeOrchestrator.analyze_series()
                  must contain 'regime' column; uses 'position_scale' if present
    returns     : 1-D array of log-returns aligned with features_df index
    risk_free_rate : annualised daily risk-free rate

    Returns
    -------
    dict with keys:
        sharpe_improvement, drawdown_reduction,
        regime_sharpe, bah_sharpe, regime_max_dd, bah_max_dd
    """
    if len(returns) < 20 or "regime" not in features_df.columns:
        return _empty()

    # Align
    n = min(len(returns), len(features_df))
    ret = returns[-n:]

    # Use actual position_scale from aggregator (matches live bot behavior)
    # Falls back to regime-label mapping if position_scale isn't available
    if "position_scale" in features_df.columns:
        weights = features_df["position_scale"].values[-n:].astype(float)
    else:
        regime_col = features_df["regime"].values[-n:]
        weights = _regime_weights(regime_col)

    regime_returns = weights * ret
    bah_returns = ret

    regime_sharpe = _sharpe(regime_returns, risk_free_rate)
    bah_sharpe = _sharpe(bah_returns, risk_free_rate)
    regime_dd = _max_drawdown(regime_returns)
    bah_dd = _max_drawdown(bah_returns)

    sharpe_improvement = regime_sharpe - bah_sharpe
    drawdown_reduction = bah_dd - regime_dd  # positive = improvement

    return {
        "sharpe_improvement": float(sharpe_improvement),
        "drawdown_reduction": float(drawdown_reduction),
        "regime_sharpe": float(regime_sharpe),
        "bah_sharpe": float(bah_sharpe),
        "regime_max_dd": float(regime_dd),
        "bah_max_dd": float(bah_dd),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Fallback weights — matches actual aggregator position_scale defaults.
# Used only when features_df doesn't have position_scale column.
# Maps all 9 aggregator labels. Long-short: negative = short position.
_WEIGHT_MAP = {
    "CLEAN_TREND_BULL":     1.0,
    "CLEAN_TREND_BEAR":    -1.0,
    "CLEAN_TREND_FLAT":     0.0,
    "VOLATILE_TREND_BULL":  0.6,
    "VOLATILE_TREND_BEAR": -0.6,
    "VOLATILE_TREND_FLAT":  0.0,
    "QUIET_MR_RANGE":       0.3,
    "QUIET_MR_SQUEEZE":     0.0,
    "CHOPPY":               0.0,
}


def _regime_weights(regime_col: np.ndarray) -> np.ndarray:
    """Map regime strings to position weights."""
    weights = np.zeros(len(regime_col))
    for i, r in enumerate(regime_col):
        weights[i] = _WEIGHT_MAP.get(r, 0.0)
    return weights


def _sharpe(returns: np.ndarray, risk_free: float = 0.0, annualise: int = 8760) -> float:
    """Annualised Sharpe ratio (hourly bars by default)."""
    excess = returns - risk_free / annualise
    std = np.std(excess)
    if std < 1e-10:
        return 0.0
    return float(np.mean(excess) / std * np.sqrt(annualise))


def _max_drawdown(returns: np.ndarray) -> float:
    """Maximum drawdown from cumulative returns series."""
    cum = np.exp(np.cumsum(returns))
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / (peak + 1e-10)
    return float(np.min(dd))


def _empty() -> dict:
    return {
        "sharpe_improvement": 0.0,
        "drawdown_reduction": 0.0,
        "regime_sharpe": 0.0,
        "bah_sharpe": 0.0,
        "regime_max_dd": 0.0,
        "bah_max_dd": 0.0,
    }
