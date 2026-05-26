"""Tests for libs/portfolio/benchmark.py — alpha, beta, correlation, IR."""

import math

import pytest

from libs.contracts.schemas import BenchmarkComparison
from libs.portfolio.benchmark import (
    build_benchmark_returns,
    compute_benchmark_comparison,
)


# ---------------------------------------------------------------------------
# compute_benchmark_comparison
# ---------------------------------------------------------------------------

class TestComputeBenchmarkComparison:
    def test_insufficient_data(self):
        result = compute_benchmark_comparison([], [], 8760)
        assert isinstance(result, BenchmarkComparison)
        assert result.alpha == 0.0
        assert result.beta == 0.0

    def test_single_point(self):
        result = compute_benchmark_comparison([0.01], [0.02], 8760)
        assert result.alpha == 0.0

    def test_perfectly_correlated(self):
        """Strategy = benchmark => beta=1, alpha=0, correlation=1."""
        returns = [0.01, -0.005, 0.02, -0.01, 0.015]
        result = compute_benchmark_comparison(returns, returns, 8760, risk_free_rate=0.0)
        assert result.beta == pytest.approx(1.0)
        assert result.alpha == pytest.approx(0.0, abs=1e-6)
        assert result.correlation == pytest.approx(1.0)
        assert result.tracking_error == pytest.approx(0.0, abs=1e-6)

    def test_uncorrelated(self):
        """Orthogonal returns should give low correlation."""
        s = [0.01, -0.01, 0.01, -0.01, 0.01]
        b = [0.01, 0.01, -0.01, -0.01, 0.01]
        result = compute_benchmark_comparison(s, b, 8760)
        # Not perfectly correlated
        assert abs(result.correlation) < 1.0

    def test_outperformance_gives_positive_alpha(self):
        """Strategy consistently beats benchmark => positive alpha."""
        s = [0.02, 0.03, 0.025, 0.02, 0.03]
        b = [0.01, 0.01, 0.01, 0.01, 0.01]
        result = compute_benchmark_comparison(s, b, 8760)
        assert result.alpha > 0

    def test_underperformance_gives_negative_alpha(self):
        s = [0.001, 0.002, 0.001, 0.001, 0.002]
        b = [0.02, 0.03, 0.025, 0.02, 0.03]
        result = compute_benchmark_comparison(s, b, 8760)
        assert result.alpha < 0

    def test_strategy_return_pct(self):
        """Total return should compound log returns."""
        s = [0.01, 0.02]
        b = [0.005, 0.01]
        result = compute_benchmark_comparison(s, b, 8760)
        expected_s = (math.exp(0.01 + 0.02) - 1) * 100
        assert result.strategy_return_pct == pytest.approx(expected_s)

    def test_different_lengths_uses_min(self):
        """Should use min(len(s), len(b))."""
        s = [0.01, 0.02, 0.03]
        b = [0.005, 0.01]
        result = compute_benchmark_comparison(s, b, 8760)
        # Should compute using only 2 points
        assert isinstance(result, BenchmarkComparison)

    def test_information_ratio(self):
        s = [0.02, 0.03, 0.025, 0.02, 0.03]
        b = [0.01, 0.01, 0.01, 0.01, 0.01]
        result = compute_benchmark_comparison(s, b, 8760)
        assert result.information_ratio != 0.0
        assert math.isfinite(result.information_ratio)


# ---------------------------------------------------------------------------
# build_benchmark_returns
# ---------------------------------------------------------------------------

class TestBuildBenchmarkReturns:
    def test_empty(self):
        assert build_benchmark_returns([]) == []

    def test_single_price(self):
        assert build_benchmark_returns([(0, 100)]) == []

    def test_basic(self):
        prices = [(0, 100), (3600, 110), (7200, 121)]
        returns = build_benchmark_returns(prices, interval_seconds=3600)
        assert len(returns) == 2
        assert returns[0] == pytest.approx(math.log(110 / 100))
        assert returns[1] == pytest.approx(math.log(121 / 110))

    def test_forward_fill(self):
        """Gaps in prices should be filled."""
        prices = [(0, 100), (7200, 120)]
        returns = build_benchmark_returns(prices, interval_seconds=3600)
        assert len(returns) == 2
        # First return: 100->100 (forward-filled) = 0
        assert returns[0] == pytest.approx(0.0)
        # Second return: 100->120
        assert returns[1] == pytest.approx(math.log(120 / 100))

    def test_unsorted_input(self):
        prices = [(7200, 121), (0, 100), (3600, 110)]
        returns = build_benchmark_returns(prices, interval_seconds=3600)
        assert len(returns) == 2

    def test_zero_interval(self):
        assert build_benchmark_returns([(0, 100), (1, 110)], interval_seconds=0) == []

    def test_zero_price_handled(self):
        """Zero price should produce zero return."""
        prices = [(0, 0), (3600, 100)]
        returns = build_benchmark_returns(prices, interval_seconds=3600)
        assert returns[0] == 0.0
