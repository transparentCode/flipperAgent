"""Phase 1 contract tests: config resolution, validation, and pipeline skeleton."""

import os
import pytest
import numpy as np
import pandas as pd

from app.regression.config.schema import (
    AssetClassConfig,
    AssetConfig,
    AssetTimeframeConfig,
    GlobalConfig,
    OrchestratorConfig,
    PluginConfig,
    ResolvedPipelineConfig,
    TimeframeConfig,
    VolumeProfile,
)
from app.regression.config.resolver import ConfigResolver
from app.regression.config.validator import ConfigValidator, ConfigValidationError
from app.regression.contracts.context import (
    AssetMeta,
    CascadeContext,
    PipelineRequest,
    RegimeSnapshot,
)
from app.regression.contracts.result import (
    DegradationLevel,
    EnsembleResult,
    FeatureSet,
    MethodResult,
    MTFOutput,
    RegressionResult,
    UniverseResult,
)
from app.regression.state import InMemoryStateManager, NullStateManager
from app.regression.registry import PluginRegistry
from app.regression.pipeline import RegressionPipeline


# ── Config Resolution Tests ──


class TestConfigResolution:
    """Test the 4-tier config resolution chain."""

    def _make_orchestrator(self) -> OrchestratorConfig:
        return OrchestratorConfig(
            regime_context_enabled=True,
            regime_window_override=True,
            global_config=GlobalConfig(
                default_window_size=100,
                trend_atr_fraction=0.10,
                spread_atr_fraction=0.15,
                momentum_atr_fraction=0.10,
                neutral_slope_atr_fraction=0.04,
                band_multiplier=2.0,
                features=[
                    PluginConfig(name="log_price"),
                    PluginConfig(name="volume_weighted"),
                ],
                methods={
                    "theil_sen": PluginConfig(name="theil_sen", weight=1.0),
                    "vwr": PluginConfig(name="vwr", weight=1.0),
                },
                ensemble=PluginConfig(name="simple_weighted"),
                uncertainty=PluginConfig(name="percentile_bands", params={"mad_scale_factor": 1.4826}),
            ),
            timeframes={
                "4h": TimeframeConfig(window_size=150),
                "1h": TimeframeConfig(window_size=100),
                "30m": TimeframeConfig(window_size=50),
            },
            asset_classes={
                "crypto": AssetClassConfig(
                    volume_profile=VolumeProfile.CONTINUOUS,
                    session_gap_handling=False,
                ),
                "stock": AssetClassConfig(
                    volume_profile=VolumeProfile.SESSION,
                    session_gap_handling=True,
                    features=[
                        PluginConfig(name="log_price"),
                        PluginConfig(name="volume_weighted"),
                        PluginConfig(name="session_aware"),
                    ],
                ),
            },
            assets={
                "BTCUSDT": AssetConfig(
                    asset_class="crypto",
                    mtf_enabled=True,
                    mtf_timeframes=["4h", "1h", "30m"],
                ),
                "ETHUSDT": AssetConfig(
                    asset_class="crypto",
                    mtf_enabled=True,
                    mtf_timeframes=["4h", "1h"],
                ),
                "AAPL": AssetConfig(
                    asset_class="stock",
                    mtf_enabled=False,
                    mtf_timeframes=["1h"],
                    window_size=120,
                    timeframes={
                        "1h": AssetTimeframeConfig(window_size=130),
                    },
                ),
            },
        )

    def test_global_defaults_apply(self):
        resolver = ConfigResolver(self._make_orchestrator())
        cfg = resolver.resolve("BTCUSDT", "1h")

        assert cfg.asset == "BTCUSDT"
        assert cfg.timeframe == "1h"
        assert cfg.asset_class == "crypto"
        assert cfg.trend_atr_fraction == 0.10
        assert cfg.spread_atr_fraction == 0.15

    def test_timeframe_overrides_window(self):
        resolver = ConfigResolver(self._make_orchestrator())

        cfg_4h = resolver.resolve("BTCUSDT", "4h")
        assert cfg_4h.window_size == 150

        cfg_1h = resolver.resolve("BTCUSDT", "1h")
        assert cfg_1h.window_size == 100

        cfg_30m = resolver.resolve("BTCUSDT", "30m")
        assert cfg_30m.window_size == 50

    def test_asset_class_sets_volume_profile(self):
        resolver = ConfigResolver(self._make_orchestrator())

        crypto = resolver.resolve("BTCUSDT", "1h")
        assert crypto.volume_profile == VolumeProfile.CONTINUOUS
        assert crypto.session_gap_handling is False

        stock = resolver.resolve("AAPL", "1h")
        assert stock.volume_profile == VolumeProfile.SESSION
        assert stock.session_gap_handling is True

    def test_asset_class_overrides_features(self):
        resolver = ConfigResolver(self._make_orchestrator())

        stock = resolver.resolve("AAPL", "1h")
        feature_names = [fc.name for fc in stock.features]
        assert "session_aware" in feature_names

        crypto = resolver.resolve("BTCUSDT", "1h")
        feature_names = [fc.name for fc in crypto.features]
        assert "session_aware" not in feature_names

    def test_per_asset_per_tf_overrides_window(self):
        resolver = ConfigResolver(self._make_orchestrator())

        # AAPL at 1h: asset-per-tf override = 130
        aapl_1h = resolver.resolve("AAPL", "1h")
        assert aapl_1h.window_size == 130

    def test_per_asset_overrides_window(self):
        resolver = ConfigResolver(self._make_orchestrator())

        # AAPL at 4h: no asset-per-tf override, falls to asset-level override = 120
        aapl_4h = resolver.resolve("AAPL", "4h")
        assert aapl_4h.window_size == 120

    def test_mtf_config_propagates(self):
        resolver = ConfigResolver(self._make_orchestrator())

        btc = resolver.resolve("BTCUSDT", "1h")
        assert btc.mtf_enabled is True
        assert btc.mtf_timeframes == ("4h", "1h", "30m")

        aapl = resolver.resolve("AAPL", "1h")
        assert aapl.mtf_enabled is False
        assert aapl.mtf_timeframes == ()

    def test_config_hash_is_deterministic(self):
        resolver = ConfigResolver(self._make_orchestrator())
        cfg1 = resolver.resolve("BTCUSDT", "1h")
        # Clear cache to force re-resolve
        resolver._cache.clear()
        cfg2 = resolver.resolve("BTCUSDT", "1h")
        assert cfg1.config_hash == cfg2.config_hash

    def test_config_hash_differs_across_assets(self):
        resolver = ConfigResolver(self._make_orchestrator())
        btc = resolver.resolve("BTCUSDT", "1h")
        aapl = resolver.resolve("AAPL", "1h")
        assert btc.config_hash != aapl.config_hash

    def test_resolve_all(self):
        resolver = ConfigResolver(self._make_orchestrator())
        all_cfgs = resolver.resolve_all(["BTCUSDT", "AAPL"], ["1h", "4h"])
        assert len(all_cfgs) == 4
        assert ("BTCUSDT", "1h") in all_cfgs
        assert ("AAPL", "4h") in all_cfgs

    def test_unknown_asset_gets_global_defaults(self):
        resolver = ConfigResolver(self._make_orchestrator())
        cfg = resolver.resolve("UNKNOWN_ASSET", "1h")
        # Falls back to global defaults + timeframe defaults
        assert cfg.window_size == 100
        assert cfg.asset_class == "crypto"  # default AssetConfig

