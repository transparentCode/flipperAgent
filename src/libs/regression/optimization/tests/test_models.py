"""Tests for optimization models: config round-trip, benchmark dataclass, result serialization."""
import json
import os
import tempfile

import pytest

from app.regression.optimization.constants import (
    DEFAULT_N_TRIALS,
    DEFAULT_PARAM_BOUNDS,
    DEFAULT_SEED,
    BARS_PER_YEAR,
    EPSILON,
)
from app.regression.optimization.models import (
    MOTPEConfig,
    RegressionBenchmarkResults,
    RegressionOptimizationConfig,
    RegressionOptimizationResult,
    RegressionTrialResult,
)


class TestMOTPEConfig:
    def test_defaults(self):
        cfg = MOTPEConfig()
        assert cfg.objectives == ["weighted_direction_score", "band_coverage_pct", "confidence_sharpe"]
        assert cfg.meta_filter_metric == "max_drawdown"
        assert len(cfg.objectives) <= 3

    def test_max_length_enforced(self):
        with pytest.raises(Exception):
            MOTPEConfig(objectives=["a", "b", "c", "d"])


class TestRegressionOptimizationConfig:
    def test_defaults(self):
        cfg = RegressionOptimizationConfig()
        assert cfg.n_trials == 200
        assert cfg.optimization_tier == "full"
        assert cfg.worst_case_percentile == 10
        assert cfg.min_valid_results == 20
        assert cfg.max_train_ratio == 0.6
        assert cfg.max_failed_folds == 10
        assert cfg.seed == 42
        assert cfg.expanding_window is False
        assert "window_size" in cfg.param_bounds
        assert "slope_acceleration_alpha" in cfg.param_bounds
        assert "methods.theil_sen.weight" in cfg.param_bounds
        assert len(cfg.param_bounds) == 9

    def test_round_trip(self):
        cfg = RegressionOptimizationConfig(
            n_trials=150,
            worst_case_percentile=15,
            max_failed_folds=1,
            optimization_tier="global",
        )
        d = cfg.to_dict()
        cfg2 = RegressionOptimizationConfig.from_dict(d)
        assert cfg2.n_trials == 150
        assert cfg2.worst_case_percentile == 15
        assert cfg2.max_failed_folds == 1
        assert cfg2.optimization_tier == "global"
        assert cfg2.motpe.meta_filter_metric == "max_drawdown"
        assert cfg2.train_bars == 4320
        assert cfg2.purge_bars == 24

    def test_to_dict_completeness(self):
        cfg = RegressionOptimizationConfig()
        d = cfg.to_dict()
        expected_keys = {
            "param_bounds", "param_types", "n_trials", "timeout_seconds",
            "n_jobs", "seed", "motpe", "min_durbin_watson", "min_confidence_rho",
            "train_bars", "validate_bars", "test_bars", "step_bars",
            "purge_bars", "min_train_bars", "direction_horizons",
            "direction_horizon_weights", "worst_case_percentile",
            "min_valid_results", "max_train_ratio", "max_failed_folds",
            "optimization_tier", "expanding_window",
        }
        assert set(d.keys()) == expected_keys


class TestRegressionBenchmarkResults:
    def test_round_trip(self):
        bench = RegressionBenchmarkResults(
            weighted_direction_score=0.65,
            band_coverage_pct=0.92,
            confidence_sharpe=1.5,
            max_drawdown=0.12,
            passed_residual_gate=True,
            passed_confidence_constraint=True,
        )
        d = bench.to_dict()
        bench2 = RegressionBenchmarkResults.from_dict(d)
        assert bench2.weighted_direction_score == 0.65
        assert bench2.max_drawdown == 0.12
        assert bench2.passed_residual_gate is True

    def test_meta_filter_field_exists(self):
        """Ensure the meta_filter_metric default maps to a real field."""
        cfg = MOTPEConfig()
        bench = RegressionBenchmarkResults()
        assert hasattr(bench, cfg.meta_filter_metric)


class TestRegressionTrialResult:
    def test_round_trip(self):
        bench = RegressionBenchmarkResults(confidence_sharpe=1.2)
        trial = RegressionTrialResult(
            trial_id=42,
            params={"window_size": 100},
            objective_values=(0.6, 0.9, 1.2),
            benchmark_results=bench,
            passed_gate=True,
            passed_constraint=True,
        )
        d = trial.to_dict()
        trial2 = RegressionTrialResult.from_dict(d)
        assert trial2.trial_id == 42
        assert trial2.objective_values == (0.6, 0.9, 1.2)
        assert trial2.params["window_size"] == 100


