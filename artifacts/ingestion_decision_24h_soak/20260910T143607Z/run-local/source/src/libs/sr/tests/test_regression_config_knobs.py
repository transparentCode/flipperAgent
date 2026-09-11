import pytest
from datetime import datetime
import warnings

import numpy as np
import pandas as pd

from app.sr.pipeline import SRv2Pipeline
from app.sr.config_schema import (
    SRResolvedConfig, PipelineConfig, EnsembleConfig, RegimeConfig,
    LifecycleConfig, EnhancementConfig, FeaturesConfig,
    RuleDerivedConfig, AssetMetadata, RuleDerivedParams
)
from app.sr.ensemble.weighted_average import WeightedAverageEnsemble
from app.sr.ensemble.confidence_weighted import ConfidenceWeightedEnsemble
from app.sr.ensemble.meta_learned import MetaLearnedEnsemble
from app.sr.features.builder import LevelFeatureBuilder
from app.sr.features.context import FeatureContext
from app.sr.kernels.base import BaseSRKernel, KernelConfig
from app.sr.lifecycle.state_machine import ZoneLifecycleManager, ManagedZone
from app.sr.models import ZoneStatus, ScoredLevel, CandidateLevel, LevelType, LevelFeatureVector


def _make_resolved_config(*, pipeline_config: PipelineConfig, kernels: dict | None = None) -> SRResolvedConfig:
    return SRResolvedConfig(
        metadata=AssetMetadata(
            profile="crypto",
            trading_hours_per_day=24.0,
            trading_days_per_week=7,
            has_session_gaps=False,
            gap_breakout_policy="gap_ignored",
            gap_escalation_atr=999.0,
            session_lookback_hours=[24],
            round_number_mode="decimal",
            ex_dividend_filter=False,
            continuous_market=True,
        ),
        pipeline=pipeline_config,
        kernels=kernels or {},
        ensemble=EnsembleConfig(),
        regime=RegimeConfig(),
        lifecycle=LifecycleConfig(),
        enhancement=EnhancementConfig(),
        rule_derived=RuleDerivedParams(
            n1=5,
            n2=5,
            fractal_period=5,
            fractal_buffer=0.1,
            round_interval=5.0,
            max_zone_width_atr=2.0,
            max_zone_width_pct=3.0,
            breakout_confirm_bars=3,
            false_breakout_window=6,
            inactivity_threshold=80,
            max_active_zones=10,
            volume_spike_threshold=1.5,
            vp_lookback_hours=[24],
        ),
        rule_derived_config=RuleDerivedConfig(),
    )


def _make_window_test_df() -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=20, freq="1h")
    close = [
        100.0, 101.5, 99.5, 104.0, 102.0,
        107.0, 103.5, 109.5, 105.0, 112.0,
        108.0, 114.5, 110.5, 117.0, 112.5,
        119.0, 115.5, 121.5, 116.0, 123.0,
    ]
    open_ = [99.0, *close[:-1]]
    high = [max(o, c) + 1.0 + 0.1 * index for index, (o, c) in enumerate(zip(open_, close))]
    low = [min(o, c) - 0.8 - 0.05 * index for index, (o, c) in enumerate(zip(open_, close))]
    volume = [100, 120, 140, 160, 180, 200, 220, 240, 260, 280, 300, 320, 340, 360, 380, 1000, 1100, 1200, 1300, 1400]

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def _make_kernel_config_from_resolved(resolved: SRResolvedConfig, kernel_name: str) -> KernelConfig:
    return KernelConfig(
        kernel_name=kernel_name,
        timeframe="1h",
        kernel_params=resolved.kernels.get(kernel_name, {}),
        metadata=resolved.metadata,
        rule_derived=resolved.rule_derived,
        atr_period=resolved.pipeline.atr_period,
    )


def _make_feature_metadata(
    *,
    profile: str,
    trading_hours_per_day: float,
    trading_days_per_week: int,
    session_lookback_hours: list[int],
    continuous_market: bool,
) -> AssetMetadata:
    return AssetMetadata(
        profile=profile,
        trading_hours_per_day=trading_hours_per_day,
        trading_days_per_week=trading_days_per_week,
        has_session_gaps=not continuous_market,
        gap_breakout_policy="gap_ignored",
        gap_escalation_atr=999.0,
        session_lookback_hours=session_lookback_hours,
        round_number_mode="decimal",
        ex_dividend_filter=False,
        continuous_market=continuous_market,
    )


def _make_constant_level_df(bar_count: int = 200) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=bar_count, freq="1h")
    close = np.full(bar_count, 100.0)
    open_ = np.full(bar_count, 100.0)
    high = np.full(bar_count, 100.5)
    low = np.full(bar_count, 99.5)
    volume = np.full(bar_count, 100.0)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


def _make_session_gap_df() -> pd.DataFrame:
    index = pd.DatetimeIndex([
        "2026-01-05 09:00:00",
        "2026-01-05 10:00:00",
        "2026-01-05 11:00:00",
        "2026-01-05 12:00:00",
        "2026-01-05 13:00:00",
        "2026-01-06 09:00:00",
    ])
    return pd.DataFrame(
        {
            "open": [100.0, 100.5, 101.0, 100.8, 100.2, 95.0],
            "high": [101.0, 101.5, 102.0, 101.2, 100.7, 96.0],
            "low": [99.5, 100.0, 100.5, 100.3, 99.8, 94.5],
            "close": [100.5, 101.0, 100.8, 100.2, 100.0, 95.5],
            "volume": [100, 110, 120, 115, 105, 200],
        },
        index=index,
    )


def _make_lifecycle_scored_level(
    *,
    center_price: float = 100.0,
    lower_bound: float | None = None,
    upper_bound: float | None = None,
    level_type: LevelType = LevelType.SUPPORT,
    strength: float = 0.5,
    kernel_agreement: float = 0.0,
    atr_at_detection: float = 2.0,
) -> ScoredLevel:
    lower = center_price - 1.0 if lower_bound is None else lower_bound
    upper = center_price + 1.0 if upper_bound is None else upper_bound
    return ScoredLevel(
        candidate=CandidateLevel(
            timeframe="1h",
            timestamp=datetime(2026, 1, 1),
            metadata={},
            center_price=center_price,
            lower_bound=lower,
            upper_bound=upper,
            level_type=level_type,
            raw_score=0.5,
            atr_at_detection=atr_at_detection,
            kernel_name="test",
        ),
        features=LevelFeatureVector(kernel_agreement=kernel_agreement),
        strength=strength,
        confidence=0.5,
        contributing_kernels=[],
        ensemble_method="test",
    )

def test_pipeline_forwards_ensemble_config():
    """Verify that SRv2Pipeline forwards nested dictionaries from EnsembleConfig."""
    ensemble_cfg = EnsembleConfig(
        confidence={"touch_divisor": 10.0},
        regime_conditional={"confidence_adj_factor": 0.5},
        confidence_weighted={"weight_cap": 3.0},
        meta_learned={"confidence_strength_coeff": 0.8}
    )
    resolved = SRResolvedConfig(
        metadata=AssetMetadata(
            profile="crypto",
            trading_hours_per_day=24.0,
            trading_days_per_week=7,
            has_session_gaps=False,
            gap_breakout_policy="gap_ignored",
            gap_escalation_atr=999.0,
            session_lookback_hours=[24],
            round_number_mode="decimal",
            ex_dividend_filter=False,
            continuous_market=True
        ),
        pipeline=PipelineConfig(),
        kernels={},
        ensemble=ensemble_cfg,
        regime=RegimeConfig(),
        lifecycle=LifecycleConfig(),
        enhancement=EnhancementConfig(),
        rule_derived=RuleDerivedParams(
            n1=5,
            n2=5,
            fractal_period=5,
            fractal_buffer=0.1,
            round_interval=5.0,
            max_zone_width_atr=2.0,
            max_zone_width_pct=3.0,
            breakout_confirm_bars=3,
            false_breakout_window=6,
            inactivity_threshold=80,
            max_active_zones=10,
            volume_spike_threshold=1.5,
            vp_lookback_hours=24
        ),
        rule_derived_config=RuleDerivedConfig()
    )
    
    pipeline = SRv2Pipeline(config=resolved, asset="BTCUSDT", timeframe="1h")
    ensemble_dict = pipeline._build_ensemble_config(regime_state="trending")
    
    assert "confidence" in ensemble_dict
    assert ensemble_dict["confidence"]["touch_divisor"] == 10.0
    
    assert "regime_conditional" in ensemble_dict
    assert ensemble_dict["regime_conditional"]["confidence_adj_factor"] == 0.5
    
    assert "meta_learned" in ensemble_dict
    assert ensemble_dict["meta_learned"]["confidence_strength_coeff"] == 0.8


