"""Tests for SignalAggregator."""

import pytest

from libs.contracts.schemas import TradeSignal
from libs.risk.mtf.aggregator import SignalAggregator


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
def agg():
    return SignalAggregator()


@pytest.fixture
def tf_weights():
    return {"1h": 1.0, "4h": 1.5, "1d": 2.0}


# -------------------------------------------------------------------
# conviction_weighted
# -------------------------------------------------------------------


class TestConvictionWeighted:
    def test_agreeing_signals(self, agg, tf_weights):
        signals = [
            _make_signal(direction=1, conviction=0.8, timeframe="1h", timestamp=100),
            _make_signal(direction=1, conviction=0.6, timeframe="4h", timestamp=200),
        ]
        result = agg.aggregate(signals, "conviction_weighted", tf_weights)
        assert result is not None
        assert result.direction == 1
        assert result.conviction > 0

    def test_conflicting_cancel(self, agg, tf_weights):
        signals = [
            _make_signal(direction=1, conviction=0.8, timeframe="1h"),
            _make_signal(direction=-1, conviction=0.8, timeframe="1h"),
        ]
        # With equal weights and equal conviction, weighted_sum = 0
        result = agg.aggregate(signals, "conviction_weighted", tf_weights)
        assert result is None

    def test_single_signal(self, agg, tf_weights):
        signals = [_make_signal(direction=-1, conviction=0.9)]
        result = agg.aggregate(signals, "conviction_weighted", tf_weights)
        assert result is not None
        assert result.direction == -1

    def test_empty_signals(self, agg, tf_weights):
        result = agg.aggregate([], "conviction_weighted", tf_weights)
        assert result is None


# -------------------------------------------------------------------
# higher_tf_priority
# -------------------------------------------------------------------


class TestHigherTfPriority:
    def test_picks_highest_tf(self, agg, tf_weights):
        signals = [
            _make_signal(direction=1, timeframe="1h"),
            _make_signal(direction=-1, timeframe="4h"),
            _make_signal(direction=1, timeframe="1d"),
        ]
        result = agg.aggregate(signals, "higher_tf_priority", tf_weights)
        assert result is not None
        assert result.timeframe == "1d"
        assert result.direction == 1

    def test_single_signal(self, agg, tf_weights):
        signals = [_make_signal(direction=-1, timeframe="5m")]
        result = agg.aggregate(signals, "higher_tf_priority", tf_weights)
        assert result.direction == -1


# -------------------------------------------------------------------
# cancel_on_conflict
# -------------------------------------------------------------------


class TestCancelOnConflict:
    def test_all_agree(self, agg, tf_weights):
        signals = [
            _make_signal(direction=1, timeframe="1h", timestamp=100),
            _make_signal(direction=1, timeframe="4h", timestamp=200),
        ]
        result = agg.aggregate(signals, "cancel_on_conflict", tf_weights)
        assert result is not None
        assert result.direction == 1

    def test_disagreement_cancels(self, agg, tf_weights):
        signals = [
            _make_signal(direction=1, timeframe="1h"),
            _make_signal(direction=-1, timeframe="4h"),
        ]
        result = agg.aggregate(signals, "cancel_on_conflict", tf_weights)
        assert result is None


# -------------------------------------------------------------------
# independent
# -------------------------------------------------------------------


class TestIndependent:
    def test_returns_all(self, agg, tf_weights):
        signals = [
            _make_signal(direction=1, timeframe="1h"),
            _make_signal(direction=-1, timeframe="4h"),
        ]
        result = agg.aggregate(signals, "independent", tf_weights)
        assert isinstance(result, list)
        assert len(result) == 2
