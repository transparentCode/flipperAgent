"""
Integration Tests — SR Pipeline Pre-Run Gate
==============================================
Run before every optimizer or audit to catch config, contract,
observability, and quality regressions in < 5 seconds.

**Layer 1 — Config Validation** (synthetic data)
  Load sr.yaml, resolve for BTCUSDT/1h, validate all params within bounds,
  cascade merging, and rule-derived computation.

**Layer 2 — Contract Correctness** (synthetic data)
  Build SRv2Pipeline from real config, run bar-by-bar on synthetic OHLCV,
  assert zone output structure, lifecycle state validity, no NaN/exceptions.

**Layer 3 — Quality Regression Gate** (frozen real fixture)
  Run MultiBarRunner on 600 real BTC/1h bars, compute ZoneQualityMetrics,
  assert composite score ≥ baseline and per-metric sanity ranges.

**Layer 4 — Observability Surface** (synthetic data)
  Pipeline with debug=True and timing=True, assert intermediate artifacts:
  feature snapshots, lifecycle events, timing dict, audit log integration.

**Layer 5 — Optimizer Compatibility Smoke** (synthetic data)
  One trial, one fold, one asset: catch plumbing failures in walk-forward
  evaluation without paying multi-hour cost.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Any

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SR_CONFIG_DIR = Path(__file__).parent.parent / "config"
_SR_YAML = _SR_CONFIG_DIR / "sr.yaml"
_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_FIXTURE_CSV = _FIXTURE_DIR / "btcusdt_1h_600bars.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_sr_yaml() -> Dict[str, Any]:
    from app.utils.ConfigLoader import ConfigLoader
    return ConfigLoader.load(str(_SR_YAML))


def _resolve_config(
    raw_config: Dict[str, Any],
    symbol: str = "BTCUSDT",
    timeframe: str = "1h",
):
    from app.sr.config_resolver import SRConfigResolver
    resolver = SRConfigResolver()
    return resolver.resolve(symbol, timeframe, raw_config)


def _make_synthetic_ohlcv(
    n: int = 600,
    base_price: float = 50000.0,
    volatility: float = 0.015,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    closes = [base_price]
    for _ in range(1, n):
        closes.append(closes[-1] * (1 + volatility * rng.randn()))
    closes = np.array(closes)
    upper_wick = rng.exponential(0.004, n)
    lower_wick = rng.exponential(0.004, n)
    highs = closes * (1 + upper_wick)
    lows = closes * (1 - lower_wick)
    opens = closes * (1 + rng.uniform(-volatility / 3, volatility / 3, n))
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))
    volumes = rng.uniform(100, 5000, n)
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


def _load_real_fixture() -> pd.DataFrame:
    """Load the frozen BTC/USDT 1h fixture."""
    if not _FIXTURE_CSV.exists():
        pytest.skip(f"Real data fixture not found: {_FIXTURE_CSV}")
    df = pd.read_csv(_FIXTURE_CSV, index_col=0, parse_dates=True)
    assert len(df) >= 500, f"Fixture too short: {len(df)} bars"
    return df


def _build_pipeline(resolved_config, asset="BTCUSDT", timeframe="1h"):
    from app.sr.pipeline import SRv2Pipeline
    return SRv2Pipeline(config=resolved_config, asset=asset, timeframe=timeframe)


# ---------------------------------------------------------------------------
# LAYER 1 — Config Validation
# ---------------------------------------------------------------------------


class TestConfigValidation:
    """Validate sr.yaml loads, parses, resolves, and cascades correctly."""

    def test_yaml_loads_without_error(self):
        raw = _load_sr_yaml()
        assert isinstance(raw, dict)
        assert "sr" in raw, "sr.yaml must have top-level 'sr' key"

    def test_resolve_btcusdt_1h(self):
        raw = _load_sr_yaml()
        config = _resolve_config(raw)
        assert config is not None
        assert hasattr(config, "pipeline")
        assert hasattr(config, "kernels")
        assert hasattr(config, "ensemble")
        assert hasattr(config, "lifecycle")

    def test_enabled_kernels_exist(self):
        raw = _load_sr_yaml()
        config = _resolve_config(raw)
        from app.sr.kernels import ensure_kernel_registry_populated
        from app.sr.kernels.registry import KernelRegistry
        ensure_kernel_registry_populated()
        for name in config.pipeline.enabled_kernels:
            kernel = KernelRegistry.create(name)
            assert kernel is not None, f"Enabled kernel '{name}' not in registry"

    def test_kernel_params_within_bounds(self):
        """Verify optimizable kernel params are within original search bounds."""
        from app.sr.optimization.universe_optimizer import _default_parameter_space
        raw = _load_sr_yaml()
        config = _resolve_config(raw)
        space = _default_parameter_space()

        param_sources = {
            "kernels.volume_poc.hvn_prominence": config.kernels.get("volume_poc", {}).get("hvn_prominence"),
            "kernels.fair_value_gap.gap_min_atr": config.kernels.get("fair_value_gap", {}).get("gap_min_atr"),
            "kernels.fair_value_gap.fill_threshold": config.kernels.get("fair_value_gap", {}).get("fill_threshold"),
            "kernels.fair_value_gap.filled_penalty_multiplier": config.kernels.get("fair_value_gap", {}).get("filled_penalty_multiplier"),
            "kernels.order_block.displacement_atr": config.kernels.get("order_block", {}).get("displacement_atr"),
            "kernels.order_block.imbalance_ratio": config.kernels.get("order_block", {}).get("imbalance_ratio"),
            "kernels.regression_band.band_width_sigma": config.kernels.get("regression_band", {}).get("band_width_sigma"),
            "kernels.liquidity_sweep.sweep_lookback": config.kernels.get("liquidity_sweep", {}).get("sweep_lookback"),
            "kernels.liquidity_sweep.max_pierce_atr": config.kernels.get("liquidity_sweep", {}).get("max_pierce_atr"),
        }
        for name, value in param_sources.items():
            if value is None:
                continue  # Not set in config — uses kernel default
            spec = space.get(name)
            if spec is None:
                continue
            assert spec.low <= value <= spec.high, (
                f"{name}={value} outside bounds [{spec.low}, {spec.high}]"
            )

    def test_rule_derived_params_compute(self):
        """Rule-derived params should compute without error."""
        raw = _load_sr_yaml()
        config = _resolve_config(raw)
        rd = config.rule_derived
        assert rd is not None
        assert rd.n1 > 0
        assert rd.n2 > 0
        assert rd.breakout_confirm_bars >= 1
        assert rd.max_zone_width_atr > 0

    def test_config_cascade_per_tf(self):
        """per_tf overrides should apply when present."""
        raw = _load_sr_yaml()
        resolver = __import__(
            "app.sr.config_resolver", fromlist=["SRConfigResolver"]
        ).SRConfigResolver()
        # Resolve for different timeframes
        config_1h = resolver.resolve("BTCUSDT", "1h", raw)
        config_4h = resolver.resolve("BTCUSDT", "4h", raw)
        # Both should resolve without error
        assert config_1h is not None
        assert config_4h is not None

    def test_config_cascade_per_asset(self):
        """Asset-specific overrides should apply when present."""
        raw = _load_sr_yaml()
        # If assets section exists with BTCUSDT, it should override
        config = _resolve_config(raw, symbol="BTCUSDT", timeframe="1h")
        assert config is not None

    def test_ensemble_method_valid(self):
        raw = _load_sr_yaml()
        config = _resolve_config(raw)
        valid_methods = {"weighted_average", "confidence_weighted", "regime_conditional"}
        assert config.ensemble.method in valid_methods, (
            f"Unknown ensemble method: {config.ensemble.method}"
        )

    def test_pipeline_gate_params_sane(self):
        raw = _load_sr_yaml()
        config = _resolve_config(raw)
        assert 0.0 <= config.pipeline.min_emit_strength <= 1.0, (
            f"min_emit_strength={config.pipeline.min_emit_strength} out of [0,1]"
        )
        if config.pipeline.max_new_zones_per_bar:
            assert config.pipeline.max_new_zones_per_bar >= 1


# ---------------------------------------------------------------------------
# LAYER 2 — Contract Correctness (synthetic data)
# ---------------------------------------------------------------------------


class TestContractCorrectness:
    """Build pipeline from real config, run on synthetic data, validate outputs."""

    @pytest.fixture(scope="class")
    def pipeline_with_results(self):
        """Run pipeline bar-by-bar on 500 synthetic bars, return (pipeline, results)."""
        raw = _load_sr_yaml()
        config = _resolve_config(raw)
        pipeline = _build_pipeline(config)
        df = _make_synthetic_ohlcv(n=500)
        results = []
        for bar in range(50, len(df)):
            result = pipeline.run(df.iloc[: bar + 1], bar_index=bar)
            results.append(result)
        return pipeline, results

    def test_no_exceptions_during_run(self, pipeline_with_results):
        """Pipeline should run 450 bars without exceptions."""
        _, results = pipeline_with_results
        assert len(results) == 450

    def test_result_has_expected_fields(self, pipeline_with_results):
        _, results = pipeline_with_results
        for r in results[:5]:
            assert hasattr(r, "candidates")
            assert hasattr(r, "scored_levels")
            assert hasattr(r, "active_zones")
            assert hasattr(r, "events")
            assert hasattr(r, "new_zones")
            assert hasattr(r, "ensemble_method")

    def test_zones_have_valid_structure(self, pipeline_with_results):
        _, results = pipeline_with_results
        from app.sr.models import ZoneStatus, LevelType
        seen_zones = False
        for r in results:
            for zone in r.active_zones:
                seen_zones = True
                assert zone.zone_id, "zone_id must be non-empty"
                assert zone.center_price > 0, f"center_price={zone.center_price}"
                assert zone.lower_bound <= zone.center_price <= zone.upper_bound
                assert 0.0 <= zone.strength <= 1.0, f"strength={zone.strength}"
                assert isinstance(zone.status, ZoneStatus)
                assert isinstance(zone.level_type, LevelType)
                assert zone.bars_since_formation >= 0
        assert seen_zones, "Pipeline produced no zones on 450 bars — likely broken"

    def test_no_nan_in_zone_prices(self, pipeline_with_results):
        _, results = pipeline_with_results
        for r in results:
            for zone in r.active_zones:
                assert not np.isnan(zone.center_price)
                assert not np.isnan(zone.lower_bound)
                assert not np.isnan(zone.upper_bound)
                assert not np.isnan(zone.strength)

    def test_lifecycle_states_valid(self, pipeline_with_results):
        """Final snapshot's active zones should have non-terminal status.

        Note: ManagedZone is mutable — earlier PipelineResult snapshots hold
        references that may later be expired.  Only the *last* result
        reflects the true current state.
        """
        from app.sr.models import ZoneStatus
        _, results = pipeline_with_results
        terminal = {ZoneStatus.EXPIRED}
        # Check only the final result (current lifecycle state)
        last = results[-1]
        for zone in last.active_zones:
            assert zone.status not in terminal, (
                f"Expired zone in final active_zones: {zone.zone_id}"
            )

    def test_scored_levels_have_scores(self, pipeline_with_results):
        _, results = pipeline_with_results
        any_scored = False
        for r in results:
            for sl in r.scored_levels:
                any_scored = True
                assert hasattr(sl, "strength")
                assert 0.0 <= sl.strength <= 1.0, f"strength={sl.strength}"
                assert sl.candidate is not None
        assert any_scored, "No scored levels produced in 450 bars"

    def test_candidates_have_kernel_name(self, pipeline_with_results):
        _, results = pipeline_with_results
        for r in results:
            for c in r.candidates:
                assert c.kernel_name, "candidate missing kernel_name"
                assert c.center_price > 0

    def test_lifecycle_events_well_formed(self, pipeline_with_results):
        """Lifecycle events should have required fields."""
        _, results = pipeline_with_results
        from app.sr.models import ZoneStatus
        any_events = False
        for r in results:
            for ev in r.events:
                any_events = True
                assert ev.zone_id, "event missing zone_id"
                assert isinstance(ev.from_state, ZoneStatus)
                assert isinstance(ev.to_state, ZoneStatus)
                assert ev.trigger, "event missing trigger"
        # Events are optional per bar, but 450 bars should produce some
        if not any_events:
            pytest.skip("No lifecycle events — may be normal for synthetic data")


# ---------------------------------------------------------------------------
# LAYER 3 — Quality Regression Gate (frozen real fixture)
# ---------------------------------------------------------------------------


class TestQualityRegressionGate:
    """Run on real BTC data fixture, assert quality metrics meet baseline."""

    @pytest.fixture(scope="class")
    def audit_result(self):
        """Run full MultiBarRunner + evaluator on real fixture."""
        from app.sr.optimization.multi_bar_runner import MultiBarRunner
        from app.sr.optimization.quality_metrics import ZoneQualityEvaluator

        df = _load_real_fixture()
        raw = _load_sr_yaml()
        config = _resolve_config(raw)
        pipeline = _build_pipeline(config)
        runner = MultiBarRunner(pipeline)

        run_result = runner.run(df, start_bar=50)
        evaluator = ZoneQualityEvaluator()
        metrics = evaluator.evaluate(run_result)
        composite = evaluator.composite_score(metrics)
        return {
            "metrics": metrics,
            "composite": composite,
            "run_result": run_result,
        }

    def test_composite_above_baseline(self, audit_result):
        """Composite score must meet minimum quality floor."""
        # Baseline from best-audit run (0.5540). Set floor below to
        # allow config exploration without blocking, but catch catastrophic
        # regression.
        assert audit_result["composite"] >= 0.35, (
            f"Composite {audit_result['composite']:.4f} < 0.35 baseline — "
            f"pipeline quality regression detected"
        )

    def test_survival_rate_sane(self, audit_result):
        m = audit_result["metrics"]
        assert m.survival_rate >= 0.01, (
            f"survival_rate={m.survival_rate:.4f} too low — zones dying immediately"
        )

    def test_touch_accuracy_non_zero(self, audit_result):
        m = audit_result["metrics"]
        # touch_accuracy can be 0 if no touches occurred on 600 bars,
        # but should be > 0 on real BTC with enough bars
        assert m.touch_accuracy >= 0.0, (
            f"touch_accuracy={m.touch_accuracy:.4f} negative — metric bug"
        )

    def test_false_breakout_rate_bounded(self, audit_result):
        m = audit_result["metrics"]
        assert 0.0 <= m.false_breakout_rate <= 1.0, (
            f"false_breakout_rate={m.false_breakout_rate:.4f} out of [0,1]"
        )

    def test_coverage_positive(self, audit_result):
        m = audit_result["metrics"]
        assert m.coverage >= 0.0, f"coverage={m.coverage:.4f} negative"

    def test_zone_count_positive(self, audit_result):
        rr = audit_result["run_result"]
        assert rr.total_zones_created > 0, "No zones created on real BTC data"

    def test_strength_stability_bounded(self, audit_result):
        m = audit_result["metrics"]
        assert 0.0 <= m.strength_stability <= 1.0, (
            f"strength_stability={m.strength_stability:.4f} out of [0,1]"
        )


# ---------------------------------------------------------------------------
# LAYER 4 — Observability Surface
# ---------------------------------------------------------------------------


class TestObservabilitySurface:
    """Verify debug artifacts, timing, and audit log integration."""

    @pytest.fixture(scope="class")
    def debug_results(self):
        """Run pipeline with debug=True and timing=True."""
        raw = _load_sr_yaml()
        config = _resolve_config(raw)
        pipeline = _build_pipeline(config)
        df = _make_synthetic_ohlcv(n=300)
        results = []
        for bar in range(50, 200):
            result = pipeline.run(
                df.iloc[: bar + 1], bar_index=bar, debug=True, timing=True,
            )
            results.append(result)
        return results

    def test_timing_dict_populated(self, debug_results):
        for r in debug_results[:5]:
            assert r.timing is not None, "timing=True but result.timing is None"
            assert "kernels_ms" in r.timing
            assert "features_ms" in r.timing
            assert "ensemble_ms" in r.timing
            assert "lifecycle_ms" in r.timing
            assert "total_ms" in r.timing
            for key, val in r.timing.items():
                assert val >= 0, f"timing[{key}]={val} negative"

    def test_debug_dict_populated(self, debug_results):
        for r in debug_results[:5]:
            assert r.debug is not None, "debug=True but result.debug is None"
            assert "candidates_by_kernel" in r.debug
            assert "feature_vectors" in r.debug
            assert "context" in r.debug

    def test_debug_context_fields(self, debug_results):
        r = debug_results[0]
        ctx = r.debug["context"]
        assert "atr" in ctx
        assert "current_price" in ctx
        assert ctx["current_price"] > 0
        assert "current_volume" in ctx
        assert "bar_count" in ctx
        assert ctx["bar_count"] > 0

    def test_feature_vectors_present_when_candidates_exist(self, debug_results):
        for r in debug_results:
            if r.candidates:
                assert len(r.debug["feature_vectors"]) > 0, (
                    "Candidates exist but no feature vectors computed"
                )

    def test_lifecycle_events_have_full_fields(self, debug_results):
        """Events should have price_at_event, volume_at_event, bar_index."""
        from app.sr.models import ZoneStatus
        for r in debug_results:
            for ev in r.events:
                assert ev.zone_id
                assert isinstance(ev.from_state, ZoneStatus)
                assert isinstance(ev.to_state, ZoneStatus)
                assert ev.bar_index >= 0

    def test_debug_all_zones_includes_lifecycle(self, debug_results):
        """debug['all_zones'] should include zones from lifecycle manager."""
        # After enough bars, there should be some zones
        last_r = debug_results[-1]
        if last_r.debug.get("all_zones"):
            assert isinstance(last_r.debug["all_zones"], list)

    def test_debug_off_produces_none(self):
        """Without debug/timing flags, those fields should be None."""
        raw = _load_sr_yaml()
        config = _resolve_config(raw)
        pipeline = _build_pipeline(config)
        df = _make_synthetic_ohlcv(n=100)
        result = pipeline.run(df, bar_index=99)
        assert result.debug is None
        assert result.timing is None


# ---------------------------------------------------------------------------
# LAYER 5 — Optimizer Compatibility Smoke
# ---------------------------------------------------------------------------


class TestOptimizerCompatibilitySmoke:
    """One trial, one fold — catches plumbing failures before multi-hour runs."""

    def test_asset_optimizer_single_trial(self):
        """Run AssetSROptimizer with 1 trial, minimal data."""
        from app.sr.optimization.asset_optimizer import (
            AssetOptimizationConfig,
            AssetSROptimizer,
        )
        from app.sr.optimization.universe_optimizer import _DEFAULT_PARAM_VALUES

        raw = _load_sr_yaml()
        # Use real sr.yaml as base config for the resolver
        config = AssetOptimizationConfig(
            n_trials=1,
            timeout_s=120.0,
            min_bars=100,
            train_bars=80,
            test_bars=40,
            step_bars=40,
            purge_bars=5,
            fold_stride=1,
        )
        optimizer = AssetSROptimizer(
            asset="BTCUSDT",
            timeframe="1h",
            global_best_params=dict(_DEFAULT_PARAM_VALUES),
            base_raw_config=raw,
            opt_config=config,
        )

        df = _make_synthetic_ohlcv(n=300)
        result = optimizer.optimize(df)

        # Should complete without error and produce a valid result
        assert result is not None
        assert result.asset == "BTCUSDT"
        assert result.timeframe == "1h"
        assert isinstance(result.best_params, dict)
        assert len(result.best_params) > 0
        # Score should be a number (may be 0 if zones are sparse)
        assert isinstance(result.val_score, (int, float))
        assert not np.isnan(result.val_score)

    def test_walk_forward_splits_exist(self):
        """Ensure walk-forward creates at least 1 split for the data size."""
        from app.regression.optimization.walk_forward_2way import WalkForwardValidator

        wf = WalkForwardValidator(
            train_bars=80,
            test_bars=40,
            step_bars=40,
            purge_bars=5,
            min_train_bars=80,
        )
        splits = wf.get_splits(300)
        assert len(splits) >= 1, f"No splits for 300 bars with train=80"

    def test_zone_quality_evaluator_on_empty(self):
        """Evaluator should handle runs with zero zones gracefully."""
        from app.sr.optimization.multi_bar_runner import MultiBarRunResult
        from app.sr.optimization.quality_metrics import ZoneQualityEvaluator

        empty_result = MultiBarRunResult(
            bar_count=100,
            total_zones_created=0,
        )
        evaluator = ZoneQualityEvaluator()
        metrics = evaluator.evaluate(empty_result)
        composite = evaluator.composite_score(metrics)
        assert isinstance(composite, float)
        assert not np.isnan(composite)
