"""Tests for libs/portfolio/metrics.py — Sharpe, Sortino, drawdown, trade stats."""

import math

import pytest

from libs.contracts.schemas import ClosedTrade, EquityPoint, PerformanceSummary
from libs.portfolio.metrics import (
    compute_calmar,
    compute_max_drawdown,
    compute_performance,
    compute_rolling_sharpe,
    compute_sharpe,
    compute_sortino,
    compute_trade_stats,
)


def _make_point(ts: float, equity: float) -> EquityPoint:
    return EquityPoint(
        timestamp=ts,
        equity=equity,
        balance=equity,
        unrealized_pnl=0.0,
        drawdown_pct=0.0,
        open_position_count=0,
    )


def _make_trade(pnl: float, duration: float = 3600, **kw) -> ClosedTrade:
    defaults = dict(
        trade_id="t1",
        asset="BTCUSDT",
        direction=1,
        entry_price=100.0,
        exit_price=100.0 + pnl,
        size=1.0,
        realized_pnl=pnl,
        realized_pnl_pct=pnl,
        entry_timestamp=1000.0,
        exit_timestamp=1000.0 + duration,
        duration_seconds=duration,
    )
    defaults.update(kw)
    return ClosedTrade(**defaults)


# ---------------------------------------------------------------------------
# compute_sharpe
# ---------------------------------------------------------------------------

class TestComputeSharpe:
    def test_empty_returns(self):
        assert compute_sharpe([]) == 0.0

    def test_single_return(self):
        assert compute_sharpe([0.01]) == 0.0

    def test_positive_returns(self):
        returns = [0.01, 0.02, 0.015, 0.01, 0.02]
        sharpe = compute_sharpe(returns, risk_free_rate=0.0, periods_per_year=8760)
        assert sharpe > 0

    def test_zero_variance_returns(self):
        """All same returns => zero std => zero Sharpe."""
        returns = [0.01, 0.01, 0.01, 0.01]
        assert compute_sharpe(returns) == 0.0

    def test_negative_returns_give_negative_sharpe(self):
        returns = [-0.01, -0.02, -0.015, -0.01, -0.02]
        sharpe = compute_sharpe(returns, risk_free_rate=0.0, periods_per_year=8760)
        assert sharpe < 0

    def test_risk_free_rate_adjusts(self):
        returns = [0.01, 0.02, 0.015, 0.01, 0.02]
        sharpe_no_rf = compute_sharpe(returns, risk_free_rate=0.0)
        sharpe_with_rf = compute_sharpe(returns, risk_free_rate=0.05)
        assert sharpe_with_rf < sharpe_no_rf


# ---------------------------------------------------------------------------
# compute_sortino
# ---------------------------------------------------------------------------

class TestComputeSortino:
    def test_empty(self):
        assert compute_sortino([]) == 0.0

    def test_all_positive_returns(self):
        """No downside => zero denominator => zero Sortino."""
        returns = [0.01, 0.02, 0.03]
        assert compute_sortino(returns) == 0.0

    def test_mixed_returns(self):
        returns = [0.01, -0.005, 0.02, -0.01, 0.015]
        sortino = compute_sortino(returns, risk_free_rate=0.0, periods_per_year=8760)
        assert sortino > 0

    def test_all_negative_returns(self):
        returns = [-0.01, -0.02, -0.015]
        sortino = compute_sortino(returns, risk_free_rate=0.0)
        assert sortino < 0


# ---------------------------------------------------------------------------
# compute_max_drawdown
# ---------------------------------------------------------------------------

class TestComputeMaxDrawdown:
    def test_empty(self):
        dd_pct, dd_dur = compute_max_drawdown([])
        assert dd_pct == 0.0
        assert dd_dur == 0.0

    def test_single_point(self):
        dd_pct, dd_dur = compute_max_drawdown([_make_point(0, 100)])
        assert dd_pct == 0.0

    def test_monotonically_increasing(self):
        pts = [_make_point(i * 3600, 100 + i * 10) for i in range(5)]
        dd_pct, _ = compute_max_drawdown(pts)
        assert dd_pct == 0.0

    def test_simple_drawdown(self):
        pts = [
            _make_point(0, 100),
            _make_point(3600, 120),
            _make_point(7200, 90),   # 25% drawdown from 120
            _make_point(10800, 110),
        ]
        dd_pct, _ = compute_max_drawdown(pts)
        assert dd_pct == pytest.approx(25.0)

    def test_drawdown_duration(self):
        pts = [
            _make_point(0, 100),
            _make_point(3600, 120),    # peak
            _make_point(7200, 90),     # trough
            _make_point(10800, 130),   # recovery and new peak
        ]
        dd_pct, dd_dur = compute_max_drawdown(pts)
        assert dd_pct == pytest.approx(25.0)
        assert dd_dur == 7200.0  # from t=3600 to t=10800

    def test_ending_in_drawdown(self):
        pts = [
            _make_point(0, 100),
            _make_point(3600, 120),
            _make_point(7200, 90),
        ]
        dd_pct, dd_dur = compute_max_drawdown(pts)
        assert dd_pct == pytest.approx(25.0)
        # Ends in drawdown — duration from peak to last point
        assert dd_dur == 3600.0  # from t=3600 to t=7200


# ---------------------------------------------------------------------------
# compute_calmar
# ---------------------------------------------------------------------------