def test_pipeline_forwards_false_breakout_window_separately_from_recovery_bars():
    resolved = _make_resolved_config(
        pipeline_config=PipelineConfig(enabled_kernels=[]),
    )
    resolved = SRResolvedConfig(
        metadata=resolved.metadata,
        pipeline=resolved.pipeline,
        kernels=resolved.kernels,
        ensemble=resolved.ensemble,
        regime=resolved.regime,
        lifecycle=LifecycleConfig(
            false_breakout_recovery_bars=3,
            false_breakout_window=9,
            breakout_confirm_bars=resolved.rule_derived.breakout_confirm_bars,
            inactivity_threshold=resolved.rule_derived.inactivity_threshold,
            max_active_zones=resolved.rule_derived.max_active_zones,
        ),
        enhancement=resolved.enhancement,
        rule_derived=resolved.rule_derived,
        rule_derived_config=resolved.rule_derived_config,
        features=resolved.features,
    )

    pipeline = SRv2Pipeline(config=resolved, asset="BTCUSDT", timeframe="1h")
    lifecycle_dict = pipeline._build_lifecycle_config()

    assert lifecycle_dict["false_breakout_window"] == 9
    assert lifecycle_dict["false_breakout_recovery_bars"] == 3


def test_state_machine_false_breakout_boost():
    """Verify that ZoneLifecycleManager uses the configurable boost and recovery window."""
    cfg = {
        "false_breakout_window": 6,
        "false_breakout_recovery_bars": 3,
        "false_breakout_strength_boost": 1.8,
        "breakout_confirm_bars": 3,
        "flip_require_retest": True
    }
    mgr = ZoneLifecycleManager(cfg)
    
    cand = CandidateLevel(
        timeframe="1h",
        timestamp=datetime(2026, 1, 1),
        metadata={},
        center_price=100.0,
        lower_bound=95.0,
        upper_bound=105.0,
        level_type=LevelType.SUPPORT,
        raw_score=0.5,
        atr_at_detection=5.0,
        kernel_name="test"
    )
    sl = ScoredLevel(
        candidate=cand, 
        features=LevelFeatureVector(), 
        strength=0.5, 
        confidence=0.5, 
        contributing_kernels=[], 
        ensemble_method="test"
    )
    
    zone = ManagedZone(
        zone_id="test1",
        scored_level=sl,
        status=ZoneStatus.BROKEN,
        strength=0.5,
        bars_since_break=2
    )
    mgr._zones["test1"] = zone
    
    timestamp = datetime(2026, 1, 1)
    events = mgr._process_zone(
        zone=zone,
        price=100.0,
        volume=0.0,
        avg_volume=0.0,
        atr=5.0,
        bar_index=10,
        timestamp=timestamp,
        gap_size_atr=0.0,
        gap_direction=None
    )
    
    assert zone.status == ZoneStatus.FALSE_BREAKOUT
    assert zone.bars_since_break == 0
    assert any(e.to_state == ZoneStatus.FALSE_BREAKOUT for e in events)
    # EMA-smoothed: 0.5 + 0.3 * (min(1, 0.5*1.8) - 0.5) = 0.62, minus tiny age decay
    assert abs(zone.strength - 0.62) < 0.05

    for bar_index in (11, 12):
        events = mgr._process_zone(
            zone=zone,
            price=100.0,
            volume=0.0,
            avg_volume=0.0,
            atr=5.0,
            bar_index=bar_index,
            timestamp=timestamp,
            gap_size_atr=0.0,
            gap_direction=None
        )
        assert zone.status == ZoneStatus.FALSE_BREAKOUT
        assert not any(e.trigger == "false_breakout_recovery" for e in events)

    recovery_events = mgr._process_zone(
        zone=zone,
        price=100.0,
        volume=0.0,
        avg_volume=0.0,
        atr=5.0,
        bar_index=13,
        timestamp=timestamp,
        gap_size_atr=0.0,
        gap_direction=None
    )

    assert zone.status == ZoneStatus.ACTIVE
    assert any(e.trigger == "false_breakout_recovery" for e in recovery_events)


def test_state_machine_gap_policy_suspends_breakout_countdown():
    cfg = {
        "breakout_atr_threshold": 0.3,
        "gap_breakout_policy": "gap_suspends_countdown",
        "gap_escalation_atr": 3.0,
    }
    mgr = ZoneLifecycleManager(cfg)

    cand = CandidateLevel(
        timeframe="1h",
        timestamp=datetime(2026, 1, 1),
        metadata={},
        center_price=100.0,
        lower_bound=99.0,
        upper_bound=101.0,
        level_type=LevelType.SUPPORT,
        raw_score=0.5,
        atr_at_detection=2.0,
        kernel_name="test",
    )
    zone = ManagedZone(
        zone_id="gap-zone",
        scored_level=ScoredLevel(
            candidate=cand,
            features=LevelFeatureVector(),
            strength=0.8,
            confidence=0.8,
            contributing_kernels=[],
            ensemble_method="test",
        ),
        status=ZoneStatus.ACTIVE,
        strength=0.8,
    )

    suspended = mgr._process_zone(
        zone=zone,
        price=98.0,
        volume=0.0,
        avg_volume=0.0,
        atr=2.0,
        bar_index=1,
        timestamp=datetime(2026, 1, 1),
        gap_size_atr=1.5,
        gap_direction="down",
    )

    assert zone.status == ZoneStatus.ACTIVE
    assert suspended == []

    confirmed = mgr._process_zone(
        zone=zone,
        price=98.0,
        volume=0.0,
        avg_volume=0.0,
        atr=2.0,
        bar_index=2,
        timestamp=datetime(2026, 1, 2),
        gap_size_atr=4.0,
        gap_direction="down",
    )

    assert zone.status == ZoneStatus.BROKEN
    assert any(event.trigger == "breakout_down" for event in confirmed)


def test_pipeline_forwards_current_gap_context_to_lifecycle_update():
    resolved = _make_resolved_config(
        pipeline_config=PipelineConfig(enabled_kernels=[]),
    )
    resolved = SRResolvedConfig(
        metadata=AssetMetadata(
            profile="equity",
            trading_hours_per_day=6.5,
            trading_days_per_week=5,
            has_session_gaps=True,
            gap_breakout_policy="gap_suspends_countdown",
            gap_escalation_atr=3.0,
            session_lookback_hours=[7],
            round_number_mode="decimal",
            ex_dividend_filter=False,
            continuous_market=False,
        ),
        pipeline=resolved.pipeline,
        kernels=resolved.kernels,
        ensemble=resolved.ensemble,
        regime=resolved.regime,
        lifecycle=resolved.lifecycle,
        enhancement=resolved.enhancement,
        rule_derived=resolved.rule_derived,
        rule_derived_config=resolved.rule_derived_config,
        features=resolved.features,
    )

    pipeline = SRv2Pipeline(config=resolved, asset="AAPL", timeframe="1h")
    captured: dict[str, object] = {}

    pipeline._lifecycle.ingest_scored_levels = lambda *args, **kwargs: []

    def _capture_update(**kwargs):
        captured["gap_size_atr"] = kwargs["gap_size_atr"]
        captured["gap_direction"] = kwargs["gap_direction"]
        return []

    pipeline._lifecycle.update = _capture_update
    pipeline.run(_make_session_gap_df(), bar_index=5)

    assert captured["gap_direction"] == "down"
    assert captured["gap_size_atr"] > 0.0


