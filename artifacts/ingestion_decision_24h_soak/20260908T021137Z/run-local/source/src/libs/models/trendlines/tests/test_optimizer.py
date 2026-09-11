"""Tests for TrendlinesOptimizer with mock pipeline factory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd
import pytest

from libs.models.trendlines.optimization.models import (
    TrendlinesOptimizationConfig,
    TrendlinesOptimizationResult,
)
from libs.models.trendlines.optimization.optimizer import TrendlinesOptimizer, OPTUNA_AVAILABLE

pytestmark = pytest.mark.skipif(not OPTUNA_AVAILABLE, reason="optuna not installed")


# ---------------------------------------------------------------------------
# Helpers — synthetic data and mock pipeline
# ---------------------------------------------------------------------------

@dataclass
class FakeTrendline:
    slope: float
    intercept: float
    is_support: bool


@dataclass
class FakeFitResult:
    is_valid: bool
    support_lines: list
    resistance_lines: list

    def to_dict(self):
        return {}


def _make_ohlcv(n: int = 4000, base: float = 100.0) -> pd.DataFrame:
    """Generate enough bars for walk-forward CV."""
    rng = np.random.RandomState(42)
    closes = base + np.cumsum(rng.randn(n) * 0.5)
    return pd.DataFrame({
        "open": closes - rng.rand(n) * 0.3,
        "high": closes + rng.rand(n) * 1.0,
        "low": closes - rng.rand(n) * 1.0,
        "close": closes,
        "volume": rng.rand(n) * 1000,
    })


def _mock_pipeline_factory(params: dict, asset: str, timeframe: str):
    """Return a runner that produces deterministic fake results."""
    def run(train_df: pd.DataFrame):
        n = len(train_df)
        median_price = train_df["close"].median()

        # Create lines that survive well (far from price)
        tol = params.get("interaction_tolerance_atr", 0.25)
        support = FakeTrendline(slope=0.0, intercept=median_price - 20, is_support=True)
        resistance = FakeTrendline(slope=0.0, intercept=median_price + 20, is_support=False)

        fit_result = FakeFitResult(
            is_valid=True,
            support_lines=[support],
            resistance_lines=[resistance],
        )
        n_pivots = 30  # In optimal range
        return fit_result, n_pivots

    return run


def _mock_pipeline_factory_invalid(params: dict, asset: str, timeframe: str):
    """Factory that always returns invalid results."""
    def run(train_df):
        return FakeFitResult(is_valid=False, support_lines=[], resistance_lines=[]), 0
    return run


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOptimizerBasic:
    def test_short_optimization(self):
        """Run 3 trials and verify result structure."""
        df = _make_ohlcv(4000)
        config = TrendlinesOptimizationConfig(
            n_trials=3, timeout_seconds=120,
        )
        optimizer = TrendlinesOptimizer(
            config=config,
            pipeline_factory=_mock_pipeline_factory,
        )
        result = optimizer.optimize(df, asset="TEST", timeframe="1h", n_trials=3)

        assert isinstance(result, TrendlinesOptimizationResult)
        assert result.asset == "TEST"
        assert result.timeframe == "1h"
        assert result.n_trials_total == 3
        assert result.best_objective > 0
        assert len(result.all_trials) == 3

    def test_param_bounds_respected(self):
        """Verify sampled params are within configured bounds."""
        df = _make_ohlcv(4000)
        config = TrendlinesOptimizationConfig(
            n_trials=3,
            interaction_tolerance_atr=(0.15, 0.40),
            squeeze_threshold=(2.0, 5.0),
        )
        optimizer = TrendlinesOptimizer(
            config=config,
            pipeline_factory=_mock_pipeline_factory,
        )
        result = optimizer.optimize(df, asset="TEST", timeframe="1h", n_trials=3)

        for trial in result.all_trials:
            ita = trial.params["interaction_tolerance_atr"]
            assert 0.15 <= ita <= 0.40, f"interaction_tolerance_atr {ita} out of bounds"
            sq = trial.params["squeeze_threshold"]
            assert 2.0 <= sq <= 5.0, f"squeeze_threshold {sq} out of bounds"

    def test_categorical_params_present(self):
        """Verify categorical params are in trial params."""
        df = _make_ohlcv(4000)
        config = TrendlinesOptimizationConfig(n_trials=2)
        optimizer = TrendlinesOptimizer(
            config=config,
            pipeline_factory=_mock_pipeline_factory,
        )
        result = optimizer.optimize(df, asset="TEST", timeframe="1h", n_trials=2)

        for trial in result.all_trials:
            assert "left_window" in trial.params
            assert "right_window" in trial.params
            assert "pivot_window" in trial.params
            assert trial.params["left_window"] in [3, 5, 7, 10]

    def test_benchmarks_populated(self):
        """Verify benchmark results are populated."""
        df = _make_ohlcv(4000)
        config = TrendlinesOptimizationConfig(n_trials=2)
        optimizer = TrendlinesOptimizer(
            config=config,
            pipeline_factory=_mock_pipeline_factory,
        )
        result = optimizer.optimize(df, asset="TEST", timeframe="1h", n_trials=2)

        bench = result.best_benchmarks
        assert bench.n_folds > 0
        assert 0.0 <= bench.mean_longevity <= 1.0
        assert 0.0 <= bench.stability_score <= 1.0

    def test_invalid_pipeline_produces_zero(self):
        """Invalid fit results should produce zero scores, not crash."""
        df = _make_ohlcv(4000)
        config = TrendlinesOptimizationConfig(n_trials=2)
        optimizer = TrendlinesOptimizer(
            config=config,
            pipeline_factory=_mock_pipeline_factory_invalid,
        )
        result = optimizer.optimize(df, asset="TEST", timeframe="1h", n_trials=2)
        assert result.n_trials_total == 2
        # All trials should have 0.0 objective since pipeline is invalid
        for trial in result.all_trials:
            assert trial.objective_value == 0.0

    def test_gate_filtering_counted(self):
        """Verify n_trials_passed_gate is tracked."""
        df = _make_ohlcv(4000)
        config = TrendlinesOptimizationConfig(n_trials=3)
        optimizer = TrendlinesOptimizer(
            config=config,
            pipeline_factory=_mock_pipeline_factory,
        )
        result = optimizer.optimize(df, asset="TEST", timeframe="1h", n_trials=3)
        assert result.n_trials_passed_gate >= 0
        assert result.n_trials_passed_gate <= result.n_trials_total


class TestOptimizerSamplers:
    def test_random_sampler(self):
        df = _make_ohlcv(4000)
        config = TrendlinesOptimizationConfig(n_trials=2, sampler="random")
        optimizer = TrendlinesOptimizer(
            config=config,
            pipeline_factory=_mock_pipeline_factory,
        )
        result = optimizer.optimize(df, asset="TEST", timeframe="1h", n_trials=2)
        assert result.n_trials_total == 2

    def test_tpe_sampler(self):
        df = _make_ohlcv(4000)
        config = TrendlinesOptimizationConfig(n_trials=2, sampler="tpe")
        optimizer = TrendlinesOptimizer(
            config=config,
            pipeline_factory=_mock_pipeline_factory,
        )
        result = optimizer.optimize(df, asset="TEST", timeframe="1h", n_trials=2)
        assert result.n_trials_total == 2
