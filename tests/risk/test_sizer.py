"""Tests for PositionSizer."""

import pytest

from libs.contracts.schemas import TradeSignal
from libs.risk.account_state import AccountState
from libs.risk.sizer import PositionSizer


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
def sizer():
    return PositionSizer()


@pytest.fixture
def account():
    return AccountState(10_000)


@pytest.fixture
def base_config():
    return {
        "position_sizing": {
            "default_strategy": "volatility_scaled",
            "fixed_fractional": {"risk_per_trade_pct": 2.0},
            "volatility_scaled": {"target_risk_pct": 1.0, "atr_multiplier": 2.0},
            "kelly": {"fraction": 0.5},
            "equal_weight": {},
        },
        "global_limits": {"max_concurrent_positions": 10},
        "stop_loss": {"fixed_pct": {"pct": 2.0}},
    }


class TestFixedFractional:
    def test_known_output(self, sizer, account, base_config):
        signal = _make_signal(price=50_000)
        size = sizer.calculate("fixed_fractional", signal, account, base_config)
        # risk_amount = 10000 * 2 / 100 = 200
        # stop_distance = 50000 * 2 / 100 = 1000
        # size = 200 / 1000 = 0.2
        assert abs(size - 0.2) < 1e-9

    def test_zero_price(self, sizer, account, base_config):
        signal = _make_signal(price=0)
        size = sizer.calculate("fixed_fractional", signal, account, base_config)
        assert size == 0.0


class TestVolatilityScaled:
    def test_known_output(self, sizer, account, base_config):
        signal = _make_signal(metadata={"ATR": 500.0})
        size = sizer.calculate("volatility_scaled", signal, account, base_config)
        # risk_amount = 10000 * 1.0 / 100 = 100
        # denominator = 500 * 2 = 1000
        # size = 100 / 1000 = 0.1
        assert abs(size - 0.1) < 1e-9

    def test_fallback_without_atr(self, sizer, account, base_config):
        signal = _make_signal(metadata={})
        size = sizer.calculate("volatility_scaled", signal, account, base_config)
        # Falls back to fixed_fractional
        assert size > 0


class TestKelly:
    def test_known_output(self, sizer, account, base_config):
        signal = _make_signal(
            price=50_000,
            metadata={"win_rate": 0.6, "rr_ratio": 2.0},
        )
        size = sizer.calculate("kelly", signal, account, base_config)
        # kelly_raw = 0.6 - (0.4 / 2.0) = 0.4
        # size = 0.5 * 0.4 * 10000 / 50000 = 0.04
        assert abs(size - 0.04) < 1e-9

    def test_fallback_without_win_rate(self, sizer, account, base_config):
        signal = _make_signal(metadata={})
        size = sizer.calculate("kelly", signal, account, base_config)
        # Falls back to fixed_fractional
        assert size > 0


class TestEqualWeight:
    def test_known_output(self, sizer, account, base_config):
        signal = _make_signal(price=50_000)
        size = sizer.calculate("equal_weight", signal, account, base_config)
        # size = 10000 / (10 * 50000) = 0.02
        assert abs(size - 0.02) < 1e-9

    def test_zero_price(self, sizer, account, base_config):
        signal = _make_signal(price=0)
        size = sizer.calculate("equal_weight", signal, account, base_config)
        assert size == 0.0


class TestUnknownStrategy:
    def test_falls_back_to_fixed_fractional(self, sizer, account, base_config):
        signal = _make_signal(price=50_000)
        size = sizer.calculate("nonexistent", signal, account, base_config)
        expected = sizer.calculate("fixed_fractional", signal, account, base_config)
        assert abs(size - expected) < 1e-9