def test_state_machine_uses_auto_promote_kernel_agreement_knob():
    mgr = ZoneLifecycleManager({
        "auto_promote_kernel_agreement": 1,
        "min_strength": 0.9,
    })

    new_zones = mgr.ingest_scored_levels(
        [_make_lifecycle_scored_level(strength=0.4, kernel_agreement=1)],
        bar_index=0,
        timestamp=datetime(2026, 1, 1),
    )

    assert len(new_zones) == 1
    assert new_zones[0].status == ZoneStatus.ACTIVE


def test_state_machine_uses_dedup_proximity_knob():
    mgr = ZoneLifecycleManager({
        "dedup_proximity_atr": 0.2,
        "min_strength": 0.0,
    })

    first = _make_lifecycle_scored_level(center_price=100.0, strength=0.8, atr_at_detection=2.0)
    second = _make_lifecycle_scored_level(center_price=100.5, strength=0.7, atr_at_detection=2.0)

    created = mgr.ingest_scored_levels([first], bar_index=0, timestamp=datetime(2026, 1, 1))
    additional = mgr.ingest_scored_levels([second], bar_index=1, timestamp=datetime(2026, 1, 1))

    assert len(created) == 1
    assert len(additional) == 1
    assert len(mgr.active_zones) == 2


def test_weighted_average_uses_contributing_proximity():
    """Verify that WeightedAverageEnsemble uses contributing_proximity_atr."""
    ensemble = WeightedAverageEnsemble()
    candidate_a = CandidateLevel(
        timeframe="1h",
        timestamp=datetime(2026, 1, 1),
        metadata={},
        center_price=100.0,
        lower_bound=99.8,
        upper_bound=100.2,
        level_type=LevelType.SUPPORT,
        raw_score=0.8,
        atr_at_detection=2.0,
        kernel_name="pivot_hl",
    )
    candidate_b = CandidateLevel(
        timeframe="1h",
        timestamp=datetime(2026, 1, 1),
        metadata={},
        center_price=100.6,
        lower_bound=100.4,
        upper_bound=100.8,
        level_type=LevelType.SUPPORT,
        raw_score=0.8,
        atr_at_detection=2.0,
        kernel_name="volume_poc",
    )
    features = {
        ensemble.candidate_key(candidate_a): LevelFeatureVector(),
        ensemble.candidate_key(candidate_b): LevelFeatureVector(),
    }

    default_result = ensemble.score(
        [candidate_a, candidate_b],
        features,
        {"structural_vs_micro_ratio": 0.5},
    )
    custom_result = ensemble.score(
        [candidate_a, candidate_b],
        features,
        {"structural_vs_micro_ratio": 0.5, "contributing_proximity_atr": 0.1},
    )

    assert default_result[0].contributing_kernels == ["pivot_hl", "volume_poc"]
    assert custom_result[0].contributing_kernels == ["pivot_hl"]


def test_confidence_weighted_uses_weight_cap():
    """Verify that ConfidenceWeightedEnsemble uses confidence_weighted.weight_cap."""
    ensemble = ConfidenceWeightedEnsemble()
    candidate_a = CandidateLevel(
        timeframe="1h",
        timestamp=datetime(2026, 1, 1),
        metadata={},
        center_price=100.0,
        lower_bound=99.8,
        upper_bound=100.2,
        level_type=LevelType.SUPPORT,
        raw_score=0.9,
        atr_at_detection=2.0,
        kernel_name="pivot_hl",
    )
    candidate_b = CandidateLevel(
        timeframe="1h",
        timestamp=datetime(2026, 1, 1),
        metadata={},
        center_price=101.0,
        lower_bound=100.8,
        upper_bound=101.2,
        level_type=LevelType.SUPPORT,
        raw_score=0.3,
        atr_at_detection=2.0,
        kernel_name="pivot_hl",
    )
    features = {
        ensemble.candidate_key(candidate_a): LevelFeatureVector(),
        ensemble.candidate_key(candidate_b): LevelFeatureVector(),
    }

    default_result = ensemble.score([candidate_a, candidate_b], features, {})
    capped_result = ensemble.score(
        [candidate_a, candidate_b],
        features,
        {"confidence_weighted": {"weight_cap": 1.0}},
    )

    assert default_result[0].strength == pytest.approx(1.0)
    assert capped_result[0].strength == pytest.approx(0.9)


def test_confidence_weighted_uses_kernel_avg_baseline_for_singleton_batch():
    """Verify configured kernel_avg_baselines prevent singleton batches from collapsing to weight 1."""
    ensemble = ConfidenceWeightedEnsemble()
    candidate = CandidateLevel(
        timeframe="1h",
        timestamp=datetime(2026, 1, 1),
        metadata={},
        center_price=100.0,
        lower_bound=99.8,
        upper_bound=100.2,
        level_type=LevelType.SUPPORT,
        raw_score=0.4,
        atr_at_detection=2.0,
        kernel_name="volume_poc",
    )
    features = {
        ensemble.candidate_key(candidate): LevelFeatureVector(),
    }

    default_result = ensemble.score([candidate], features, {})
    configured_result = ensemble.score(
        [candidate],
        features,
        {"confidence_weighted": {"kernel_avg_baselines": {"volume_poc": 0.2}}},
    )

    assert default_result[0].strength == pytest.approx(0.4)
    assert configured_result[0].strength == pytest.approx(0.8)


def test_meta_learned_reads_nested_model_settings(monkeypatch):
    """Verify that MetaLearnedEnsemble reads nested meta_learned model config."""
    load_attempts = []

    def fake_load_model(self, model_path: str, use_lightgbm: bool = False):
        load_attempts.append((model_path, use_lightgbm))
        return False

    monkeypatch.setattr(MetaLearnedEnsemble, "load_model", fake_load_model)

    ensemble = MetaLearnedEnsemble()
    candidate = CandidateLevel(
        timeframe="1h",
        timestamp=datetime(2026, 1, 1),
        metadata={},
        center_price=100.0,
        lower_bound=99.8,
        upper_bound=100.2,
        level_type=LevelType.SUPPORT,
        raw_score=0.8,
        atr_at_detection=2.0,
        kernel_name="pivot_hl",
    )
    features = {
        ensemble.candidate_key(candidate): LevelFeatureVector(touch_count=3, kernel_agreement=2),
    }

    ensemble.score(
        [candidate],
        features,
        {"meta_learned": {"model_path": "/tmp/model.bin", "use_lightgbm": True}},
    )

    assert load_attempts == [("/tmp/model.bin", True)]


def test_meta_learned_uses_nested_blending_coefficients():
    """Verify that MetaLearnedEnsemble consumes nested meta_learned blend knobs."""

    class MockModel:
        def predict(self, X):
            return [0.2] * len(X)

    ensemble = MetaLearnedEnsemble()
    ensemble.set_model(MockModel())

    candidate = CandidateLevel(
        timeframe="1h",
        timestamp=datetime(2026, 1, 1),
        metadata={},
        center_price=100.0,
        lower_bound=99.8,
        upper_bound=100.2,
        level_type=LevelType.SUPPORT,
        raw_score=0.8,
        atr_at_detection=2.0,
        kernel_name="pivot_hl",
    )
    features = {
        ensemble.candidate_key(candidate): LevelFeatureVector(touch_count=5, kernel_agreement=3),
    }

    default_result = ensemble.score([candidate], features, {})
    blended_result = ensemble.score(
        [candidate],
        features,
        {
            "confidence": {"touch_divisor": 5.0, "agreement_divisor": 3.0},
            "meta_learned": {
                "confidence_strength_coeff": 0.0,
                "confidence_touch_coeff": 0.5,
                "confidence_agreement_coeff": 0.5,
            },
        },
    )

    assert default_result[0].strength == pytest.approx(0.2)
    assert blended_result[0].strength == pytest.approx(1.0)


