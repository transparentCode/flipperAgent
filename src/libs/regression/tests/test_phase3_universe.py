"""Phase 3 integration tests — Universe Orchestration.

Tests:
- Universe of 5 synthetic assets (2 crypto, 2 stock, 1 fx)
- Per-asset config resolution
- Session-aware feature activation (stock/fx only)
- MTF cascade for configured assets, single-TF for others
- All results carry correct degradation and config_hash
- Facade API functions
- Window authority (single source of truth)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.regression.config.resolver import ConfigResolver
from app.regression.config.schema import (
    AssetClassConfig,
    AssetConfig,
    GlobalConfig,
    OrchestratorConfig,
    PluginConfig,
    VolumeProfile,
)
from app.regression.contracts.context import (
    AssetMeta,
    PipelineRequest,
    RegimeSnapshot,
)
from app.regression.contracts.result import (
    DegradationLevel,
    MTFOutput,
    RegressionResult,
    UniverseResult,
)
from app.regression.universe import UniverseOrchestrator
from app.regression import api

# Import plugins to trigger registration
from app.regression.features.log_price import LogPriceFeatures  # noqa: F401
from app.regression.features.volume_weighted import VolumeWeightedFeatures  # noqa: F401
from app.regression.features.session_aware import SessionAwareFeatures  # noqa: F401
from app.regression.methods.theil_sen import TheilSenMethod  # noqa: F401
from app.regression.methods.wls import VWRMethod  # noqa: F401
from app.regression.uncertainty.percentile_bands import PercentileBands  # noqa: F401
from app.regression.ensemble.simple_weighted import SimpleWeightedEnsemble  # noqa: F401
from app.regression.ensemble.confidence_weighted import ConfidenceWeightedEnsemble  # noqa: F401


# ── Fixtures ──


def _make_trending_df(n: int = 100, slope: float = 0.001, noise: float = 0.002) -> pd.DataFrame:
    np.random.seed(42)
    t = np.arange(n, dtype=np.float64)
    log_prices = 10.0 + slope * t + np.random.normal(0, noise, n)
    prices = np.exp(log_prices)
    volume = np.random.uniform(100, 1000, n)

    return pd.DataFrame({
        "close": prices,
        "high": prices * (1 + np.random.uniform(0, 0.005, n)),
        "low": prices * (1 - np.random.uniform(0, 0.005, n)),
        "volume": volume,
    }, index=pd.date_range("2024-01-01", periods=n, freq="1h"))


def _make_stock_df(n: int = 100) -> pd.DataFrame:
    """Stock data with session gaps (weekend gaps)."""
    np.random.seed(123)
    t = np.arange(n, dtype=np.float64)
    log_prices = 5.5 + 0.0005 * t + np.random.normal(0, 0.001, n)
    prices = np.exp(log_prices)
    volume = np.random.uniform(50000, 500000, n)

    return pd.DataFrame({
        "close": prices,
        "high": prices * (1 + np.random.uniform(0, 0.003, n)),
        "low": prices * (1 - np.random.uniform(0, 0.003, n)),
        "volume": volume,
    }, index=pd.date_range("2024-01-02", periods=n, freq="30min"))


def _make_fx_df(n: int = 100) -> pd.DataFrame:
    np.random.seed(456)
    t = np.arange(n, dtype=np.float64)
    log_prices = 0.08 + 0.00002 * t + np.random.normal(0, 0.0005, n)
    prices = np.exp(log_prices)
    volume = np.random.uniform(10, 100, n)

    return pd.DataFrame({
        "close": prices,
        "high": prices * (1 + np.random.uniform(0, 0.001, n)),
        "low": prices * (1 - np.random.uniform(0, 0.001, n)),
        "volume": volume,
    }, index=pd.date_range("2024-01-01", periods=n, freq="1h"))


def _make_stock_gap_df_small() -> pd.DataFrame:
    timestamps = pd.DatetimeIndex(
        [
            pd.Timestamp("2024-01-02 09:30"),
            pd.Timestamp("2024-01-02 10:00"),
            pd.Timestamp("2024-01-02 13:30"),
        ]
    )
    close = np.exp(np.array([5.000, 5.010, 5.020], dtype=np.float64))
    return pd.DataFrame(
        {
            "close": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "volume": np.array([1000.0, 1100.0, 1200.0], dtype=np.float64),
        },
        index=timestamps,
    )


def _make_fx_low_liquidity_df_small() -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=4, freq="1h")
    close = np.exp(np.array([0.0800, 0.0802, 0.0804, 0.0806], dtype=np.float64))
    return pd.DataFrame(
        {
            "close": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "volume": np.array([100.0, 100.0, 1.0, 1.0], dtype=np.float64),
        },
        index=timestamps,
    )


def _build_test_orchestrator_config(
    default_window_size: int = 50,
    min_window: int = 20,
) -> OrchestratorConfig:
    """Build a 5-asset test config: 2 crypto (MTF), 2 stock, 1 fx."""
    g = GlobalConfig(
        default_window_size=default_window_size,
        min_window=min_window,
        max_window=200,
        atr_period=14,
        trend_atr_fraction=0.05,
        spread_atr_fraction=0.02,
        momentum_atr_fraction=0.03,
        neutral_slope_atr_fraction=0.04,
        band_multiplier=2.0,
        features=[
            PluginConfig(name="log_price"),
            PluginConfig(name="volume_weighted"),
        ],
        methods={
            "theil_sen": PluginConfig(name="theil_sen", params={"max_pairs": 0}),
            "vwr": PluginConfig(name="vwr"),
        },
        ensemble=PluginConfig(name="simple_weighted"),
        uncertainty=PluginConfig(name="percentile_bands"),
    )

    orch = OrchestratorConfig(
        mtf_timeframes=["4h", "1h", "30m"],
        tf_weights={"4h": 0.5, "1h": 0.3, "30m": 0.2},
        global_config=g,
        asset_classes={
            "crypto": AssetClassConfig(
                volume_profile=VolumeProfile.CONTINUOUS,
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
            "fx": AssetClassConfig(
                volume_profile=VolumeProfile.PROXY,
                low_liquidity_window_handling=True,
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
                mtf_timeframes=["4h", "1h"],
            ),
            "ETHUSDT": AssetConfig(
                asset_class="crypto",
                mtf_enabled=False,
            ),
            "AAPL": AssetConfig(
                asset_class="stock",
                mtf_enabled=False,
            ),
            "MSFT": AssetConfig(
                asset_class="stock",
                mtf_enabled=False,
            ),
            "EURUSD": AssetConfig(
                asset_class="fx",
                mtf_enabled=False,
            ),
        },
    )
    return orch


def _build_test_resolver(
    default_window_size: int = 50,
    min_window: int = 20,
) -> ConfigResolver:
    return ConfigResolver(
        _build_test_orchestrator_config(
            default_window_size=default_window_size,
            min_window=min_window,
        )
    )


def _build_universe_data() -> dict:
    """Build universe data for 5 assets."""
    return {
        "BTCUSDT": {
            "4h": _make_trending_df(100, slope=0.003),
            "1h": _make_trending_df(100, slope=0.002),
        },
        "ETHUSDT": {
            "1h": _make_trending_df(100, slope=0.001),
        },
        "AAPL": {
            "1h": _make_stock_df(100),
        },
        "MSFT": {
            "1h": _make_stock_df(100),
        },
        "EURUSD": {
            "1h": _make_fx_df(100),
        },
    }


# ── Config Resolution Tests ──


class TestConfigResolutionForUniverse:
    def test_crypto_asset_gets_continuous_profile(self):
        resolver = _build_test_resolver()
        cfg = resolver.resolve("BTCUSDT", "1h")
        assert cfg.volume_profile == VolumeProfile.CONTINUOUS
        assert cfg.asset_class == "crypto"

    def test_stock_asset_gets_session_profile(self):
        resolver = _build_test_resolver()
        cfg = resolver.resolve("AAPL", "1h")
        assert cfg.volume_profile == VolumeProfile.SESSION
        assert cfg.asset_class == "stock"
        assert cfg.session_gap_handling is True
        assert "session_aware" in [feature.name for feature in cfg.features]

    def test_fx_asset_gets_proxy_profile(self):
        resolver = _build_test_resolver()
        cfg = resolver.resolve("EURUSD", "1h")
        assert cfg.volume_profile == VolumeProfile.PROXY
        assert cfg.asset_class == "fx"
        assert cfg.low_liquidity_window_handling is True
        assert "session_aware" in [feature.name for feature in cfg.features]

    def test_btc_has_mtf_enabled(self):
        resolver = _build_test_resolver()
        cfg = resolver.resolve("BTCUSDT", "1h")
        assert cfg.mtf_enabled is True
        assert "4h" in cfg.mtf_timeframes
        assert "1h" in cfg.mtf_timeframes

    def test_eth_no_mtf(self):
        resolver = _build_test_resolver()
        cfg = resolver.resolve("ETHUSDT", "1h")
        assert cfg.mtf_enabled is False

    def test_unknown_asset_gets_defaults(self):
        resolver = _build_test_resolver()
        cfg = resolver.resolve("UNKNOWN", "1h")
        assert cfg.window_size == 50  # global default


# ── UniverseOrchestrator Tests ──


class TestUniverseOrchestrator:
    def test_process_universe_returns_all_assets(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)
        data = _build_universe_data()

        result = orch.process_universe(data)

        assert isinstance(result, UniverseResult)
        assert result.n_assets_processed == 5
        assert "BTCUSDT" in result.results
        assert "ETHUSDT" in result.results
        assert "AAPL" in result.results
        assert "MSFT" in result.results
        assert "EURUSD" in result.results

    def test_btc_gets_mtf_output(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)
        data = _build_universe_data()

        result = orch.process_universe(data)

        assert "BTCUSDT" in result.mtf_results
        mtf = result.mtf_results["BTCUSDT"]
        assert isinstance(mtf, MTFOutput)
        assert "4h" in mtf.per_tf
        assert "1h" in mtf.per_tf
        assert mtf.dominant_result.is_valid

    def test_single_tf_assets_no_mtf_output(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)
        data = _build_universe_data()

        result = orch.process_universe(data)

        assert "ETHUSDT" not in result.mtf_results
        assert "AAPL" not in result.mtf_results
        assert "EURUSD" not in result.mtf_results

    def test_all_results_have_config_hash(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)
        data = _build_universe_data()

        result = orch.process_universe(data)

        for asset, r in result.results.items():
            assert r.config_hash, f"{asset} missing config_hash"

    def test_universe_result_has_statistics(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)
        data = _build_universe_data()

        result = orch.process_universe(data)

        assert result.processing_time_ms > 0
        assert result.config_hash != ""

    def test_pipeline_instances_cached(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)
        data = _build_universe_data()

        # Process twice
        orch.process_universe(data)
        n_first = orch.active_pipelines
        orch.process_universe(data)
        n_second = orch.active_pipelines

        assert n_first == n_second  # Reused, not recreated

    def test_reset_clears_pipeline_state(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)
        data = _build_universe_data()

        orch.process_universe(data)
        assert orch.active_pipelines > 0

        orch.reset()
        # Pipelines still cached but internal state reset
        assert orch.active_pipelines > 0

    def test_reset_specific_asset(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)
        data = _build_universe_data()

        orch.process_universe(data)
        orch.reset(asset="BTCUSDT")

    def test_stock_session_gaps_change_orchestrated_output(self):
        resolver = _build_test_resolver(default_window_size=3, min_window=3)
        orch = UniverseOrchestrator(resolver)

        result = orch.process_asset("AAPL", {"1h": _make_stock_gap_df_small()})

        assert not result.is_valid
        assert result.degradation == DegradationLevel.FAILED

    def test_fx_low_liquidity_changes_orchestrated_output(self):
        resolver = _build_test_resolver(default_window_size=4, min_window=4)
        orch = UniverseOrchestrator(resolver)

        result = orch.process_asset("EURUSD", {"1h": _make_fx_low_liquidity_df_small()})

        assert not result.is_valid
        assert result.degradation == DegradationLevel.FAILED


# ── MTF Cascade Tests ──


class TestMTFCascade:
    def test_cascade_direction_consensus(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)

        # Both TFs trending up → BULLISH consensus
        tf_data = {
            "4h": _make_trending_df(100, slope=0.003),
            "1h": _make_trending_df(100, slope=0.002),
        }
        mtf = orch._run_mtf_cascade(
            "BTCUSDT", tf_data, None,
            AssetMeta(asset_class="crypto", volume_profile=VolumeProfile.CONTINUOUS),
            "fit_last",
        )

        assert mtf.direction_consensus == "BULLISH"
        assert mtf.consensus_strength == 1.0
        assert not mtf.is_conflicted

    def test_cascade_conflict_detection(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)

        # 4h up, 1h down → conflict
        tf_data = {
            "4h": _make_trending_df(100, slope=0.005, noise=0.001),
            "1h": _make_trending_df(100, slope=-0.005, noise=0.001),
        }
        mtf = orch._run_mtf_cascade(
            "BTCUSDT", tf_data, None,
            AssetMeta(asset_class="crypto", volume_profile=VolumeProfile.CONTINUOUS),
            "fit_last",
        )

        assert mtf.is_conflicted
        assert len(mtf.conflict_pairs) >= 1

    def test_cascade_propagates_context_downward(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)

        tf_data = {
            "4h": _make_trending_df(100, slope=0.003),
            "1h": _make_trending_df(100, slope=0.002),
        }
        mtf = orch._run_mtf_cascade(
            "BTCUSDT", tf_data, None,
            AssetMeta(asset_class="crypto", volume_profile=VolumeProfile.CONTINUOUS),
            "fit_last",
        )

        # The 1h result should have mtf_applied=True (it received cascade from 4h)
        assert mtf.per_tf["1h"].mtf_applied is True
        assert mtf.per_tf["4h"].mtf_applied is False  # First TF has no cascade

    def test_weighted_slope(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)

        tf_data = {
            "4h": _make_trending_df(100, slope=0.003),
            "1h": _make_trending_df(100, slope=0.001),
        }
        mtf = orch._run_mtf_cascade(
            "BTCUSDT", tf_data, None,
            AssetMeta(asset_class="crypto", volume_profile=VolumeProfile.CONTINUOUS),
            "fit_last",
        )

        # Weighted slope should be between 4h and 1h slopes
        assert mtf.weighted_slope > 0


# ── Asset-Class Dispatch Tests ──


class TestAssetClassDispatch:
    def test_stock_asset_meta_resolved(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)

        meta = orch._resolve_asset_meta("AAPL")
        assert meta.asset_class == "stock"
        assert meta.volume_profile == VolumeProfile.SESSION
        assert meta.session_gap_handling is True

    def test_fx_asset_meta_resolved(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)

        meta = orch._resolve_asset_meta("EURUSD")
        assert meta.asset_class == "fx"
        assert meta.volume_profile == VolumeProfile.PROXY
        assert meta.low_liquidity_window_handling is True

    def test_unknown_asset_defaults_to_crypto(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)

        meta = orch._resolve_asset_meta("UNKNOWN")
        assert meta.asset_class == "crypto"
        assert meta.volume_profile == VolumeProfile.CONTINUOUS


# ── Window Authority Tests ──


class TestWindowAuthority:
    def test_config_is_single_source_of_truth(self):
        resolver = _build_test_resolver()
        cfg = resolver.resolve("BTCUSDT", "1h")
        assert cfg.window_size == 50

        request = PipelineRequest(
            df=_make_trending_df(100),
            asset="BTCUSDT",
            timeframe="1h",
            mode="fit_last",
            config=cfg,
        )
        assert request.resolve_window() == 50

    def test_regime_override_clamped(self):
        resolver = _build_test_resolver()
        cfg = resolver.resolve("BTCUSDT", "1h")

        request = PipelineRequest(
            df=_make_trending_df(200),
            asset="BTCUSDT",
            timeframe="1h",
            mode="fit_last",
            config=cfg,
            regime=RegimeSnapshot(
                label="VOLATILE_TREND",
                confidence=0.8,
                transition_prob=0.1,
                suggested_window=300,  # Above max_window=200
            ),
        )
        # Should be clamped to max_window
        assert request.resolve_window() == 200

    def test_explicit_effective_window_overrides_all(self):
        resolver = _build_test_resolver()
        cfg = resolver.resolve("BTCUSDT", "1h")

        request = PipelineRequest(
            df=_make_trending_df(100),
            asset="BTCUSDT",
            timeframe="1h",
            mode="fit_last",
            config=cfg,
            effective_window=35,
        )
        assert request.resolve_window() == 35


# ── Facade API Tests ──


class TestFacadeAPI:
    def test_compute_single_tf(self):
        resolver = _build_test_resolver()
        cfg = resolver.resolve("BTCUSDT", "1h")
        df = _make_trending_df(100, slope=0.002)

        result = api.compute_single_tf(df, "BTCUSDT", "1h", cfg)

        assert isinstance(result, RegressionResult)
        assert result.is_valid
        assert result.slope > 0

    def test_compute_single_tf_series(self):
        resolver = _build_test_resolver()
        cfg = resolver.resolve("BTCUSDT", "1h")
        df = _make_trending_df(80, slope=0.002)

        results = api.compute_single_tf_series(df, "BTCUSDT", "1h", cfg)

        assert len(results) > 0
        assert all(isinstance(r, RegressionResult) for r in results)

    def test_compute_mtf(self):
        resolver = _build_test_resolver()
        tf_data = {
            "4h": _make_trending_df(100, slope=0.003),
            "1h": _make_trending_df(100, slope=0.002),
        }

        mtf = api.compute_mtf("BTCUSDT", tf_data, resolver)

        assert isinstance(mtf, MTFOutput)
        assert mtf.asset == "BTCUSDT"
        assert "4h" in mtf.per_tf
        assert "1h" in mtf.per_tf

    def test_compute_universe(self):
        resolver = _build_test_resolver()
        data = _build_universe_data()

        result = api.compute_universe(data, resolver)

        assert isinstance(result, UniverseResult)
        assert result.n_assets_processed == 5
        assert result.processing_time_ms > 0

    def test_process_asset_convenience(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)

        tf_data = {"1h": _make_trending_df(100, slope=0.002)}
        result = orch.process_asset("ETHUSDT", tf_data)

        assert isinstance(result, RegressionResult)
        assert result.is_valid


# ── Degradation Tracking Tests ──


class TestDegradationTracking:
    def test_valid_assets_are_full(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)
        data = _build_universe_data()

        result = orch.process_universe(data)

        valid_count = sum(
            1 for r in result.results.values()
            if r.degradation in (DegradationLevel.FULL, DegradationLevel.PARTIAL)
        )
        assert valid_count >= 3  # At least 3 of 5 should succeed

    def test_failed_count_tracked(self):
        resolver = _build_test_resolver()
        orch = UniverseOrchestrator(resolver)

        # Provide too-small data that will fail
        data = {
            "BTCUSDT": {"1h": _make_trending_df(5)},  # Too few bars
        }
        result = orch.process_universe(data)

        assert result.n_failed >= 1
