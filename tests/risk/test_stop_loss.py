"""Tests for StopLossCalculator."""

import pytest

from libs.contracts.schemas import TradeSignal
from libs.risk.stop_loss import StopLossCalculator


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
    return StopLossCalculator()


@pytest.fixture
def config():
    return {
        "atr_based": {"multiplier": 2.0},
        "fixed_pct": {"pct": 2.0},
        "trailing": {"atr_multiplier": 2.0},
    }


class TestAtrBased:
    def test_long_sl(self, calc, config):
        signal = _make_signal(direction=1, metadata={"ATR": 500.0})
        sl = calc.calculate("atr_based", signal, config)
        # SL = 50000 - 500 * 2 = 49000
        assert sl == pytest.approx(49_000.0)

    def test_short_sl(self, calc, config):
        signal = _make_signal(direction=-1, metadata={"ATR": 500.0})
        sl = calc.calculate("atr_based", signal, config)
        # SL = 50000 + 500 * 2 = 51000
        assert sl == pytest.approx(51_000.0)

    def test_returns_none_without_atr(self, calc, config):
        signal = _make_signal(direction=1)
        sl = calc.calculate("atr_based", signal, config)
        assert sl is None


class TestFixedPct:
    def test_long_sl(self, calc, config):
        signal = _make_signal(direction=1)
        sl = calc.calculate("fixed_pct", signal, config)
        # SL = 50000 * (1 - 2/100) = 49000
        assert sl == pytest.approx(49_000.0)

    def test_short_sl(self, calc, config):
        signal = _make_signal(direction=-1)
        sl = calc.calculate("fixed_pct", signal, config)
        # SL = 50000 * (1 + 2/100) = 51000
        assert sl == pytest.approx(51_000.0)


class TestTrailing:
    def test_initial_sl_uses_trailing_config(self, calc):
        signal = _make_signal(direction=1, metadata={"ATR": 500.0})
        config = {
            "atr_based": {"multiplier": 2.0},
            "trailing": {"atr_multiplier": 3.0},
        }
        sl = calc.calculate("trailing", signal, config)
        # Uses trailing atr_multiplier=3.0: SL = 50000 - 500*3 = 48500
        assert sl == pytest.approx(48_500.0)

    def test_initial_sl_same_as_atr_when_same_multiplier(self, calc, config):
        signal = _make_signal(direction=1, metadata={"ATR": 500.0})
        sl_trailing = calc.calculate("trailing", signal, config)
        sl_atr = calc.calculate("atr_based", signal, config)
        # Both use multiplier=2.0 so they should match
        assert sl_trailing == sl_atr
