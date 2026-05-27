"""Scoring utility functions for optimization objective functions.

Pure math — no class, no state, no side effects.
Each model's optimizer imports what it needs.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


# Annualization factors by common timeframe labels.
BARS_PER_YEAR: dict[str, int] = {
    "1m": 525_600,
    "5m": 105_120,
    "15m": 35_040,
    "1h": 8_760,
    "4h": 2_190,
    "1d": 365,
}


def split_temporal(
    df: pd.DataFrame,
    train: float = 0.6,
    test: float = 0.2,
    val: float = 0.2,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Chronological train/test/val split — no shuffling.

    Parameters
    ----------
    df : pd.DataFrame
        Full historical dataset sorted by time.
    train : float
        Fraction for training (Optuna optimizes params).
    test : float
        Fraction for testing (early stopping / pruning during optimization).
    val : float
        Fraction for validation (final audit — never seen during optimization).

    Returns
    -------
    train_df, test_df, val_df : tuple of DataFrames
    """
    assert abs(train + test + val - 1.0) < 1e-6, f"Ratios must sum to 1.0, got {train + test + val}"
    n = len(df)
    t1 = int(n * train)
    t2 = int(n * (train + test))
    return df.iloc[:t1], df.iloc[t1:t2], df.iloc[t2:]


def compute_returns(
    directions: np.ndarray,
    close_prices: np.ndarray,
    cost_bps: float = 10.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute per-bar strategy returns from directions and close prices.

    Parameters
    ----------
    directions : np.ndarray
        Array of positions (-1, 0, 1) from model.batch_evaluate().
    close_prices : np.ndarray
        Array of close prices aligned with directions.
    cost_bps : float
        Round-trip transaction cost in basis points per position change.

    Returns
    -------
    strategy_returns : np.ndarray
        Per-bar strategy returns (len = len(close_prices) - 1).
    trade_mask : np.ndarray
        Boolean mask where position changes occurred.
    """
    bar_returns = np.diff(close_prices) / close_prices[:-1]

    # Direction[i] applied to return[i] (direction at bar i earns return from i to i+1)
    pos = directions[:-1].astype(float)
    strategy_returns = pos * bar_returns

    # Subtract transaction costs on position changes
    trades = np.diff(np.concatenate([[0.0], pos]))
    trade_mask = trades != 0
    trade_costs = np.abs(trades) * (cost_bps / 10_000.0)
    strategy_returns -= trade_costs[: len(strategy_returns)]

    return strategy_returns, trade_mask


def compute_sharpe(
    returns: np.ndarray,
    timeframe: str = "1h",
) -> float:
    """Annualized Sharpe ratio (risk-free rate = 0)."""
    if len(returns) == 0 or np.std(returns) == 0:
        return 0.0
    ann_factor = BARS_PER_YEAR.get(timeframe, 8_760)
    return float((np.mean(returns) / np.std(returns)) * math.sqrt(ann_factor))


def compute_max_drawdown(returns: np.ndarray) -> float:
    """Maximum drawdown as a negative fraction (e.g. -0.15 = 15% DD)."""
    if len(returns) == 0:
        return 0.0
    cumulative = np.cumprod(1.0 + returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - running_max) / running_max
    return float(np.min(drawdowns))


def compute_win_rate(returns: np.ndarray, trade_mask: np.ndarray) -> float:
    """Win rate = fraction of trades with positive return."""
    mask = trade_mask[: len(returns)]
    if np.sum(mask) == 0:
        return 0.0
    trade_returns = returns[mask]
    return float(np.sum(trade_returns > 0) / len(trade_returns))


def compute_signal_weighted_returns(
    edge_scores: np.ndarray,
    close_prices: np.ndarray,
    cost_bps: float = 10.0,
    max_position: float = 1.0,
) -> np.ndarray:
    """Compute per-bar strategy returns from continuous edge scores.

    position[t] = clip(edge_score[t], -max_position, max_position)
    bar_return[t] = (close[t+1] - close[t]) / close[t]
    strategy_return[t] = position[t] * bar_return[t]
    cost[t] = |position[t] - position[t-1]| * cost_bps / 10000

    Parameters
    ----------
    edge_scores : np.ndarray
        Continuous signed edge scores from batch_evaluate().
    close_prices : np.ndarray
        Close prices aligned with edge_scores.
    cost_bps : float
        Transaction cost in basis points per unit of position change.
    max_position : float
        Maximum absolute position size. Default 1.0.

    Returns
    -------
    np.ndarray
        Per-bar strategy returns (length = len(close_prices) - 1).
    """
    positions = np.clip(edge_scores, -max_position, max_position)
    bar_returns = np.diff(close_prices) / close_prices[:-1]

    pos = positions[:-1]
    strategy_returns = pos * bar_returns

    # Transaction costs on position changes
    pos_changes = np.diff(np.concatenate([[0.0], pos]))
    trade_costs = np.abs(pos_changes) * (cost_bps / 10_000.0)
    strategy_returns -= trade_costs[: len(strategy_returns)]

    return strategy_returns
