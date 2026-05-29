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


class TestMultiLevel:
    """Tests for TakeProfitCalculator.calculate_multi()."""

    @pytest.fixture
    def multi_config(self):
        return {
            "multi_level": {
                "levels": [
                    {"pct": 1.5, "portion": 0.40},
                    {"pct": 3.0, "portion": 0.30},
                    {"pct": 5.0, "portion": 0.30},
                ],
                "trail_to_breakeven": True,
            },
        }

    def test_long_multi_tp(self, calc, multi_config):
        signal = _make_signal(direction=1, price=100.0)
        levels, portions, trail = calc.calculate_multi(signal, 98.0, multi_config)
        assert len(levels) == 3
        assert levels[0] == pytest.approx(101.5)
        assert levels[1] == pytest.approx(103.0)
        assert levels[2] == pytest.approx(105.0)
        assert portions == [0.40, 0.30, 0.30]
        assert trail is True

    def test_short_multi_tp(self, calc, multi_config):
        signal = _make_signal(direction=-1, price=100.0)
        levels, portions, trail = calc.calculate_multi(signal, 102.0, multi_config)
        assert len(levels) == 3
        assert levels[0] == pytest.approx(98.5)
        assert levels[1] == pytest.approx(97.0)
        assert levels[2] == pytest.approx(95.0)
        assert trail is True

    def test_empty_levels(self, calc):
        signal = _make_signal(direction=1, price=100.0)
        levels, portions, trail = calc.calculate_multi(
            signal, 98.0, {"multi_level": {"levels": []}},
        )
        assert levels == []
        assert portions == []

    def test_no_multi_level_config(self, calc):
        signal = _make_signal(direction=1, price=100.0)
        levels, portions, trail = calc.calculate_multi(signal, 98.0, {})
        assert levels == []
        assert portions == []
        assert trail is False

    def test_portions_normalized_if_over_one(self, calc):
        config = {
            "multi_level": {
                "levels": [
                    {"pct": 1.0, "portion": 0.60},
                    {"pct": 2.0, "portion": 0.60},
                ],
                "trail_to_breakeven": False,
            },
        }
        signal = _make_signal(direction=1, price=100.0)
        levels, portions, trail = calc.calculate_multi(signal, 98.0, config)
        assert sum(portions) == pytest.approx(1.0)
        assert trail is False

    def test_trail_to_breakeven_false(self, calc):
        config = {
            "multi_level": {
                "levels": [{"pct": 2.0, "portion": 1.0}],
                "trail_to_breakeven": False,
            },
        }
        signal = _make_signal(direction=1, price=100.0)
        _, _, trail = calc.calculate_multi(signal, 98.0, config)
        assert trail is False

    def test_flat_direction_skipped(self, calc, multi_config):
        signal = _make_signal(direction=0, price=100.0)
        levels, portions, trail = calc.calculate_multi(signal, None, multi_config)
        assert levels == []
        assert portions == []

    def test_method_set_includes_multi_level(self, calc):
        assert "multi_level" in calc._METHODS
