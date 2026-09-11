"""
S/R v2 Phase 4 Unit Tests
=========================
Tests for:
  - CrossAssetSRAnalyzer (TASK-029)
  - Cross-asset features in LevelFeatureVector (TASK-030)
  - UniverseSROptimizer + Tier 6 benchmark (TASK-031/032)
  - MetaLearnedEnsemble (TASK-033)
  - Integration: full universe pipeline end-to-end with 3+ assets (TASK-035)
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List

import numpy as np
import pandas as pd
import pytest

from app.sr.models import LevelType
from app.sr.kernels.base import BaseSRKernel, KernelConfig
from app.sr.models import (
    AssetMetadata,
    CandidateLevel,
    LevelFeatureVector,
    RuleDerivedParams,
    ScoredLevel,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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


def _make_scored_level(
    price: float = 100.0,
    kernel_name: str = "pivot_hl",
    level_type: LevelType = LevelType.SUPPORT,
    strength: float = 0.7,
    atr: float = 2.0,
) -> ScoredLevel:
    return ScoredLevel(
        candidate=CandidateLevel(
            center_price=price,
            lower_bound=price - 0.1 * atr,
            upper_bound=price + 0.1 * atr,
            level_type=level_type,
            kernel_name=kernel_name,
            timeframe="1h",
            raw_score=0.8,
            metadata={},
            timestamp=datetime(2025, 1, 1),
            atr_at_detection=atr,
        ),
        features=LevelFeatureVector(
            touch_count=3, kernel_agreement=2,
            rejection_ratio=0.6, volume_at_touches=1.2,
        ),
        strength=strength,
        confidence=0.65,
        contributing_kernels=[kernel_name],
        ensemble_method="weighted_average",
    )


def _make_correlation_matrix(assets: List[str], base_corr: float = 0.7) -> pd.DataFrame:
    """Create a synthetic correlation matrix."""
    n = len(assets)
    matrix = np.eye(n) * (1 - base_corr) + base_corr
    return pd.DataFrame(matrix, index=assets, columns=assets)


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


# ===================================================================
# 1. CROSS-ASSET ANALYZER
# ===================================================================

class TestCrossAssetSRAnalyzer:
    def test_basic_analysis(self):
        from app.sr.cross_asset import CrossAssetSRAnalyzer, CrossAssetConfig

        analyzer = CrossAssetSRAnalyzer(CrossAssetConfig(correlation_threshold=0.5))
        universe_zones = {
            "BTC": [_make_scored_level(100.0), _make_scored_level(110.0)],
            "ETH": [_make_scored_level(100.5), _make_scored_level(120.0)],
            "SOL": [_make_scored_level(99.8), _make_scored_level(115.0)],
        }
        corr = _make_correlation_matrix(["BTC", "ETH", "SOL"], base_corr=0.7)
        results = analyzer.analyze(universe_zones, corr)
        assert "BTC" in results
        assert "ETH" in results
        assert "SOL" in results
        for asset, r in results.items():
            assert len(r.enriched_zones) > 0

    def test_no_correlation_no_cross_features(self):
        from app.sr.cross_asset import CrossAssetSRAnalyzer, CrossAssetConfig

        analyzer = CrossAssetSRAnalyzer(CrossAssetConfig(correlation_threshold=0.99))
        universe_zones = {
            "BTC": [_make_scored_level(100.0)],
            "ETH": [_make_scored_level(200.0)],
        }
        corr = _make_correlation_matrix(["BTC", "ETH"], base_corr=0.3)
        results = analyzer.analyze(universe_zones, corr)
        # Low correlation → no cross-asset agreement
        for r in results.values():
            for ez in r.enriched_zones:
                assert ez.cross_features.universe_agreement_count == 0

    def test_far_normalized_levels_do_not_agree(self):
        from app.sr.cross_asset import CrossAssetConfig, CrossAssetSRAnalyzer

        analyzer = CrossAssetSRAnalyzer(
            CrossAssetConfig(correlation_threshold=0.5, sector_cluster_eps_atr=0.5),
        )
        universe_zones = {
            "BTC": [_make_scored_level(100.0, atr=2.0)],
            "ETH": [_make_scored_level(140.0, atr=2.0)],
        }
        corr = _make_correlation_matrix(["BTC", "ETH"], base_corr=0.8)
        results = analyzer.analyze(universe_zones, corr)

        btc_zone = results["BTC"].enriched_zones[0]
        assert btc_zone.cross_features.universe_agreement_count == 0

    def test_dominant_asset_alignment(self):
        from app.sr.cross_asset import CrossAssetSRAnalyzer, CrossAssetConfig

        analyzer = CrossAssetSRAnalyzer(CrossAssetConfig(correlation_threshold=0.5))
        universe_zones = {
            "SPX": [_make_scored_level(100.0)],
            "AAPL": [_make_scored_level(100.2)],
        }
        corr = _make_correlation_matrix(["SPX", "AAPL"], base_corr=0.8)
        results = analyzer.analyze(universe_zones, corr, dominant_assets=["SPX"])
        # AAPL should see dominant alignment from SPX
        aapl_result = results["AAPL"]
        # At least one zone should have been compared
        assert len(aapl_result.compared_assets) > 0

    def test_empty_universe(self):
        from app.sr.cross_asset import CrossAssetSRAnalyzer

        analyzer = CrossAssetSRAnalyzer()
        results = analyzer.analyze({}, pd.DataFrame())
        assert results == {}

    def test_strength_adjustment(self):
        from app.sr.cross_asset import CrossAssetSRAnalyzer, CrossAssetConfig

        analyzer = CrossAssetSRAnalyzer(CrossAssetConfig(
            correlation_threshold=0.5,
            min_universe_agreement=1,
            agreement_strength_bonus=0.1,
        ))
        # Create similar levels across 3 assets
        universe_zones = {
            "A": [_make_scored_level(100.0, strength=0.5)],
            "B": [_make_scored_level(100.1, strength=0.6)],
            "C": [_make_scored_level(100.2, strength=0.7)],
        }
        corr = _make_correlation_matrix(["A", "B", "C"], base_corr=0.8)
        results = analyzer.analyze(universe_zones, corr)
        for r in results.values():
            for ez in r.enriched_zones:
                # Adjusted strength should be >= original strength
                assert ez.adjusted_strength >= ez.scored_level.strength


# ===================================================================
# 2. CROSS-ASSET FEATURES IN MODEL
# ===================================================================

class TestCrossAssetFeatures:
    def test_feature_vector_has_cross_fields(self):
        fv = LevelFeatureVector(
            touch_count=3,
            universe_agreement=2,
            sector_cluster=0.75,
            dominant_alignment=1.0,
        )
        assert fv.universe_agreement == 2
        assert fv.sector_cluster == 0.75
        assert fv.dominant_alignment == 1.0

    def test_defaults_are_zero(self):
        fv = LevelFeatureVector()
        assert fv.universe_agreement == 0
        assert fv.sector_cluster == 0.0
        assert fv.dominant_alignment == 0.0


# ===================================================================
# 3. TIER 6 BENCHMARK
# ===================================================================

class TestTier6Benchmark:
    def test_basic_evaluation(self):
        from app.sr.cross_asset import CrossAssetFeatures, EnrichedZone
        from app.sr.optimization.benchmark_tier6 import CrossAssetBenchmark

        benchmark = CrossAssetBenchmark(min_agreement=2)

        # Create agreed and isolated zones
        agreed_zone = EnrichedZone(
            scored_level=_make_scored_level(100.0),
            cross_features=CrossAssetFeatures(universe_agreement_count=3),
        )
        isolated_zone = EnrichedZone(
            scored_level=_make_scored_level(200.0),
            cross_features=CrossAssetFeatures(universe_agreement_count=0),
        )

        bounce_rates = {
            "pivot_hl:100.00000000": 0.8,  # agreed zone bounces well
            "pivot_hl:200.00000000": 0.3,  # isolated zone bounces poorly
        }

        result = benchmark.evaluate([agreed_zone, isolated_zone], bounce_rates)
        assert result.agreed_zone_count == 1
        assert result.isolated_zone_count == 1
        assert result.agreed_zone_bounce_rate > result.isolated_zone_bounce_rate
        assert result.universe_agreement_lift > 0
        assert 0.0 <= result.score <= 1.0

    def test_no_agreed_zones(self):
        from app.sr.cross_asset import CrossAssetFeatures, EnrichedZone
        from app.sr.optimization.benchmark_tier6 import CrossAssetBenchmark

        benchmark = CrossAssetBenchmark()
        zone = EnrichedZone(
            scored_level=_make_scored_level(100.0),
            cross_features=CrossAssetFeatures(universe_agreement_count=0),
        )
        result = benchmark.evaluate([zone], {"pivot_hl:100.00000000": 0.5})
        assert result.agreed_zone_count == 0
        assert result.score == 0.0

    def test_empty_zones(self):
        from app.sr.optimization.benchmark_tier6 import CrossAssetBenchmark
        result = CrossAssetBenchmark().evaluate([], {})
        assert result.score == 0.0


# ===================================================================
# 4. META-LEARNED ENSEMBLE
# ===================================================================

class TestMetaLearnedEnsemble:
    def test_registered(self):
        import app.sr.ensemble.meta_learned  # noqa: F401
        from app.sr.ensemble.registry import EnsembleRegistry
        assert EnsembleRegistry.has("meta_learned")

    def test_fallback_when_no_model(self):
        from app.sr.ensemble.meta_learned import MetaLearnedEnsemble

        ensemble = MetaLearnedEnsemble()
        candidates = [
            CandidateLevel(
                center_price=100.0, lower_bound=99.8, upper_bound=100.2,
                level_type=LevelType.SUPPORT, kernel_name="pivot_hl",
                timeframe="1h", raw_score=0.8, metadata={},
                timestamp=datetime(2025, 1, 1), atr_at_detection=2.0,
            ),
        ]
        features = {
            "pivot_hl:100.00000000": LevelFeatureVector(touch_count=3),
        }
        result = ensemble.score(candidates, features, {})
        assert len(result) == 1
        assert result[0].ensemble_method == "weighted_average"  # fallback

    def test_prepare_training_data(self):
        from app.sr.ensemble.meta_learned import MetaLearnedEnsemble

        fvs = [
            LevelFeatureVector(touch_count=3, kernel_agreement=2),
            LevelFeatureVector(touch_count=1, kernel_agreement=1),
        ]
        labels = [0.8, 0.3]
        X, y = MetaLearnedEnsemble.prepare_training_data(fvs, labels)
        assert X.shape == (2, 20)  # 20 features
        assert y.shape == (2,)
        assert X[0, 0] == 3.0  # touch_count

    def test_set_model_and_predict(self):
        """Test with a mock model that has predict()."""
        from app.sr.ensemble.meta_learned import MetaLearnedEnsemble

        class MockModel:
            def predict(self, X):
                return np.full(len(X), 0.75)

        ensemble = MetaLearnedEnsemble()
        ensemble.set_model(MockModel())

        candidates = [
            CandidateLevel(
                center_price=100.0, lower_bound=99.8, upper_bound=100.2,
                level_type=LevelType.SUPPORT, kernel_name="pivot_hl",
                timeframe="1h", raw_score=0.8, metadata={},
                timestamp=datetime(2025, 1, 1), atr_at_detection=2.0,
            ),
        ]
        features = {
            "pivot_hl:100.00000000": LevelFeatureVector(
                touch_count=3, kernel_agreement=2,
            ),
        }
        result = ensemble.score(candidates, features, {})
        assert len(result) == 1
        assert result[0].ensemble_method == "meta_learned"
        assert abs(result[0].strength - 0.75) < 0.01

    def test_missing_features_use_default_vector(self):
        from app.sr.ensemble.meta_learned import MetaLearnedEnsemble

        class MockModel:
            def predict(self, X):
                return np.full(len(X), 0.5)

        ensemble = MetaLearnedEnsemble()
        ensemble.set_model(MockModel())

        candidates = [
            CandidateLevel(
                center_price=100.0, lower_bound=99.8, upper_bound=100.2,
                level_type=LevelType.SUPPORT, kernel_name="pivot_hl",
                timeframe="1h", raw_score=0.8, metadata={},
                timestamp=datetime(2025, 1, 1), atr_at_detection=2.0,
            ),
        ]

        result = ensemble.score(candidates, {}, {})
        assert len(result) == 1
        assert result[0].ensemble_method == "meta_learned"
        assert result[0].strength == pytest.approx(0.5)

    def test_strategy_name(self):
        from app.sr.ensemble.meta_learned import MetaLearnedEnsemble
        assert MetaLearnedEnsemble().strategy_name == "meta_learned"


# ===================================================================
# 5. UNIVERSE OPTIMIZER
# ===================================================================

class TestUniverseSROptimizer:
    def test_default_optimization_config_uses_narrow_initial_bounds(self):
        from app.sr.optimization.universe_optimizer import UniverseOptimizationConfig

        config = UniverseOptimizationConfig()

        assert config.stage1_eval_bars == 300
        assert config.parameter_space["ensemble.structural_vs_micro_ratio"].low == pytest.approx(0.4)
        assert config.parameter_space["ensemble.structural_vs_micro_ratio"].high == pytest.approx(0.65)
        assert config.parameter_space["kernels.anchored_vwap.volume_spike_multiplier"].low == pytest.approx(1.5)
        assert config.parameter_space["kernels.tpo_value_area.tpo_value_area_pct"].high == pytest.approx(0.85)
        assert config.parameter_space["kernels.session_gap.gap_min_atr"].enabled is False

    def test_suggest_params(self):
        pytest.importorskip("optuna")
        import optuna

        from app.sr.optimization.universe_optimizer import (
            UniverseOptimizationConfig,
            UniverseSROptimizer,
        )
        from app.sr.universe.config import UniverseSRConfig

        optimizer = UniverseSROptimizer(
            UniverseSRConfig(),
            UniverseOptimizationConfig(),
        )
        study = optuna.create_study()
        trial = study.ask()
        params = optimizer.suggest_params(trial)
        # HIGH-sensitivity params (enabled by default after Sobol tiering)
        assert "lifecycle.dedup_proximity_atr" in params
        assert "pipeline.merge_threshold_pct_atr" in params
        assert "kernels.anchored_vwap.volume_spike_multiplier" in params
        assert "kernels.tpo_value_area.tpo_value_area_pct" in params
        assert "lifecycle.min_strength" in params
        # Frozen params (disabled after Sobol tiering)
        assert "ensemble.structural_vs_micro_ratio" not in params
        assert "lifecycle.age_lambda" not in params
        assert "cross_asset.sector_cluster_eps_atr" not in params
        # Stage 2-only / gated params
        assert "pipeline.min_emit_strength" not in params
        assert "pipeline.max_new_zones_per_bar" not in params
        assert "kernels.session_gap.gap_min_atr" not in params

    def test_apply_params_to_config(self):
        from app.sr.optimization.universe_optimizer import UniverseSROptimizer
        from app.sr.universe.config import UniverseSRConfig

        optimizer = UniverseSROptimizer(UniverseSRConfig())
        overrides = optimizer.apply_params_to_config({
            "ensemble.structural_vs_micro_ratio": 0.6,
            "lifecycle.age_lambda": 0.003,
            "cross_asset.sector_cluster_eps_atr": 0.8,
        })
        assert overrides["ensemble"]["structural_vs_micro_ratio"] == 0.6
        assert overrides["lifecycle"]["age_lambda"] == 0.003
        assert overrides["cross_asset"]["sector_cluster_eps_atr"] == 0.8

    def test_build_cross_asset_analyzer_uses_cluster_eps(self):
        from app.sr.optimization.universe_optimizer import UniverseSROptimizer
        from app.sr.universe.config import UniverseSRConfig

        optimizer = UniverseSROptimizer(UniverseSRConfig())
        analyzer = optimizer._build_cross_asset_analyzer({"cross_asset.sector_cluster_eps_atr": 0.8})

        assert analyzer._config.sector_cluster_eps_atr == 0.8

    def test_evaluate_trial(self):
        from app.sr.optimization.universe_optimizer import UniverseSROptimizer
        from app.sr.universe.config import AssetSRConfig, UniverseSRConfig

        config = UniverseSRConfig(
            assets=[AssetSRConfig(symbol="BTC"), AssetSRConfig(symbol="ETH")],
            max_workers=1,
            global_config={
                "pipeline": {"enabled_kernels": ["pivot_hl", "round_number"]},
            },
        )
        optimizer = UniverseSROptimizer(config)
        data_map = {
            "BTC": {"1h": _make_ohlcv(seed=1)},
            "ETH": {"1h": _make_ohlcv(seed=2)},
        }
        result = optimizer.evaluate_trial(
            {
                "lifecycle.dedup_proximity_atr": 0.5,
                "pipeline.merge_threshold_pct_atr": 0.3,
            },
            data_map,
        )
        assert result.total_score >= 0.0
        assert "BTC/1h" in result.per_asset_scores
        assert "ETH/1h" in result.per_asset_scores
        assert "lifecycle.dedup_proximity_atr" in result.metadata["search_space_keys"]

    def test_optimize_without_optuna_returns_deterministic_default_trial(self, monkeypatch):
        import app.sr.optimization.universe_optimizer as universe_optimizer_module
        from app.sr.optimization.universe_optimizer import UniverseSROptimizer
        from app.sr.universe.config import AssetSRConfig, UniverseSRConfig

        monkeypatch.setattr(universe_optimizer_module, "OPTUNA_AVAILABLE", False)

        config = UniverseSRConfig(
            assets=[AssetSRConfig(symbol="BTC"), AssetSRConfig(symbol="ETH")],
            max_workers=1,
            global_config={
                "pipeline": {"enabled_kernels": ["pivot_hl", "round_number"]},
            },
        )
        optimizer = UniverseSROptimizer(config)
        data_map = {
            "BTC": {"1h": _make_ohlcv(seed=1)},
            "ETH": {"1h": _make_ohlcv(seed=2)},
        }

        result = optimizer.optimize(data_map)

        assert "lifecycle.dedup_proximity_atr" in result.best_params
        assert result.metadata["optuna_available"] is False
        assert result.metadata["n_trials"] == 1
        assert len(result.all_trials) == 1

    def test_optimize_populates_trial_history_and_tier6_result(self):
        pytest.importorskip("optuna")

        from app.sr.optimization.universe_optimizer import (
            UniverseOptimizationConfig,
            UniverseSROptimizer,
        )
        from app.sr.universe.config import AssetSRConfig, UniverseSRConfig

        config = UniverseSRConfig(
            assets=[AssetSRConfig(symbol="BTC"), AssetSRConfig(symbol="ETH")],
            max_workers=1,
            global_config={
                "pipeline": {"enabled_kernels": ["pivot_hl", "round_number"]},
            },
        )
        optimizer = UniverseSROptimizer(
            config,
            UniverseOptimizationConfig(n_trials=2, timeout_s=30.0),
        )
        data_map = {
            "BTC": {"1h": _make_ohlcv(seed=1)},
            "ETH": {"1h": _make_ohlcv(seed=2)},
        }
        correlation_matrix = _make_correlation_matrix(["BTC", "ETH"], base_corr=0.8)

        result = optimizer.optimize(data_map, correlation_matrix=correlation_matrix)

        assert result.best_score >= 0.0
        assert len(result.all_trials) == 2
        assert result.tier6_result is not None
        assert result.metadata["optuna_available"] is True
        assert "lifecycle.dedup_proximity_atr" in result.metadata["search_space_keys"]

    def test_optimize_uses_configured_stage1_eval_bars(self, monkeypatch):
        pytest.importorskip("optuna")

        from app.sr.optimization.universe_optimizer import (
            UniverseOptimizationConfig,
            UniverseSROptimizer,
            UniverseTrialResult,
        )
        from app.sr.universe.config import AssetSRConfig, UniverseSRConfig

        captured: dict[str, int] = {}
        config = UniverseSRConfig(
            assets=[AssetSRConfig(symbol="BTC")],
            max_workers=1,
            global_config={
                "pipeline": {"enabled_kernels": ["pivot_hl"]},
            },
        )
        optimizer = UniverseSROptimizer(
            config,
            UniverseOptimizationConfig(n_trials=1, timeout_s=30.0, stage1_eval_bars=512),
        )

        monkeypatch.setattr(optimizer, "_apply_data_driven_bounds", lambda data_map: None)

        def fake_evaluate_trial(
            params,
            data_map,
            correlation_matrix=None,
            bar_index=0,
            eval_bars=300,
        ):
            captured["eval_bars"] = eval_bars
            return UniverseTrialResult(
                trial_number=0,
                params=params,
                per_asset_scores={"BTC/1h": 1.0},
                total_score=1.0,
                metadata={"search_space_keys": list(params.keys())},
            )

        monkeypatch.setattr(optimizer, "evaluate_trial", fake_evaluate_trial)

        result = optimizer.optimize({"BTC": {"1h": _make_ohlcv(seed=1)}})

        assert captured["eval_bars"] == 512
        assert result.metadata["stage1_eval_bars"] == 512


# ===================================================================
# 6. INTEGRATION: FULL UNIVERSE PIPELINE (3+ ASSETS)
# ===================================================================

class TestFullUniverseIntegration:
    def test_three_asset_pipeline(self):
        """Full pipeline: 3 assets → universe router → cross-asset analysis."""
        import app.sr.kernels.pivot_hl  # noqa: F401
        import app.sr.kernels.round_number  # noqa: F401

        from app.sr.cross_asset import CrossAssetSRAnalyzer
        from app.sr.universe.config import AssetSRConfig, UniverseSRConfig
        from app.sr.universe.router import UniverseSRRouter

        # Setup
        assets = ["BTC", "ETH", "SOL"]
        config = UniverseSRConfig(
            assets=[AssetSRConfig(symbol=a) for a in assets],
            max_workers=1,
            global_config={
                "pipeline": {
                    "enabled_kernels": ["pivot_hl", "round_number"],
                    "min_emit_strength": 0.0,
                    "max_new_zones_per_bar": 0,
                },
            },
        )
        router = UniverseSRRouter(config)
        data_map = {a: {"1h": _make_ohlcv(seed=i)} for i, a in enumerate(assets)}

        # 1. Run universe pipeline
        universe_result = router.process(data_map, bar_index=100)
        assert len(universe_result.all_results) == 3
        assert not universe_result.errors

        # 2. Collect scored levels per asset
        universe_zones = {}
        for asset in assets:
            all_scored = []
            for tf, atr in universe_result.results[asset].items():
                all_scored.extend(atr.result.scored_levels)
            universe_zones[asset] = all_scored

        # Every asset should have produced some zones
        for asset in assets:
            assert len(universe_zones[asset]) > 0, f"No zones for {asset}"

        # 3. Cross-asset analysis
        corr = _make_correlation_matrix(assets, base_corr=0.7)
        analyzer = CrossAssetSRAnalyzer()
        cross_results = analyzer.analyze(universe_zones, corr)
        assert len(cross_results) == 3

    def test_single_asset_no_cross(self):
        """Single asset pipeline should work fine without cross-asset."""
        from app.sr.universe.config import AssetSRConfig, UniverseSRConfig
        from app.sr.universe.router import UniverseSRRouter

        config = UniverseSRConfig(
            assets=[AssetSRConfig(symbol="BTC")],
            max_workers=1,
            global_config={
                "pipeline": {"enabled_kernels": ["pivot_hl"]},
            },
        )
        router = UniverseSRRouter(config)
        result = router.process({"BTC": {"1h": _make_ohlcv()}})
        assert "BTC" in result.results
        assert len(result.all_results) == 1

    def test_multi_timeframe_single_asset(self):
        """Single asset with multiple timeframes."""
        from app.sr.universe.config import AssetSRConfig, UniverseSRConfig
        from app.sr.universe.router import UniverseSRRouter

        config = UniverseSRConfig(
            assets=[AssetSRConfig(symbol="BTC", timeframes=["1h", "4h"])],
            max_workers=1,
            global_config={
                "pipeline": {"enabled_kernels": ["pivot_hl", "round_number"]},
            },
        )
        router = UniverseSRRouter(config)
        result = router.process({
            "BTC": {
                "1h": _make_ohlcv(seed=1),
                "4h": _make_ohlcv(seed=2),
            },
        })
        assert len(result.all_results) == 2
        assert result.get("BTC", "1h") is not None
        assert result.get("BTC", "4h") is not None