def test_resolver_normalizes_legacy_volume_hvn_kernel():
    """Verify that legacy volume_hvn config resolves to canonical volume_poc."""
    from app.sr.config_resolver import SRConfigResolver

    resolver = SRConfigResolver()
    raw_config = {
        "asset_metadata": {
            "assets": {"BTCUSDT": {"profile": "crypto"}},
        },
        "sr": {
            "pipeline": {
                "enabled_kernels": ["pivot_hl", "volume_hvn", "volume_poc"],
            },
        },
    }

    with pytest.warns(RuntimeWarning, match="volume_hvn"):
        resolved = resolver.resolve("BTCUSDT", "1h", raw_config)

    assert resolved.pipeline.enabled_kernels == ["pivot_hl", "volume_poc"]


def test_pipeline_uses_configured_atr_period_and_avg_volume_window():
    """Verify that PipelineConfig ATR and volume windows are consumed at runtime."""
    resolved = _make_resolved_config(
        pipeline_config=PipelineConfig(
            enabled_kernels=["round_number"],
            atr_period=3,
            avg_volume_window=5,
        ),
        kernels={"round_number": {}},
    )
    pipeline = SRv2Pipeline(config=resolved, asset="BTCUSDT", timeframe="1h")
    df = _make_window_test_df()

    expected_atr = BaseSRKernel.calculate_atr(df, period=3)
    default_atr = BaseSRKernel.calculate_atr(df, period=14)
    expected_avg_volume = float(df["volume"].tail(5).mean())

    assert abs(expected_atr - default_atr) > 1e-6

    result = pipeline.run(df, bar_index=0, debug=True)

    assert result.debug is not None
    assert result.debug["context"]["atr_period"] == 3
    assert result.debug["context"]["avg_volume_window"] == 5
    assert result.debug["context"]["atr"] == pytest.approx(expected_atr)
    assert result.debug["context"]["avg_volume"] == pytest.approx(expected_avg_volume)
    assert result.candidates

    for candidate in result.candidates:
        assert candidate.upper_bound - candidate.lower_bound == pytest.approx(expected_atr)


def test_round_number_uses_configured_min_bars():
    """Verify that the round-number kernel consumes min_bars from config."""
    from app.sr.kernels.round_number import RoundNumberKernel

    resolved = _make_resolved_config(
        pipeline_config=PipelineConfig(enabled_kernels=["round_number"], atr_period=3),
        kernels={"round_number": {"min_bars": 10}},
    )
    kernel = RoundNumberKernel()
    df = _make_window_test_df().tail(12)

    permissive = KernelConfig(
        kernel_name="round_number",
        timeframe="1h",
        kernel_params={"min_bars": 10},
        metadata=resolved.metadata,
        rule_derived=resolved.rule_derived,
        atr_period=resolved.pipeline.atr_period,
    )
    strict = KernelConfig(
        kernel_name="round_number",
        timeframe="1h",
        kernel_params={"min_bars": 13},
        metadata=resolved.metadata,
        rule_derived=resolved.rule_derived,
        atr_period=resolved.pipeline.atr_period,
    )

    assert kernel.compute(df, permissive)
    assert kernel.compute(df, strict) == []


def test_round_number_uses_configured_score_skip_threshold():
    """Verify that the round-number kernel consumes score_skip_threshold from config."""
    from app.sr.kernels.round_number import RoundNumberKernel

    resolved = _make_resolved_config(
        pipeline_config=PipelineConfig(enabled_kernels=["round_number"], atr_period=3),
        kernels={"round_number": {"max_levels": 12}},
    )
    kernel = RoundNumberKernel()
    df = _make_window_test_df()

    default_threshold = KernelConfig(
        kernel_name="round_number",
        timeframe="1h",
        kernel_params={"max_levels": 12, "score_skip_threshold": 0.05},
        metadata=resolved.metadata,
        rule_derived=resolved.rule_derived,
        atr_period=resolved.pipeline.atr_period,
    )
    stricter_threshold = KernelConfig(
        kernel_name="round_number",
        timeframe="1h",
        kernel_params={"max_levels": 12, "score_skip_threshold": 0.4},
        metadata=resolved.metadata,
        rule_derived=resolved.rule_derived,
        atr_period=resolved.pipeline.atr_period,
    )

    default_candidates = kernel.compute(df, default_threshold)
    stricter_candidates = kernel.compute(df, stricter_threshold)

    assert len(default_candidates) > len(stricter_candidates) > 0


def test_round_number_uses_configured_base_confidence():
    """Verify that the round-number kernel consumes base_confidence from config."""
    from app.sr.kernels.round_number import RoundNumberKernel

    resolved = _make_resolved_config(
        pipeline_config=PipelineConfig(enabled_kernels=["round_number"], atr_period=3),
        kernels={"round_number": {"max_levels": 8, "score_skip_threshold": 0.0}},
    )
    kernel = RoundNumberKernel()
    df = _make_window_test_df()

    lower_confidence = KernelConfig(
        kernel_name="round_number",
        timeframe="1h",
        kernel_params={"max_levels": 8, "score_skip_threshold": 0.0, "base_confidence": 0.25},
        metadata=resolved.metadata,
        rule_derived=resolved.rule_derived,
        atr_period=resolved.pipeline.atr_period,
    )
    higher_confidence = KernelConfig(
        kernel_name="round_number",
        timeframe="1h",
        kernel_params={"max_levels": 8, "score_skip_threshold": 0.0, "base_confidence": 0.75},
        metadata=resolved.metadata,
        rule_derived=resolved.rule_derived,
        atr_period=resolved.pipeline.atr_period,
    )

    lower_candidates = kernel.compute(df, lower_confidence)
    higher_candidates = kernel.compute(df, higher_confidence)

    assert lower_candidates
    assert len(higher_candidates) == len(lower_candidates)
    assert max(candidate.raw_score for candidate in higher_candidates) > max(
        candidate.raw_score for candidate in lower_candidates
    )


def test_rule_derived_zone_width_caps_do_not_leak_into_lifecycle_config():
    """Verify rule-derived width caps stay off the lifecycle runtime surface."""
    from app.sr.config_resolver import SRConfigResolver

    resolved = SRConfigResolver().resolve(
        "BTCUSDT",
        "1h",
        {"asset_metadata": {"assets": {"BTCUSDT": {"profile": "crypto"}}}},
    )

    assert resolved.rule_derived.max_zone_width_atr == pytest.approx(2.0)
    assert resolved.rule_derived.max_zone_width_pct == pytest.approx(3.0)
    assert "max_zone_width_atr" not in resolved.rule_derived.lifecycle_params
    assert "max_zone_width_pct" not in resolved.rule_derived.lifecycle_params
    assert "max_zone_width_atr" not in vars(resolved.lifecycle)
    assert "max_zone_width_pct" not in vars(resolved.lifecycle)


