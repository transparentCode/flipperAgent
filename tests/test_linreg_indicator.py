"""Tests for LinReg (Linear Regression Value) indicator."""

import pytest
from libs.features.indicators.momentum.linreg import LinReg
from libs.features.indicators.registry import IndicatorRegistry


class TestLinRegRegistry:
    def test_registered(self):
        cls = IndicatorRegistry.get("LinReg")
        assert cls is LinReg


class TestLinRegBatch:
    def test_output_length_matches_input(self):
        lr = LinReg(period=12)
        data = [float(i) for i in range(50)]
        result = lr.batch(data)
        assert len(result) == len(data)

    def test_linear_input_matches_last_value(self):
        """For perfectly linear data, LinReg should match the last value in the window."""
        lr = LinReg(period=12)
        data = [float(i) for i in range(20)]
        result = lr.batch(data)
        # At index 11 (first valid), window is [0..11], linreg at end = 11.0
        assert result[11] is not None
        assert abs(result[11] - 11.0) < 1e-6
        # At index 19, window is [8..19], linreg at end = 19.0
        assert abs(result[19] - 19.0) < 1e-6

    def test_constant_input(self):
        """Constant input → LinReg should equal the constant."""
        lr = LinReg(period=12)
        data = [50.0] * 30
        result = lr.batch(data)
        valid = [x for x in result if x is not None]
        for v in valid:
            assert abs(v - 50.0) < 1e-6

    def test_nans_before_lookback(self):
        lr = LinReg(period=12)
        data = [float(i) for i in range(50)]
        result = lr.batch(data)
        for i in range(11):
            assert result[i] is None

    def test_short_data_returns_nans(self):
        lr = LinReg(period=12)
        data = [1.0, 2.0, 3.0]
        result = lr.batch(data)
        assert all(x is None for x in result)

    def test_empty_input(self):
        lr = LinReg(period=12)
        assert lr.batch([]) == []

    def test_lookback_required(self):
        lr = LinReg(period=12)
        assert lr.lookback_required == 12


class TestLinRegPrimeUpdate:
    def test_prime_then_update_consistency(self):
        """Prime + sequential updates should match batch output."""
        data = [float(i * 3 + 10) for i in range(40)]

        lr_batch = LinReg(period=12)
        batch_result = lr_batch.batch(data)

        lr_live = LinReg(period=12)
        lr_live.prime(data[:20])
        assert lr_live.is_primed

        for i in range(20, 40):
            live_val = lr_live.update(data[i])

        assert batch_result[-1] is not None
        assert abs(live_val - batch_result[-1]) < 1e-6

    def test_prime_too_few_raises(self):
        lr = LinReg(period=12)
        with pytest.raises(ValueError, match="at least 12"):
            lr.prime([1.0, 2.0])

    def test_update_before_prime_raises(self):
        lr = LinReg(period=12)
        with pytest.raises(RuntimeError, match="primed"):
            lr.update(1.0)
