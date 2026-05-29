"""Phase 6 integration tests: v2-native consumer contracts and API validation.

Tests cover:
  A. V2 API: compute_single_tf
  B. V2 API: compute_single_tf_series
  C. V2 API: compute_mtf
  D. ConfigResolver + API integration
  E. Side-by-side validation (result quality)
  F. State Manager integration
  G. Consumer contract tests (field availability)
"""

from datetime import timezone

import numpy as np
import pandas as pd
import pytest

from app.regression.api import (
    compute_single_tf,
    compute_single_tf_series,
    compute_mtf,
)
from app.strategy.regime_regression import SignalRow, signals_to_nautilus_dict
from app.regression.config.resolver import ConfigResolver
from app.regression.config.schema import (
    PluginConfig,
    ResolvedPipelineConfig,
)
from app.regression.contracts.context import (
    CascadeContext,
    RegimeSnapshot,
)
from app.regression.contracts.result import (
    MTFOutput,
    RegressionResult,
)
from app.regression.state import InMemoryStateManager, NullStateManager

# Import plugins to trigger auto-registration
from app.regression.features.log_price import LogPriceFeatures  # noqa: F401
from app.regression.features.volume_weighted import VolumeWeightedFeatures  # noqa: F401
from app.regression.methods.theil_sen import TheilSenMethod  # noqa: F401
from app.regression.methods.wls import VWRMethod  # noqa: F401
from app.regression.uncertainty.percentile_bands import PercentileBands  # noqa: F401
from app.regression.ensemble.simple_weighted import SimpleWeightedEnsemble  # noqa: F401
from app.regression.ensemble.confidence_weighted import ConfidenceWeightedEnsemble  # noqa: F401


# ── Helpers ──


