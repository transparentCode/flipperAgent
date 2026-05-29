"""Phase 7 tests: Optimization foundation — V2 models, 2-way walk-forward, V2 search space."""

import json
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from app.regression.config.schema import (
    OrchestratorConfig,
    OptimizationTier,
)
from app.regression.optimization.models import (
    RegressionBenchmarkResults,
    RegressionOptimizationConfig,
    RegressionOptimizationResult,
    RegressionTrialResult,
)
from app.regression.optimization.walk_forward_2way import (
    WalkForwardSplit,
    WalkForwardValidator,
)
from app.regression.optimization.search_space import (
    ParamSpec,
    SearchSpaceBuilder,
)


# ═══════════════════════════════════════════════════════════════════════
# Walk-Forward Validator (2-way — retained for SR compatibility)
# ═══════════════════════════════════════════════════════════════════════


class TestWalkForwardSplit:
    """Test WalkForwardSplit dataclass."""

    def test_train_size(self):
        s = WalkForwardSplit(fold_id=0, train_start=0, train_end=100, test_start=110, test_end=200)
        assert s.train_size == 100

    def test_test_size(self):
        s = WalkForwardSplit(fold_id=0, train_start=0, train_end=100, test_start=110, test_end=200)
        assert s.test_size == 90


class TestWalkForwardValidator:
    """Test walk-forward cross-validation splits."""

    def test_default_params(self):
        wf = WalkForwardValidator()
        assert wf.train_bars == 4320
        assert wf.test_bars == 720
        assert wf.step_bars == 720
        assert wf.purge_bars == 24
        assert wf.min_train_bars == 2160

    def test_n_folds_basic(self):
        wf = WalkForwardValidator(train_bars=100, test_bars=50, step_bars=50, purge_bars=10, min_train_bars=50)
        assert wf.n_folds(200) >= 1

    def test_n_folds_insufficient_data(self):
        wf = WalkForwardValidator(train_bars=100, test_bars=50, step_bars=50, purge_bars=10, min_train_bars=50)
        with pytest.raises(ValueError, match="Insufficient data for walk-forward validation"):
            wf.n_folds(90)

    def test_splits_no_overlap(self):
        """Train and test windows must not overlap, purge gap respected."""
        wf = WalkForwardValidator(train_bars=100, test_bars=50, step_bars=50, purge_bars=10, min_train_bars=50)
        splits = wf.get_splits(500)
        assert len(splits) > 0
        for s in splits:
            assert s.test_start >= s.train_end + wf.purge_bars
            assert s.train_end <= s.test_start
            assert s.train_start >= 0
            assert s.test_end <= 500

    def test_splits_sequential(self):
        """Folds should step forward."""
        wf = WalkForwardValidator(train_bars=100, test_bars=50, step_bars=50, purge_bars=10, min_train_bars=50)
        splits = wf.get_splits(500)
        for i in range(1, len(splits)):
            assert splits[i].train_start > splits[i - 1].train_start

    def test_iterate_splits_yields_dataframes(self):
        wf = WalkForwardValidator(train_bars=100, test_bars=50, step_bars=50, purge_bars=5, min_train_bars=50)
        df = pd.DataFrame({"close": np.random.randn(300)})
        folds = list(wf.iterate_splits(df))
        assert len(folds) > 0
        for split, train_df, test_df in folds:
            assert len(train_df) == split.train_size
            assert len(test_df) == split.test_size

    def test_expanding_window(self):
        """Expanding splits always start at 0."""
        wf = WalkForwardValidator(train_bars=100, test_bars=50, step_bars=50, purge_bars=10, min_train_bars=50)
        splits = wf.expanding_window_splits(500)
        assert len(splits) > 0
        for s in splits:
            assert s.train_start == 0

    def test_fold_count_matches_get_splits(self):
        wf = WalkForwardValidator(train_bars=100, test_bars=50, step_bars=50, purge_bars=10, min_train_bars=50)
        n = 1000
        assert wf.n_folds(n) == len(wf.get_splits(n))


# ═══════════════════════════════════════════════════════════════════════
# Models — Serialization (V2)
# ═══════════════════════════════════════════════════════════════════════