class TestComputeCalmar:
    def test_empty(self):
        assert compute_calmar([], [], 8760) == 0.0

    def test_no_drawdown(self):
        """No drawdown => zero calmar (div-by-zero guarded)."""
        pts = [_make_point(i * 3600, 100 + i * 10) for i in range(5)]
        returns = [0.01] * 4
        assert compute_calmar(returns, pts) == 0.0

    def test_positive_calmar(self):
        pts = [
            _make_point(0, 10000),
            _make_point(3600, 10100),
            _make_point(7200, 9900),
            _make_point(10800, 10200),
            _make_point(14400, 10300),
            _make_point(18000, 10400),
        ]
        returns = [0.01, -0.02, 0.03, 0.01, 0.01]
        calmar = compute_calmar(returns, pts, periods_per_year=8760)
        assert calmar > 0


# ---------------------------------------------------------------------------
# compute_trade_stats
# ---------------------------------------------------------------------------

class TestComputeTradeStats:
    def test_no_trades(self):
        stats = compute_trade_stats([])
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0.0

    def test_all_winners(self):
        trades = [_make_trade(10, trade_id=f"t{i}") for i in range(3)]
        stats = compute_trade_stats(trades)
        assert stats["total_trades"] == 3
        assert stats["winning_trades"] == 3
        assert stats["losing_trades"] == 0
        assert stats["win_rate"] == pytest.approx(1.0)
        assert stats["total_pnl"] == pytest.approx(30.0)
        assert stats["profit_factor"] == float("inf")

    def test_all_losers(self):
        trades = [_make_trade(-5, trade_id=f"t{i}") for i in range(2)]
        stats = compute_trade_stats(trades)
        assert stats["win_rate"] == pytest.approx(0.0)
        assert stats["profit_factor"] == pytest.approx(0.0)

    def test_mixed(self):
        trades = [
            _make_trade(10, trade_id="t1"),
            _make_trade(-5, trade_id="t2"),
            _make_trade(20, trade_id="t3"),
            _make_trade(-3, trade_id="t4"),
        ]
        stats = compute_trade_stats(trades)
        assert stats["total_trades"] == 4
        assert stats["winning_trades"] == 2
        assert stats["losing_trades"] == 2
        assert stats["win_rate"] == pytest.approx(0.5)
        assert stats["total_pnl"] == pytest.approx(22.0)
        assert stats["gross_profit"] == pytest.approx(30.0)
        assert stats["gross_loss"] == pytest.approx(-8.0)
        assert stats["profit_factor"] == pytest.approx(30.0 / 8.0)
        assert stats["largest_win"] == pytest.approx(20.0)
        assert stats["largest_loss"] == pytest.approx(-5.0)

    def test_avg_duration(self):
        trades = [
            _make_trade(10, duration=100, trade_id="t1"),
            _make_trade(5, duration=200, trade_id="t2"),
        ]
        stats = compute_trade_stats(trades)
        assert stats["avg_trade_duration_seconds"] == pytest.approx(150.0)

    def test_expectancy_and_payoff(self):
        trades = [
            _make_trade(10, trade_id="t1"),
            _make_trade(-5, trade_id="t2"),
        ]
        stats = compute_trade_stats(trades)
        # win_rate=0.5, avg_win=10, avg_loss=-5
        # expectancy = 0.5*10 - 0.5*5 = 2.5
        assert stats["expectancy"] == pytest.approx(2.5)
        # payoff_ratio = 10/5 = 2.0
        assert stats["payoff_ratio"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# compute_rolling_sharpe
# ---------------------------------------------------------------------------

class TestComputeRollingSharpe:
    def test_insufficient_data(self):
        returns = [0.01, 0.02]
        ts = [100, 200]
        assert compute_rolling_sharpe(returns, ts, window_periods=5) == []

    def test_basic(self):
        returns = [0.01, 0.02, -0.01, 0.015, 0.01]
        ts = [100, 200, 300, 400, 500]
        result = compute_rolling_sharpe(returns, ts, window_periods=3)
        assert len(result) == 3
        # Each entry is (timestamp, sharpe)
        assert result[0][0] == 300
        assert result[1][0] == 400
        assert result[2][0] == 500
        # Values should be finite
        for _, sharpe in result:
            assert math.isfinite(sharpe)


# ---------------------------------------------------------------------------
# compute_performance
# ---------------------------------------------------------------------------

class TestComputePerformance:
    def test_empty(self):
        perf = compute_performance(
            trades=[], returns=[], equity_curve=[]
        )
        assert isinstance(perf, PerformanceSummary)
        assert perf.total_trades == 0
        assert perf.sharpe_ratio == 0.0

    def test_below_min_trades_for_ratios(self):
        trades = [_make_trade(10, trade_id="t1")]
        returns = [0.01, 0.02, 0.015]
        pts = [_make_point(i * 3600, 100 + i * 10) for i in range(4)]
        perf = compute_performance(
            trades=trades,
            returns=returns,
            equity_curve=pts,
            min_trades_for_ratios=5,
        )
        assert perf.total_trades == 1
        assert perf.sharpe_ratio == 0.0  # below threshold

    def test_full_metrics(self):
        trades = [
            _make_trade(10, trade_id="t1"),
            _make_trade(-5, trade_id="t2"),
            _make_trade(20, trade_id="t3"),
            _make_trade(-3, trade_id="t4"),
            _make_trade(15, trade_id="t5"),
        ]
        returns = [0.01, -0.005, 0.02, -0.003, 0.015]
        pts = [_make_point(i * 3600, 100 + i * 5) for i in range(6)]
        perf = compute_performance(
            trades=trades,
            returns=returns,
            equity_curve=pts,
            min_trades_for_ratios=3,
        )
        assert perf.total_trades == 5
        assert perf.win_rate == pytest.approx(0.6)
        assert perf.sharpe_ratio != 0.0
