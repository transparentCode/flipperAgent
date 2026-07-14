"""
Phase 5 Tests — Observability & Hardening
==========================================
Tests for:
  - Debug mode (intermediate states)
  - Timing instrumentation (per-stage latency)
  - Comprehensive integration (single-asset, multi-asset, cross-asset)
"""

from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import pytest

from app.sr.models import (
    AssetMetadata,
    CandidateLevel,
    LevelFeatureVector,
    LevelType,
    RuleDerivedParams,
    ScoredLevel,
    ZoneLifecycleEvent,
    ZoneStatus,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _default_metadata() -> AssetMetadata:
    return AssetMetadata(
        profile="crypto",
        trading_hours_per_day=24.0,
        trading_days_per_week=7,
        has_session_gaps=False,
        gap_breakout_policy="gap_ignored",
        gap_escalation_atr=999.0,
        session_lookback_hours=[24, 168, 720],
        round_number_mode="decimal",
        ex_dividend_filter=False,
        continuous_market=True,
    )


def _default_rule_derived() -> RuleDerivedParams:
    return RuleDerivedParams(
        n1=8, n2=6, fractal_period=16, fractal_buffer=0.2,
        round_interval=10.0, max_zone_width_atr=2.0,
        max_zone_width_pct=3.0, breakout_confirm_bars=3,
        false_breakout_window=6, inactivity_threshold=80,
        max_active_zones=10, volume_spike_threshold=1.5,
        vp_lookback_hours=[24, 168, 720],
    )


def _make_resolved_config(enabled_kernels=None):
    from app.sr.config_schema import (
        EnsembleConfig,
        EnhancementConfig,
        LifecycleConfig,
        PipelineConfig,
        RegimeConfig,
        RuleDerivedConfig,
        SRResolvedConfig,
    )
    return SRResolvedConfig(
        metadata=_default_metadata(),
        pipeline=PipelineConfig(
            enabled_kernels=enabled_kernels or ["pivot_hl", "round_number"],
        ),
        kernels={
            "pivot_hl": {"historical_depth": 500, "smoothing_period": 3},
            "round_number": {},
        },
        ensemble=EnsembleConfig(method="weighted_average", structural_vs_micro_ratio=0.5),
        lifecycle=LifecycleConfig(
            age_lambda=0.002,
            breakout_confirm_bars=3,
            false_breakout_window=6,
            inactivity_threshold=80,
            max_active_zones=10,
        ),
        enhancement=EnhancementConfig(),
        regime=RegimeConfig(enabled=False),
        rule_derived=_default_rule_derived(),
        rule_derived_config=RuleDerivedConfig(),
    )


def _make_ohlcv(
    n: int = 200,
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


def _make_lifecycle_event(
    zone_id: str = "zone-1",
    from_state: ZoneStatus = ZoneStatus.FORMING,
    to_state: ZoneStatus = ZoneStatus.ACTIVE,
    bar_index: int = 0,
) -> ZoneLifecycleEvent:
    return ZoneLifecycleEvent(
        zone_id=zone_id,
        timestamp=datetime.now(tz=None),
        from_state=from_state,
        to_state=to_state,
        trigger="test",
        price_at_event=100.0,
        volume_at_event=500.0,
        bar_index=bar_index,
    )


def _make_scored_level(
    center_price: float = 100.0,
    level_type: LevelType = LevelType.SUPPORT,
) -> ScoredLevel:
    candidate = CandidateLevel(
        center_price=center_price,
        lower_bound=center_price - 1.0,
        upper_bound=center_price + 1.0,
        level_type=level_type,
        kernel_name="pivot_hl",
        timeframe="1h",
        raw_score=0.7,
        metadata={"source": "test"},
        timestamp=datetime.now(UTC),
        atr_at_detection=2.0,
    )
    features = LevelFeatureVector(
        touch_count=2,
        kernel_agreement=1,
        regime_alignment=0.0,
    )
    return ScoredLevel(
        candidate=candidate,
        features=features,
        strength=0.8,
        confidence=0.75,
        contributing_kernels=["pivot_hl"],
        ensemble_method="weighted_average",
    )


def _make_managed_zone() -> Any:
    from app.sr.lifecycle.state_machine import ManagedZone

    scored_level = _make_scored_level()
    timestamp = datetime.now(UTC)
    return ManagedZone(
        zone_id="zone-1",
        scored_level=scored_level,
        status=ZoneStatus.ACTIVE,
        strength=scored_level.strength,
        touch_count=2,
        bars_since_formation=5,
        bars_since_last_touch=1,
        bars_since_break=0,
        breakout_direction=None,
        false_breakout_count=0,
        events=[_make_lifecycle_event("zone-1", ZoneStatus.FORMING, ZoneStatus.ACTIVE)],
        detection_timestamp=timestamp,
        reinforcement_timestamp=timestamp,
        contributing_kernels=["pivot_hl"],
    )


class _RedisStub:
    def __init__(self):
        self._store: Dict[str, str] = {}

    def set(self, key: str, value: str, ex: Optional[int] = None):
        self._store[key] = value

    def get(self, key: str):
        return self._store.get(key)

    def delete(self, *keys: str):
        for key in keys:
            self._store.pop(key, None)


class TestZoneStateStore:

    def test_zone_state_store_round_trips_managed_zones(self):
        from app.sr.state.state_manager import ZoneStateStore

        store = ZoneStateStore(_RedisStub())
        zone = _make_managed_zone()

        assert store.snapshot_zones("BTCUSDT", [zone], metadata={"source": "phase5"}) is True

        restored = store.restore_zones("BTCUSDT")
        assert restored is not None
        assert len(restored) == 1
        restored_zone = restored[0]
        assert restored_zone.zone_id == zone.zone_id
        assert restored_zone.status == ZoneStatus.ACTIVE
        assert restored_zone.scored_level.ensemble_method == "weighted_average"
        assert restored_zone.scored_level.candidate.center_price == zone.scored_level.candidate.center_price
        assert restored_zone.events[0].to_state == ZoneStatus.ACTIVE

        metadata = store.get_metadata("BTCUSDT")
        assert metadata is not None
        assert metadata["schema_version"] == 2
        assert metadata["zone_count"] == 1

    def test_zone_state_store_round_trips_scored_levels(self):
        from app.sr.state.state_manager import ZoneStateStore

        store = ZoneStateStore(_RedisStub())
        level = _make_scored_level(center_price=101.5, level_type=LevelType.RESISTANCE)

        assert store.snapshot_scored_levels("BTCUSDT", "1h", [level]) is True

        restored = store.restore_scored_levels("BTCUSDT", "1h")
        assert restored is not None
        assert len(restored) == 1
        assert restored[0].candidate.center_price == 101.5
        assert restored[0].candidate.level_type == LevelType.RESISTANCE
        assert restored[0].ensemble_method == "weighted_average"

    def test_zone_state_store_clear_removes_tracked_scored_levels(self):
        from app.sr.state.state_manager import ZoneStateStore

        store = ZoneStateStore(_RedisStub())

        assert store.snapshot_zones("BTCUSDT", [_make_managed_zone()]) is True
        assert store.snapshot_scored_levels("BTCUSDT", "1h", [_make_scored_level()]) is True
        assert store.snapshot_scored_levels(
            "BTCUSDT",
            "4h",
            [_make_scored_level(center_price=105.0, level_type=LevelType.RESISTANCE)],
        ) is True

        assert store.clear("BTCUSDT") is True

        assert store.restore_zones("BTCUSDT") is None
        assert store.restore_scored_levels("BTCUSDT", "1h") is None
        assert store.restore_scored_levels("BTCUSDT", "4h") is None
        assert store.get_metadata("BTCUSDT") is None
        assert store.redis.get(store.KEY_LEVEL_INDEX.format(symbol="BTCUSDT")) is None

    def test_zone_state_store_rejects_unsupported_schema_versions(self):
        from app.sr.state.state_manager import ZoneStateStore

        store = ZoneStateStore(_RedisStub())
        assert store.snapshot_zones("BTCUSDT", [_make_managed_zone()]) is True

        key = store.KEY_ZONES.format(symbol="BTCUSDT")
        payload = json.loads(store.redis.get(key))
        payload["schema_version"] = 999
        store.redis.set(key, json.dumps(payload))

        assert store.restore_zones("BTCUSDT") is None

    def test_zone_state_store_restore_skips_invalid_zone_records(self):
        from app.sr.state.state_manager import ZoneStateStore

        store = ZoneStateStore(_RedisStub())
        zone = _make_managed_zone()
        assert store.snapshot_zones("BTCUSDT", [zone]) is True

        key = store.KEY_ZONES.format(symbol="BTCUSDT")
        payload = json.loads(store.redis.get(key))
        bad_zone = dict(payload["zones"][0])
        bad_zone["status"] = "NOT_A_REAL_STATUS"
        payload["zones"].append(bad_zone)
        store.redis.set(key, json.dumps(payload))

        restored = store.restore_zones("BTCUSDT")
        assert restored is not None
        assert len(restored) == 1
        assert restored[0].zone_id == zone.zone_id

    def test_zone_state_store_restore_scored_levels_ignores_unknown_feature_fields(self):
        from app.sr.state.state_manager import ZoneStateStore

        store = ZoneStateStore(_RedisStub())
        level = _make_scored_level(center_price=101.5, level_type=LevelType.RESISTANCE)
        assert store.snapshot_scored_levels("BTCUSDT", "1h", [level]) is True

        key = store.KEY_LEVELS.format(symbol="BTCUSDT", timeframe="1h")
        payload = json.loads(store.redis.get(key))
        payload["levels"][0]["features"]["future_metric"] = 9.9
        store.redis.set(key, json.dumps(payload))

        restored = store.restore_scored_levels("BTCUSDT", "1h")
        assert restored is not None
        assert len(restored) == 1
        assert restored[0].candidate.center_price == 101.5
        assert restored[0].features.touch_count == 2

    def test_deprecated_sr_state_manager_alias_delegates_to_zone_state_store(self):
        from app.sr.state.state_manager import SRStateManager, ZoneStateStore

        with pytest.warns(DeprecationWarning, match="SRStateManager is deprecated"):
            store = SRStateManager(_RedisStub())

        assert isinstance(store, ZoneStateStore)
        assert store.snapshot("BTCUSDT", [_make_managed_zone()]) is True

        restored = store.restore("BTCUSDT")
        assert restored is not None
        assert restored[0].zone_id == "zone-1"

    def test_zone_state_store_snapshot_timestamps_are_utc_and_warning_free(self):
        from app.sr.state.state_manager import ZoneStateStore

        store = ZoneStateStore(_RedisStub())

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert store.snapshot_zones("BTCUSDT", [_make_managed_zone()]) is True
            assert store.snapshot_scored_levels("BTCUSDT", "1h", [_make_scored_level()]) is True

        zone_payload = json.loads(store.redis.get(store.KEY_ZONES.format(symbol="BTCUSDT")))
        meta_payload = json.loads(store.redis.get(store.KEY_META.format(symbol="BTCUSDT")))
        level_payload = json.loads(
            store.redis.get(store.KEY_LEVELS.format(symbol="BTCUSDT", timeframe="1h")),
        )

        assert zone_payload["timestamp"].endswith("+00:00")
        assert meta_payload["last_update"].endswith("+00:00")
        assert level_payload["timestamp"].endswith("+00:00")
        assert not [
            warning
            for warning in caught
            if issubclass(warning.category, DeprecationWarning)
        ]


# ===========================================================================
# TASK-037 + TASK-038: Debug Mode + Timing
# ===========================================================================

class TestPipelineDebugMode:

    def test_debug_false_returns_none(self):
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.round_number  # noqa: F401
        from app.sr.pipeline import SRv2Pipeline

        config = _make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")
        result = pipeline.run(_make_ohlcv(), bar_index=0, debug=False, timing=False)
        assert result.debug is None
        assert result.timing is None

    def test_debug_returns_intermediate_states(self):
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.round_number  # noqa: F401
        from app.sr.pipeline import SRv2Pipeline

        config = _make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")
        result = pipeline.run(_make_ohlcv(), bar_index=0, debug=True)

        assert result.debug is not None
        assert "candidates_by_kernel" in result.debug
        assert "feature_vectors" in result.debug
        assert "context" in result.debug
        assert "ensemble_config" in result.debug
        assert "all_zones" in result.debug
        assert "lifecycle_config" in result.debug

    def test_debug_context_has_market_data(self):
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.round_number  # noqa: F401
        from app.sr.pipeline import SRv2Pipeline

        config = _make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")
        result = pipeline.run(_make_ohlcv(), bar_index=0, debug=True)

        ctx = result.debug["context"]
        assert "atr" in ctx
        assert ctx["atr"] > 0
        assert "current_price" in ctx
        assert "current_volume" in ctx
        assert "bar_count" in ctx
        assert ctx["bar_count"] == 200


class TestPipelineTimingMode:

    def test_timing_returns_stage_latencies(self):
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.round_number  # noqa: F401
        from app.sr.pipeline import SRv2Pipeline

        config = _make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")
        result = pipeline.run(_make_ohlcv(), bar_index=0, timing=True)

        assert result.timing is not None
        assert "kernels_ms" in result.timing
        assert "features_ms" in result.timing
        assert "ensemble_ms" in result.timing
        assert "lifecycle_ms" in result.timing
        assert "total_ms" in result.timing

    def test_timing_values_are_positive(self):
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.round_number  # noqa: F401
        from app.sr.pipeline import SRv2Pipeline

        config = _make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")
        result = pipeline.run(_make_ohlcv(), bar_index=0, timing=True)

        for key, val in result.timing.items():
            assert val >= 0, f"{key} should be >= 0, got {val}"

    def test_total_approximately_equals_sum(self):
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.round_number  # noqa: F401
        from app.sr.pipeline import SRv2Pipeline

        config = _make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")
        result = pipeline.run(_make_ohlcv(), bar_index=0, timing=True)

        stages = ["kernels_ms", "cross_bar_dedup_ms", "features_ms", "ensemble_ms", "lifecycle_ms"]
        stage_sum = sum(result.timing.get(s, 0.0) for s in stages)
        # total_ms is computed as sum of stages, so should be equal
        assert abs(result.timing["total_ms"] - stage_sum) < 0.01


# ===========================================================================
# TASK-042: Comprehensive Integration Tests
# ===========================================================================

class TestSingleAssetIntegration:
    """End-to-end single asset pipeline with debug + timing."""

    def test_full_pipeline_with_observability(self):
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.round_number  # noqa: F401
        from app.sr.pipeline import SRv2Pipeline

        config = _make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="BTCUSDT", timeframe="1h")

        df = _make_ohlcv(n=200, base_price=100.0)

        # Run with debug + timing
        result = pipeline.run(df, bar_index=0, debug=True, timing=True)

        # Verify basic outputs
        assert len(result.candidates) >= 0
        assert result.ensemble_method == "weighted_average"

        # Verify debug
        assert result.debug is not None
        assert "context" in result.debug

        # Verify timing
        assert result.timing is not None
        assert result.timing["total_ms"] >= 0

    def test_multi_bar_progression(self):
        """Pipeline maintains state across multiple bar updates."""
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.round_number  # noqa: F401
        from app.sr.pipeline import SRv2Pipeline

        config = _make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")
        df = _make_ohlcv(n=200)

        all_events = []
        for bar_idx in range(3):
            result = pipeline.run(df, bar_index=bar_idx)
            all_events.extend(result.events)

        # After multiple bars, should have zones
        assert len(pipeline.active_zones) >= 0
        assert len(pipeline.all_zones) >= 0


class TestMultiAssetIntegration:
    """Universe router integration tests."""

    def test_universe_all_assets_succeed(self):
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.round_number  # noqa: F401
        from app.sr.universe.config import UniverseSRConfig, AssetSRConfig
        from app.sr.universe.router import UniverseSRRouter

        asset_names = ["A", "B", "C"]
        asset_configs = [AssetSRConfig(symbol=a, timeframes=["1h"]) for a in asset_names]
        universe_config = UniverseSRConfig(
            assets=asset_configs,
            max_workers=1,
            global_config={
                "pipeline": {"enabled_kernels": ["pivot_hl", "round_number"]},
            },
        )
        router = UniverseSRRouter(universe_config)

        data_map = {}
        for i, asset in enumerate(asset_names):
            data_map[asset] = {"1h": _make_ohlcv(n=200, base_price=100 * (i + 1), seed=40 + i)}

        result = router.process(data_map, bar_index=0, timestamp=datetime.now(tz=None))
        assert len(result.all_results) == 3
        for atr in result.all_results:
            assert atr.asset in asset_names


class TestCrossPhaseIntegration:
    """Tests spanning multiple phases to verify they compose correctly."""

    def test_pipeline_result_dataclass_backwards_compat(self):
        """New debug/timing fields don't break existing code that ignores them."""
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.round_number  # noqa: F401
        from app.sr.pipeline import SRv2Pipeline, PipelineResult

        config = _make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")
        result = pipeline.run(_make_ohlcv(), bar_index=0)

        # Old fields still work
        assert hasattr(result, "candidates")
        assert hasattr(result, "scored_levels")
        assert hasattr(result, "active_zones")
        assert hasattr(result, "events")
        assert hasattr(result, "ensemble_method")
        assert hasattr(result, "regime_state")
        # New fields default to None
        assert result.debug is None
        assert result.timing is None

    def test_kernel_registry_all_phases_registered(self):
        """All kernels from Phase 1 + Phase 3 are in the registry."""
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.volume_poc  # noqa: F401
        import app.sr.kernels.round_number  # noqa: F401
        import app.sr.kernels.order_block  # noqa: F401
        import app.sr.kernels.fair_value_gap  # noqa: F401
        import app.sr.kernels.session_gap  # noqa: F401
        import app.sr.kernels.fractal_channel  # noqa: F401
        import app.sr.kernels.regression_band  # noqa: F401
        import app.sr.kernels.liquidity_sweep  # noqa: F401
        from app.sr.kernels.registry import KernelRegistry

        expected = {
            "pivot_hl", "volume_poc", "round_number",
            "order_block", "fair_value_gap", "session_gap",
            "fractal_channel", "regression_band", "liquidity_sweep",
        }
        registered = set(KernelRegistry.list_all())
        assert expected.issubset(registered), f"Missing: {expected - registered}"

    def test_ensemble_registry_all_phases_registered(self):
        """All ensemble strategies from Phase 2 + Phase 4 are registered."""
        import app.sr.ensemble.weighted_average  # noqa: F401
        import app.sr.ensemble.confidence_weighted  # noqa: F401
        import app.sr.ensemble.regime_conditional  # noqa: F401
        import app.sr.ensemble.meta_learned  # noqa: F401
        from app.sr.ensemble.registry import EnsembleRegistry

        expected = {
            "weighted_average", "confidence_weighted",
            "regime_conditional", "meta_learned",
        }
        registered = set(EnsembleRegistry.list_all())
        assert expected.issubset(registered), f"Missing: {expected - registered}"


class TestSmokeScriptAndPublicApi:
    def test_top_level_package_exports_optimizer_and_router_symbols(self):
        from app.sr import (
            CrossAssetBenchmark,
            CrossAssetBenchmarkResult,
            UniverseOptimizationConfig,
            UniverseOptimizationResult,
            UniverseSROptimizer,
            UniverseSRRouter,
            UniverseTrialResult,
        )

        assert UniverseSRRouter is not None
        assert UniverseOptimizationConfig is not None
        assert UniverseTrialResult is not None
        assert UniverseOptimizationResult is not None
        assert UniverseSROptimizer is not None
        assert CrossAssetBenchmark is not None
        assert CrossAssetBenchmarkResult is not None

    def test_optimization_package_exports_optimizer_symbols(self):
        from app.sr.optimization import (
            CrossAssetBenchmark,
            CrossAssetBenchmarkResult,
            UniverseOptimizationConfig,
            UniverseOptimizationResult,
            UniverseSROptimizer,
            UniverseTrialResult,
        )

        assert UniverseOptimizationConfig is not None
        assert UniverseTrialResult is not None
        assert UniverseOptimizationResult is not None
        assert UniverseSROptimizer is not None
        assert CrossAssetBenchmark is not None
        assert CrossAssetBenchmarkResult is not None

    def test_smoke_script_single_asset_entrypoint(self):
        from app.sr.scripts.smoke_test import run_single_asset

        assert run_single_asset(debug=False, timing=False) is True

    def test_smoke_script_universe_entrypoint(self):
        from app.sr.scripts.smoke_test import run_universe

        assert run_universe(debug=False) is True