class TestBenchmarkResults:
    """Test RegressionBenchmarkResults round-trip."""

    def test_to_dict_from_dict_roundtrip(self):
        br = RegressionBenchmarkResults(
            direction_accuracy_4bar=0.65,
            direction_accuracy_12bar=0.60,
            direction_accuracy_24bar=0.55,
            weighted_direction_score=0.61,
            band_coverage_pct=0.92,
            band_width_stability=0.35,
            durbin_watson=1.5,
            passed_residual_gate=True,
            confidence_return_spearman=0.12,
            passed_confidence_constraint=True,
            confidence_sharpe=1.2,
            bah_sharpe=0.5,
            sharpe_improvement=0.7,
            computation_time_ms=42.5,
            n_bars=720,
            n_valid_results=700,
        )
        d = br.to_dict()
        restored = RegressionBenchmarkResults.from_dict(d)
        assert restored.direction_accuracy_4bar == br.direction_accuracy_4bar
        assert restored.passed_residual_gate is True
        assert restored.n_bars == 720

    def test_from_dict_ignores_extra_keys(self):
        d = {"direction_accuracy_4bar": 0.5, "unknown_key": 99}
        br = RegressionBenchmarkResults.from_dict(d)
        assert br.direction_accuracy_4bar == 0.5

    def test_numpy_scalar_serialization(self):
        """Numpy scalars should be cast to Python natives."""
        br = RegressionBenchmarkResults(
            direction_accuracy_4bar=np.float64(0.75),
            passed_residual_gate=np.bool_(True),
            n_bars=np.int64(500),
        )
        d = br.to_dict()
        assert isinstance(d["direction_accuracy_4bar"], float)
        assert isinstance(d["passed_residual_gate"], bool)
        assert isinstance(d["n_bars"], int)


class TestOptimizationConfig:
    """Test V2 optimization config serialization."""

    def test_to_dict_from_dict(self):
        cfg = RegressionOptimizationConfig(
            n_trials=50,
            optimization_tier="per_tf",
        )
        d = cfg.to_dict()
        restored = RegressionOptimizationConfig.from_dict(d)
        assert restored.n_trials == 50
        assert restored.optimization_tier == "per_tf"

    def test_param_bounds_preserved(self):
        cfg = RegressionOptimizationConfig(
            param_bounds={"custom_param": (0.1, 0.9)}
        )
        d = cfg.to_dict()
        restored = RegressionOptimizationConfig.from_dict(d)
        assert "custom_param" in restored.param_bounds
        assert restored.param_bounds["custom_param"] == (0.1, 0.9)


class TestTrialResult:
    """Test V2 trial result serialization."""

    def test_to_dict_from_dict(self):
        tr = RegressionTrialResult(
            trial_id=5,
            params={"window_size": 100, "band_multiplier": 2.0},
            objective_values=(0.62, 0.85, 0.35),
            benchmark_results=RegressionBenchmarkResults(weighted_direction_score=0.6),
            passed_gate=True,
            passed_constraint=True,
            fold_results=[RegressionBenchmarkResults(n_bars=100)],
        )
        d = tr.to_dict()
        restored = RegressionTrialResult.from_dict(d)
        assert restored.trial_id == 5
        assert restored.params["window_size"] == 100
        assert restored.objective_values == (0.62, 0.85, 0.35)
        assert len(restored.fold_results) == 1


class TestOptimizationResult:
    """Test V2 optimization result save/load."""

    def test_save_load_roundtrip(self, tmp_path):
        results_dir = tmp_path / "results"
        results_dir.mkdir()
        path = str(results_dir / "test_result.json")

        result = RegressionOptimizationResult(
            asset="BTCUSDT",
            timeframe="1h",
            best_params={"window_size": 120},
            best_objective_values=(0.62, 0.85, 0.35),
            best_benchmarks=RegressionBenchmarkResults(weighted_direction_score=0.7),
            pareto_candidates=[],
            n_trials_passed_gate=80,
            n_trials_total=100,
            total_time_seconds=60.0,
            config=RegressionOptimizationConfig(n_trials=100),
        )
        # Monkey-patch _RESULTS_DIR for test
        import app.regression.optimization.models as models_mod
        orig_dir = models_mod._RESULTS_DIR
        models_mod._RESULTS_DIR = str(results_dir)
        try:
            result.save(path)
            loaded = RegressionOptimizationResult.load(path)
            assert loaded.asset == "BTCUSDT"
            assert loaded.best_params["window_size"] == 120
            assert loaded.best_objective_values == (0.62, 0.85, 0.35)
        finally:
            models_mod._RESULTS_DIR = orig_dir

    def test_save_path_validation(self, tmp_path):
        result = RegressionOptimizationResult(
            asset="BTCUSDT",
            timeframe="1h",
            best_params={},
            best_objective_values=(0.0, 0.0, 0.0),
            best_benchmarks=RegressionBenchmarkResults(),
            pareto_candidates=[],
            n_trials_passed_gate=0,
            n_trials_total=0,
            total_time_seconds=0.0,
            config=RegressionOptimizationConfig(),
        )
        with pytest.raises(ValueError, match="Save path must be under"):
            result.save("/tmp/evil_path.json")