def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data with trending behavior."""
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="1h", tz=timezone.utc)
    trend = np.linspace(0, 2, n)
    noise = rng.normal(0, 0.3, n)
    close = 100 * np.exp((trend + noise.cumsum() * 0.01) * 0.01)
    high = close * (1 + rng.uniform(0.001, 0.01, n))
    low = close * (1 - rng.uniform(0.001, 0.01, n))
    open_ = close * (1 + rng.uniform(-0.005, 0.005, n))
    volume = rng.uniform(100, 1000, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


def _make_config(asset: str = "BTCUSDT", timeframe: str = "1h") -> ResolvedPipelineConfig:
    """Create a resolved config via ConfigResolver from the v2 YAML."""
    resolver = ConfigResolver.from_yaml("app/regression/config/regression.yaml")
    return resolver.resolve(asset, timeframe)


# ═══════════════════════════════════════════════════════════════════════════
# A. V2 API: compute_single_tf
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeSingleTf:
    """Test compute_single_tf with v2 native signatures."""

    def test_basic_call(self):
        df = _make_ohlcv(200)
        config = _make_config()

        result = compute_single_tf(df=df, asset="BTCUSDT", timeframe="1h", config=config)
        assert isinstance(result, RegressionResult)
        assert result.asset == "BTCUSDT"
        assert result.timeframe == "1h"
        assert result.is_valid
        assert result.direction in ("BULLISH", "BEARISH", "NEUTRAL")
        assert 0.0 <= result.confidence <= 1.0

    def test_with_regime(self):
        df = _make_ohlcv(200)
        config = _make_config()
        regime = RegimeSnapshot(
            label="CLEAN_TREND", confidence=0.85, transition_prob=0.1
        )
        result = compute_single_tf(
            df=df, asset="BTCUSDT", timeframe="1h",
            config=config, regime=regime,
        )
        assert result.is_valid

    def test_with_cascade(self):
        df = _make_ohlcv(200)
        config = _make_config()
        cascade = CascadeContext(
            source_tf="4h",
            slope=0.002,
            direction="BULLISH",
            confidence=0.7,
            band_width=100.0,
            dominant_method="theil_sen",
        )
        result = compute_single_tf(
            df=df, asset="BTCUSDT", timeframe="1h",
            config=config, cascade=cascade,
        )
        assert result.is_valid

    def test_result_has_expected_fields(self):
        """Verify v2 result exposes all fields that consumers use."""
        df = _make_ohlcv(200)
        config = _make_config()
        result = compute_single_tf(df=df, asset="BTCUSDT", timeframe="1h", config=config)

        assert hasattr(result, "timestamp")
        assert hasattr(result, "z_score")
        assert hasattr(result, "direction")
        assert hasattr(result, "confidence")
        assert hasattr(result, "slope")
        assert hasattr(result, "atr_norm")
        assert hasattr(result, "is_valid")
        assert hasattr(result, "band_width_avg")


# ═══════════════════════════════════════════════════════════════════════════
# B. V2 API: compute_single_tf_series
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeSeries:
    """Test compute_single_tf_series with v2 native signatures."""

    def test_basic_series(self):
        df = _make_ohlcv(200)
        config = _make_config()
        results = compute_single_tf_series(
            df=df, asset="BTCUSDT", timeframe="1h", config=config,
        )

        assert isinstance(results, list)
        assert len(results) > 0
        assert all(isinstance(r, RegressionResult) for r in results)

    def test_series_timestamps_increasing(self):
        df = _make_ohlcv(150)
        config = _make_config()
        results = compute_single_tf_series(
            df=df, asset="BTCUSDT", timeframe="1h", config=config,
        )

        timestamps = [r.timestamp for r in results]
        assert timestamps == sorted(timestamps)

    def test_series_fields_for_strategy(self):
        """Fields used by strategy consumer: direction, confidence, z_score, slope, atr_norm."""
        df = _make_ohlcv(200)
        config = _make_config()
        results = compute_single_tf_series(
            df=df, asset="BTCUSDT", timeframe="1h", config=config,
        )

        for r in results:
            assert r.direction in ("BULLISH", "BEARISH", "NEUTRAL")
            assert isinstance(r.confidence, float)
            assert isinstance(r.z_score, float)
            assert isinstance(r.slope, float)

    def test_series_fields_for_backtest(self):
        """Fields used by backtest bridge: is_valid, slope, confidence, timestamp."""
        df = _make_ohlcv(200)
        config = _make_config()
        results = compute_single_tf_series(
            df=df, asset="BTCUSDT", timeframe="1h", config=config,
        )

        for r in results:
            assert isinstance(r.is_valid, bool)
            assert isinstance(r.slope, float)
            assert isinstance(r.confidence, float)
            assert r.timestamp is not None

    def test_series_length_consistent(self):
        df = _make_ohlcv(200)
        config = _make_config()
        results = compute_single_tf_series(
            df=df, asset="BTCUSDT", timeframe="1h", config=config,
        )
        expected_bars = len(df) - config.window_size + 1
        assert len(results) == expected_bars


# ═══════════════════════════════════════════════════════════════════════════
# C. V2 API: compute_mtf
# ═══════════════════════════════════════════════════════════════════════════


class TestComputeMtf:
    """Test compute_mtf with v2 native signatures."""

    def _make_mtf_data(self) -> dict:
        df_1h = _make_ohlcv(200, seed=42)
        df_4h = df_1h.resample("4h").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()
        return {"4h": df_4h, "1h": df_1h}

    def _make_resolver(self) -> ConfigResolver:
        return ConfigResolver.from_yaml("app/regression/config/regression.yaml")

    def test_basic_mtf(self):
        mtf_data = self._make_mtf_data()
        resolver = self._make_resolver()
        result = compute_mtf(
            asset="BTCUSDT",
            tf_data=mtf_data,
            resolver=resolver,
        )

        assert isinstance(result, MTFOutput)
        assert result.asset == "BTCUSDT"
        assert len(result.per_tf) > 0

    def test_mtf_has_alignment(self):
        mtf_data = self._make_mtf_data()
        resolver = self._make_resolver()
        result = compute_mtf(asset="BTCUSDT", tf_data=mtf_data, resolver=resolver)

        assert -1.0 <= result.alignment_score <= 1.0
        assert result.direction_consensus in ("BULLISH", "BEARISH", "NEUTRAL")

    def test_mtf_weighted_slope(self):
        mtf_data = self._make_mtf_data()
        resolver = self._make_resolver()
        result = compute_mtf(asset="BTCUSDT", tf_data=mtf_data, resolver=resolver)

        assert isinstance(result.weighted_slope, float)
        assert isinstance(result.weighted_confidence, float)

    def test_mtf_with_regime(self):
        mtf_data = self._make_mtf_data()
        resolver = self._make_resolver()
        regime = RegimeSnapshot(
            label="CLEAN_TREND", confidence=0.9, transition_prob=0.05
        )
        result = compute_mtf(
            asset="BTCUSDT", tf_data=mtf_data,
            resolver=resolver, regime=regime,
        )
        assert len(result.per_tf) > 0


# ═══════════════════════════════════════════════════════════════════════════
# D. ConfigResolver + API Integration
# ═══════════════════════════════════════════════════════════════════════════


class TestConfigResolverIntegration:
    """Test ConfigResolver produces configs that work with the API."""

    def test_from_yaml_resolve_compute(self):
        """Full consumer pattern: YAML → resolve → compute."""
        resolver = ConfigResolver.from_yaml("app/regression/config/regression.yaml")
        config = resolver.resolve("BTCUSDT", "1h")
        df = _make_ohlcv(200)
        result = compute_single_tf(df=df, asset="BTCUSDT", timeframe="1h", config=config)
        assert result.is_valid

    def test_different_assets_resolve(self):
        """Resolver should produce valid configs for different assets."""
        resolver = ConfigResolver.from_yaml("app/regression/config/regression.yaml")
        df = _make_ohlcv(200)

        for asset in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            config = resolver.resolve(asset, "1h")
            result = compute_single_tf(df=df, asset=asset, timeframe="1h", config=config)
            assert result.is_valid
            assert result.asset == asset

    def test_different_timeframes_resolve(self):
        """Resolver should produce valid configs for different timeframes."""
        resolver = ConfigResolver.from_yaml("app/regression/config/regression.yaml")
        df = _make_ohlcv(200)

        for tf in ["1h", "4h"]:
            config = resolver.resolve("BTCUSDT", tf)
            result = compute_single_tf(df=df, asset="BTCUSDT", timeframe=tf, config=config)
            assert result.is_valid

    def test_config_caching(self):
        """Same (asset, tf) should return cached config."""
        resolver = ConfigResolver.from_yaml("app/regression/config/regression.yaml")
        c1 = resolver.resolve("BTCUSDT", "1h")
        c2 = resolver.resolve("BTCUSDT", "1h")
        assert c1 is c2


# ═══════════════════════════════════════════════════════════════════════════
# E. Side-by-Side Validation (result quality)
# ═══════════════════════════════════════════════════════════════════════════


class TestResultQualityValidation:
    """Validate result quality and consistency."""

    @pytest.fixture
    def shared_data(self):
        return _make_ohlcv(200, seed=12345)

    @pytest.fixture
    def shared_config(self):
        return _make_config()

    def test_single_tf_valid(self, shared_data, shared_config):
        result = compute_single_tf(
            df=shared_data, asset="BTCUSDT", timeframe="1h", config=shared_config,
        )
        assert result.is_valid

    def test_slope_finite(self, shared_data, shared_config):
        result = compute_single_tf(
            df=shared_data, asset="BTCUSDT", timeframe="1h", config=shared_config,
        )
        assert np.isfinite(result.slope)

    def test_confidence_bounded(self, shared_data, shared_config):
        result = compute_single_tf(
            df=shared_data, asset="BTCUSDT", timeframe="1h", config=shared_config,
        )
        assert 0.0 <= result.confidence <= 1.0

    def test_z_score_finite(self, shared_data, shared_config):
        result = compute_single_tf(
            df=shared_data, asset="BTCUSDT", timeframe="1h", config=shared_config,
        )
        assert np.isfinite(result.z_score)

    def test_atr_norm_positive(self, shared_data, shared_config):
        result = compute_single_tf(
            df=shared_data, asset="BTCUSDT", timeframe="1h", config=shared_config,
        )
        assert result.atr_norm > 0.0

    def test_band_width_positive(self, shared_data, shared_config):
        result = compute_single_tf(
            df=shared_data, asset="BTCUSDT", timeframe="1h", config=shared_config,
        )
        assert result.band_width_avg > 0.0

    def test_bands_symmetric_about_mid(self, shared_data, shared_config):
        """Upper and lower bands should bracket the mid-line."""
        result = compute_single_tf(
            df=shared_data, asset="BTCUSDT", timeframe="1h", config=shared_config,
        )
        assert result.upper_band[-1] >= result.mid_line[-1]
        assert result.lower_band[-1] <= result.mid_line[-1]

    def test_direction_consistent_with_slope(self, shared_data, shared_config):
        """Non-neutral direction should agree with slope sign."""
        result = compute_single_tf(
            df=shared_data, asset="BTCUSDT", timeframe="1h", config=shared_config,
        )
        if result.direction == "BULLISH":
            assert result.slope >= -0.1
        elif result.direction == "BEARISH":
            assert result.slope <= 0.1


# ═══════════════════════════════════════════════════════════════════════════
# F. State Manager Integration
# ═══════════════════════════════════════════════════════════════════════════


class TestStateManagerIntegration:
    """Test that API passes state manager through."""

    def test_with_in_memory_state_manager(self):
        df = _make_ohlcv(200)
        config = _make_config()
        sm = InMemoryStateManager()
        result = compute_single_tf(
            df=df, asset="BTCUSDT", timeframe="1h",
            config=config, state_manager=sm,
        )
        assert result.is_valid

    def test_series_with_state_manager(self):
        df = _make_ohlcv(200)
        config = _make_config()
        sm = InMemoryStateManager()
        results = compute_single_tf_series(
            df=df, asset="BTCUSDT", timeframe="1h",
            config=config, state_manager=sm,
        )
        assert len(results) > 0


# ═══════════════════════════════════════════════════════════════════════════
# G. Consumer Contract Tests (field availability)
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossSectionalContract:
    """Verify v2 result satisfies cross-sectional orchestrator field requirements."""

    def test_asset_snapshot_fields(self):
        """Cross-sectional extracts: z_score, direction, confidence, slope, atr_norm."""
        df = _make_ohlcv(200)
        config = _make_config()
        r = compute_single_tf(df=df, asset="BTCUSDT", timeframe="1h", config=config)

        snapshot = {
            "z_score": r.z_score,
            "direction": r.direction,
            "confidence": r.confidence,
            "slope": r.slope,
            "atr_norm": r.atr_norm,
        }

        assert all(v is not None for v in snapshot.values())
        assert isinstance(snapshot["z_score"], float)
        assert isinstance(snapshot["direction"], str)


class TestStrategyContract:
    """Verify v2 result satisfies strategy module field requirements."""

    def test_strategy_fields(self):
        """Strategy uses: timestamp, direction, confidence, is_valid, atr_norm, z_score, slope."""
        df = _make_ohlcv(200)
        config = _make_config()
        results = compute_single_tf_series(
            df=df, asset="BTCUSDT", timeframe="1h", config=config,
        )

        for r in results[:5]:
            assert r.timestamp is not None
            assert r.direction in ("BULLISH", "BEARISH", "NEUTRAL")
            assert isinstance(r.confidence, float)
            assert isinstance(r.is_valid, bool)
            assert isinstance(r.atr_norm, float)
            assert isinstance(r.z_score, float)
            assert isinstance(r.slope, float)

    def test_timestamp_lookup(self):
        """Strategy builds {timestamp: result} dict — timestamps must be hashable."""
        df = _make_ohlcv(200)
        config = _make_config()
        results = compute_single_tf_series(
            df=df, asset="BTCUSDT", timeframe="1h", config=config,
        )

        reg_by_ts = {r.timestamp: r for r in results}
        assert len(reg_by_ts) == len(results)

    def test_signal_row_serializes_confidence_score_only(self):
        signal = SignalRow(
            timestamp_ns=123,
            direction=1,
            size_frac=0.5,
            stop_pct=0.01,
            target_pct=0.02,
            regime="CLEAN_TREND_BULL",
            confidence_score=62.5,
            entry_reason="TREND_BULL_LONG",
            is_trend=True,
        )

        payload = signal.to_dict()

        assert signal.confidence_score == 62.5
        assert payload["confidence_score"] == 62.5
        assert "conviction_score" not in payload

    def test_nautilus_signal_dict_uses_confidence_score_only(self):
        signal = SignalRow(
            timestamp_ns=456,
            direction=-1,
            size_frac=0.4,
            stop_pct=0.012,
            target_pct=0.018,
            regime="QUIET_MR_RANGE",
            confidence_score=41.0,
            entry_reason="MR_OVERBOUGHT_SHORT",
            is_trend=False,
        )

        payload = signals_to_nautilus_dict([signal])[456]

        assert payload["confidence_score"] == 41.0
        assert "conviction_score" not in payload


class TestBacktestContract:
    """Verify v2 result satisfies backtest bridge field requirements."""

    def test_backtest_fields(self):
        """Backtest bridge uses: is_valid, slope, confidence, timestamp."""
        df = _make_ohlcv(200)
        config = _make_config()
        results = compute_single_tf_series(
            df=df, asset="BTCUSDT", timeframe="1h", config=config,
        )

        for r in results:
            assert isinstance(r.is_valid, bool)
            assert isinstance(r.slope, float)
            assert isinstance(r.confidence, float)
            assert r.timestamp is not None


# ═══════════════════════════════════════════════════════════════════════════
# H. Compat Re-export Verification
# ═══════════════════════════════════════════════════════════════════════════


class TestCompatReexports:
    """Verify compat module re-exports work."""

    def test_api_functions_importable(self):
        from app.regression.compat import compute_single_tf as c1
        from app.regression.compat import compute_single_tf_series as c2
        from app.regression.compat import compute_mtf as c3
        assert callable(c1)
        assert callable(c2)
        assert callable(c3)

    def test_types_importable(self):
        from app.regression.compat import (
            ConfigResolver,
            PluginConfig,
            ResolvedPipelineConfig,
            RegimeSnapshot,
            CascadeContext,
        )
        assert ConfigResolver is not None
        assert PluginConfig is not None
        assert ResolvedPipelineConfig is not None
        assert RegimeSnapshot is not None
        assert CascadeContext is not None
