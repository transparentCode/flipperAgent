"""Tests for KeltnerChannel indicator."""

import pytest
from libs.features.indicators.volatility.keltner import KeltnerChannel
from libs.features.indicators.registry import IndicatorRegistry


class TestKeltnerRegistry:
    def test_registered(self):
        cls = IndicatorRegistry.get("KeltnerChannel")
        assert cls is KeltnerChannel


class TestKeltnerBatch:
    @pytest.fixture
    def hlc_data(self):
        """Generate synthetic HLC data."""
        data = []
        for i in range(60):
            close = 100.0 + i * 0.5
            high = close + 2.0
            low = close - 2.0
            data.append((high, low, close))
        return data

    def test_output_length(self, hlc_data):
        kc = KeltnerChannel(period=20, multiplier=1.5, atr_period=14)
        result = kc.batch(hlc_data)
        assert len(result) == len(hlc_data)

    def test_upper_greater_middle_greater_lower(self, hlc_data):
        kc = KeltnerChannel(period=20, multiplier=1.5, atr_period=14)
        result = kc.batch(hlc_data)
        valid = [r for r in result if r is not None]
        assert len(valid) > 0
        for mid, upper, lower in valid:
            assert upper > mid
            assert mid > lower

    def test_tuple_output_shape(self, hlc_data):
        kc = KeltnerChannel(period=20, multiplier=1.5, atr_period=14)
        result = kc.batch(hlc_data)
        valid = [r for r in result if r is not None]
        for item in valid:
            assert isinstance(item, tuple)
            assert len(item) == 3

    def test_nans_before_lookback(self, hlc_data):
        kc = KeltnerChannel(period=20, multiplier=1.5, atr_period=14)
        result = kc.batch(hlc_data)
        # First few values should be None
        assert result[0] is None

    def test_empty_input(self):
        kc = KeltnerChannel()
        assert kc.batch([]) == []

    def test_lookback_required(self):
        kc = KeltnerChannel(period=20, atr_period=14)
        assert kc.lookback_required == 20  # max(20, 15)


class TestKeltnerPrimeUpdate:
    def test_prime_then_update_consistency(self):
        data = []
        for i in range(60):
            close = 100.0 + i * 0.5
            high = close + 2.0
            low = close - 2.0
            data.append((high, low, close))

        # Batch reference
        kc_batch = KeltnerChannel(period=20, multiplier=1.5, atr_period=14)
        batch_result = kc_batch.batch(data)

        # Prime + update
        kc_live = KeltnerChannel(period=20, multiplier=1.5, atr_period=14)
        kc_live.prime(data[:40])
        assert kc_live.is_primed

        for i in range(40, 60):
            live_val = kc_live.update(data[i])

        batch_last = batch_result[-1]
        assert batch_last is not None
        mid_b, upper_b, lower_b = batch_last
        mid_l, upper_l, lower_l = live_val
        assert abs(mid_l - mid_b) < 1e-6
        assert abs(upper_l - upper_b) < 1e-6
        assert abs(lower_l - lower_b) < 1e-6

    def test_prime_too_few_raises(self):
        kc = KeltnerChannel(period=20, atr_period=14)
        with pytest.raises(ValueError, match="at least"):
            kc.prime([(100, 99, 99.5)] * 5)

    def test_update_before_prime_raises(self):
        kc = KeltnerChannel()
        with pytest.raises(RuntimeError, match="primed"):
            kc.update((100, 99, 99.5))