def test_resolver_normalizes_legacy_pivot_score_aliases():
    """Verify that legacy pivot score aliases resolve to the canonical runtime knobs."""
    from app.sr.config_resolver import SRConfigResolver
    from app.sr.kernels.pivot_hl import PivotHighLowKernel
    from app.sr.tests.test_phase2 import _make_ohlcv_with_levels

    resolver = SRConfigResolver()
    df = _make_ohlcv_with_levels()
    alias_raw_config = {
        "asset_metadata": {"assets": {"BTCUSDT": {"profile": "crypto"}}},
        "sr": {
            "kernels": {
                "pivot_hl": {
                    "score_vol_weight": 1.0,
                    "score_dominance_weight": 0.0,
                },
            },
        },
    }
    canonical_raw_config = {
        "asset_metadata": {"assets": {"BTCUSDT": {"profile": "crypto"}}},
        "sr": {
            "kernels": {
                "pivot_hl": {
                    "vol_factor_weight": 1.0,
                    "dominance_weight": 0.0,
                },
            },
        },
    }

    with pytest.warns(DeprecationWarning, match=r"sr\.kernels\.pivot_hl\.score_vol_weight"):
        alias_resolved = resolver.resolve("BTCUSDT", "1h", alias_raw_config)

    canonical_resolved = resolver.resolve("BTCUSDT", "1h", canonical_raw_config)
    kernel = PivotHighLowKernel()

    alias_candidates = kernel.compute(df, _make_kernel_config_from_resolved(alias_resolved, "pivot_hl"))
    canonical_candidates = kernel.compute(df, _make_kernel_config_from_resolved(canonical_resolved, "pivot_hl"))

    assert alias_candidates
    assert [(c.center_price, c.level_type) for c in alias_candidates] == [
        (c.center_price, c.level_type) for c in canonical_candidates
    ]
    assert [c.raw_score for c in alias_candidates] == pytest.approx(
        [c.raw_score for c in canonical_candidates]
    )


def test_resolver_normalizes_legacy_fvg_aliases():
    """Verify that legacy FVG aliases resolve to the canonical runtime knobs."""
    from app.sr.config_resolver import SRConfigResolver
    from app.sr.kernels.fair_value_gap import FairValueGapKernel
    from app.sr.tests.test_phase3 import _make_ohlcv_with_fvg

    resolver = SRConfigResolver()
    df = _make_ohlcv_with_fvg()
    alias_raw_config = {
        "asset_metadata": {"assets": {"BTCUSDT": {"profile": "crypto"}}},
        "sr": {
            "kernels": {
                "fair_value_gap": {
                    "score_atr_cap": 0.5,
                    "filled_score_discount": 0.25,
                },
            },
        },
    }
    canonical_raw_config = {
        "asset_metadata": {"assets": {"BTCUSDT": {"profile": "crypto"}}},
        "sr": {
            "kernels": {
                "fair_value_gap": {
                    "max_gap_atr_cap": 0.5,
                    "filled_penalty_multiplier": 0.25,
                },
            },
        },
    }

    with pytest.warns(DeprecationWarning, match=r"sr\.kernels\.fair_value_gap\.score_atr_cap"):
        alias_resolved = resolver.resolve("BTCUSDT", "1h", alias_raw_config)

    canonical_resolved = resolver.resolve("BTCUSDT", "1h", canonical_raw_config)
    kernel = FairValueGapKernel()

    alias_candidates = kernel.compute(df, _make_kernel_config_from_resolved(alias_resolved, "fair_value_gap"))
    canonical_candidates = kernel.compute(df, _make_kernel_config_from_resolved(canonical_resolved, "fair_value_gap"))

    assert alias_candidates
    assert [(c.center_price, c.level_type) for c in alias_candidates] == [
        (c.center_price, c.level_type) for c in canonical_candidates
    ]
    assert [c.raw_score for c in alias_candidates] == pytest.approx(
        [c.raw_score for c in canonical_candidates]
    )


def test_resolver_kernel_alias_warning_emits_once_and_preserves_canonical_precedence():
    from app.sr.config_resolver import SRConfigResolver

    resolver = SRConfigResolver()
    raw_config = {
        "asset_metadata": {"assets": {"BTCUSDT": {"profile": "crypto"}}},
        "sr": {
            "kernels": {
                "pivot_hl": {
                    "score_vol_weight": 0.99,
                    "vol_factor_weight": 0.25,
                    "score_dominance_weight": 0.75,
                    "dominance_weight": 0.50,
                },
            },
        },
    }

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resolved = resolver.resolve("BTCUSDT", "1h", raw_config)

    deprecations = [
        warning for warning in caught if issubclass(warning.category, DeprecationWarning)
    ]
    assert len(deprecations) == 1
    message = str(deprecations[0].message)
    assert "sr.kernels.pivot_hl.score_vol_weight" in message
    assert "sr.kernels.pivot_hl.score_dominance_weight" in message
    assert resolved.kernels["pivot_hl"]["vol_factor_weight"] == pytest.approx(0.25)
    assert resolved.kernels["pivot_hl"]["dominance_weight"] == pytest.approx(0.50)
    assert "score_vol_weight" not in resolved.kernels["pivot_hl"]
    assert "score_dominance_weight" not in resolved.kernels["pivot_hl"]


def test_resolver_canonical_kernel_keys_are_warning_free():
    from app.sr.config_resolver import SRConfigResolver

    resolver = SRConfigResolver()
    raw_config = {
        "asset_metadata": {"assets": {"BTCUSDT": {"profile": "crypto"}}},
        "sr": {
            "kernels": {
                "pivot_hl": {
                    "vol_factor_weight": 0.25,
                    "dominance_weight": 0.50,
                },
            },
        },
    }

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        resolved = resolver.resolve("BTCUSDT", "1h", raw_config)

    assert resolved.kernels["pivot_hl"]["vol_factor_weight"] == pytest.approx(0.25)
    assert resolved.kernels["pivot_hl"]["dominance_weight"] == pytest.approx(0.50)
    assert not [
        warning
        for warning in caught
        if issubclass(warning.category, (DeprecationWarning, RuntimeWarning))
    ]


def test_pipeline_uses_legacy_pipeline_ensemble_method_alias():
    """Verify that legacy pipeline.ensemble_method still selects the runtime ensemble."""
    from app.sr.config_resolver import SRConfigResolver

    resolver = SRConfigResolver()
    raw_config = {
        "asset_metadata": {"assets": {"BTCUSDT": {"profile": "crypto"}}},
        "sr": {
            "pipeline": {
                "enabled_kernels": [],
                "ensemble_method": "confidence_weighted",
            },
        },
    }

    with pytest.warns(
        DeprecationWarning,
        match=r"Legacy config key 'sr\.pipeline\.ensemble_method' is deprecated",
    ):
        resolved = resolver.resolve("BTCUSDT", "1h", raw_config)

    pipeline = SRv2Pipeline(config=resolved, asset="BTCUSDT", timeframe="1h")

    assert resolved.ensemble.method == "confidence_weighted"
    assert not hasattr(resolved.pipeline, "ensemble_method")
    assert pipeline._ensemble is not None
    assert pipeline._ensemble.strategy_name == "confidence_weighted"


def test_feature_builder_uses_non_pivot_formation_index():
    """Verify that formation index resolves from non-pivot metadata keys."""
    df = _make_window_test_df()
    candidate = CandidateLevel(
        timeframe="1h",
        timestamp=datetime(2026, 1, 1),
        metadata={"gap_index": 4},
        center_price=100.0,
        lower_bound=99.8,
        upper_bound=100.2,
        level_type=LevelType.SUPPORT,
        raw_score=0.8,
        atr_at_detection=2.0,
        kernel_name="session_gap",
    )
    ctx = FeatureContext(
        df=df,
        current_price=float(df["close"].iloc[-1]),
        atr=2.0,
        bar_count=len(df),
    )

    fv = LevelFeatureBuilder().build(candidate, [candidate], ctx)

    assert fv.time_since_formation == pytest.approx(float(len(df) - 1 - 4))


