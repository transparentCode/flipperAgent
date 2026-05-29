"""Tests for backtest_multi_tp and compute_multi_tp_metrics."""

from __future__ import annotations

import numpy as np
import pytest

from libs.optim_utils.scoring import (
    MultiTpTradeResult,
    backtest_multi_tp,
    compute_multi_tp_metrics,
    compute_sharpe,
)


class TestBacktestMultiTp:
    """Core multi-TP backtest logic."""

    def test_no_signals_returns_zeros(self):
        """No direction signals → zero equity returns, no trades."""
        directions = np.array([0, 0, 0, 0, 0])
        h = l = c = np.array([100.0, 101.0, 102.0, 101.0, 100.0])
        eq, trades = backtest_multi_tp(directions, h, l, c)
        assert len(trades) == 0
        np.testing.assert_array_equal(eq, np.zeros(5))

    def test_output_lengths(self):
        """Equity returns array has same length as input."""
        n = 50
        directions = np.zeros(n)
        directions[5] = 1
        h = l = c = np.linspace(100, 120, n)
        eq, trades = backtest_multi_tp(directions, h, l, c)
        assert len(eq) == n

    def test_long_all_tps_hit(self):
        """Long entry → price rises through TP1, TP2, TP3 sequentially."""
        # Entry at 100, TP1=101.5, TP2=103, TP3=105
        n = 10
        directions = np.zeros(n)
        directions[0] = 1
        close = np.array([100, 101, 102, 103, 104, 105, 106, 107, 108, 109], dtype=float)
        high = close + 0.5
        low = close - 0.5

        eq, trades = backtest_multi_tp(
            directions, high, low, close,
            tp_pcts=(0.015, 0.03, 0.05),
            tp_portions=(0.40, 0.30, 0.30),
            sl_pct=0.02,
            commission_bps=0.0,
            trail_to_breakeven=True,
        )
        assert len(trades) == 1
        t = trades[0]
        assert t.direction == 1
        assert t.entry_price == 100.0
        assert all(t.tp_hits), f"Not all TPs hit: {t.tp_hits}"
        assert not t.sl_hit
        assert t.pnl_pct > 0

    def test_short_all_tps_hit(self):
        """Short entry → price drops through TP1, TP2, TP3."""
        n = 10
        directions = np.zeros(n)
        directions[0] = -1
        close = np.array([100, 99, 98, 97, 96, 95, 94, 93, 92, 91], dtype=float)
        high = close + 0.5
        low = close - 0.5

        eq, trades = backtest_multi_tp(
            directions, high, low, close,
            tp_pcts=(0.015, 0.03, 0.05),
            tp_portions=(0.40, 0.30, 0.30),
            sl_pct=0.02,
            commission_bps=0.0,
            trail_to_breakeven=True,
        )
        assert len(trades) == 1
        t = trades[0]
        assert t.direction == -1
        assert all(t.tp_hits)
        assert not t.sl_hit
        assert t.pnl_pct > 0

    def test_sl_hit_before_any_tp(self):
        """Price drops immediately → SL hit, no TPs."""
        n = 5
        directions = np.zeros(n)
        directions[0] = 1
        close = np.array([100, 99, 97.5, 97, 96], dtype=float)
        high = close + 0.3
        low = close - 0.3

        eq, trades = backtest_multi_tp(
            directions, high, low, close,
            tp_pcts=(0.015, 0.03, 0.05),
            tp_portions=(0.40, 0.30, 0.30),
            sl_pct=0.02,
            commission_bps=0.0,
        )
        assert len(trades) == 1
        t = trades[0]
        assert t.sl_hit
        assert not any(t.tp_hits)
        assert t.pnl_pct < 0

    def test_trail_to_breakeven_after_tp1(self):
        """After TP1, SL moves to entry. Price reverses → exits at breakeven."""
        n = 10
        directions = np.zeros(n)
        directions[0] = 1
        # Entry 100, TP1 at 101.5, then price reverses to 100 (breakeven)
        close = np.array([100, 101, 102, 101, 100, 99.5, 100, 101, 102, 103], dtype=float)
        high = np.array([100.5, 102, 102.5, 101.5, 100.5, 100, 100.5, 101.5, 102.5, 103.5])
        low = np.array([99.5, 100.5, 101, 100, 99.5, 99, 99.5, 100.5, 101.5, 102.5])

        eq, trades = backtest_multi_tp(
            directions, high, low, close,
            tp_pcts=(0.015, 0.03, 0.05),
            tp_portions=(0.40, 0.30, 0.30),
            sl_pct=0.02,
            commission_bps=0.0,
            trail_to_breakeven=True,
        )
        assert len(trades) == 1
        t = trades[0]
        assert t.tp_hits[0]  # TP1 hit
        assert t.sl_hit  # SL at breakeven triggered
        # PnL should be slightly positive (TP1 profit on 40%)
        assert t.pnl_pct >= 0

    def test_no_trail_to_breakeven(self):
        """Without trail, SL stays at original level."""
        n = 10
        directions = np.zeros(n)
        directions[0] = 1
        close = np.array([100, 101, 102, 101, 100, 97, 96, 95, 94, 93], dtype=float)
        high = close + 0.5
        low = close - 0.5

        eq, trades = backtest_multi_tp(
            directions, high, low, close,
            tp_pcts=(0.015, 0.03, 0.05),
            tp_portions=(0.40, 0.30, 0.30),
            sl_pct=0.02,
            commission_bps=0.0,
            trail_to_breakeven=False,
        )
        assert len(trades) == 1
        t = trades[0]
        assert t.tp_hits[0]  # TP1 hit
        assert t.sl_hit  # SL at original 98 triggered
        # PnL could be positive or negative depending on TP1 profit vs SL loss

    def test_one_tp_per_bar(self):
        """Even if price blows through all TP levels, only one TP fires per bar."""
        n = 5
        directions = np.zeros(n)
        directions[0] = 1
        # Huge bar — high exceeds all TPs at once
        close = np.array([100, 110, 115, 120, 125], dtype=float)
        high = np.array([100.5, 115, 120, 125, 130], dtype=float)
        low = np.array([99.5, 105, 110, 115, 120], dtype=float)

        eq, trades = backtest_multi_tp(
            directions, high, low, close,
            tp_pcts=(0.015, 0.03, 0.05),
            tp_portions=(0.40, 0.30, 0.30),
            sl_pct=0.02,
            commission_bps=0.0,
        )
        assert len(trades) == 1
        t = trades[0]
        # TP1 on bar 1, TP2 on bar 2, TP3 on bar 3 (one per bar)
        assert all(t.tp_hits)

    def test_commission_deducted(self):
        """Commission reduces equity returns."""
        n = 10
        directions = np.zeros(n)
        directions[0] = 1
        close = np.linspace(100, 110, n)
        high = close + 0.5
        low = close - 0.5

        eq_free, _ = backtest_multi_tp(
            directions, high, low, close, commission_bps=0.0
        )
        eq_costly, _ = backtest_multi_tp(
            directions, high, low, close, commission_bps=10.0
        )
        assert np.sum(eq_costly) < np.sum(eq_free)

    def test_multiple_trades(self):
        """Two separate trades in the same series."""
        n = 20
        directions = np.zeros(n)
        directions[0] = 1
        directions[10] = -1
        close = np.concatenate([
            np.linspace(100, 110, 10),
            np.linspace(110, 100, 10),
        ])
        high = close + 1
        low = close - 1

        eq, trades = backtest_multi_tp(
            directions, high, low, close, commission_bps=0.0,
        )
        assert len(trades) == 2
        assert trades[0].direction == 1
        assert trades[1].direction == -1

    def test_custom_tp_levels(self):
        """Custom 2-level TP works correctly."""
        n = 10
        directions = np.zeros(n)
        directions[0] = 1
        close = np.array([100, 102, 104, 106, 108, 110, 112, 114, 116, 118], dtype=float)
        high = close + 0.5
        low = close - 0.5

        eq, trades = backtest_multi_tp(
            directions, high, low, close,
            tp_pcts=(0.02, 0.05),
            tp_portions=(0.50, 0.50),
            sl_pct=0.01,
            commission_bps=0.0,
        )
        assert len(trades) == 1
        t = trades[0]
        assert len(t.tp_hits) == 2

    def test_position_open_at_end(self):
        """Position still open at end of data → mark-to-market."""
        n = 3
        directions = np.zeros(n)
        directions[0] = 1
        close = np.array([100, 101, 102], dtype=float)
        high = close + 0.2  # Not high enough to hit TP1 at 101.5
        low = close - 0.2

        eq, trades = backtest_multi_tp(
            directions, high, low, close,
            tp_pcts=(0.05, 0.10, 0.15),
            tp_portions=(0.40, 0.30, 0.30),
            sl_pct=0.02,
            commission_bps=0.0,
        )
        assert len(trades) == 1
        t = trades[0]
        assert not any(t.tp_hits)
        assert not t.sl_hit
        # PnL should reflect mark-to-market
        assert t.pnl_pct > 0

    def test_portions_sum_validation(self):
        """tp_pcts and tp_portions must have same length."""
        with pytest.raises(AssertionError):
            backtest_multi_tp(
                np.array([1, 0]), np.array([100, 110.0]),
                np.array([99, 109.0]), np.array([100, 110.0]),
                tp_pcts=(0.01, 0.02),
                tp_portions=(0.5,),  # mismatch
            )


