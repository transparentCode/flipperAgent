"""MetricsCalculator — Sharpe, Sortino, drawdown, trade stats, rolling metrics."""

from __future__ import annotations

import math

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import (
    ClosedTrade,
    EquityPoint,
    PerformanceSummary,
)

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


def compute_sharpe(
    returns: list[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 8760,
) -> float:
    """Annualized Sharpe ratio from regular-interval return series."""
    if len(returns) < 2:
        return 0.0

    rf_per_period = risk_free_rate / periods_per_year
    excess = [r - rf_per_period for r in returns]

    mean_excess = sum(excess) / len(excess)
    variance = sum((r - mean_excess) ** 2 for r in excess) / (len(excess) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0

    if std == 0.0:
        return 0.0

    return (mean_excess / std) * math.sqrt(periods_per_year)


def compute_sortino(
    returns: list[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 8760,
) -> float:
    """Annualized Sortino ratio (downside deviation only)."""
    if len(returns) < 2:
        return 0.0

    rf_per_period = risk_free_rate / periods_per_year
    excess = [r - rf_per_period for r in returns]

    mean_excess = sum(excess) / len(excess)

    # Downside deviation: sqrt(mean of squared negative excess returns over ALL periods)
    downside_sq = [e ** 2 if e < 0 else 0.0 for e in excess]
    downside_dev = math.sqrt(sum(downside_sq) / len(excess))
    if downside_dev == 0.0:
        return 0.0

    return (mean_excess / downside_dev) * math.sqrt(periods_per_year)


def compute_max_drawdown(
    equity_points: list[EquityPoint],
) -> tuple[float, float]:
    """Returns (max_drawdown_pct, max_drawdown_duration_seconds)."""
    if len(equity_points) < 2:
        return 0.0, 0.0

    peak = equity_points[0].equity
    max_dd_pct = 0.0
    max_dd_duration = 0.0
    current_dd_start_ts = equity_points[0].timestamp

    for pt in equity_points:
        if pt.equity >= peak:
            # Recovered to a new peak — record duration of the preceding drawdown.
            # No guard on initial equity: a strategy that never exceeds its starting
            # equity still has real drawdown durations worth tracking.
            duration = pt.timestamp - current_dd_start_ts
            if duration > max_dd_duration:
                max_dd_duration = duration
            peak = pt.equity
            current_dd_start_ts = pt.timestamp
        else:
            dd_pct = (peak - pt.equity) / peak * 100 if peak > 0 else 0.0
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

    # Check if we end in a drawdown
    if equity_points[-1].equity < peak:
        duration = equity_points[-1].timestamp - current_dd_start_ts
        if duration > max_dd_duration:
            max_dd_duration = duration

    return max_dd_pct, max_dd_duration


def compute_calmar(
    returns: list[float],
    equity_points: list[EquityPoint],
    periods_per_year: int = 8760,
) -> float:
    """Calmar ratio = annualized return / max drawdown pct."""
    if len(returns) < 2 or len(equity_points) < 2:
        return 0.0

    max_dd_pct, _ = compute_max_drawdown(equity_points)
    if max_dd_pct == 0.0:
        return 0.0

    # Compound annual return
    first_eq = equity_points[0].equity
    last_eq = equity_points[-1].equity
    if first_eq <= 0:
        return 0.0

    n_periods = len(returns)
    total_return = last_eq / first_eq
    if total_return <= 0:
        return 0.0

    try:
        annual_return = total_return ** (periods_per_year / n_periods) - 1
    except (OverflowError, ValueError):
        return 0.0

    return (annual_return * 100) / max_dd_pct


def compute_trade_stats(
    trades: list[ClosedTrade],
) -> dict[str, float]:
    """Compute win_rate, profit_factor, expectancy, payoff_ratio, avg_duration."""
    if not trades:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "profit_factor": 0.0,
            "avg_trade_pnl": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "largest_win": 0.0,
            "largest_loss": 0.0,
            "avg_trade_duration_seconds": 0.0,
            "expectancy": 0.0,
            "payoff_ratio": 0.0,
        }

    wins = [t for t in trades if t.realized_pnl > 0]
    losses = [t for t in trades if t.realized_pnl <= 0]

    total_pnl = sum(t.realized_pnl for t in trades)
    gross_profit = sum(t.realized_pnl for t in wins)
    gross_loss = sum(t.realized_pnl for t in losses)

    win_rate = len(wins) / len(trades) if trades else 0.0
    loss_rate = 1.0 - win_rate

    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0

    profit_factor = (
        gross_profit / abs(gross_loss) if gross_loss != 0 else float("inf")
    )

    payoff_ratio = (
        avg_win / abs(avg_loss) if avg_loss != 0 else float("inf")
    )

    expectancy = (win_rate * avg_win) - (loss_rate * abs(avg_loss))

    largest_win = max((t.realized_pnl for t in wins), default=0.0)
    largest_loss = min((t.realized_pnl for t in losses), default=0.0)

    avg_duration = (
        sum(t.duration_seconds for t in trades) / len(trades) if trades else 0.0
    )

    return {
        "total_trades": len(trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "avg_trade_pnl": total_pnl / len(trades),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "largest_win": largest_win,
        "largest_loss": largest_loss,
        "avg_trade_duration_seconds": avg_duration,
        "expectancy": expectancy,
        "payoff_ratio": payoff_ratio,
    }


def compute_rolling_sharpe(
    returns: list[float],
    timestamps: list[float],
    window_periods: int,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 8760,
) -> list[tuple[float, float]]:
    """Rolling Sharpe ratio over a sliding window.

    Returns list of (timestamp, sharpe) tuples.
    """
    if len(returns) < window_periods or window_periods < 2:
        return []

    results: list[tuple[float, float]] = []
    for i in range(window_periods - 1, len(returns)):
        window = returns[i - window_periods + 1 : i + 1]
        sharpe = compute_sharpe(window, risk_free_rate, periods_per_year)
        results.append((timestamps[i], sharpe))
    return results


def compute_performance(
    trades: list[ClosedTrade],
    returns: list[float],
    equity_curve: list[EquityPoint],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 8760,
    min_trades_for_ratios: int = 5,
) -> PerformanceSummary:
    """Compute aggregate performance metrics."""
    stats = compute_trade_stats(trades)

    # Compute ratio metrics from regular-interval returns
    if len(returns) >= 2 and len(trades) >= min_trades_for_ratios:
        sharpe = compute_sharpe(returns, risk_free_rate, periods_per_year)
        sortino = compute_sortino(returns, risk_free_rate, periods_per_year)
        calmar = compute_calmar(returns, equity_curve, periods_per_year)
    else:
        sharpe = 0.0
        sortino = 0.0
        calmar = 0.0

    max_dd_pct, max_dd_dur = compute_max_drawdown(equity_curve)

    start_ts = equity_curve[0].timestamp if equity_curve else 0.0
    end_ts = equity_curve[-1].timestamp if equity_curve else 0.0

    return PerformanceSummary(
        start_timestamp=start_ts,
        end_timestamp=end_ts,
        total_trades=int(stats["total_trades"]),
        winning_trades=int(stats["winning_trades"]),
        losing_trades=int(stats["losing_trades"]),
        win_rate=stats["win_rate"],
        total_pnl=stats["total_pnl"],
        gross_profit=stats["gross_profit"],
        gross_loss=stats["gross_loss"],
        profit_factor=stats["profit_factor"],
        avg_trade_pnl=stats["avg_trade_pnl"],
        avg_win=stats["avg_win"],
        avg_loss=stats["avg_loss"],
        largest_win=stats["largest_win"],
        largest_loss=stats["largest_loss"],
        avg_trade_duration_seconds=stats["avg_trade_duration_seconds"],
        max_drawdown_pct=max_dd_pct,
        max_drawdown_duration_seconds=max_dd_dur,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        expectancy=stats["expectancy"],
        payoff_ratio=stats["payoff_ratio"],
    )