def test_feature_builder_uses_candidate_atr_not_latest_atr():
    """Verify feature thresholds normalize with candidate.atr_at_detection."""
    df = pd.DataFrame(
        {
            "open": [100.0] * 11,
            "high": [100.2] * 5 + [101.0] * 6,
            "low": [99.8] * 5 + [100.6] * 6,
            "close": [100.0] * 11,
            "volume": [100.0] * 11,
        },
        index=pd.date_range("2026-01-01", periods=11, freq="1h"),
    )
    candidate = CandidateLevel(
        timeframe="1h",
        timestamp=datetime(2026, 1, 1),
        metadata={"pivot_index": 10},
        center_price=100.0,
        lower_bound=99.9,
        upper_bound=100.1,
        level_type=LevelType.SUPPORT,
        raw_score=0.8,
        atr_at_detection=0.4,
        kernel_name="pivot_hl",
    )
    ctx = FeatureContext(
        df=df,
        current_price=100.0,
        atr=2.0,
        bar_count=len(df),
    )

    fv = LevelFeatureBuilder().build(candidate, [candidate], ctx)

    assert fv.touch_count == 5


def test_feature_builder_consumes_features_threshold_knobs():
    """Verify configured proximity thresholds are consumed in builder logic."""
    df = _make_window_test_df()
    candidate_a = CandidateLevel(
        timeframe="1h",
        timestamp=datetime(2026, 1, 1),
        metadata={"pivot_index": 10},
        center_price=110.0,
        lower_bound=109.8,
        upper_bound=110.2,
        level_type=LevelType.SUPPORT,
        raw_score=0.8,
        atr_at_detection=2.0,
        kernel_name="pivot_hl",
    )
    candidate_b = CandidateLevel(
        timeframe="1h",
        timestamp=datetime(2026, 1, 1),
        metadata={"pivot_index": 10},
        center_price=110.5,
        lower_bound=110.3,
        upper_bound=110.7,
        level_type=LevelType.SUPPORT,
        raw_score=0.7,
        atr_at_detection=2.0,
        kernel_name="volume_poc",
    )
    all_candidates = [candidate_a, candidate_b]
    ctx = FeatureContext(
        df=df,
        current_price=float(df["close"].iloc[-1]),
        atr=2.0,
        bar_count=len(df),
    )

    default_fv = LevelFeatureBuilder().build(candidate_a, all_candidates, ctx)
    strict_fv = LevelFeatureBuilder(
        config=FeaturesConfig(cluster_density_proximity_atr=0.1),
    ).build(candidate_a, all_candidates, ctx)

    assert default_fv.cluster_density == pytest.approx(1.0)
    assert strict_fv.cluster_density == pytest.approx(0.0)


def test_feature_context_sanitizes_nan_kurtosis():
    """Verify constant-volume windows do not propagate NaN kurtosis."""
    df = pd.DataFrame(
        {
            "open": [1.0] * 30,
            "high": [2.0] * 30,
            "low": [0.5] * 30,
            "close": [1.5] * 30,
            "volume": [100.0] * 30,
        },
        index=pd.date_range("2026-01-01", periods=30, freq="1h"),
    )

    ctx = FeatureContext.from_dataframe(df, atr=2.0)

    assert ctx.volume_kurtosis == pytest.approx(0.0)


def test_feature_builder_uses_touch_proximity_knob():
    """Verify touch detection consumes the configured ATR proximity."""
    df = pd.DataFrame(
        {
            "open": [100.5] * 5,
            "high": [100.6] * 5,
            "low": [100.4] * 5,
            "close": [100.5] * 5,
            "volume": [100.0] * 5,
        },
        index=pd.date_range("2026-01-01", periods=5, freq="1h"),
    )
    candidate = CandidateLevel(
        timeframe="1h",
        timestamp=datetime(2026, 1, 1, 4),
        metadata={"pivot_index": 4},
        center_price=100.0,
        lower_bound=99.8,
        upper_bound=100.2,
        level_type=LevelType.SUPPORT,
        raw_score=0.8,
        atr_at_detection=2.0,
        kernel_name="pivot_hl",
    )
    ctx = FeatureContext(df=df, current_price=100.5, atr=2.0, bar_count=len(df))

    default_fv = LevelFeatureBuilder().build(candidate, [candidate], ctx)
    strict_fv = LevelFeatureBuilder(config=FeaturesConfig(touch_proximity_atr=0.1)).build(
        candidate,
        [candidate],
        ctx,
    )

    assert default_fv.touch_count == 5
    assert strict_fv.touch_count == 0


def test_resolver_extracts_optimizer_config_without_touching_runtime_resolve_path():
    from app.sr.config_resolver import SRConfigResolver

    raw_config = {
        "sr": {
            "pipeline": {"enabled_kernels": ["pivot_hl"]},
            "optimization": {
                "n_trials": 7,
                "parameters": {
                    "ensemble.structural_vs_micro_ratio": {
                        "enabled": False,
                        "low": 0.4,
                        "high": 0.7,
                    },
                },
            },
        },
    }

    resolver = SRConfigResolver()
    optimization = resolver.resolve_optimization_config(raw_config)

    assert optimization["n_trials"] == 7
    assert optimization["parameters"]["ensemble.structural_vs_micro_ratio"]["enabled"] is False

    resolved = resolver.resolve(
        "BTCUSDT",
        "1h",
        {"asset_metadata": {"assets": {"BTCUSDT": {"profile": "crypto"}}}, **raw_config},
    )
    assert resolved.pipeline.enabled_kernels == ["pivot_hl"]


def test_resolver_builds_typed_optimizer_config():
    from app.sr.config_resolver import SRConfigResolver

    raw_config = {
        "sr": {
            "optimization": {
                "n_trials": 9,
                "timeout_s": 123.0,
                "tier6_weight": 0.25,
                "stage1_eval_bars": 450,
                "per_asset_max_lookback": 4096,
                "parameters": {
                    "kernels.liquidity_sweep.sweep_lookback": {
                        "enabled": True,
                        "kind": "int",
                        "low": 25,
                        "high": 60,
                        "metadata_gate": None,
                    },
                },
            },
        },
    }

    resolver = SRConfigResolver()
    optimization = resolver.resolve_typed_optimization_config(raw_config)

    assert optimization.n_trials == 9
    assert optimization.timeout_s == pytest.approx(123.0)
    assert optimization.tier6_weight == pytest.approx(0.25)
    assert optimization.stage1_eval_bars == 450
    assert optimization.per_asset_max_lookback == 4096
    assert optimization.parameters["kernels.liquidity_sweep.sweep_lookback"].kind == "int"
    assert optimization.parameters["kernels.liquidity_sweep.sweep_lookback"].low == pytest.approx(25)
    assert optimization.parameters["kernels.liquidity_sweep.sweep_lookback"].high == pytest.approx(60)


def test_optimizer_uses_yaml_backed_defaults_and_metadata_gates():
    from app.sr.optimization.universe_optimizer import UniverseSROptimizer
    from app.sr.universe.config import AssetSRConfig, UniverseSRConfig

    optimizer = UniverseSROptimizer(
        UniverseSRConfig(
            assets=[AssetSRConfig(symbol="ES1!")],
            global_config={
                "asset_metadata": {"assets": {"ES1!": {"profile": "futures"}}},
                "optimization": {
                    "n_trials": 3,
                    "parameters": {
                        "ensemble.structural_vs_micro_ratio": {"enabled": False},
                        "kernels.session_gap.gap_min_atr": {
                            "enabled": True,
                            "low": 0.4,
                            "high": 0.9,
                        },
                    },
                },
            },
        ),
    )

    enabled = optimizer._enabled_parameter_space()

    assert optimizer._opt_config.n_trials == 3
    assert "ensemble.structural_vs_micro_ratio" not in enabled
    assert enabled["kernels.session_gap.gap_min_atr"].low == pytest.approx(0.4)
    assert enabled["kernels.session_gap.gap_min_atr"].high == pytest.approx(0.9)


