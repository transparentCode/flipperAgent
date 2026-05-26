"""Tests for KAMA (Kaufman Adaptive Moving Average) indicator."""

import pytest
from libs.features.indicators.trend.kama import KAMA
from libs.features.indicators.registry import IndicatorRegistry


class TestKAMARegistry:
    def test_registered(self):
        cls = IndicatorRegistry.get("KAMA")
        assert cls is KAMA


class TestKAMABatch:
    def test_output_length_matches_input(self):
        kama = KAMA(period=10)
        data = [float(i) for i in range(50)]
        result = kama.batch(data)
        assert len(result) == len(data)

    def test_nans_before_lookback(self):
        kama = KAMA(period=10)
        data = [float(i) for i in range(50)]
        result = kama.batch(data)
        for i in range(9):
            assert result[i] is None

    def test_constant_input_returns_constant(self):
        """Constant input → KAMA should converge to that constant."""
        kama = KAMA(period=10)
        data = [100.0] * 50
        result = kama.batch(data)
        valid = [x for x in result if x is not None]
        for v in valid:
            assert abs(v - 100.0) < 1e-6

    def test_short_data_returns_nans(self):
        kama = KAMA(period=10)
        data = [1.0, 2.0, 3.0]
        result = kama.batch(data)
        assert all(x is None for x in result)

    def test_empty_input(self):
        kama = KAMA(period=10)
        assert kama.batch([]) == []

    def test_lookback_required(self):
        kama = KAMA(period=10)
        assert kama.lookback_required == 10


class TestKAMAPrimeUpdate:
    def test_prime_then_update_consistency(self):
        """Prime + sequential update should match batch output."""
        data = [float(i * 2 + 5) for i in range(40)]

        # Batch reference
        kama_batch = KAMA(period=10)
        batch_result = kama_batch.batch(data)

        # Prime + update
        kama_live = KAMA(period=10)
        kama_live.prime(data[:20])
        assert kama_live.is_primed

        # Continue from bar 20 onward
        for i in range(20, 40):
            live_val = kama_live.update(data[i])

        # The final value should be close to batch
        assert batch_result[-1] is not None
        assert abs(live_val - batch_result[-1]) < 1e-4

    def test_prime_too_few_raises(self):
        kama = KAMA(period=10)
        with pytest.raises(ValueError, match="at least 10"):
            kama.prime([1.0, 2.0])

    def test_update_before_prime_raises(self):
        kama = KAMA(period=10)
        with pytest.raises(RuntimeError, match="primed"):
            kama.update(1.0)