class TestConfigResolutionFromYAML:
    """Test YAML → resolved config round-trip."""

    def test_load_reference_yaml(self):
        yaml_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "regression.yaml"
        )
        if not os.path.exists(yaml_path):
            pytest.skip("Reference YAML not found")

        resolver = ConfigResolver.from_yaml(yaml_path)
        cfg = resolver.resolve("BTCUSDT", "1h")

        assert cfg.asset == "BTCUSDT"
        assert cfg.timeframe == "1h"
        assert cfg.window_size == 73  # optimized for BTCUSDT 1h (2026-05-16)
        assert cfg.volume_profile == VolumeProfile.CONTINUOUS
        assert cfg.mtf_enabled is True
        assert "coverage" not in cfg.uncertainty.params
        assert cfg.uncertainty.params["mad_scale_factor"] == pytest.approx(1.4826)
        assert "geometric" not in {name for name, plugin in cfg.methods if plugin.enabled}

        stock_features = [
            feature.name
            for feature in resolver.orchestrator_config.asset_classes["stock"].features or []
        ]
        fx_features = [
            feature.name
            for feature in resolver.orchestrator_config.asset_classes["fx"].features or []
        ]
        assert "session_aware" in stock_features
        assert "session_aware" in fx_features


# ── Config Validation Tests ──