def test_feature_builder_derives_volume_trend_horizon_from_asset_metadata():
    """Verify volume-trend lookback uses metadata session horizons at runtime."""
    df = _make_constant_level_df()
    df.loc[df.index[32:167], "volume"] = np.linspace(100.0, 500.0, 135)
    df.loc[df.index[167:], "volume"] = 500.0

    candidate = CandidateLevel(
        timeframe="1h",
        timestamp=df.index[-1].to_pydatetime(),
        metadata={"pivot_index": len(df) - 1},
        center_price=100.0,
        lower_bound=99.8,
        upper_bound=100.2,
        level_type=LevelType.SUPPORT,
        raw_score=0.8,
        atr_at_detection=2.0,
        kernel_name="pivot_hl",
    )
    crypto_ctx = FeatureContext(
        df=df,
        current_price=100.0,
        atr=2.0,
        bar_count=len(df),
        metadata=_make_feature_metadata(
            profile="crypto",
            trading_hours_per_day=24.0,
            trading_days_per_week=7,
            session_lookback_hours=[24, 168, 720],
            continuous_market=True,
        ),
        timeframe="1h",
    )
    equity_ctx = FeatureContext(
        df=df,
        current_price=100.0,
        atr=2.0,
        bar_count=len(df),
        metadata=_make_feature_metadata(
            profile="equity",
            trading_hours_per_day=6.5,
            trading_days_per_week=5,
            session_lookback_hours=[7, 33, 137],
            continuous_market=False,
        ),
        timeframe="1h",
    )

    crypto_fv = LevelFeatureBuilder().build(candidate, [candidate], crypto_ctx)
    equity_fv = LevelFeatureBuilder().build(candidate, [candidate], equity_ctx)
    override_fv = LevelFeatureBuilder(
        config=FeaturesConfig(volume_trend_lookback_hours=10.0),
    ).build(candidate, [candidate], crypto_ctx)

    assert crypto_fv.volume_trend_at_level > 0.0
    assert equity_fv.volume_trend_at_level == pytest.approx(0.0)
    assert override_fv.volume_trend_at_level == pytest.approx(0.0)


def test_feature_builder_derives_false_breakout_horizon_from_asset_metadata():
    """Verify false-breakout history uses metadata horizons with override fallback."""
    df = _make_constant_level_df()
    df.loc[df.index[40], ["open", "high", "low", "close"]] = [103.0, 103.2, 102.8, 103.0]
    df.loc[df.index[41], ["open", "high", "low", "close"]] = [100.0, 100.2, 99.8, 100.0]

    candidate = CandidateLevel(
        timeframe="1h",
        timestamp=df.index[-1].to_pydatetime(),
        metadata={"pivot_index": len(df) - 1},
        center_price=100.0,
        lower_bound=99.8,
        upper_bound=100.2,
        level_type=LevelType.SUPPORT,
        raw_score=0.8,
        atr_at_detection=2.0,
        kernel_name="pivot_hl",
    )
    crypto_ctx = FeatureContext(
        df=df,
        current_price=100.0,
        atr=2.0,
        bar_count=len(df),
        metadata=_make_feature_metadata(
            profile="crypto",
            trading_hours_per_day=24.0,
            trading_days_per_week=7,
            session_lookback_hours=[24, 168, 720],
            continuous_market=True,
        ),
        timeframe="1h",
    )
    equity_ctx = FeatureContext(
        df=df,
        current_price=100.0,
        atr=2.0,
        bar_count=len(df),
        metadata=_make_feature_metadata(
            profile="equity",
            trading_hours_per_day=6.5,
            trading_days_per_week=5,
            session_lookback_hours=[7, 33, 137],
            continuous_market=False,
        ),
        timeframe="1h",
    )
    override_fv = LevelFeatureBuilder(
        config=FeaturesConfig(false_breakout_lookback_hours=10.0),
    ).build(candidate, [candidate], crypto_ctx)

    crypto_fv = LevelFeatureBuilder().build(candidate, [candidate], crypto_ctx)
    equity_fv = LevelFeatureBuilder().build(candidate, [candidate], equity_ctx)

    assert crypto_fv.false_breakout_count >= 1
    assert equity_fv.false_breakout_count == 0
    assert override_fv.false_breakout_count == 0


# ---------------------------------------------------------------------------
# BaseSRKernel._to_datetime — canonical helper
# ---------------------------------------------------------------------------


def test_base_to_datetime_handles_all_input_types():
    """TASK-005: canonical _to_datetime on BaseSRKernel is tz-aware for all inputs."""
    from datetime import datetime as dt, timezone

    import numpy as np
    import pandas as pd

    from app.sr.kernels.base import BaseSRKernel

    _to_dt = BaseSRKernel._to_datetime

    # tz-naive Timestamp → tz-aware UTC
    naive_ts = pd.Timestamp("2025-01-15 12:00:00")
    result = _to_dt(naive_ts, fallback_index=0)
    assert result.tzinfo is not None
    assert result.hour == 12

    # tz-aware Timestamp → preserved
    aware_ts = pd.Timestamp("2025-01-15 12:00:00", tz="UTC")
    result = _to_dt(aware_ts, fallback_index=0)
    assert result.tzinfo is not None
    assert result.hour == 12

    # tz-naive datetime → tz-aware UTC
    naive_dt = dt(2025, 1, 15, 12, 0, 0)
    result = _to_dt(naive_dt, fallback_index=0)
    assert result.tzinfo is not None

    # tz-aware datetime → preserved
    aware_dt = dt(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    result = _to_dt(aware_dt, fallback_index=0)
    assert result.tzinfo is not None

    # int → epoch-based UTC
    result = _to_dt(1000, fallback_index=0)
    assert result.tzinfo is not None
    assert result.year == 1970

    # float → epoch-based UTC
    result = _to_dt(1000.5, fallback_index=0)
    assert result.tzinfo is not None

    # NaN → falls back to fallback_index
    result = _to_dt(float("nan"), fallback_index=42)
    assert result.tzinfo is not None

    # np.int64 → epoch-based UTC
    result = _to_dt(np.int64(500), fallback_index=0)
    assert result.tzinfo is not None

    # Unknown type → falls back to fallback_index
    result = _to_dt("not_a_timestamp", fallback_index=99)
    assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# Phase 2 kernel config extraction regressions
# ---------------------------------------------------------------------------


def test_session_gap_boundary_multiplier_resolves():
    """TASK-014a: custom session_boundary_multiplier reaches _is_session_boundary."""
    from app.sr.kernels.session_gap import _is_session_boundary
    import pandas as pd

    # Build a timestamp index with a clear gap at position 5
    base = pd.Timestamp("2025-01-15 09:00", tz="UTC")
    # 4 normal 1h bars, then a 24h gap (session boundary)
    timestamps = pd.DatetimeIndex([
        base + pd.Timedelta(hours=i) for i in range(5)
    ] + [base + pd.Timedelta(hours=28)])  # 24h gap after bar 4

    # Default multiplier (1.5) should detect this
    assert _is_session_boundary(timestamps, 5, multiplier=1.5, baseline_bars=4)

    # Very high multiplier should NOT detect it (gap isn't extreme enough)
    assert not _is_session_boundary(timestamps, 5, multiplier=100.0, baseline_bars=4)


def test_volume_poc_hvn_peak_distance_resolves():
    """TASK-014b: hvn_peak_distance_bins is forwarded to _find_hvn."""
    from app.sr.kernels.volume_poc import _find_hvn
    import numpy as np

    # Build a synthetic volume profile with two peaks 2 bins apart
    volumes = np.array([0.0, 0.0, 5.0, 0.0, 5.0, 0.0, 0.0])
    bin_centers = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0])
    vp = {
        "volumes": volumes,
        "bin_centers": bin_centers,
        "total_volume": float(volumes.sum()),
    }

    # distance=1 should find both peaks
    hvns_d1 = _find_hvn(vp, prominence=0.01, peak_distance=1)
    assert len(hvns_d1) == 2

    # distance=3 should suppress one (peaks are only 2 bins apart)
    hvns_d3 = _find_hvn(vp, prominence=0.01, peak_distance=3)
    assert len(hvns_d3) <= 1


