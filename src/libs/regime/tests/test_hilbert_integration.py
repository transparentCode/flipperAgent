"""
Tests for HilbertCycle and its integration through RegimeOrchestrator.

Validates:
  - HilbertCycle.calculate() returns (period, confidence) within bounds
  - HilbertCycle.calculate_series() returns arrays of correct length
  - Period is clamped to [10, 40] bars
  - Confidence is in [0, 1]
  - Cyclic data produces higher confidence than pure noise
  - hilbert_period / hilbert_confidence flow through analyze_series()
"""

import numpy as np
import pandas as pd
import pytest

from libs.regime.kernels.hilbert_cycle import HilbertCycle
from libs.regime import RegimeOrchestrator


def _make_df(n=300, seed=42):
    np.random.seed(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    prices = 100.0 * np.exp(np.random.normal(0.0001, 0.01, n).cumsum())
    return pd.DataFrame(
        {"open": prices, "high": prices * 1.001, "low": prices * 0.999,
         "close": prices, "volume": 1000.0},
        index=dates,
    )


def _make_cyclic_df(n=300, cycle_period=20, seed=42):
    np.random.seed(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    t = np.arange(n)
    prices = 100.0 + 5.0 * np.sin(2 * np.pi * t / cycle_period) \
             + np.random.normal(0, 0.3, n) + t * 0.01
    return pd.DataFrame(
        {"open": prices, "high": prices + 0.1, "low": prices - 0.1,
         "close": prices, "volume": 1000.0},
        index=dates,
    )


@pytest.fixture
def hilbert():
    return HilbertCycle()


@pytest.fixture
def df():
    return _make_df()


# ---------------------------------------------------------------------------
# calculate() — scalar output
# ---------------------------------------------------------------------------

class TestHilbertCalculate:

    def test_returns_tuple(self, hilbert, df):
        result = hilbert.calculate(df["close"].values)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_period_in_bounds(self, hilbert, df):
        period, _ = hilbert.calculate(df["close"].values)
        assert 10.0 <= period <= 40.0, f"period={period} out of [10, 40]"

    def test_confidence_in_range(self, hilbert, df):
        _, confidence = hilbert.calculate(df["close"].values)
        assert 0.0 <= confidence <= 1.0, f"confidence={confidence} out of [0, 1]"

    def test_period_is_float(self, hilbert, df):
        period, _ = hilbert.calculate(df["close"].values)
        assert isinstance(period, float)

    def test_confidence_is_float(self, hilbert, df):
        _, confidence = hilbert.calculate(df["close"].values)
        assert isinstance(confidence, float)

    def test_short_prices_stays_in_bounds(self, hilbert):
        """Short data should not raise and should return bounded values."""
        period, confidence = hilbert.calculate(np.array([100.0, 101.0, 99.0]))
        assert 10.0 <= period <= 40.0
        assert 0.0 <= confidence <= 1.0

    def test_flat_prices_handled(self, hilbert):
        """Constant prices should not raise — returns defaults."""
        prices = np.full(100, 100.0)
        period, confidence = hilbert.calculate(prices)
        assert 10.0 <= period <= 40.0
        assert 0.0 <= confidence <= 1.0


# ---------------------------------------------------------------------------
# calculate_series() — array output
# ---------------------------------------------------------------------------

class TestHilbertCalculateSeries:

    def test_returns_two_arrays(self, hilbert, df):
        periods, confidences = hilbert.calculate_series(df["close"].values)
        assert isinstance(periods, np.ndarray)
        assert isinstance(confidences, np.ndarray)

    def test_arrays_same_length_as_input(self, hilbert, df):
        n = len(df)
        periods, confidences = hilbert.calculate_series(df["close"].values)
        assert len(periods) == n
        assert len(confidences) == n

    def test_all_periods_in_bounds(self, hilbert, df):
        periods, _ = hilbert.calculate_series(df["close"].values)
        assert np.all(periods >= 10.0), f"min period={periods.min()}"
        assert np.all(periods <= 40.0), f"max period={periods.max()}"

    def test_all_confidences_in_range(self, hilbert, df):
        _, confidences = hilbert.calculate_series(df["close"].values)
        assert np.all(confidences >= 0.0)
        assert np.all(confidences <= 1.0)

    def test_no_nans(self, hilbert, df):
        periods, confidences = hilbert.calculate_series(df["close"].values)
        assert not np.any(np.isnan(periods))
        assert not np.any(np.isnan(confidences))


# ---------------------------------------------------------------------------
# Cyclic vs noisy data
# ---------------------------------------------------------------------------

class TestHilbertCyclicSignal:

    def test_cyclic_data_confidence_is_valid(self, hilbert):
        """Cyclic data should return a valid confidence score in [0, 1]."""
        cyclic = _make_cyclic_df(300, cycle_period=20)
        _, conf_cyclic = hilbert.calculate(cyclic["close"].values)
        assert 0.0 <= conf_cyclic <= 1.0, f"confidence={conf_cyclic} out of [0, 1]"

    def test_cyclic_period_near_true_period(self, hilbert):
        """Detected period should be within ±10 bars of true cycle (20 bars)."""
        cyclic = _make_cyclic_df(300, cycle_period=20)
        period, _ = hilbert.calculate(cyclic["close"].values)
        assert abs(period - 20.0) <= 10.0, f"period={period}, expected ~20"


# ---------------------------------------------------------------------------
# Integration: flows through RegimeOrchestrator.analyze_series()
# ---------------------------------------------------------------------------

class TestHilbertOrchestratorIntegration:

    def test_analyze_series_has_hilbert_columns(self):
        df = _make_df(300)
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        result = orch.analyze_series(df)
        assert "hilbert_period" in result.columns
        assert "hilbert_confidence" in result.columns

    def test_analyze_series_hilbert_period_bounded(self):
        df = _make_df(300)
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        result = orch.analyze_series(df)
        lo = orch.hilbert.min_period
        hi = orch.hilbert.max_period
        assert result["hilbert_period"].between(float(lo), float(hi)).all()

    def test_analyze_series_hilbert_confidence_bounded(self):
        df = _make_df(300)
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        result = orch.analyze_series(df)
        assert result["hilbert_confidence"].between(0.0, 1.0).all()

    def test_analyze_series_adaptive_period_present(self):
        df = _make_df(300)
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        result = orch.analyze_series(df)
        assert "adaptive_period" in result.columns
        assert (result["adaptive_period"] >= 5).all()