class TestConfigValidation:

    def _make_valid_config(self) -> ResolvedPipelineConfig:
        return ResolvedPipelineConfig(
            asset="BTCUSDT",
            timeframe="1h",
            asset_class="crypto",
            volume_profile=VolumeProfile.CONTINUOUS,
            config_hash="abc123",
            window_size=100,
            min_window=15,
            max_window=300,
            atr_period=14,
            trend_atr_fraction=0.10,
            spread_atr_fraction=0.15,
            momentum_atr_fraction=0.10,
            neutral_slope_atr_fraction=0.04,
            band_multiplier=2.0,
            slope_acceleration_alpha=0.0,
            features=(
                PluginConfig(name="log_price"),
                PluginConfig(name="volume_weighted"),
            ),
            methods=(
                ("theil_sen", PluginConfig(name="theil_sen", weight=1.0)),
                ("vwr", PluginConfig(name="vwr", weight=1.0)),
            ),
            ensemble=PluginConfig(name="simple_weighted"),
            uncertainty=PluginConfig(name="percentile_bands", params={"mad_scale_factor": 1.4826}),
            session_gap_handling=False,
            low_liquidity_window_handling=False,
            regime_context_enabled=True,
            regime_window_override=True,
            mtf_enabled=False,
            mtf_timeframes=(),
        )

    def test_valid_config_passes(self):
        cfg = self._make_valid_config()
        ConfigValidator().validate(cfg)  # should not raise

    def test_window_below_min_fails(self):
        cfg = ResolvedPipelineConfig(
            **{
                **self._make_valid_config().__dict__,
                "window_size": 5,
            }
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            ConfigValidator().validate(cfg)
        assert "min_window" in str(exc_info.value)

    def test_window_above_max_fails(self):
        cfg = ResolvedPipelineConfig(
            **{
                **self._make_valid_config().__dict__,
                "window_size": 500,
            }
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            ConfigValidator().validate(cfg)
        assert "max_window" in str(exc_info.value)

    def test_no_enabled_methods_fails(self):
        cfg = ResolvedPipelineConfig(
            **{
                **self._make_valid_config().__dict__,
                "methods": (
                    ("theil_sen", PluginConfig(name="theil_sen", enabled=False)),
                ),
            }
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            ConfigValidator().validate(cfg)
        assert "No enabled" in str(exc_info.value)

    def test_invalid_atr_fraction_fails(self):
        cfg = ResolvedPipelineConfig(
            **{
                **self._make_valid_config().__dict__,
                "trend_atr_fraction": 1.5,
            }
        )
        with pytest.raises(ConfigValidationError) as exc_info:
            ConfigValidator().validate(cfg)
        assert "trend_atr_fraction" in str(exc_info.value)

# ── State Manager Tests ──


class TestStateManager:

    def test_null_state_manager(self):
        sm = NullStateManager()
        assert sm.get("BTC", "1h", "kalman") is None
        sm.set("BTC", "1h", "kalman", {"theta": [1, 2]})
        assert sm.get("BTC", "1h", "kalman") is None
        assert sm.list_keys() == []

    def test_in_memory_state_manager(self):
        sm = InMemoryStateManager()
        assert sm.get("BTC", "1h", "kalman") is None

        sm.set("BTC", "1h", "kalman", {"theta": [1, 2]})
        state = sm.get("BTC", "1h", "kalman")
        assert state == {"theta": [1, 2]}

        assert len(sm.list_keys()) == 1
        assert ("BTC", "1h", "kalman") in sm.list_keys()

        sm.reset("BTC", "1h", "kalman")
        assert sm.get("BTC", "1h", "kalman") is None

    def test_in_memory_reset_all(self):
        sm = InMemoryStateManager()
        sm.set("BTC", "1h", "kalman", {"a": 1})
        sm.set("ETH", "1h", "kalman", {"a": 2})
        assert len(sm.list_keys()) == 2

        sm.reset_all()
        assert len(sm.list_keys()) == 0


# ── Registry Tests ──


class TestPluginRegistry:

    def test_register_and_get(self):
        reg = PluginRegistry("test")

        @reg.register("foo")
        class Foo:
            pass

        assert reg.has("foo")
        assert reg.get("foo") is Foo

    def test_duplicate_registration_fails(self):
        reg = PluginRegistry("test")

        @reg.register("bar")
        class Bar:
            pass

        with pytest.raises(ValueError, match="already registered"):

            @reg.register("bar")
            class Bar2:
                pass

    def test_get_missing_raises(self):
        reg = PluginRegistry("test")
        with pytest.raises(KeyError, match="not found"):
            reg.get("missing")

    def test_list_names(self):
        reg = PluginRegistry("test")

        @reg.register("alpha")
        class A:
            pass

        @reg.register("beta")
        class B:
            pass

        assert reg.list_names() == ["alpha", "beta"]


# ── Contract Tests ──


class TestContracts:

    def test_degradation_level_values(self):
        assert DegradationLevel.FULL.value == "full"
        assert DegradationLevel.PARTIAL.value == "partial"
        assert DegradationLevel.FALLBACK.value == "fallback"
        assert DegradationLevel.FAILED.value == "failed"

    def test_pipeline_request_resolve_window_default(self):
        cfg = self._make_resolved_config(window_size=100)
        req = PipelineRequest(
            df=pd.DataFrame(),
            asset="BTC",
            timeframe="1h",
            mode="fit_last",
            config=cfg,
        )
        assert req.resolve_window() == 100

    def test_pipeline_request_resolve_window_regime_override(self):
        cfg = self._make_resolved_config(window_size=100, regime_window_override=True)
        regime = RegimeSnapshot(
            label="CLEAN_TREND",
            confidence=0.8,
            transition_prob=0.1,
            suggested_window=60,
        )
        req = PipelineRequest(
            df=pd.DataFrame(),
            asset="BTC",
            timeframe="1h",
            mode="fit_last",
            config=cfg,
            regime=regime,
        )
        assert req.resolve_window() == 60

    def test_pipeline_request_resolve_window_regime_clamped(self):
        cfg = self._make_resolved_config(
            window_size=100, regime_window_override=True, min_window=20, max_window=200
        )
        regime = RegimeSnapshot(
            label="CHOPPY", confidence=0.5, transition_prob=0.3,
            suggested_window=5,  # below min
        )
        req = PipelineRequest(
            df=pd.DataFrame(), asset="BTC", timeframe="1h",
            mode="fit_last", config=cfg, regime=regime,
        )
        assert req.resolve_window() == 20  # clamped to min

    def test_pipeline_request_explicit_effective_window(self):
        cfg = self._make_resolved_config(window_size=100)
        req = PipelineRequest(
            df=pd.DataFrame(), asset="BTC", timeframe="1h",
            mode="fit_last", config=cfg, effective_window=75,
        )
        assert req.resolve_window() == 75

    def test_regime_window_defaults_populate_suggested_window(self):
        """OrchestratorConfig.regime_window_defaults should provide window when regime has no suggested_window."""
        from app.regression.config.schema import OrchestratorConfig

        orch = OrchestratorConfig()
        assert orch.regime_window_defaults["VOLATILE_TREND"] == 60
        assert orch.regime_window_defaults["CLEAN_TREND"] == 150
        assert orch.regime_window_defaults["CHOPPY"] == 30
        assert orch.regime_window_defaults["QUIET_MR"] == 100

    def test_regime_window_defaults_resolve_via_request(self):
        """When suggested_window is populated from defaults, resolve_window() returns it."""
        cfg = self._make_resolved_config(
            window_size=100, regime_window_override=True, min_window=15, max_window=300,
        )
        # Simulate what universe.py does: populate suggested_window from defaults
        regime = RegimeSnapshot(
            label="VOLATILE_TREND", confidence=0.7, transition_prob=0.2,
            suggested_window=60,  # as populated from regime_window_defaults
        )
        req = PipelineRequest(
            df=pd.DataFrame(), asset="BTC", timeframe="1h",
            mode="fit_last", config=cfg, regime=regime,
        )
        assert req.resolve_window() == 60

    def test_regime_explicit_suggested_window_overrides_defaults(self):
        """An explicit suggested_window should take precedence (already populated)."""
        cfg = self._make_resolved_config(
            window_size=100, regime_window_override=True, min_window=15, max_window=300,
        )
        regime = RegimeSnapshot(
            label="CLEAN_TREND", confidence=0.9, transition_prob=0.1,
            suggested_window=80,  # explicitly set, not from defaults (which would be 150)
        )
        req = PipelineRequest(
            df=pd.DataFrame(), asset="BTC", timeframe="1h",
            mode="fit_last", config=cfg, regime=regime,
        )
        assert req.resolve_window() == 80  # uses explicit, not default 150

    def test_ensemble_result_has_agreement_and_degradation(self):
        er = EnsembleResult(center=100.0, slope=0.01, confidence=0.8)
        assert er.agreement_score == 0.0
        assert er.degradation == DegradationLevel.FULL
        assert er.dominant_method == ""

    def _make_resolved_config(self, **overrides) -> ResolvedPipelineConfig:
        defaults = dict(
            asset="BTC", timeframe="1h", asset_class="crypto",
            volume_profile=VolumeProfile.CONTINUOUS, config_hash="test",
            window_size=100, min_window=15, max_window=300,
            atr_period=14, trend_atr_fraction=0.10, spread_atr_fraction=0.15,
            momentum_atr_fraction=0.10, neutral_slope_atr_fraction=0.04,
            band_multiplier=2.0, slope_acceleration_alpha=0.0,
            features=(PluginConfig(name="log_price"),),
            methods=(("theil_sen", PluginConfig(name="theil_sen")),),
            ensemble=PluginConfig(name="simple_weighted"),
            uncertainty=PluginConfig(name="percentile_bands"),
            session_gap_handling=False, low_liquidity_window_handling=False,
            regime_context_enabled=True, regime_window_override=False,
            mtf_enabled=False, mtf_timeframes=(),
        )
        defaults.update(overrides)
        return ResolvedPipelineConfig(**defaults)


# ── Pipeline Skeleton Tests ──


class TestPipelineSkeleton:
    """Test pipeline runs with stub plugins and produces valid contracts."""

    def _make_df(self, n: int = 150) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": np.arange(n) + 100.0,
                "high": np.arange(n) + 101.0,
                "low": np.arange(n) + 99.0,
                "close": np.arange(n) + 100.5,
                "volume": np.ones(n) * 1000.0,
            },
            index=pd.date_range("2025-01-01", periods=n, freq="1h"),
        )

    def _make_config(self) -> ResolvedPipelineConfig:
        return ResolvedPipelineConfig(
            asset="BTCUSDT", timeframe="1h", asset_class="crypto",
            volume_profile=VolumeProfile.CONTINUOUS, config_hash="test123",
            window_size=50, min_window=15, max_window=300,
            atr_period=14, trend_atr_fraction=0.10, spread_atr_fraction=0.15,
            momentum_atr_fraction=0.10, neutral_slope_atr_fraction=0.04,
            band_multiplier=2.0, slope_acceleration_alpha=0.0,
            features=(),  # no registered features
            methods=(),  # no registered methods
            ensemble=PluginConfig(name="stub"),
            uncertainty=PluginConfig(name="stub"),
            session_gap_handling=False, low_liquidity_window_handling=False,
            regime_context_enabled=False, regime_window_override=False,
            mtf_enabled=False, mtf_timeframes=(),
        )

    def test_pipeline_with_no_plugins_returns_failed(self):
        cfg = self._make_config()
        pipeline = RegressionPipeline(cfg, validate=False)
        req = PipelineRequest(
            df=self._make_df(), asset="BTCUSDT", timeframe="1h",
            mode="fit_last", config=cfg,
        )
        result = pipeline.compute(req)

        assert isinstance(result, RegressionResult)
        assert result.is_valid is False
        assert result.degradation == DegradationLevel.FAILED
        assert result.config_hash == "test123"
        assert result.asset == "BTCUSDT"
        assert result.timeframe == "1h"

    def test_pipeline_with_insufficient_data_returns_failed(self):
        cfg = self._make_config()
        pipeline = RegressionPipeline(cfg, validate=False)
        short_df = self._make_df(10)
        req = PipelineRequest(
            df=short_df, asset="BTCUSDT", timeframe="1h",
            mode="fit_last", config=cfg,
        )
        result = pipeline.compute(req)

        assert result.is_valid is False
        assert result.degradation == DegradationLevel.FAILED

    def test_pipeline_reset(self):
        cfg = self._make_config()
        pipeline = RegressionPipeline(cfg, validate=False)
        req = PipelineRequest(
            df=self._make_df(), asset="BTCUSDT", timeframe="1h",
            mode="fit_last", config=cfg,
        )
        pipeline.compute(req)
        assert pipeline._bars_seen == 1

        pipeline.reset()
        assert pipeline._bars_seen == 0