# ═══════════════════════════════════════════════════════════════════════
# Search Space Builder (V2)
# ═══════════════════════════════════════════════════════════════════════


class TestSearchSpaceBuilder:
    """Test tier-aware search space building."""

    def _make_orch_config(self) -> OrchestratorConfig:
        return OrchestratorConfig(
            optimization={
                "global_tunable": [
                    "trend_atr_fraction",
                    "spread_atr_fraction",
                    "momentum_atr_fraction",
                    "neutral_slope_atr_fraction",
                    "band_multiplier",
                ],
                "per_tf_tunable": [
                    "window_size",
                    "slope_acceleration_alpha",
                ],
                "per_asset_tunable": [
                    "window_size",
                ],
            }
        )

    def test_global_tier_params(self):
        builder = SearchSpaceBuilder()
        specs = builder.build(self._make_orch_config(), OptimizationTier.GLOBAL)
        names = [s.name for s in specs]
        assert "trend_atr_fraction" in names
        assert "spread_atr_fraction" in names
        assert "band_multiplier" in names
        assert "window_size" not in names

    def test_per_tf_tier_params(self):
        builder = SearchSpaceBuilder()
        specs = builder.build(self._make_orch_config(), OptimizationTier.PER_TF)
        names = [s.name for s in specs]
        assert "window_size" in names
        ws = next(s for s in specs if s.name == "window_size")
        assert ws.param_type == "int"

    def test_per_asset_tier_params(self):
        builder = SearchSpaceBuilder()
        specs = builder.build(self._make_orch_config(), OptimizationTier.PER_ASSET)
        names = [s.name for s in specs]
        assert "window_size" in names

    def test_custom_bounds_override(self):
        builder = SearchSpaceBuilder()
        custom_cfg = RegressionOptimizationConfig(
            param_bounds={"window_size": (50, 150), "trend_atr_fraction": (0.01, 0.30)}
        )
        specs = builder.build(
            self._make_orch_config(), OptimizationTier.GLOBAL, opt_config=custom_cfg,
        )
        taf = next(s for s in specs if s.name == "trend_atr_fraction")
        assert taf.low == 0.01
        assert taf.high == 0.30

    def test_build_all_tiers(self):
        builder = SearchSpaceBuilder()
        orch = self._make_orch_config()
        global_specs = builder.build(orch, OptimizationTier.GLOBAL)
        per_tf_specs = builder.build(orch, OptimizationTier.PER_TF)
        assert len(global_specs) > 0
        assert len(per_tf_specs) > 0

    def test_unknown_param_skipped(self):
        """Params not in bounds should raise ValueError."""
        orch = OrchestratorConfig(
            optimization={"global_tunable": ["nonexistent_param"]}
        )
        builder = SearchSpaceBuilder()
        with pytest.raises(ValueError, match="No optimization bounds defined"):
            builder.build(orch, OptimizationTier.GLOBAL)

    def test_sample_params_with_mock_trial(self):
        """Test param sampling with a mock Optuna trial."""
        specs = [
            ParamSpec(name="window_size", param_type="int", low=30, high=200),
            ParamSpec(name="band_multiplier", param_type="float", low=1.5, high=3.0),
        ]

        class MockTrial:
            def __init__(self):
                self._values = {}

            def suggest_int(self, name, low, high, step=1):
                self._values[name] = (low + high) // 2
                return self._values[name]

            def suggest_float(self, name, low, high, step=None):
                self._values[name] = (low + high) / 2.0
                return self._values[name]

        trial = MockTrial()
        params = SearchSpaceBuilder.sample_params(trial, specs)
        assert params["window_size"] == 115
        assert params["band_multiplier"] == 2.25