class TestRegressionOptimizationResultSaveLoad:
    def test_save_load_round_trip(self):
        bench = RegressionBenchmarkResults(
            weighted_direction_score=0.65,
            band_coverage_pct=0.92,
            confidence_sharpe=1.5,
            max_drawdown=0.12,
        )
        trial = RegressionTrialResult(
            trial_id=1,
            params={"window_size": 120},
            objective_values=(0.65, 0.92, 1.5),
            benchmark_results=bench,
            passed_gate=True,
            passed_constraint=True,
            fold_results=[bench],
        )
        result = RegressionOptimizationResult(
            asset="BTCUSDT",
            timeframe="1h",
            best_params={"window_size": 120},
            best_objective_values=(0.65, 0.92, 1.5),
            best_benchmarks=bench,
            pareto_candidates=[{"trial_id": 1}],
            n_trials_passed_gate=50,
            n_trials_total=200,
            total_time_seconds=123.45,
            config=RegressionOptimizationConfig(),
            all_trials=[trial],
        )

        # Save to the valid results dir
        results_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "results",
        )
        os.makedirs(results_dir, exist_ok=True)
        path = os.path.join(results_dir, "_test_round_trip.json")

        try:
            result.save(path)
            loaded = RegressionOptimizationResult.load(path)

            assert loaded.asset == "BTCUSDT"
            assert loaded.timeframe == "1h"
            assert loaded.best_params == {"window_size": 120}
            assert loaded.best_objective_values == (0.65, 0.92, 1.5)
            assert loaded.best_benchmarks.max_drawdown == 0.12
            assert loaded.n_trials_total == 200
            assert loaded.config.n_trials == 200
            assert len(loaded.all_trials) == 1
            assert loaded.all_trials[0].trial_id == 1
            assert loaded.all_trials[0].fold_results[0].max_drawdown == 0.12
        finally:
            if os.path.exists(path):
                os.remove(path)


class TestConstants:
    def test_bars_per_year_has_common_timeframes(self):
        for tf in ["1m", "5m", "15m", "1h", "4h", "1d"]:
            assert tf in BARS_PER_YEAR

    def test_default_param_bounds_complete(self):
        assert len(DEFAULT_PARAM_BOUNDS) == 9
        assert "window_size" in DEFAULT_PARAM_BOUNDS
        assert "methods.vwr.weight" in DEFAULT_PARAM_BOUNDS

    def test_epsilon_positive(self):
        assert EPSILON > 0
        assert EPSILON < 1e-5

    def test_defaults_match_config(self):
        cfg = RegressionOptimizationConfig()
        assert cfg.n_trials == DEFAULT_N_TRIALS
        assert cfg.seed == DEFAULT_SEED


class TestYAMLLoading:
    def test_from_yaml(self, tmp_path):
        yaml_content = """
optimization:
  n_trials: 100
  seed: 99
  expanding_window: true
  param_bounds:
    window_size: [50, 150]
"""
        yaml_file = tmp_path / "test_config.yaml"
        yaml_file.write_text(yaml_content)
        cfg = RegressionOptimizationConfig.from_yaml(str(yaml_file))
        assert cfg.n_trials == 100
        assert cfg.seed == 99
        assert cfg.expanding_window is True
        assert cfg.param_bounds["window_size"] == (50, 150)

    def test_from_yaml_defaults(self, tmp_path):
        yaml_content = """
optimization:
  n_trials: 300
"""
        yaml_file = tmp_path / "minimal.yaml"
        yaml_file.write_text(yaml_content)
        cfg = RegressionOptimizationConfig.from_yaml(str(yaml_file))
        assert cfg.n_trials == 300
        assert cfg.seed == DEFAULT_SEED  # Default
        assert cfg.expanding_window is False


class TestMetaFilterValidation:
    def test_valid_metric(self):
        from app.regression.optimization.meta_filter import MetaFilterSelector
        selector = MetaFilterSelector(metric="max_drawdown", minimize=True)
        assert selector.metric == "max_drawdown"

    def test_invalid_metric_raises(self):
        from app.regression.optimization.meta_filter import MetaFilterSelector
        with pytest.raises(ValueError, match="Invalid meta_filter_metric"):
            MetaFilterSelector(metric="max_drawdwon")  # typo


class TestExpandingWindow:
    def test_expanding_round_trip(self):
        cfg = RegressionOptimizationConfig(expanding_window=True)
        d = cfg.to_dict()
        cfg2 = RegressionOptimizationConfig.from_dict(d)
        assert cfg2.expanding_window is True

    def test_seed_round_trip(self):
        cfg = RegressionOptimizationConfig(seed=123)
        d = cfg.to_dict()
        cfg2 = RegressionOptimizationConfig.from_dict(d)
        assert cfg2.seed == 123
