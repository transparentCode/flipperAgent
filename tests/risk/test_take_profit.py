"""Tests for TakeProfitCalculator."""

import pytest

from libs.contracts.schemas import TradeSignal
from libs.risk.take_profit import TakeProfitCalculator


def _make_signal(**overrides) -> TradeSignal:
    defaults = dict(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1_000_000.0,
        direction=1,
        conviction=0.8,
        price=50_000.0,
        idempotency_key="test_key",
        model_name="test_model",
        metadata={},
    )
    defaults.update(overrides)
    return TradeSignal(**defaults)


@pytest.fixture
def calc():
    return TakeProfitCalculator()


@pytest.fixture
def config():
    return {
        "risk_reward": {"ratio": 2.0},
        "fixed_pct": {"pct": 4.0},
        "trailing": {"atr_multiplier": 3.0},
    }


class TestRiskReward:
    def test_long_tp(self, calc, config):
        signal = _make_signal(direction=1)
        sl_price = 49_000.0  # risk = 1000
        tp = calc.calculate("risk_reward", signal, sl_price, config)
        # TP = 50000 + 1000 * 2 = 52000
        assert tp == pytest.approx(52_000.0)

    def test_short_tp(self, calc, config):
        signal = _make_signal(direction=-1)
        sl_price = 51_000.0  # risk = 1000
        tp = calc.calculate("risk_reward", signal, sl_price, config)
        # TP = 50000 - 1000 * 2 = 48000
        assert tp == pytest.approx(48_000.0)

    def test_returns_none_without_sl(self, calc, config):
        signal = _make_signal(direction=1)
        tp = calc.calculate("risk_reward", signal, None, config)
        assert tp is None


class TestFixedPct:
    def test_long_tp(self, calc, config):
        signal = _make_signal(direction=1)
        tp = calc.calculate("fixed_pct", signal, None, config)
        # TP = 50000 * (1 + 4/100) = 52000
        assert tp == pytest.approx(52_000.0)

    def test_short_tp(self, calc, config):
        signal = _make_signal(direction=-1)
        tp = calc.calculate("fixed_pct", signal, None, config)
        # TP = 50000 * (1 - 4/100) = 48000
        assert tp == pytest.approx(48_000.0)


class TestTrailing:
    def test_initial_tp_uses_trailing_config(self, calc, config):
        signal = _make_signal(direction=1)
        sl_price = 49_000.0  # risk = 1000
        tp = calc.calculate("trailing", signal, sl_price, config)
        # Uses trailing atr_multiplier=3.0 as ratio: TP = 50000 + 1000*3 = 53000
        assert tp == pytest.approx(53_000.0)

    def test_returns_none_without_sl(self, calc, config):
        signal = _make_signal(direction=1)
        tp = calc.calculate("trailing", signal, None, config)
        assert tp is None