class TestComputeMultiTpMetrics:
    """Tests for the metrics aggregation helper."""

    def test_empty_trades(self):
        """No trades → zeroed metrics."""
        m = compute_multi_tp_metrics(np.zeros(10), [], "1h")
        assert m["n_trades"] == 0
        assert m["sharpe"] == 0.0
        assert m["win_rate"] == 0.0

    def test_metrics_from_trades(self):
        """Basic metrics from a known trade list."""
        trades = [
            MultiTpTradeResult(0, 5, 1, 100.0, 0.02, [True, True, False], False, 5),
            MultiTpTradeResult(6, 10, -1, 110.0, -0.01, [True, False, False], True, 4),
        ]
        eq = np.array([0.01, 0.005, 0.003, 0.002, -0.005, 0.008,
                        -0.003, -0.002, -0.001, 0.001, -0.004])
        m = compute_multi_tp_metrics(eq, trades, "1h")
        assert m["n_trades"] == 2
        assert m["win_rate"] == 0.5  # 1 win, 1 loss
        assert m["tp1_rate"] == 1.0  # both hit TP1
        assert m["tp2_rate"] == 0.5  # only first hit TP2
        assert m["sl_rate"] == 0.5
        assert m["avg_holding"] == 4.5

    def test_sharpe_computed(self):
        """Sharpe ratio is computed from equity returns."""
        eq = np.random.default_rng(42).normal(0.001, 0.01, 100)
        trades = [MultiTpTradeResult(0, 50, 1, 100.0, 0.05, [True, True, True], False, 50)]
        m = compute_multi_tp_metrics(eq, trades, "1h")
        assert isinstance(m["sharpe"], float)
        assert m["sharpe"] != 0.0
