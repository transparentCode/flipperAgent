"""
S/R v2 Phase 2 Unit Tests
=========================
Tests for:
  - Ensemble base / registry
  - WeightedAverageEnsemble
  - ConfidenceWeightedEnsemble
  - RegimeConditionalEnsemble
  - RegimeGate + RegimeProvider
  - ZoneLifecycleManager (state machine)
  - SRv2Pipeline (integration)
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import pytest

from app.sr.models import LevelType
from app.sr.models import (
    AssetMetadata,
    CandidateLevel,
    LevelFeatureVector,
    RuleDerivedParams,
    ScoredLevel,
    ZoneLifecycleEvent,
    ZoneStatus,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    return datetime.now(UTC)

def _make_ohlcv(
    n: int = 200,
    base_price: float = 100.0,
    volatility: float = 0.02,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    closes = [base_price]
    for i in range(1, n):
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


def _make_ohlcv_with_levels(
    n: int = 300,
    support_price: float = 95.0,
    resistance_price: float = 105.0,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="1h")
    mid = (support_price + resistance_price) / 2
    amplitude = (resistance_price - support_price) / 2
    t = np.linspace(0, 6 * np.pi, n)
    base = mid + amplitude * np.sin(t)
    closes = base + rng.randn(n) * 0.3
    highs = closes + rng.uniform(0.1, 0.5, n)
    lows = closes - rng.uniform(0.1, 0.5, n)
    opens = closes + rng.uniform(-0.2, 0.2, n)
    volumes = rng.uniform(200, 800, n)
    for i in range(n):
        if closes[i] > resistance_price - 1 or closes[i] < support_price + 1:
            volumes[i] *= 2
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=dates,
    )


def _make_candidate(
    price: float = 100.0,
    level_type: LevelType = LevelType.SUPPORT,
    kernel_name: str = "pivot_hl",
    raw_score: float = 0.7,
    atr: float = 2.0,
) -> CandidateLevel:
    return CandidateLevel(
        center_price=price,
        lower_bound=price - 0.1 * atr,
        upper_bound=price + 0.1 * atr,
        level_type=level_type,
        kernel_name=kernel_name,
        timeframe="1h",
        raw_score=raw_score,
        metadata={},
        timestamp=datetime(2025, 1, 1),
        atr_at_detection=atr,
    )


def _make_feature_vector(**kwargs) -> LevelFeatureVector:
    return LevelFeatureVector(**kwargs)


def _make_scored_level(
    price: float = 100.0,
    strength: float = 0.6,
    kernel_name: str = "pivot_hl",
    level_type: LevelType = LevelType.SUPPORT,
    atr: float = 2.0,
) -> ScoredLevel:
    c = _make_candidate(price=price, kernel_name=kernel_name,
                        level_type=level_type, atr=atr)
    return ScoredLevel(
        candidate=c,
        features=LevelFeatureVector(kernel_agreement=1, touch_count=2),
        strength=strength,
        confidence=0.5,
        contributing_kernels=[kernel_name],
        ensemble_method="weighted_average",
    )


def _default_metadata() -> AssetMetadata:
    return AssetMetadata(
        profile="crypto", trading_hours_per_day=24.0,
        trading_days_per_week=7, has_session_gaps=False,
        gap_breakout_policy="gap_ignored", gap_escalation_atr=999.0,
        session_lookback_hours=[24, 168, 720],
        round_number_mode="decimal", ex_dividend_filter=False,
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


@pytest.fixture
def ohlcv():
    return _make_ohlcv()


@pytest.fixture
def ohlcv_with_levels():
    return _make_ohlcv_with_levels()


# ===================================================================
# 1. ENSEMBLE REGISTRY
# ===================================================================

class TestEnsembleRegistry:
    def test_strategies_registered(self):
        from app.sr.ensemble.registry import EnsembleRegistry
        import app.sr.ensemble.weighted_average  # noqa: F401
        import app.sr.ensemble.confidence_weighted  # noqa: F401
        import app.sr.ensemble.regime_conditional  # noqa: F401

        assert EnsembleRegistry.has("weighted_average")
        assert EnsembleRegistry.has("confidence_weighted")
        assert EnsembleRegistry.has("regime_conditional")

    def test_list_all(self):
        from app.sr.ensemble.registry import EnsembleRegistry
        names = EnsembleRegistry.list_all()
        assert len(names) >= 3

    def test_create_instance(self):
        from app.sr.ensemble.registry import EnsembleRegistry
        from app.sr.ensemble.base import BaseEnsembleStrategy
        import app.sr.ensemble.weighted_average  # noqa: F401

        strategy = EnsembleRegistry.create("weighted_average")
        assert strategy is not None
        assert isinstance(strategy, BaseEnsembleStrategy)
        assert strategy.strategy_name == "weighted_average"

    def test_nonexistent(self):
        from app.sr.ensemble.registry import EnsembleRegistry
        assert EnsembleRegistry.create("nonexistent_xyz") is None


# ===================================================================
# 2. WEIGHTED AVERAGE ENSEMBLE
# ===================================================================

class TestWeightedAverageEnsemble:
    def test_empty_candidates(self):
        from app.sr.ensemble.weighted_average import WeightedAverageEnsemble
        e = WeightedAverageEnsemble()
        result = e.score([], {}, {})
        assert result == []

    def test_single_candidate(self):
        from app.sr.ensemble.weighted_average import WeightedAverageEnsemble
        e = WeightedAverageEnsemble()
        c = _make_candidate(raw_score=0.8)
        key = e.candidate_key(c)
        fv = _make_feature_vector(touch_count=3, kernel_agreement=1)

        result = e.score([c], {key: fv}, {"structural_vs_micro_ratio": 0.5})
        assert len(result) == 1
        assert result[0].strength == pytest.approx(0.8)
        assert result[0].confidence > 0
        assert result[0].ensemble_method == "weighted_average"

    def test_single_micro_candidate_uses_full_weight(self):
        from app.sr.ensemble.weighted_average import WeightedAverageEnsemble
        e = WeightedAverageEnsemble()
        c = _make_candidate(kernel_name="volume_poc", raw_score=0.8)
        key = e.candidate_key(c)

        result = e.score([c], {key: _make_feature_vector()}, {"structural_vs_micro_ratio": 0.8})
        assert len(result) == 1
        assert result[0].strength == pytest.approx(0.8)

    def test_structural_vs_micro_ratio(self):
        from app.sr.ensemble.weighted_average import WeightedAverageEnsemble
        e = WeightedAverageEnsemble()

        c_pivot = _make_candidate(kernel_name="pivot_hl", raw_score=0.8)
        c_vp = _make_candidate(kernel_name="volume_poc", raw_score=0.8, price=101.0)

        features = {
            e.candidate_key(c_pivot): _make_feature_vector(kernel_agreement=1),
            e.candidate_key(c_vp): _make_feature_vector(kernel_agreement=1),
        }

        # High structural ratio → pivot gets more weight
        result_high = e.score(
            [c_pivot, c_vp], features,
            {"structural_vs_micro_ratio": 0.8},
        )
        pivot_strength_high = result_high[0].strength

        result_low = e.score(
            [c_pivot, c_vp], features,
            {"structural_vs_micro_ratio": 0.2},
        )
        pivot_strength_low = result_low[0].strength

        assert pivot_strength_high > pivot_strength_low

    def test_contributing_kernels(self):
        from app.sr.ensemble.weighted_average import WeightedAverageEnsemble
        e = WeightedAverageEnsemble()

        # Two candidates at same price from different kernels
        c1 = _make_candidate(kernel_name="pivot_hl", price=100.0)
        c2 = _make_candidate(kernel_name="volume_poc", price=100.1)  # within 0.5 ATR

        features = {
            e.candidate_key(c1): _make_feature_vector(),
            e.candidate_key(c2): _make_feature_vector(),
        }

        result = e.score([c1, c2], features, {})
        # Both should list both kernels as contributing
        assert len(result[0].contributing_kernels) == 2

    def test_confidence_from_features(self):
        from app.sr.ensemble.weighted_average import WeightedAverageEnsemble
        e = WeightedAverageEnsemble()

        c = _make_candidate()
        # Rich features → high confidence
        fv_rich = _make_feature_vector(
            touch_count=5, kernel_agreement=3,
            rejection_ratio=0.8, volume_at_touches=2.0,
        )
        # Poor features → low confidence
        fv_poor = _make_feature_vector(
            touch_count=0, kernel_agreement=1,
            rejection_ratio=0.0, volume_at_touches=0.0,
        )

        r_rich = e.score([c], {e.candidate_key(c): fv_rich}, {})
        r_poor = e.score([c], {e.candidate_key(c): fv_poor}, {})

        assert r_rich[0].confidence > r_poor[0].confidence


# ===================================================================
# 3. CONFIDENCE WEIGHTED ENSEMBLE
# ===================================================================

class TestConfidenceWeightedEnsemble:
    def test_higher_score_gets_higher_strength(self):
        from app.sr.ensemble.confidence_weighted import ConfidenceWeightedEnsemble
        e = ConfidenceWeightedEnsemble()

        c_high = _make_candidate(raw_score=0.9, price=100.0, kernel_name="pivot_hl")
        c_low = _make_candidate(raw_score=0.3, price=102.0, kernel_name="pivot_hl")

        features = {
            e.candidate_key(c_high): _make_feature_vector(),
            e.candidate_key(c_low): _make_feature_vector(),
        }

        result = e.score([c_high, c_low], features, {})
        assert result[0].strength > result[1].strength
        assert result[0].ensemble_method == "confidence_weighted"

    def test_empty(self):
        from app.sr.ensemble.confidence_weighted import ConfidenceWeightedEnsemble
        assert ConfidenceWeightedEnsemble().score([], {}, {}) == []


# ===================================================================
# 4. REGIME CONDITIONAL ENSEMBLE
# ===================================================================

class TestRegimeConditionalEnsemble:
    def test_fallback_without_regime(self):
        from app.sr.ensemble.regime_conditional import RegimeConditionalEnsemble
        e = RegimeConditionalEnsemble()

        c = _make_candidate()
        features = {e.candidate_key(c): _make_feature_vector(kernel_agreement=1)}

        # No regime_state in config → fallback to weighted_average
        result = e.score([c], features, {})
        assert len(result) == 1
        assert result[0].ensemble_method == "weighted_average"  # fell back

    def test_regime_trending_multiplier(self):
        from app.sr.ensemble.regime_conditional import RegimeConditionalEnsemble
        e = RegimeConditionalEnsemble()

        c = _make_candidate(raw_score=0.7)
        features = {e.candidate_key(c): _make_feature_vector(kernel_agreement=1)}

        config_trending = {
            "regime_state": "trending",
            "regime_weights": {"trending": 1.5, "ranging": 1.0, "volatile": 0.8},
            "structural_vs_micro_ratio": 0.5,
        }
        config_ranging = {
            "regime_state": "ranging",
            "regime_weights": {"trending": 1.5, "ranging": 1.0, "volatile": 0.8},
            "structural_vs_micro_ratio": 0.5,
        }

        r_trend = e.score([c], features, config_trending)
        r_range = e.score([c], features, config_ranging)

        # Trending with multiplier 1.5 should produce higher strength
        assert r_trend[0].strength >= r_range[0].strength
        assert r_trend[0].ensemble_method == "regime_conditional"

    def test_regime_alignment_affects_confidence(self):
        from app.sr.ensemble.regime_conditional import RegimeConditionalEnsemble
        e = RegimeConditionalEnsemble()

        c = _make_candidate()
        fv_aligned = _make_feature_vector(regime_alignment=0.5, kernel_agreement=1)
        fv_opposed = _make_feature_vector(regime_alignment=-0.5, kernel_agreement=1)

        config = {
            "regime_state": "ranging",
            "regime_weights": {"ranging": 1.0},
            "structural_vs_micro_ratio": 0.5,
        }

        r_aligned = e.score([c], {e.candidate_key(c): fv_aligned}, config)
        r_opposed = e.score([c], {e.candidate_key(c): fv_opposed}, config)

        assert r_aligned[0].confidence > r_opposed[0].confidence


# ===================================================================
# 5. REGIME GATE
# ===================================================================

class TestRegimeGate:
    def test_no_provider(self):
        from app.sr.regime_gate import RegimeGate
        gate = RegimeGate(provider=None)
        assert not gate.is_available
        assert gate.get_regime_or_none("BTC", "1h") is None
        assert gate.get_confidence("BTC", "1h") == 0.0

    def test_low_confidence_gated(self):
        from app.sr.regime_gate import RegimeGate

        class LowConfProvider:
            def get_regime(self, asset, tf):
                return "trending"
            def get_regime_confidence(self, asset, tf):
                return 0.2  # Below default 0.5 threshold

        gate = RegimeGate(provider=LowConfProvider(), config={"min_confidence": 0.5})
        assert gate.is_available
        assert gate.get_regime_or_none("BTC", "1h") is None

    def test_high_confidence_passes(self):
        from app.sr.regime_gate import RegimeGate

        class GoodProvider:
            def get_regime(self, asset, tf):
                return "ranging"
            def get_regime_confidence(self, asset, tf):
                return 0.9

        gate = RegimeGate(provider=GoodProvider(), config={"min_confidence": 0.5})
        assert gate.get_regime_or_none("BTC", "1h") == "ranging"

    def test_high_entropy_gated(self):
        from app.sr.regime_gate import RegimeGate

        call_count = 0

        class UnstableProvider:
            def get_regime(self, asset, tf):
                nonlocal call_count
                call_count += 1
                # Alternating labels → high entropy
                return "trending" if call_count % 2 == 0 else "ranging"
            def get_regime_confidence(self, asset, tf):
                return 0.9

        gate = RegimeGate(
            provider=UnstableProvider(),
            config={"min_confidence": 0.5, "max_entropy": 0.5, "stability_window_bars": 10},
        )

        # First few calls build up history
        for _ in range(10):
            gate.get_regime_or_none("BTC", "1h")

        # After enough oscillation, entropy should be high → gated
        result = gate.get_regime_or_none("BTC", "1h")
        assert result is None  # High entropy → gated

    def test_protocol_compliance(self):
        from app.sr.regime_gate import RegimeProvider

        class ValidProvider:
            def get_regime(self, asset: str, timeframe: str) -> Optional[str]:
                return "trending"
            def get_regime_confidence(self, asset: str, timeframe: str) -> float:
                return 0.8

        assert isinstance(ValidProvider(), RegimeProvider)


# ===================================================================
# 6. ZONE LIFECYCLE MANAGER
# ===================================================================

class TestZoneLifecycleManager:
    def _make_lifecycle_config(self, **kwargs) -> Dict[str, Any]:
        defaults = {
            "age_lambda": 0.002,
            "inactivity_decay": 0.8,
            "min_strength": 0.3,
            "breakout_confirm_bars": 3,
            "false_breakout_window": 6,
            "inactivity_threshold": 80,
            "max_active_zones": 10,
            "breakout_atr_threshold": 0.3,
            "flip_require_retest": True,
            "min_touches_to_confirm": 1,
        }
        defaults.update(kwargs)
        return defaults

    def test_ingest_creates_zones(self):
        from app.sr.lifecycle.state_machine import ZoneLifecycleManager

        mgr = ZoneLifecycleManager(self._make_lifecycle_config())
        sl = _make_scored_level(strength=0.6)

        new = mgr.ingest_scored_levels([sl], bar_index=0, timestamp=_utc_now())
        assert len(new) == 1
        # Should be auto-promoted to ACTIVE (strength >= min_strength)
        assert new[0].status == ZoneStatus.ACTIVE

    def test_forming_not_promoted_if_weak(self):
        from app.sr.lifecycle.state_machine import ZoneLifecycleManager

        mgr = ZoneLifecycleManager(self._make_lifecycle_config(min_strength=0.8))
        sl = _make_scored_level(strength=0.5)

        new = mgr.ingest_scored_levels([sl], bar_index=0, timestamp=_utc_now())
        assert len(new) == 1
        assert new[0].status == ZoneStatus.FORMING

    def test_deduplication(self):
        from app.sr.lifecycle.state_machine import ZoneLifecycleManager

        mgr = ZoneLifecycleManager(self._make_lifecycle_config())
        sl1 = _make_scored_level(price=100.0, strength=0.6)
        sl2 = _make_scored_level(price=100.3, strength=0.5)  # within 0.5 ATR

        mgr.ingest_scored_levels([sl1], bar_index=0, timestamp=_utc_now())
        new2 = mgr.ingest_scored_levels([sl2], bar_index=1, timestamp=_utc_now())
        assert len(new2) == 0  # deduplicated

    def test_age_decay(self):
        from app.sr.lifecycle.state_machine import ZoneLifecycleManager

        mgr = ZoneLifecycleManager(self._make_lifecycle_config(age_lambda=0.01))
        sl = _make_scored_level(price=100.0, strength=0.8)
        mgr.ingest_scored_levels([sl], bar_index=0, timestamp=_utc_now())

        initial_strength = mgr.active_zones[0].strength

        # Simulate 50 bars with price away from zone
        for i in range(1, 51):
            mgr.update(
                current_price=110.0, current_volume=500, avg_volume=400,
                atr=2.0, bar_index=i, timestamp=_utc_now(),
            )

        # Strength should have decayed
        assert mgr.active_zones[0].strength < initial_strength

    def test_breakout_transition(self):
        from app.sr.lifecycle.state_machine import ZoneLifecycleManager

        mgr = ZoneLifecycleManager(self._make_lifecycle_config())
        sl = _make_scored_level(price=100.0, level_type=LevelType.SUPPORT, strength=0.8)
        mgr.ingest_scored_levels([sl], bar_index=0, timestamp=_utc_now())

        # Price breaks below support
        events = mgr.update(
            current_price=99.0,  # below lower_bound (99.8) - 0.3*2 = 99.2
            current_volume=600, avg_volume=400,
            atr=2.0, bar_index=1, timestamp=_utc_now(),
        )

        # Check if zone is now BROKEN
        zone = mgr.active_zones[0] if mgr.active_zones else None
        broken_zones = [z for z in mgr.all_zones if z.status == ZoneStatus.BROKEN]
        # Price 99.0 < lower_bound(99.8) - threshold(0.6) = 99.2 → broken
        assert len(broken_zones) == 1

    def test_touch_increments(self):
        from app.sr.lifecycle.state_machine import ZoneLifecycleManager

        mgr = ZoneLifecycleManager(self._make_lifecycle_config())
        sl = _make_scored_level(price=100.0, strength=0.8)
        mgr.ingest_scored_levels([sl], bar_index=0, timestamp=_utc_now())

        # Price touches the zone
        mgr.update(
            current_price=100.0, current_volume=500, avg_volume=400,
            atr=2.0, bar_index=1, timestamp=_utc_now(),
        )

        zone = mgr.active_zones[0]
        assert zone.touch_count >= 1

    def test_max_zones_pruning(self):
        from app.sr.lifecycle.state_machine import ZoneLifecycleManager

        mgr = ZoneLifecycleManager(self._make_lifecycle_config(max_active_zones=3))

        # Add 5 zones at different prices
        for i in range(5):
            sl = _make_scored_level(price=90.0 + i * 5.0, strength=0.4 + i * 0.1)
            mgr.ingest_scored_levels([sl], bar_index=i, timestamp=_utc_now())

        # Trigger update to prune
        mgr.update(
            current_price=110.0, current_volume=500, avg_volume=400,
            atr=2.0, bar_index=10, timestamp=_utc_now(),
        )

        assert len(mgr.active_zones) <= 3

    def test_events_are_recorded(self):
        from app.sr.lifecycle.state_machine import ZoneLifecycleManager

        mgr = ZoneLifecycleManager(self._make_lifecycle_config())
        sl = _make_scored_level(price=100.0, strength=0.6)
        new = mgr.ingest_scored_levels([sl], bar_index=0, timestamp=_utc_now())

        # Zone should have events
        assert len(new[0].events) >= 1


# ===================================================================
# 7. SRv2 PIPELINE (INTEGRATION)
# ===================================================================

class TestSRv2Pipeline:
    def _make_resolved_config(self):
        from app.sr.config_schema import (
            SRResolvedConfig, PipelineConfig, EnsembleConfig,
            LifecycleConfig, EnhancementConfig,
            RegimeConfig, RuleDerivedConfig,
        )

        return SRResolvedConfig(
            metadata=_default_metadata(),
            pipeline=PipelineConfig(
                enabled_kernels=["pivot_hl", "volume_poc"],
                min_emit_strength=0.0,
                max_new_zones_per_bar=0,
            ),
            kernels={
                "pivot_hl": {"historical_depth": 500, "smoothing_period": 3},
                "volume_poc": {
                    "num_bins": 50, "value_area_pct": 0.70,
                    "poc_strength": 0.9, "vah_val_strength": 0.7,
                    "hvn_strength": 0.6, "max_hvn_count": 3,
                    "hvn_prominence": 0.2,
                },
            },
            ensemble=EnsembleConfig(
                method="weighted_average",
                structural_vs_micro_ratio=0.5,
            ),
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

    def test_pipeline_bootstraps_kernels_without_manual_imports(self):
        from app.sr.kernels.registry import KernelRegistry
        from app.sr.pipeline import SRv2Pipeline
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.volume_poc  # noqa: F401

        KernelRegistry.clear()

        config = self._make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")

        assert KernelRegistry.has("pivot_hl")
        assert KernelRegistry.has("volume_poc")
        assert set(config.pipeline.enabled_kernels).issubset(pipeline._kernels)

    def test_pipeline_smoke(self, ohlcv_with_levels):
        from app.sr.pipeline import SRv2Pipeline
        # Ensure kernel modules are imported
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.volume_poc  # noqa: F401

        config = self._make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")

        result = pipeline.run(ohlcv_with_levels, bar_index=0)

        assert len(result.candidates) > 0
        assert len(result.scored_levels) > 0
        assert result.ensemble_method == "weighted_average"
        assert result.regime_state is None  # No regime gate

    def test_pipeline_zones_accumulate(self, ohlcv_with_levels):
        from app.sr.pipeline import SRv2Pipeline
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.volume_poc  # noqa: F401

        config = self._make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")

        # Run twice — zones should accumulate (deduplicated)
        r1 = pipeline.run(ohlcv_with_levels, bar_index=0)
        r2 = pipeline.run(ohlcv_with_levels, bar_index=1)

        # Active zones should exist
        assert len(pipeline.active_zones) > 0

    def test_pipeline_with_regime_gate(self, ohlcv_with_levels):
        from app.sr.pipeline import SRv2Pipeline
        from app.sr.regime_gate import RegimeGate
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.volume_poc  # noqa: F401

        class TestProvider:
            def get_regime(self, asset, tf):
                return "ranging"
            def get_regime_confidence(self, asset, tf):
                return 0.9

        gate = RegimeGate(provider=TestProvider())
        config = self._make_resolved_config()
        pipeline = SRv2Pipeline(config, regime_gate=gate, asset="TEST", timeframe="1h")

        result = pipeline.run(ohlcv_with_levels, bar_index=0)
        assert result.regime_state == "ranging"

    def test_pipeline_result_structure(self, ohlcv_with_levels):
        from app.sr.pipeline import SRv2Pipeline, PipelineResult
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.volume_poc  # noqa: F401

        config = self._make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")

        result = pipeline.run(ohlcv_with_levels, bar_index=0)

        assert isinstance(result, PipelineResult)
        assert hasattr(result, "candidates")
        assert hasattr(result, "scored_levels")
        assert hasattr(result, "active_zones")
        assert hasattr(result, "events")
        assert hasattr(result, "new_zones")
        assert hasattr(result, "ensemble_method")

    def test_pipeline_raises_when_any_enabled_kernel_fails(self, ohlcv_with_levels, monkeypatch):
        from app.sr.pipeline import PipelineKernelError, SRv2Pipeline
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.volume_poc  # noqa: F401

        config = self._make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")

        def _boom(df, config):
            raise ValueError("forced kernel failure")

        monkeypatch.setattr(pipeline._kernels["pivot_hl"], "compute", _boom)

        with pytest.raises(
            PipelineKernelError,
            match=r"kernels failed: pivot_hl",
        ):
            pipeline.run(ohlcv_with_levels, bar_index=0)

    def test_event_fingerprint_uses_absolute_timestamp(self):
        from dataclasses import replace

        from app.sr.pipeline import SRv2Pipeline

        config = self._make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")

        base = _make_candidate(
            price=100.0,
            level_type=LevelType.SUPPORT,
            kernel_name="fair_value_gap",
            atr=2.0,
        )
        base = replace(
            base,
            metadata={"fvg_type": "bullish", "displacement_index": 17},
            timestamp=datetime(2025, 1, 5, 12, 0, tzinfo=UTC),
        )
        shifted_window = replace(
            base,
            metadata={"fvg_type": "bullish", "displacement_index": 9},
        )
        later_event = replace(
            base,
            timestamp=datetime(2025, 1, 5, 13, 0, tzinfo=UTC),
        )

        assert pipeline._fingerprint(base) == pipeline._fingerprint(shifted_window)
        assert pipeline._fingerprint(base) != pipeline._fingerprint(later_event)

    def test_pipeline_dedup_cross_bar_cache_evicts_stale(self):
        from app.sr.pipeline import SRv2Pipeline
        from dataclasses import replace

        config = self._make_resolved_config()
        pipeline = SRv2Pipeline(config, asset="TEST", timeframe="1h")
        # Ensure staleness bars is 5
        config = replace(config, pipeline=replace(config.pipeline, candidate_dedup_staleness_bars=5))

        base_candidate = _make_candidate(
            price=100.0,
            level_type=LevelType.SUPPORT,
            kernel_name="fair_value_gap",
            atr=2.0,
        )
        base_candidate = replace(base_candidate, metadata={"fvg_type": "bullish", "displacement_index": 17})

        # Bar 10: initial detection
        out1 = pipeline._dedup_cross_bar([base_candidate], bar_index=10)
        assert len(out1) == 1

        # Bar 11: should be suppressed
        out2 = pipeline._dedup_cross_bar([base_candidate], bar_index=11)
        assert len(out2) == 0
        
        # Cache hits correctly updated last-seen? 
        # Actually pipeline checks cache first, so it doesn't update the last-seen if it suppresses.
        # Wait, the code says:
        # cache key = _fingerprint... if key in cache and cache[key] >= eviction_horizon, suppress.
        # Else add to cache, set cache[key] = bar_index.
        # So eviction horizon is bar_index - staleness_bars (16 - 5 = 11).
        
        # Bar 16: stale enough (horizon is 16 - 5 = 11 > 10). Should emit.
        out3 = pipeline._dedup_cross_bar([base_candidate], bar_index=16)
        assert len(out3) == 1

        # Check stale keys were removed
        # Wait, out3 updates the key to bar 16.
        # Let's check size of cache.
        assert len(pipeline._candidate_cache) == 1
        assert pipeline._candidate_cache[pipeline._fingerprint(base_candidate)] == 16