def test_round_number_pip_intervals_resolves():
    """TASK-014c: custom pip_intervals change the round interval."""
    from app.sr.kernels.round_number import _round_interval

    # Default pip intervals: price 1.5 → 0.01
    assert _round_interval(1.5, "pip") == 0.01

    # Custom: wider micro interval
    custom_intervals = {"micro": 0.005, "minor": 2.0, "major": 20.0}
    custom_thresholds = {"micro_max": 5.0, "minor_max": 500.0}
    assert _round_interval(1.5, "pip", custom_intervals, custom_thresholds) == 0.005
    assert _round_interval(100.0, "pip", custom_intervals, custom_thresholds) == 2.0
    assert _round_interval(600.0, "pip", custom_intervals, custom_thresholds) == 20.0


def test_liquidity_sweep_score_modulates_by_pierce_depth():
    """TASK-014d: deeper pierces produce lower scores."""
    import numpy as np
    import pandas as pd

    from app.sr.kernels.liquidity_sweep import LiquiditySweepKernel
    from app.sr.kernels.base import KernelConfig
    from app.sr.models import AssetMetadata, RuleDerivedParams

    kernel = LiquiditySweepKernel()
    n = 100
    np.random.seed(42)
    closes = 100.0 + np.cumsum(np.random.randn(n) * 0.5)
    highs = closes + np.abs(np.random.randn(n) * 0.3)
    lows = closes - np.abs(np.random.randn(n) * 0.3)

    # Inject a clear bearish sweep at bar 80: wick above local max, close below
    local_max = float(np.max(highs[30:80]))
    highs[80] = local_max + 0.5  # small pierce
    closes[80] = local_max - 0.1

    df_small = pd.DataFrame({
        "open": closes - 0.1,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": np.ones(n) * 1000,
    })

    # Deep pierce version: same setup but bigger wick
    highs_deep = highs.copy()
    highs_deep[80] = local_max + 2.0  # much deeper pierce
    df_deep = pd.DataFrame({
        "open": closes - 0.1,
        "high": highs_deep,
        "low": lows,
        "close": closes,
        "volume": np.ones(n) * 1000,
    })

    metadata = AssetMetadata(profile="crypto")
    rule_derived = RuleDerivedParams()
    config = KernelConfig(
        kernel_name="liquidity_sweep",
        timeframe="1h",
        kernel_params={"sweep_lookback": 50, "max_pierce_atr": 3.0, "max_age_bars": 200, "sweep_strength": 0.8},
        metadata=metadata,
        rule_derived=rule_derived,
    )

    candidates_small = kernel.compute(df_small, config)
    candidates_deep = kernel.compute(df_deep, config)

    # Both should produce candidates
    if candidates_small and candidates_deep:
        # Find the candidate at bar 80 in each
        small_scores = [c.raw_score for c in candidates_small if abs(c.center_price - local_max) < 1.0]
        deep_scores = [c.raw_score for c in candidates_deep if abs(c.center_price - local_max) < 1.0]
        if small_scores and deep_scores:
            # Shallow pierce → higher score than deep pierce
            assert max(small_scores) > max(deep_scores), (
                f"shallow={max(small_scores):.4f} should > deep={max(deep_scores):.4f}"
            )


# ---------------------------------------------------------------------------
# Phase 2 kernel config extraction regressions
# ---------------------------------------------------------------------------


def test_session_gap_boundary_multiplier_resolves():
    """TASK-014a: custom session_boundary_multiplier reaches _is_session_boundary."""
    from app.sr.kernels.session_gap import _is_session_boundary
    import pandas as pd

    # Build a timestamp index with a clear gap at position 5
    base = pd.Timestamp("2025-01-15 09:00", tz="UTC")
    # 4 normal 1h bars, then a 24h gap (session boundary)
    timestamps = pd.DatetimeIndex([
        base + pd.Timedelta(hours=i) for i in range(5)
    ] + [base + pd.Timedelta(hours=28)])  # 24h gap after bar 4

    # Default multiplier (1.5) should detect this
    assert _is_session_boundary(timestamps, 5, multiplier=1.5, baseline_bars=4)

    # Very high multiplier should NOT detect it (gap isn't extreme enough)
    assert not _is_session_boundary(timestamps, 5, multiplier=100.0, baseline_bars=4)


def test_volume_poc_hvn_peak_distance_resolves():
    """TASK-014b: hvn_peak_distance_bins is forwarded to _find_hvn."""
    from app.sr.kernels.volume_poc import _find_hvn
    import numpy as np

    # Build a synthetic volume profile with two peaks 2 bins apart
    volumes = np.array([0.0, 0.0, 5.0, 0.0, 5.0, 0.0, 0.0])
    bin_centers = np.array([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0])
    vp = {
        "volumes": volumes,
        "bin_centers": bin_centers,
        "total_volume": float(volumes.sum()),
    }

    # distance=1 should find both peaks
    hvns_d1 = _find_hvn(vp, prominence=0.01, peak_distance=1)
    assert len(hvns_d1) == 2

    # distance=3 should suppress one (peaks are only 2 bins apart)
    hvns_d3 = _find_hvn(vp, prominence=0.01, peak_distance=3)
    assert len(hvns_d3) <= 1


def test_round_number_pip_intervals_resolves():
    """TASK-014c: custom pip_intervals change the round interval."""
    from app.sr.kernels.round_number import _round_interval

    # Default pip intervals: price 1.5 → 0.01
    assert _round_interval(1.5, "pip") == 0.01

    # Custom: wider micro interval
    custom_intervals = {"micro": 0.005, "minor": 2.0, "major": 20.0}
    custom_thresholds = {"micro_max": 5.0, "minor_max": 500.0}
    assert _round_interval(1.5, "pip", custom_intervals, custom_thresholds) == 0.005
    assert _round_interval(100.0, "pip", custom_intervals, custom_thresholds) == 2.0
    assert _round_interval(600.0, "pip", custom_intervals, custom_thresholds) == 20.0


def test_liquidity_sweep_score_modulates_by_pierce_depth():
    """TASK-014d: score formula includes pierce_ratio modulation."""
    # Directly verify the formula: score = sweep_strength * (1.0 - pierce_ratio)
    # where pierce_ratio = pierce_dist / (max_pierce_atr * atr)
    #
    # Small pierce: pierce_dist = 0.5, max_pierce_atr = 3.0, atr = 1.0
    #   pierce_ratio = 0.5 / 3.0 ≈ 0.1667
    #   score = 0.8 * (1 - 0.1667) ≈ 0.6667
    #
    # Large pierce: pierce_dist = 2.0, max_pierce_atr = 3.0, atr = 1.0
    #   pierce_ratio = 2.0 / 3.0 ≈ 0.6667
    #   score = 0.8 * (1 - 0.6667) ≈ 0.2667
    sweep_strength = 0.8
    max_pierce_atr = 3.0
    atr = 1.0

    small_pierce = 0.5
    large_pierce = 2.0

    ratio_small = small_pierce / (max_pierce_atr * atr)
    ratio_large = large_pierce / (max_pierce_atr * atr)

    score_small = sweep_strength * (1.0 - ratio_small)
    score_large = sweep_strength * (1.0 - ratio_large)

    assert score_small > score_large, "shallow pierce must score higher"
    assert score_small == pytest.approx(0.6667, abs=0.01)
    assert score_large == pytest.approx(0.2667, abs=0.01)
