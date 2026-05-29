"""Scoring utility functions for optimization objective functions.

Pure math — no class, no state, no side effects.
Each model's optimizer imports what it needs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

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


# ---------------------------------------------------------------------------
# Multi-TP backtest — matches production partial-exit logic
# ---------------------------------------------------------------------------

@dataclass
class MultiTpTradeResult:
    """Result of a single trade in the multi-TP backtest."""
    entry_idx: int
    exit_idx: int
    direction: int
    entry_price: float
    pnl_pct: float
    tp_hits: list[bool]
    sl_hit: bool = False
    holding_bars: int = 0


def backtest_multi_tp(
    directions: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    tp_pcts: tuple[float, ...] = (0.015, 0.03, 0.05),
    tp_portions: tuple[float, ...] = (0.40, 0.30, 0.30),
    sl_pct: float = 0.02,
    commission_bps: float = 4.0,
    trail_to_breakeven: bool = True,
) -> tuple[np.ndarray, list[MultiTpTradeResult]]:
    """Multi-TP backtest matching production partial-exit logic.

    One TP level fires per bar (conservative). After the first TP hit,
    SL moves to entry price if *trail_to_breakeven* is True.

    Parameters
    ----------
    directions : np.ndarray
        Signal directions (-1, 0, 1).
    high, low, close : np.ndarray
        OHLC price arrays (same length as *directions*).
    tp_pcts : tuple[float, ...]
        TP levels as fractions above/below entry (e.g. 0.015 = 1.5%).
    tp_portions : tuple[float, ...]
        Fraction of original position to close at each level.
    sl_pct : float
        Stop-loss as fraction below/above entry (e.g. 0.02 = 2%).
    commission_bps : float
        One-way commission in basis points (applied at entry and each exit).
    trail_to_breakeven : bool
        Move SL to entry after first TP hit.

    Returns
    -------
    equity_returns : np.ndarray
        Per-bar equity returns (same length as input arrays).
    trades : list[MultiTpTradeResult]
        Trade-level detail.
    """
    n = len(close)
    n_levels = len(tp_pcts)
    assert len(tp_portions) == n_levels, "tp_pcts and tp_portions must have same length"

    commission = commission_bps / 10_000.0
    equity_returns = np.zeros(n)
    trades: list[MultiTpTradeResult] = []

    i = 0
    while i < n:
        if directions[i] == 0:
            i += 1
            continue

        direction = int(directions[i])
        entry_price = close[i]
        entry_idx = i

        # Compute TP and SL levels
        tp_lvls = [entry_price * (1.0 + direction * pct) for pct in tp_pcts]
        sl_lvl = entry_price * (1.0 - direction * sl_pct)

        remaining = 1.0
        realized_pnl = 0.0
        tp_hit = [False] * n_levels
        sl_hit = False
        exit_idx = i
        prev_close = entry_price

        # Entry commission
        equity_returns[i] -= commission

        j = i + 1
        while j < n and remaining > 1e-9:
            # Unrealized bar return on remaining position
            bar_return = direction * (close[j] - prev_close) / entry_price * remaining

            # --- Check SL ---
            if direction == 1:
                sl_triggered = low[j] <= sl_lvl
            else:
                sl_triggered = high[j] >= sl_lvl

            if sl_triggered:
                bar_return = direction * (sl_lvl - prev_close) / entry_price * remaining
                realized_pnl += direction * (sl_lvl - entry_price) / entry_price * remaining
                equity_returns[j] += bar_return - commission
                sl_hit = True
                exit_idx = j
                remaining = 0.0
                break

            # --- Check TP levels (one per bar, in order) ---
            bar_tp_cost = 0.0
            for k in range(n_levels):
                if tp_hit[k]:
                    continue
                lvl = tp_lvls[k]
                hit = (direction == 1 and high[j] >= lvl) or (
                    direction == -1 and low[j] <= lvl
                )
                if hit:
                    # Last TP level or final remaining? Close everything
                    if k == n_levels - 1:
                        portion = remaining
                    else:
                        portion = tp_portions[k]
                        portion = min(portion, remaining)
                    tp_pnl = direction * (lvl - entry_price) / entry_price * portion
                    realized_pnl += tp_pnl
                    remaining -= portion
                    tp_hit[k] = True
                    bar_tp_cost += commission
                    # Trail-to-breakeven after first TP
                    if k == 0 and trail_to_breakeven:
                        sl_lvl = entry_price
                    break  # one TP per bar

            equity_returns[j] += bar_return - bar_tp_cost
            exit_idx = j
            prev_close = close[j]
            j += 1

        # Position still open at end of data — mark-to-market
        if remaining > 1e-9:
            final_pnl = direction * (close[exit_idx] - entry_price) / entry_price * remaining
            realized_pnl += final_pnl
            equity_returns[exit_idx] -= commission

        trades.append(MultiTpTradeResult(
            entry_idx=entry_idx,
            exit_idx=exit_idx,
            direction=direction,
            entry_price=entry_price,
            pnl_pct=realized_pnl,
            tp_hits=tp_hit,
            sl_hit=sl_hit,
            holding_bars=exit_idx - entry_idx,
        ))
        i = exit_idx + 1

    return equity_returns, trades


def compute_multi_tp_metrics(
    equity_returns: np.ndarray,
    trades: list[MultiTpTradeResult],
    timeframe: str = "1h",
) -> dict[str, float]:
    """Compute summary metrics from multi-TP backtest results.

    Returns dict with: sharpe, max_drawdown, win_rate, n_trades,
    total_return, tp1_rate, tp2_rate, ..., sl_rate, avg_holding.
    """
    n = len(trades)
    if n == 0:
        return {
            "sharpe": 0.0, "max_drawdown": 0.0, "win_rate": 0.0,
            "n_trades": 0, "total_return": 0.0, "sl_rate": 0.0,
            "avg_holding": 0.0,
        }

    sharpe = compute_sharpe(equity_returns, timeframe)
    max_dd = compute_max_drawdown(equity_returns)
    wins = sum(1 for t in trades if t.pnl_pct > 0)

    n_levels = max(len(t.tp_hits) for t in trades) if trades else 0
    tp_rates = {}
    for k in range(n_levels):
        tp_rates[f"tp{k+1}_rate"] = sum(
            1 for t in trades if len(t.tp_hits) > k and t.tp_hits[k]
        ) / n

    return {
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "win_rate": wins / n,
        "n_trades": n,
        "total_return": float(np.sum(equity_returns)),
        **tp_rates,
        "sl_rate": sum(1 for t in trades if t.sl_hit) / n,
        "avg_holding": sum(t.holding_bars for t in trades) / n,
    }
