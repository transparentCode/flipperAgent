"""Phase 7 tests: Optimization integration — V2 MOTPE optimizer + API facade."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.regression.contracts.result import (
    DegradationLevel,
    EnsembleResult,
    RegressionResult,
)
from app.regression.optimization.models import (
    RegressionBenchmarkResults,
    RegressionOptimizationConfig,
)
from app.regression.config.schema import OrchestratorConfig


def _passing_benchmarks(**overrides) -> RegressionBenchmarkResults:
    """Return a RegressionBenchmarkResults that passes all gates/constraints."""
    defaults = dict(
        direction_accuracy_4bar=0.60,
        direction_accuracy_12bar=0.58,
        direction_accuracy_24bar=0.55,
        weighted_direction_score=0.58,
        band_coverage_pct=0.80,
        band_width_stability=0.85,
        confidence_sharpe=0.50,
        bah_sharpe=0.20,
        sharpe_improvement=0.30,
        max_drawdown=0.05,
        durbin_watson=2.0,
        passed_residual_gate=True,
        confidence_return_spearman=0.15,
        passed_confidence_constraint=True,
        computation_time_ms=50.0,
        n_bars=500,
        n_valid_results=400,
        turnover_rate=0.05,
    )
    defaults.update(overrides)
    return RegressionBenchmarkResults(**defaults)


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════


def _make_ohlcv(n: int = 6000) -> pd.DataFrame:
    """Generate synthetic OHLCV data large enough for walk-forward."""
    rng = np.random.RandomState(42)
    returns = 0.001 + 0.01 * rng.randn(n - 1)
    close = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)]))
    high = close * (1.0 + 0.005 * np.abs(rng.randn(n)))
    low = close * (1.0 - 0.005 * np.abs(rng.randn(n)))
    open_ = close * (1.0 + 0.002 * rng.randn(n))
    volume = 1000 + 500 * np.abs(rng.randn(n))
    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def _make_result(
    idx: int, close: float, window_used: int = 50,
    direction: str = "BULLISH", confidence: float = 0.70,
) -> RegressionResult:
    """Create minimal synthetic result at a bar index."""
    return RegressionResult(
        asset="TEST",
        timeframe="1h",
        timestamp=datetime(2025, 1, 1),
        config_hash="test",
        slope=0.01,
        direction=direction,
        confidence=confidence,
        upper_band=np.array([close * 1.03]),
        lower_band=np.array([close * 0.97]),
        mid_line=np.array([close]),
        band_width_avg=close * 0.06,
        atr_norm=0.02,
        z_score=0.0,
        method_outputs={},
        method_weights={},
        ensemble_result=EnsembleResult(center=close),
        window_used=window_used,
        bars_since_init=idx - window_used + 1,
    )


def _mock_pipeline_factory(params, asset, timeframe):
    """Return a mock pipeline + config that produces synthetic results."""

    class MockConfig:
        config_hash = "mock_hash"

    class MockPipeline:
        def __init__(self):
            self.computed = False

        def compute_series(self, request):
            df = request.df
            closes = df["close"].values
            window = int(params.get("window_size", 50))
            results = []
            for i in range(window, len(closes)):
                d = "BULLISH" if closes[i] > closes[max(0, i - 10)] else "BEARISH"
                results.append(_make_result(
                    i, closes[i], window_used=window,
                    direction=d, confidence=float(np.clip(0.6 + 0.2 * abs(np.random.randn()), 0.0, 1.0)),
                ))
            return results

    return MockPipeline(), MockConfig()


# ═══════════════════════════════════════════════════════════════════════
# V2 MOTPE Optimizer Integration
# ═══════════════════════════════════════════════════════════════════════


class TestRegressionMOTPEOptimizer:
    """Integration tests using a mock pipeline factory with V2 optimizer."""

    @pytest.fixture
    def optimizer(self):
        from app.regression.optimization.optimizer import RegressionMOTPEOptimizer

        config = RegressionOptimizationConfig(
            param_bounds={
                "window_size": (30, 100),
                "band_multiplier": (1.5, 3.0),
            },
            param_types={"window_size": "int", "band_multiplier": "float"},
            n_trials=3,
            timeout_seconds=60,
            train_bars=500,
            validate_bars=200,
            test_bars=200,
            step_bars=200,
            purge_bars=10,
            min_train_bars=300,
        )
        orch_config = OrchestratorConfig()
        opt = RegressionMOTPEOptimizer(
            config=config,
            orch_config=orch_config,
            pipeline_factory=_mock_pipeline_factory,
        )
        return opt

    def _run(self, optimizer, df, asset="TEST", timeframe="1h"):
        """Run optimize with _compute_benchmarks patched to return passing results."""
        with patch.object(
            optimizer,
            "_compute_benchmarks",
            side_effect=lambda results, closes, elapsed_ms, bars_per_year: _passing_benchmarks(
                weighted_direction_score=0.55 + 0.1 * np.random.rand(),
                confidence_sharpe=0.3 + 0.4 * np.random.rand(),
                band_coverage_pct=0.75 + 0.1 * np.random.rand(),
            ),
        ):
            return optimizer.optimize(df, asset=asset, timeframe=timeframe)

    def test_optimize_runs_to_completion(self, optimizer):
        df = _make_ohlcv(2000)
        result = self._run(optimizer, df, asset="BTCUSDT")
        assert result.asset == "BTCUSDT"
        assert result.timeframe == "1h"
        assert result.n_trials_total == 3
        assert len(result.best_objective_values) > 0
        assert "window_size" in result.best_params or "band_multiplier" in result.best_params

    def test_all_trials_recorded(self, optimizer):
        df = _make_ohlcv(2000)
        result = self._run(optimizer, df)
        assert len(result.all_trials) == 3
        for trial in result.all_trials:
            assert isinstance(trial.benchmark_results, RegressionBenchmarkResults)

    def test_params_within_bounds(self, optimizer):
        df = _make_ohlcv(2000)
        result = self._run(optimizer, df)
        for trial in result.all_trials:
            if "window_size" in trial.params:
                assert 30 <= trial.params["window_size"] <= 100
            if "band_multiplier" in trial.params:
                assert 1.5 <= trial.params["band_multiplier"] <= 3.0

    def test_fold_results_populated(self, optimizer):
        df = _make_ohlcv(2000)
        result = self._run(optimizer, df)
        for trial in result.all_trials:
            assert len(trial.fold_results) > 0

    def test_derived_thresholds_present(self, optimizer):
        df = _make_ohlcv(2000)
        result = self._run(optimizer, df)
        assert result.derived_thresholds is not None
        assert "min_direction_floor" in result.derived_thresholds


# ═══════════════════════════════════════════════════════════════════════
# API Facade
# ═══════════════════════════════════════════════════════════════════════


class TestOptimizeRegressionFacade:
    """Test the optimize_regression() facade in api.py."""

    def test_facade_import(self):
        from app.regression.api import optimize_regression
        assert callable(optimize_regression)

    def test_compat_reexport_import(self):
        from app.regression.compat import optimize_regression
        assert callable(optimize_regression)
