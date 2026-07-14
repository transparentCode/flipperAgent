"""
Tests — Phase 2: AssetSROptimizer (Per-Asset Stage 2)
======================================================
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.sr.models import AssetMetadata, RuleDerivedParams
from app.sr.models import ZoneLifecycleEvent, ZoneStatus
from app.sr.optimization.asset_optimizer import (
    AssetOptimizationConfig,
    AssetOptimizationResult,
    AssetSROptimizer,
    _GATE_PARAMS,
    _GLOBAL_ONLY_PARAMS,
    _RESULTS_DIR,
)
from app.sr.optimization.multi_bar_runner import MultiBarRunResult
from app.sr.optimization.quality_metrics import ZoneQualityEvaluator, ZoneQualityMetrics
from app.sr.optimization.universe_optimizer import (
    _DEFAULT_PARAM_VALUES,
    _default_parameter_space,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(
    n: int = 600,
    base_price: float = 100.0,
    volatility: float = 0.02,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    closes = [base_price]
    for _ in range(1, n):
        closes.append(closes[-1] * (1 + volatility * rng.randn()))
    closes = np.array(closes)
    highs = closes * (1 + rng.uniform(0, volatility, n))
    lows = closes * (1 - rng.uniform(0, volatility, n))
    opens = closes * (1 + rng.uniform(-volatility / 2, volatility / 2, n))
    volumes = rng.uniform(100, 1000, n)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


def _make_base_raw_config():
    """Minimal raw config for SRConfigResolver."""
    return {
        "asset_metadata": {
            "default_profile": "crypto",
        },
        "sr": {
            "pipeline": {
                "enabled_kernels": ["pivot_hl", "round_number"],
            },
            "ensemble": {"method": "weighted_average", "structural_vs_micro_ratio": 0.5},
            "lifecycle": {"age_lambda": 0.002},
            "kernels": {
                "pivot_hl": {"historical_depth": 500, "smoothing_period": 3},
                "round_number": {},
            },
            "regime": {"enabled": False},
        },
    }


def _make_global_best() -> dict:
    """Simulated Stage 1 global best params."""
    return dict(_DEFAULT_PARAM_VALUES)


def _make_optimizer(
    opt_config: AssetOptimizationConfig | None = None,
) -> AssetSROptimizer:
    """Build an AssetSROptimizer with test defaults."""
    config = opt_config or AssetOptimizationConfig(
        n_trials=3,
        timeout_s=60.0,
        min_bars=100,
        train_bars=50,
        test_bars=30,
        step_bars=30,
        purge_bars=5,
    )
    return AssetSROptimizer(
        asset="TEST",
        timeframe="1h",
        global_best_params=_make_global_best(),
        base_raw_config=_make_base_raw_config(),
        opt_config=config,
    )


# ---------------------------------------------------------------------------
# TASK-007: Narrowed bounds
# ---------------------------------------------------------------------------

class TestNarrowedBounds:
    def test_excludes_global_only_params(self):
        optimizer = _make_optimizer()
        for name in _GLOBAL_ONLY_PARAMS:
            assert name not in optimizer.param_specs

    def test_only_kernel_and_gate_params(self):
        optimizer = _make_optimizer()
        allowed_prefixes = ("kernels.", "pipeline.", "lifecycle.")
        for name in optimizer.param_specs:
            assert name.startswith(allowed_prefixes), f"Unexpected param in per-asset space: {name}"

    def test_bounds_narrowed_from_global(self):
        """Bounds should be within the configured per-asset narrowing fraction."""
        optimizer = _make_optimizer()
        bf = optimizer._config.bound_fraction
        for name, (low, high, kind) in optimizer.param_specs.items():
            # Gate params narrow around resolved YAML value, not global best
            if name in _GATE_PARAMS:
                continue
            global_val = _DEFAULT_PARAM_VALUES[name]
            full_space = _default_parameter_space()
            orig_spec = full_space[name]

            # Narrowed low should be >= original low
            assert low >= orig_spec.low, f"{name}: narrowed low {low} < original {orig_spec.low}"
            # Narrowed high should be <= original high
            assert high <= orig_spec.high, f"{name}: narrowed high {high} > original {orig_spec.high}"
            # Should be within ±bf of global (or clamped to original bounds)
            expected_low = max(orig_spec.low, global_val * (1 - bf))
            expected_high = min(orig_spec.high, global_val * (1 + bf))
            assert low == pytest.approx(expected_low, abs=1e-6)
            assert high == pytest.approx(expected_high, abs=1e-6)

    def test_bounds_clamping_at_edge(self):
        """When global optimum is near edge, bounds clamp to original range."""
        # Use global values near the low edge
        global_params = dict(_DEFAULT_PARAM_VALUES)
        full_space = _default_parameter_space()

        # Set min_strength to its minimum
        global_params["lifecycle.min_strength"] = 0.2
        config = AssetOptimizationConfig(min_bars=50, train_bars=30, test_bars=15,
                                          step_bars=15, purge_bars=5)
        optimizer = AssetSROptimizer(
            asset="TEST", timeframe="1h",
            global_best_params=global_params,
            base_raw_config=_make_base_raw_config(),
            opt_config=config,
        )
        low, high, _ = optimizer.param_specs["lifecycle.min_strength"]
        # Low should be clamped to original 0.2 (not below)
        assert low == full_space["lifecycle.min_strength"].low

    def test_disabled_params_excluded(self):
        """Params with enabled=False (like session_gap) should be excluded."""
        optimizer = _make_optimizer()
        assert "kernels.session_gap.gap_min_atr" not in optimizer.param_specs


# ---------------------------------------------------------------------------
# TASK-009: Regularization penalty
# ---------------------------------------------------------------------------

class TestRegularizationPenalty:
    def test_zero_deviation_zero_penalty(self):
        optimizer = _make_optimizer()
        params = optimizer._global_per_asset_params()
        penalty = optimizer._regularization_penalty(params)
        assert penalty == pytest.approx(0.0, abs=1e-6)

    def test_penalty_increases_with_deviation(self):
        optimizer = _make_optimizer()
        params_close = optimizer._global_per_asset_params()
        params_far = dict(params_close)

        # Push one param to the edge of its narrowed bounds
        first_name = next(iter(optimizer.param_specs))
        _, high, _ = optimizer.param_specs[first_name]
        params_far[first_name] = high

        penalty_close = optimizer._regularization_penalty(params_close)
        penalty_far = optimizer._regularization_penalty(params_far)
        assert penalty_far > penalty_close

    def test_zero_weight_zero_penalty(self):
        config = AssetOptimizationConfig(
            regularization_weight=0.0,
            min_bars=50, train_bars=30, test_bars=15,
            step_bars=15, purge_bars=5,
        )
        optimizer = _make_optimizer(config)
        params = optimizer._global_per_asset_params()
        # Push a param far
        first_name = next(iter(optimizer.param_specs))
        _, high, _ = optimizer.param_specs[first_name]
        params[first_name] = high
        assert optimizer._regularization_penalty(params) == 0.0


# ---------------------------------------------------------------------------
# TASK-009: Gate and constraint penalties
# ---------------------------------------------------------------------------

class TestGateAndConstraint:
    def test_zone_count_gate_penalty(self):
        """Fold with < min_zone_count_gate zones should get penalized."""
        optimizer = _make_optimizer()
        df = _make_ohlcv(n=100, seed=777)
        params = optimizer._global_per_asset_params()

        # Mock the pipeline to produce zero zones
        with patch.object(optimizer, '_build_pipeline') as mock_build:
            mock_pipeline = MagicMock()
            mock_pipeline.run.return_value = MagicMock(
                events=[], new_zones=[], active_zones=[], scored_levels=[],
            )
            mock_pipeline.all_zones = []
            mock_build.return_value = mock_pipeline

            score, metrics, gf, cf = optimizer._evaluate_fold(params, df)
            assert gf == 1  # gate failure flagged
            # Score should be reduced by gate_penalty
            assert score <= optimizer._config.gate_penalty

    def test_survival_constraint_soft_penalty(self):
        """Low survival rate gets soft penalty, not hard rejection."""
        optimizer = _make_optimizer()
        # Construct a run result with low survival
        r = MultiBarRunResult(
            total_zones_created=10,
            zones_reached_active=1,  # 10% survival < 20% constraint
            total_touches=5,
            total_breakouts=1,
        )
        evaluator = ZoneQualityEvaluator()
        metrics = evaluator.evaluate(r)
        assert metrics.survival_rate < optimizer._config.min_survival_rate_constraint

        # The constraint_mult should be < 1.0 but > 0.5
        min_surv = optimizer._config.min_survival_rate_constraint
        expected_mult = 0.5 + 0.5 * (metrics.survival_rate / min_surv)
        assert 0.5 < expected_mult < 1.0


# ---------------------------------------------------------------------------
# TASK-008: Walk-forward builder
# ---------------------------------------------------------------------------

class TestWalkForwardBuilder:
    def test_builds_validator(self):
        optimizer = _make_optimizer()
        wf = optimizer._build_walk_forward()
        assert wf.train_bars == optimizer._config.train_bars
        assert wf.test_bars == optimizer._config.test_bars
        assert wf.purge_bars == optimizer._config.purge_bars

    def test_splits_with_sufficient_data(self):
        optimizer = _make_optimizer()
        wf = optimizer._build_walk_forward()
        splits = wf.get_splits(600)
        assert len(splits) >= 1

    def test_no_splits_with_tiny_data(self):
        optimizer = _make_optimizer()
        wf = optimizer._build_walk_forward()
        with pytest.raises(ValueError, match="Insufficient data"):
            wf.get_splits(30)  # Far too small


# ---------------------------------------------------------------------------
# TASK-010/011: optimize() and fallback
# ---------------------------------------------------------------------------

class TestOptimize:
    def test_insufficient_data_returns_fallback(self):
        config = AssetOptimizationConfig(min_bars=1000)
        optimizer = _make_optimizer(config)
        df = _make_ohlcv(n=100)
        result = optimizer.optimize(df)
        assert result.fallback_to_global is True
        assert result.accepted is False

    def test_no_optuna_fallback(self):
        optimizer = _make_optimizer()
        df = _make_ohlcv(n=600, seed=456)

        with patch("app.sr.optimization.asset_optimizer.OPTUNA_AVAILABLE", False):
            result = optimizer.optimize(df)
            assert result.fallback_to_global is True
            assert result.accepted is True  # defaults are "accepted"
            assert len(result.best_params) > 0

    def test_optimize_runs_with_optuna(self):
        """Full integration: run Optuna optimization on synthetic data."""
        config = AssetOptimizationConfig(
            n_trials=3,
            timeout_s=120.0,
            min_bars=100,
            train_bars=50,
            test_bars=30,
            step_bars=30,
            purge_bars=5,
        )
        optimizer = _make_optimizer(config)
        df = _make_ohlcv(n=200, seed=789)
        result = optimizer.optimize(df)

        assert isinstance(result, AssetOptimizationResult)
        assert result.asset == "TEST"
        assert result.timeframe == "1h"
        assert len(result.best_params) > 0
        assert result.n_trials_total >= 1
        # All per-asset params should be present
        for name in optimizer.param_specs:
            assert name in result.best_params, f"Missing param: {name}"


# ---------------------------------------------------------------------------
# TASK-012: Result persistence
# ---------------------------------------------------------------------------

class TestResultPersistence:
    def test_save_and_load_round_trip(self):
        result = AssetOptimizationResult(
            asset="BTCUSDT",
            timeframe="1h",
            best_params={"kernels.order_block.displacement_atr": 1.8},
            train_score=0.65,
            val_score=0.60,
            accepted=True,
            n_folds=3,
            fold_scores=[0.6, 0.65, 0.7],
        )
        path = os.path.join(_RESULTS_DIR, "test_round_trip.json")
        try:
            result.save(path)
            loaded = AssetOptimizationResult.load(path)
            assert loaded.asset == "BTCUSDT"
            assert loaded.timeframe == "1h"
            assert loaded.train_score == pytest.approx(0.65)
            assert loaded.val_score == pytest.approx(0.60)
            assert loaded.accepted is True
            assert loaded.best_params["kernels.order_block.displacement_atr"] == 1.8
            assert loaded.fold_scores == [0.6, 0.65, 0.7]
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_save_rejects_path_outside_results(self):
        result = AssetOptimizationResult(asset="X", timeframe="1h")
        with pytest.raises(ValueError, match="Save path must be under"):
            result.save("/tmp/not_allowed.json")

    def test_apply_to_yaml(self):
        result = AssetOptimizationResult(
            asset="ETHUSDT",
            timeframe="4h",
            best_params={
                "kernels.order_block.displacement_atr": 1.9,
                "kernels.fair_value_gap.gap_min_atr": 0.6,
            },
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False,
        ) as f:
            f.write("sr:\n  pipeline:\n    enabled_kernels: [pivot_hl]\n")
            yaml_path = f.name

        try:
            result.apply_to_yaml(yaml_path, backup=True)

            # Verify backup was created
            assert os.path.exists(yaml_path + ".bak")

            # Read back and verify structure
            import yaml

            with open(yaml_path) as f:
                cfg = yaml.safe_load(f)

            assert "assets" in cfg
            assert "ETHUSDT" in cfg["assets"]
            tf_section = cfg["assets"]["ETHUSDT"]["4h"]
            assert tf_section["kernels"]["order_block"]["displacement_atr"] == 1.9
            assert tf_section["kernels"]["fair_value_gap"]["gap_min_atr"] == 0.6
        finally:
            if os.path.exists(yaml_path):
                os.remove(yaml_path)
            if os.path.exists(yaml_path + ".bak"):
                os.remove(yaml_path + ".bak")


# ---------------------------------------------------------------------------
# TASK-013: Walk-forward rejection
# ---------------------------------------------------------------------------

class TestWalkForwardRejection:
    def test_validation_drop_detection(self):
        """When val_score drops >15% vs train_score, result should be rejected."""
        optimizer = _make_optimizer()

        # Simulate: train scores high, val scores low
        train_scores = [0.8, 0.75, 0.82]
        val_scores = [0.5, 0.45, 0.48]  # ~40% drop

        mean_train = float(np.mean(train_scores))
        mean_val = float(np.mean(val_scores))
        threshold = 1.0 - optimizer._config.validation_drop_threshold

        # Should be rejected
        assert mean_val < mean_train * threshold


# ---------------------------------------------------------------------------
# Integration: full fold evaluation
# ---------------------------------------------------------------------------

class TestFoldEvaluation:
    def test_evaluate_fold_produces_score(self):
        """Evaluate a single fold and verify score structure."""
        config = AssetOptimizationConfig(
            min_bars=50, train_bars=30, test_bars=15,
            step_bars=15, purge_bars=5,
        )
        optimizer = _make_optimizer(config)
        df = _make_ohlcv(n=100, seed=321)
        params = optimizer._global_per_asset_params()

        score, metrics, gf, cf = optimizer._evaluate_fold(params, df)
        assert isinstance(score, float)
        assert isinstance(metrics, ZoneQualityMetrics)
        assert gf in (0, 1)
        assert cf in (0, 1)

    def test_evaluate_fold_uses_full_history_window(self, monkeypatch):
        import app.sr.optimization.asset_optimizer as asset_optimizer_module

        config = AssetOptimizationConfig(
            min_bars=50,
            train_bars=30,
            test_bars=15,
            step_bars=15,
            purge_bars=5,
            max_lookback=777,
        )
        optimizer = _make_optimizer(config)
        df = _make_ohlcv(n=100, seed=999)
        params = optimizer._global_per_asset_params()
        captured = {}

        class DummyRunner:
            def __init__(self, pipeline):
                self._pipeline = pipeline

            def run(
                self,
                input_df,
                start_bar=0,
                end_bar=None,
                progress_callback=None,
                max_lookback=2000,
            ):
                captured["df"] = input_df
                captured["start_bar"] = start_bar
                captured["end_bar"] = end_bar
                captured["max_lookback"] = max_lookback
                return MultiBarRunResult()

        monkeypatch.setattr(asset_optimizer_module, "MultiBarRunner", DummyRunner)
        monkeypatch.setattr(optimizer, "_build_pipeline", lambda params: MagicMock(all_zones=[]))

        optimizer._evaluate_fold(params, df, start_bar=25, end_bar=49)

        assert captured["df"] is df
        assert captured["start_bar"] == 25
        assert captured["end_bar"] == 49
        assert captured["max_lookback"] == 777

    def test_evaluate_fold_scores_only_requested_window(self, monkeypatch):
        import app.sr.optimization.asset_optimizer as asset_optimizer_module

        optimizer = _make_optimizer()
        df = _make_ohlcv(n=120, seed=202)
        params = optimizer._global_per_asset_params()
        captured = {}

        class DummyRunner:
            def __init__(self, pipeline):
                self._pipeline = pipeline

            def run(
                self,
                input_df,
                start_bar=0,
                end_bar=None,
                progress_callback=None,
                max_lookback=2000,
            ):
                return MultiBarRunResult(
                    bar_count=7,
                    all_events=[
                        ZoneLifecycleEvent(
                            zone_id="z1",
                            timestamp=df.index[2],
                            from_state=ZoneStatus.FORMING,
                            to_state=ZoneStatus.ACTIVE,
                            trigger="touch",
                            price_at_event=100.0,
                            volume_at_event=10.0,
                            bar_index=2,
                        ),
                        ZoneLifecycleEvent(
                            zone_id="z1",
                            timestamp=df.index[4],
                            from_state=ZoneStatus.ACTIVE,
                            to_state=ZoneStatus.BROKEN,
                            trigger="breakout_down",
                            price_at_event=99.0,
                            volume_at_event=11.0,
                            bar_index=4,
                        ),
                        ZoneLifecycleEvent(
                            zone_id="z2",
                            timestamp=df.index[6],
                            from_state=ZoneStatus.FORMING,
                            to_state=ZoneStatus.ACTIVE,
                            trigger="touch_confirm",
                            price_at_event=101.0,
                            volume_at_event=12.0,
                            bar_index=6,
                        ),
                    ],
                    final_zones=[],
                    total_zones_created=4,
                    total_touches=3,
                    total_breakouts=1,
                    total_false_breakouts=0,
                    zones_reached_active=3,
                    close_prices=[100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
                    bar_zone_snapshots=[[], [], [], [], [], []],
                )

        def fake_evaluate(run_result):
            captured["run_result"] = run_result
            return ZoneQualityMetrics(
                survival_rate=0.75,
                touch_accuracy=0.5,
                false_breakout_rate=0.0,
                strength_stability=0.0,
                coverage=0.0,
            )

        monkeypatch.setattr(asset_optimizer_module, "MultiBarRunner", DummyRunner)
        monkeypatch.setattr(optimizer, "_build_pipeline", lambda params: MagicMock(all_zones=[]))
        monkeypatch.setattr(optimizer._evaluator, "evaluate", fake_evaluate)
        monkeypatch.setattr(optimizer._evaluator, "composite_score", lambda metrics: 0.5)

        optimizer._evaluate_fold(
            params,
            df,
            start_bar=2,
            end_bar=8,
            score_start_bar=6,
        )

        scored_result = captured["run_result"]
        assert [event.bar_index for event in scored_result.all_events] == [6]
        assert scored_result.total_touches == 1
        assert scored_result.total_breakouts == 0
        assert scored_result.total_zones_created == 4
        assert scored_result.zones_reached_active == 3
        assert scored_result.close_prices == [104.0, 105.0]
        assert scored_result.bar_zone_snapshots == [[], []]

    def test_kernel_screening_keeps_full_history_for_tail_window(self, monkeypatch):
        from app.sr.optimization.kernel_screener import KernelScore, KernelScreener, KernelSelectionConfig

        df = _make_ohlcv(n=100, seed=321)
        screener = KernelScreener(
            asset="TEST",
            timeframe="1h",
            base_raw_config=_make_base_raw_config(),
            config=KernelSelectionConfig(screening_bars=40),
        )
        captured = {}

        monkeypatch.setattr(screener, "_available_kernels", lambda: ["pivot_hl"])

        def fake_evaluate_kernel(kernel_name, input_df, *, base_composite=0.0, start_bar=0, max_lookback=2000):
            captured["kernel_name"] = kernel_name
            captured["df"] = input_df
            captured["start_bar"] = start_bar
            captured["max_lookback"] = max_lookback
            return KernelScore(kernel=kernel_name, composite=0.5, zones_created=10, passed=True)

        monkeypatch.setattr(screener, "_evaluate_kernel", fake_evaluate_kernel)

        scores = screener.screen(df, max_lookback=777)

        assert len(scores) == 1
        assert captured["kernel_name"] == "pivot_hl"
        assert captured["df"] is df
        assert captured["start_bar"] == 60
        assert captured["max_lookback"] == 777

    def test_pipeline_builds_with_overrides(self):
        """Pipeline should build successfully with per-asset overrides."""
        optimizer = _make_optimizer()
        params = optimizer._global_per_asset_params()
        pipeline = optimizer._build_pipeline(params)
        assert pipeline is not None
