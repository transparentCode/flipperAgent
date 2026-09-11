from __future__ import annotations

import pandas as pd

from libs.regime.optimization.simple_baseline_benchmark import (
    _backtest_positions,
    _build_strategy_positions,
    _donchian_breakout_positions,
    _rsi_mean_reversion_positions,
    build_simple_panel_summary,
)


def test_build_strategy_positions_produces_expected_simple_baselines():
    index = pd.date_range("2026-01-01", periods=240, freq="h", tz="UTC")
    close = pd.Series(range(100, 340), index=index, dtype=float)
    frame = pd.DataFrame({"close": close}, index=index)

    positions = _build_strategy_positions(
        frame,
        timeframe="1h",
        strategy_names=("cash_flat", "buy_and_hold", "ema_20_50", "sma_50_200"),
    )

    assert positions["cash_flat"].sum() == 0.0
    assert positions["buy_and_hold"].iloc[-1] == 1.0
    assert positions["ema_20_50"].iloc[-1] == 1.0
    assert positions["sma_50_200"].iloc[-1] == 1.0


def test_donchian_breakout_positions_toggle_on_entry_and_exit():
    close = pd.Series([10, 11, 12, 13, 14, 15, 14, 13, 12, 11, 10], dtype=float)

    positions = _donchian_breakout_positions(close, entry=3, exit_=2)

    assert positions.max() == 1.0
    assert positions.iloc[-1] == 0.0


def test_rsi_mean_reversion_positions_enter_and_exit():
    close = pd.Series([100, 99, 98, 97, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106], dtype=float)

    positions = _rsi_mean_reversion_positions(close, period=3, lower=30.0, upper=70.0)

    assert positions.max() == 1.0
    assert positions.iloc[-1] == 0.0


def test_backtest_positions_returns_calmar():
    positions = [0.0, 1.0, 1.0, 0.0, 1.0]
    close = [100.0, 101.0, 103.0, 100.0, 104.0]

    metrics = _backtest_positions(positions, close, timeframe="1h", cost_bps=0.0)

    assert "calmar" in metrics
    assert metrics["trade_count"] >= 1


def test_build_simple_panel_summary_groups_by_strategy():
    row = {
        "asset": "BTCUSDT",
        "timeframe": "1h",
        "slice_usable": True,
        "strategies": {
            "buy_and_hold": {
                "candidates": {
                    "no_regime": {"walk_forward": {"sharpe": 1.0, "cumulative_return": 0.2, "max_drawdown": -0.2, "calmar": 1.0, "turnover": 1.0, "trade_count": 1, "active_ratio": 1.0, "decision": "baseline"}},
                    "breadth_blend": {"walk_forward": {"sharpe": 1.2, "cumulative_return": 0.25, "max_drawdown": -0.15, "calmar": 1.5, "turnover": 0.8, "trade_count": 1, "active_ratio": 0.8, "decision": "promote_to_integration_design"}},
                }
            },
            "cash_flat": {
                "candidates": {
                    "no_regime": {"walk_forward": {"sharpe": 0.0, "cumulative_return": 0.0, "max_drawdown": 0.0, "calmar": 0.0, "turnover": 0.0, "trade_count": 0, "active_ratio": 0.0, "decision": "baseline"}},
                    "breadth_blend": {"walk_forward": {"sharpe": 0.0, "cumulative_return": 0.0, "max_drawdown": 0.0, "calmar": 0.0, "turnover": 0.0, "trade_count": 0, "active_ratio": 0.0, "decision": "reject"}},
                }
            },
        },
    }

    summary = build_simple_panel_summary(
        [row],
        candidate_names=("no_regime", "breadth_blend"),
        strategy_names=("buy_and_hold", "cash_flat"),
    )

    assert summary["usable_slices"] == 1
    assert summary["strategy_summary"]["buy_and_hold"]["breadth_blend"]["panel_decision"] == "promote_to_integration_design"
