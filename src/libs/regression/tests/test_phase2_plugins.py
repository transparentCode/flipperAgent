"""Phase 2 plugin tests.

Validates each ported plugin against synthetic data:
- Features produce correct shapes and masks
- Methods produce valid slopes/intercepts matching expected values
- TheilSen matches v1 output within tolerance
- Uncertainty bands are coherent
- Ensembles compute agreement_score and degradation correctly
- Full pipeline integration with real plugins
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.regression.config.schema import (
    PluginConfig,
    ResolvedPipelineConfig,
    VolumeProfile,
)
from app.regression.contracts.context import (
    AssetMeta,
    PipelineRequest,
)
from app.regression.contracts.result import (
    DegradationLevel,
    EnsembleResult,
    FeatureSet,
    MethodResult,
)

# Import plugins to trigger registration
from app.regression.features.log_price import LogPriceFeatures
from app.regression.features.volume_weighted import VolumeWeightedFeatures
from app.regression.features.session_aware import SessionAwareFeatures
from app.regression.methods.theil_sen import TheilSenMethod
from app.regression.methods.wls import VWRMethod
from app.regression.uncertainty.percentile_bands import PercentileBands
from app.regression.ensemble.simple_weighted import SimpleWeightedEnsemble
from app.regression.ensemble.confidence_weighted import ConfidenceWeightedEnsemble
from app.regression.pipeline import RegressionPipeline


# ── Fixtures ──


def _make_config(**overrides) -> ResolvedPipelineConfig:
    """Minimal resolved config for testing."""
    defaults = dict(
        asset="BTCUSDT",
        timeframe="1h",
        asset_class="crypto",
        volume_profile=VolumeProfile.CONTINUOUS,
        config_hash="test_hash_001",
        window_size=50,
        min_window=20,
        max_window=200,
        atr_period=14,
        trend_atr_fraction=0.05,
        spread_atr_fraction=0.02,
        momentum_atr_fraction=0.03,
        neutral_slope_atr_fraction=0.04,
        band_multiplier=2.0,
        slope_acceleration_alpha=0.3,
        features=(PluginConfig(name="log_price"), PluginConfig(name="volume_weighted")),
        methods=(
            ("theil_sen", PluginConfig(name="theil_sen", params={"max_pairs": 0})),
            ("vwr", PluginConfig(name="vwr")),
        ),
        ensemble=PluginConfig(name="simple_weighted"),
        uncertainty=PluginConfig(name="percentile_bands"),
        session_gap_handling=False,
        low_liquidity_window_handling=False,
        regime_context_enabled=False,
        regime_window_override=False,
        mtf_enabled=False,
        mtf_timeframes=(),
    )
    defaults.update(overrides)
    return ResolvedPipelineConfig(**defaults)


def _make_trending_df(n: int = 100, slope: float = 0.001, noise: float = 0.002) -> pd.DataFrame:
    """Create a synthetic trending DataFrame with close, volume, high, low."""
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


def _make_stock_gap_df() -> pd.DataFrame:
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


def _make_fx_low_liquidity_df() -> pd.DataFrame:
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


def _make_features(df: pd.DataFrame) -> FeatureSet:
    """Create a FeatureSet initialized from a DataFrame."""
    n = len(df)
    return FeatureSet(
        valid_mask=np.ones(n, dtype=bool),
        timestamps=df.index.values,
        close_raw=df["close"].values.astype(np.float64),
        log_prices=np.empty(n, dtype=np.float64),
        weights=np.ones(n, dtype=np.float64),
        volume_raw=df["volume"].values.astype(np.float64),
        volume_clipped=np.empty(n, dtype=np.float64),
    )


def _make_request(df: pd.DataFrame, config: ResolvedPipelineConfig = None) -> PipelineRequest:
    if config is None:
        config = _make_config()
    return PipelineRequest(
        df=df, asset="BTCUSDT", timeframe="1h", mode="fit_last", config=config,
    )


# ── Feature Extractor Tests ──


class TestLogPriceFeatures:
    def test_basic_extraction(self):
        df = _make_trending_df(50)
        features = _make_features(df)
        request = _make_request(df)

        extractor = LogPriceFeatures(PluginConfig(name="log_price"))
        extractor.extract(request, features)

        assert np.all(features.valid_mask)
        assert np.allclose(features.log_prices, np.log(df["close"].values))

    def test_nan_handling(self):
        df = _make_trending_df(50)
        df.iloc[10, df.columns.get_loc("close")] = np.nan
        df.iloc[20, df.columns.get_loc("close")] = 0.0
        features = _make_features(df)
        request = _make_request(df)

        extractor = LogPriceFeatures(PluginConfig(name="log_price"))
        extractor.extract(request, features)

        assert not features.valid_mask[10]
        assert not features.valid_mask[20]
        assert np.isnan(features.log_prices[10])
        assert np.isnan(features.log_prices[20])

    def test_all_valid_bars_have_log_prices(self):
        df = _make_trending_df(100)
        features = _make_features(df)
        request = _make_request(df)

        extractor = LogPriceFeatures(PluginConfig(name="log_price"))
        extractor.extract(request, features)

        valid = features.valid_mask
        assert not np.any(np.isnan(features.log_prices[valid]))


class TestVolumeWeightedFeatures:
    def test_basic_extraction(self):
        df = _make_trending_df(50)
        features = _make_features(df)
        request = _make_request(df)

        # First extract log prices (dependency)
        LogPriceFeatures(PluginConfig(name="log_price")).extract(request, features)

        extractor = VolumeWeightedFeatures(PluginConfig(name="volume_weighted"))
        extractor.extract(request, features)

        assert features.weights is not None
        assert features.volume_clipped is not None
        # Weights should be normalized: mean ≈ 1.0 for valid bars
        valid = features.valid_mask
        assert abs(np.mean(features.weights[valid]) - 1.0) < 0.1

    def test_sqrt_transform(self):
        df = _make_trending_df(50)
        features = _make_features(df)
        request = _make_request(df)

        LogPriceFeatures(PluginConfig(name="log_price")).extract(request, features)
        extractor = VolumeWeightedFeatures(
            PluginConfig(name="volume_weighted", params={"weight_method": "sqrt"})
        )
        extractor.extract(request, features)

        # Weights should be positive
        valid = features.valid_mask
        assert np.all(features.weights[valid] > 0)

    def test_invalid_weight_method_raises(self):
        with pytest.raises(ValueError, match="Unknown weight_method"):
            VolumeWeightedFeatures(
                PluginConfig(name="volume_weighted", params={"weight_method": "invalid"})
            )


class TestSessionAwareFeatures:
    def test_crypto_passthrough(self):
        df = _make_trending_df(50)
        features = _make_features(df)
        meta = AssetMeta(asset_class="crypto", volume_profile=VolumeProfile.CONTINUOUS)
        request = PipelineRequest(
            df=df, asset="BTCUSDT", timeframe="1h", mode="fit_last",
            config=_make_config(), asset_meta=meta,
        )

        extractor = SessionAwareFeatures(PluginConfig(name="session_aware"))
        extractor.extract(request, features)

        assert features.session_mask is not None
        assert np.all(features.session_mask)

    def test_stock_gap_detection(self):
        # Create timestamps with a 3-hour gap (> 2h threshold)
        n = 20
        timestamps = pd.date_range("2024-01-02 09:30", periods=10, freq="30min").tolist()
        # 3-hour gap
        timestamps.extend(pd.date_range("2024-01-02 17:00", periods=10, freq="30min").tolist())
        df = pd.DataFrame({
            "close": np.exp(np.linspace(10, 10.1, n)),
            "high": np.exp(np.linspace(10, 10.1, n)) * 1.001,
            "low": np.exp(np.linspace(10, 10.1, n)) * 0.999,
            "volume": np.random.uniform(100, 1000, n),
        }, index=pd.DatetimeIndex(timestamps))

        features = _make_features(df)
        meta = AssetMeta(
            asset_class="stock", volume_profile=VolumeProfile.SESSION,
            session_gap_handling=True,
        )
        request = PipelineRequest(
            df=df, asset="AAPL", timeframe="30m", mode="fit_last",
            config=_make_config(), asset_meta=meta,
        )

        extractor = SessionAwareFeatures(PluginConfig(name="session_aware"))
        extractor.extract(request, features)

        # Bar 10 (first after gap) should be marked False
        assert not features.session_mask[10]
        # Other bars should remain True
        assert features.session_mask[0]
        assert features.session_mask[9]

    def test_fx_low_liquidity(self):
        n = 50
        df = _make_trending_df(n)
        # Make some bars very low volume
        df.iloc[5:10, df.columns.get_loc("volume")] = 0.1

        features = _make_features(df)
        meta = AssetMeta(
            asset_class="fx", volume_profile=VolumeProfile.PROXY,
            low_liquidity_window_handling=True,
        )
        request = PipelineRequest(
            df=df, asset="EURUSD", timeframe="1h", mode="fit_last",
            config=_make_config(), asset_meta=meta,
        )

        extractor = SessionAwareFeatures(PluginConfig(name="session_aware"))
        extractor.extract(request, features)

        # Low-volume bars should be marked False
        assert not np.all(features.session_mask[5:10])

    def test_no_meta_passthrough(self):
        df = _make_trending_df(30)
        features = _make_features(df)
        request = _make_request(df)

        extractor = SessionAwareFeatures(PluginConfig(name="session_aware"))
        extractor.extract(request, features)

        assert features.session_mask is not None
        assert np.all(features.session_mask)


# ── Method Tests ──


class TestTheilSenMethod:
    def test_trending_data_positive_slope(self):
        config = _make_config()
        df = _make_trending_df(100, slope=0.003, noise=0.001)
        y = np.log(df["close"].values)
        X = np.arange(len(y), dtype=np.float64)
        w = np.ones(len(y))

        method = TheilSenMethod("theil_sen", PluginConfig(name="theil_sen", params={"max_pairs": 0}))
        method.fit(X, y, w, config)

        assert method.is_valid
        assert method.get_slope() > 0
        # Slope should be approximately 0.003
        assert abs(method.get_slope() - 0.003) < 0.001

    def test_subsampling_tracks_recent_regime_shift(self):
        config = _make_config()
        X = np.arange(100, dtype=np.float64)
        y = np.empty(100, dtype=np.float64)
        y[:75] = 10.0 - 0.002 * X[:75]
        y[75:] = y[74] + 0.02 * np.arange(1, 26, dtype=np.float64)
        w = np.ones(len(y))

        full_method = TheilSenMethod(
            "theil_sen", PluginConfig(name="theil_sen", params={"max_pairs": 0})
        )
        subsampled_method = TheilSenMethod(
            "theil_sen", PluginConfig(name="theil_sen", params={"max_pairs": 100})
        )

        full_method.fit(X, y, w, config)
        subsampled_method.fit(X, y, w, config)

        assert full_method.is_valid
        assert subsampled_method.is_valid
        assert full_method.get_slope() < 0.0
        assert subsampled_method.get_slope() > 0.0
        assert subsampled_method.get_slope() > full_method.get_slope()

    def test_bands_are_coherent(self):
        config = _make_config()
        df = _make_trending_df(80, slope=0.002)
        y = np.log(df["close"].values)
        X = np.arange(len(y), dtype=np.float64)
        w = np.ones(len(y))

        method = TheilSenMethod("theil_sen", PluginConfig(name="theil_sen", params={"max_pairs": 0}))
        method.fit(X, y, w, config)

        upper, lower = method.get_bands(X, 2.0)
        assert upper is not None and len(upper) > 0
        assert lower is not None and len(lower) > 0
        assert np.all(upper >= lower)  # upper always >= lower

    def test_insufficient_data(self):
        config = _make_config()
        X = np.array([0.0, 1.0])
        y = np.array([1.0, 2.0])
        w = np.array([1.0, 1.0])

        method = TheilSenMethod("theil_sen", PluginConfig(name="theil_sen"))
        method.fit(X, y, w, config)

        assert not method.is_valid

    def test_confidence_range(self):
        config = _make_config()
        df = _make_trending_df(100, slope=0.005, noise=0.0005)
        y = np.log(df["close"].values)
        X = np.arange(len(y), dtype=np.float64)
        w = np.ones(len(y))

        method = TheilSenMethod("theil_sen", PluginConfig(name="theil_sen", params={"max_pairs": 0}))
        method.fit(X, y, w, config)

        assert 0.0 <= method.get_confidence() <= 1.0

    def test_metadata_has_pseudo_r2(self):
        config = _make_config()
        df = _make_trending_df(60)
        y = np.log(df["close"].values)
        X = np.arange(len(y), dtype=np.float64)
        w = np.ones(len(y))

        method = TheilSenMethod("theil_sen", PluginConfig(name="theil_sen", params={"max_pairs": 0}))
        method.fit(X, y, w, config)

        meta = method.get_metadata()
        assert "pseudo_r2" in meta
        assert "mad" in meta


class TestWLSMethods:
    def test_vwr_positive_slope(self):
        config = _make_config()
        df = _make_trending_df(100, slope=0.002, noise=0.001)
        y = np.log(df["close"].values)
        X = np.arange(len(y), dtype=np.float64)
        w = np.random.uniform(0.5, 2.0, len(y))

        method = VWRMethod("vwr", PluginConfig(name="vwr"))
        method.fit(X, y, w, config)

        assert method.is_valid
        assert method.get_slope() > 0
        assert abs(method.get_slope() - 0.002) < 0.001

    def test_bands_upper_above_lower(self):
        config = _make_config()
        df = _make_trending_df(50)
        y = np.log(df["close"].values)
        X = np.arange(len(y), dtype=np.float64)
        w = np.ones(len(y))

        method = VWRMethod("vwr", PluginConfig(name="vwr"))
        method.fit(X, y, w, config)

        upper, lower = method.get_bands(X, 2.0)
        assert len(upper) > 0
        assert np.all(upper >= lower)


# ── Uncertainty Tests ──


class TestPercentileBands:
    def test_bands_in_price_space(self):
        config = _make_config()
        n = 60
        df = _make_trending_df(n, slope=0.002)
        y = np.log(df["close"].values)
        X = np.arange(n, dtype=np.float64)

        wrapper = PercentileBands(PluginConfig(name="percentile_bands"))
        upper, lower, mid = wrapper.wrap(X, y, np.ones(n), 0.002, 10.0, 2.0, X, config)

        assert len(upper) == n
        assert len(lower) == n
        assert len(mid) == n
        # All in price space (> 0)
        assert np.all(upper > 0)
        assert np.all(lower > 0)
        assert np.all(mid > 0)
        # Upper >= lower
        assert np.all(upper >= lower)

    def test_zero_residuals_collapse_bands(self):
        config = _make_config()
        n = 30
        X = np.arange(n, dtype=np.float64)
        y = 10.0 + 0.001 * X  # perfectly linear
        w = np.ones(n)

        wrapper = PercentileBands(PluginConfig(name="percentile_bands"))
        upper, lower, mid = wrapper.wrap(X, y, w, 0.001, 10.0, 2.0, X, config)

        # Bands should collapse to mid-line
        np.testing.assert_allclose(upper, mid, atol=1e-10)
        np.testing.assert_allclose(lower, mid, atol=1e-10)

    def test_nan_slope_returns_zeros(self):
        config = _make_config()
        X = np.arange(10, dtype=np.float64)
        y = np.ones(10)
        w = np.ones(10)

        wrapper = PercentileBands(PluginConfig(name="percentile_bands"))
        upper, lower, mid = wrapper.wrap(X, y, w, np.nan, np.nan, 2.0, X, config)

        assert np.all(upper == 0)

    def test_bands_ignore_history_outside_valid_window(self):
        config = _make_config()
        valid_size = 30
        extra_size = 25

        X_valid = np.arange(valid_size, dtype=np.float64)
        y_valid = 10.0 + 0.0015 * X_valid + np.sin(X_valid) * 0.002
        w_valid = np.ones(valid_size)

        X_window_only = X_valid.copy()
        X_full = np.arange(valid_size + extra_size, dtype=np.float64)

        wrapper = PercentileBands(PluginConfig(name="percentile_bands"))
        upper_window, lower_window, mid_window = wrapper.wrap(
            X_valid,
            y_valid,
            w_valid,
            0.0015,
            10.0,
            2.0,
            X_window_only,
            config,
        )
        upper_full, lower_full, mid_full = wrapper.wrap(
            X_valid,
            y_valid,
            w_valid,
            0.0015,
            10.0,
            2.0,
            X_full,
            config,
        )

        np.testing.assert_allclose(mid_full[:valid_size], mid_window)
        np.testing.assert_allclose(upper_full[:valid_size], upper_window)
        np.testing.assert_allclose(lower_full[:valid_size], lower_window)


# ── Ensemble Tests ──


def _make_method_results(slopes, confidences, names=None):
    """Helper to create a dict of MethodResult."""
    if names is None:
        names = [f"method_{i}" for i in range(len(slopes))]
    results = {}
    for name, slope, conf in zip(names, slopes, confidences):
        center = np.exp(slope * np.arange(50) + 10.0)
        results[name] = MethodResult(
            method_name=name,
            slope=slope,
            intercept=10.0,
            center=center,
            confidence=conf,
            r_squared=conf,
            upper=center * 1.01,
            lower=center * 0.99,
            is_valid=True,
        )
    return results


class TestSimpleWeightedEnsemble:
    def test_single_method(self):
        results = _make_method_results([0.002], [0.9], ["theil_sen"])
        config = _make_config()
        request = _make_request(_make_trending_df(50), config)

        ensemble = SimpleWeightedEnsemble(PluginConfig(name="simple_weighted"))
        out = ensemble.combine(results, request)

        assert out.is_valid
        assert out.slope == pytest.approx(0.002, abs=1e-6)
        assert out.agreement_score == 1.0  # single method → perfect agreement
        assert out.dominant_method == "theil_sen"

    def test_multiple_methods_agreement(self):
        results = _make_method_results(
            [0.002, 0.002], [0.8, 0.9],
            ["theil_sen", "vwr"],
        )
        config = _make_config()
        request = _make_request(_make_trending_df(50), config)

        ensemble = SimpleWeightedEnsemble(PluginConfig(name="simple_weighted"))
        out = ensemble.combine(results, request)

        assert out.is_valid
        assert out.agreement_score == pytest.approx(1.0, abs=0.01)

    def test_disagreement_lowers_score(self):
        results = _make_method_results(
            [0.005, -0.003], [0.8, 0.8],
            ["theil_sen", "vwr"],
        )
        config = _make_config()
        request = _make_request(_make_trending_df(50), config)

        ensemble = SimpleWeightedEnsemble(PluginConfig(name="simple_weighted"))
        out = ensemble.combine(results, request)

        assert out.is_valid
        assert out.agreement_score < 0.5

    def test_no_valid_results(self):
        results = {"bad": MethodResult(
            method_name="bad", slope=np.nan, intercept=np.nan,
            center=np.array([]), confidence=0.0, r_squared=0.0, is_valid=False,
        )}
        config = _make_config()
        request = _make_request(_make_trending_df(50), config)

        ensemble = SimpleWeightedEnsemble(PluginConfig(name="simple_weighted"))
        out = ensemble.combine(results, request)

        assert not out.is_valid
        assert out.degradation == DegradationLevel.FAILED

    def test_degradation_when_some_fail(self):
        good = _make_method_results([0.002], [0.9], ["theil_sen"])
        bad = {"bad": MethodResult(
            method_name="bad", slope=np.nan, intercept=np.nan,
            center=np.array([]), confidence=0.0, r_squared=0.0, is_valid=False,
        )}
        results = {**good, **bad}
        config = _make_config()
        request = _make_request(_make_trending_df(50), config)

        ensemble = SimpleWeightedEnsemble(PluginConfig(name="simple_weighted"))
        out = ensemble.combine(results, request)

        assert out.is_valid
        assert out.degradation == DegradationLevel.PARTIAL


class TestConfidenceWeightedEnsemble:
    def test_weight_capping(self):
        results = _make_method_results(
            [0.002, 0.001], [0.99, 0.10],
            ["strong", "weak"],
        )
        config = _make_config()
        request = _make_request(_make_trending_df(50), config)

        ensemble = ConfidenceWeightedEnsemble(
            PluginConfig(name="confidence_weighted", params={
                "max_method_weight": 0.40, "min_confidence": 0.05,
            })
        )
        out = ensemble.combine(results, request)

        assert out.is_valid
        # Strong method should be capped at 0.40
        assert out.method_weights.get("strong", 0) <= 0.41  # small tolerance for rounding

    def test_min_confidence_filter(self):
        results = _make_method_results(
            [0.002, 0.001], [0.9, 0.01],
            ["good", "terrible"],
        )
        config = _make_config()
        request = _make_request(_make_trending_df(50), config)

        ensemble = ConfidenceWeightedEnsemble(
            PluginConfig(name="confidence_weighted", params={"min_confidence": 0.05})
        )
        out = ensemble.combine(results, request)

        assert out.is_valid
        # Only "good" should contribute — "terrible" has conf=0.01 < min_confidence=0.05
        assert "terrible" not in out.method_weights
        assert out.dominant_method == "good"

    def test_agreement_score(self):
        results = _make_method_results(
            [0.002, 0.002, 0.002], [0.8, 0.7, 0.9],
            ["a", "b", "c"],
        )
        config = _make_config()
        request = _make_request(_make_trending_df(50), config)

        ensemble = ConfidenceWeightedEnsemble(PluginConfig(name="confidence_weighted"))
        out = ensemble.combine(results, request)

        assert out.agreement_score == pytest.approx(1.0, abs=0.01)


# ── Full Pipeline Integration ──


class TestPipelineWithPlugins:
    def test_pipeline_feature_stage_applies_session_mask_to_valid_mask_and_weights(self):
        config = _make_config(
            asset="EURUSD",
            features=(
                PluginConfig(name="log_price"),
                PluginConfig(name="volume_weighted"),
                PluginConfig(name="session_aware"),
            ),
            methods=(("theil_sen", PluginConfig(name="theil_sen", params={"max_pairs": 0})),),
            window_size=4,
            min_window=3,
        )
        df = _make_fx_low_liquidity_df()
        request = PipelineRequest(
            df=df,
            asset="EURUSD",
            timeframe="1h",
            mode="fit_last",
            config=config,
            asset_meta=AssetMeta(
                asset_class="fx",
                volume_profile=VolumeProfile.PROXY,
                low_liquidity_window_handling=True,
            ),
        )

        pipeline = RegressionPipeline(config)
        features, degradation = pipeline._run_features(request, pipeline._extract_bar_arrays(df))

        assert degradation == DegradationLevel.FULL
        assert features.session_mask is not None
        assert not features.session_mask[2]
        assert not features.session_mask[3]
        assert not features.valid_mask[2]
        assert not features.valid_mask[3]
        assert features.weights[2] == 0.0
        assert features.weights[3] == 0.0

    def test_stock_session_gaps_change_pipeline_validity(self):
        config = _make_config(
            asset="AAPL",
            timeframe="30m",
            features=(
                PluginConfig(name="log_price"),
                PluginConfig(name="volume_weighted"),
                PluginConfig(name="session_aware"),
            ),
            methods=(("theil_sen", PluginConfig(name="theil_sen", params={"max_pairs": 0})),),
            window_size=3,
            min_window=3,
        )
        df = _make_stock_gap_df()

        baseline_request = PipelineRequest(
            df=df,
            asset="AAPL",
            timeframe="30m",
            mode="fit_last",
            config=config,
        )
        gated_request = PipelineRequest(
            df=df,
            asset="AAPL",
            timeframe="30m",
            mode="fit_last",
            config=config,
            asset_meta=AssetMeta(
                asset_class="stock",
                volume_profile=VolumeProfile.SESSION,
                session_gap_handling=True,
            ),
        )

        pipeline = RegressionPipeline(config)
        baseline = pipeline.compute(baseline_request)
        gated = pipeline.compute(gated_request)

        assert baseline.is_valid
        assert not gated.is_valid
        assert gated.degradation == DegradationLevel.FAILED

    def test_fx_low_liquidity_changes_pipeline_validity(self):
        config = _make_config(
            asset="EURUSD",
            features=(
                PluginConfig(name="log_price"),
                PluginConfig(name="volume_weighted"),
                PluginConfig(name="session_aware"),
            ),
            methods=(("theil_sen", PluginConfig(name="theil_sen", params={"max_pairs": 0})),),
            window_size=4,
            min_window=3,
        )
        df = _make_fx_low_liquidity_df()

        baseline_request = PipelineRequest(
            df=df,
            asset="EURUSD",
            timeframe="1h",
            mode="fit_last",
            config=config,
        )
        gated_request = PipelineRequest(
            df=df,
            asset="EURUSD",
            timeframe="1h",
            mode="fit_last",
            config=config,
            asset_meta=AssetMeta(
                asset_class="fx",
                volume_profile=VolumeProfile.PROXY,
                low_liquidity_window_handling=True,
            ),
        )

        pipeline = RegressionPipeline(config)
        baseline = pipeline.compute(baseline_request)
        gated = pipeline.compute(gated_request)

        assert baseline.is_valid
        assert not gated.is_valid
        assert gated.degradation == DegradationLevel.FAILED

    def test_full_pipeline_trending_data(self):
        """Pipeline with all Phase 2 plugins produces valid BULLISH result."""
        config = _make_config()
        df = _make_trending_df(100, slope=0.003, noise=0.001)
        request = PipelineRequest(
            df=df, asset="BTCUSDT", timeframe="1h", mode="fit_last", config=config,
        )

        pipeline = RegressionPipeline(config)
        result = pipeline.compute(request)

        assert result.is_valid
        assert result.slope > 0
        assert result.direction == "BULLISH"
        assert result.confidence > 0
        assert len(result.upper_band) > 0
        assert len(result.lower_band) > 0
        assert np.all(result.upper_band >= result.lower_band)
        assert result.config_hash == "test_hash_001"
        assert result.degradation in (DegradationLevel.FULL, DegradationLevel.PARTIAL)

    def test_full_pipeline_bearish_data(self):
        """Pipeline produces BEARISH for downtrending data."""
        config = _make_config()
        df = _make_trending_df(100, slope=-0.003, noise=0.001)
        request = PipelineRequest(
            df=df, asset="ETHUSDT", timeframe="1h", mode="fit_last", config=config,
        )

        pipeline = RegressionPipeline(config)
        result = pipeline.compute(request)

        assert result.is_valid
        assert result.slope < 0
        assert result.direction == "BEARISH"

    def test_full_pipeline_series_mode(self):
        config = _make_config(window_size=30)
        df = _make_trending_df(80, slope=0.002)
        request = PipelineRequest(
            df=df, asset="BTCUSDT", timeframe="1h", mode="fit_series", config=config,
        )

        pipeline = RegressionPipeline(config)
        results = pipeline.compute_series(request)

        assert len(results) == 80 - 30 + 1
        valid_count = sum(1 for r in results if r.is_valid)
        assert valid_count > 0

    def test_fit_last_ignores_history_outside_window(self):
        config = _make_config(window_size=30)
        df = _make_trending_df(80, slope=0.002)
        trailing_df = df.iloc[-30:]

        full_request = PipelineRequest(
            df=df, asset="BTCUSDT", timeframe="1h", mode="fit_last", config=config,
        )
        trailing_request = PipelineRequest(
            df=trailing_df, asset="BTCUSDT", timeframe="1h", mode="fit_last", config=config,
        )

        full_result = RegressionPipeline(config).compute(full_request)
        trailing_result = RegressionPipeline(config).compute(trailing_request)

        assert full_result.is_valid
        assert trailing_result.is_valid
        assert full_result.slope == pytest.approx(trailing_result.slope)
        assert full_result.confidence == pytest.approx(trailing_result.confidence)
        np.testing.assert_allclose(full_result.mid_line, trailing_result.mid_line)
        np.testing.assert_allclose(full_result.upper_band, trailing_result.upper_band)
        np.testing.assert_allclose(full_result.lower_band, trailing_result.lower_band)

    def test_pipeline_method_outputs(self):
        """Both enabled methods produce results."""
        config = _make_config()
        df = _make_trending_df(100, slope=0.002)
        request = PipelineRequest(
            df=df, asset="BTCUSDT", timeframe="1h", mode="fit_last", config=config,
        )

        pipeline = RegressionPipeline(config)
        result = pipeline.compute(request)

        assert "theil_sen" in result.method_outputs
        assert "vwr" in result.method_outputs
        for name, mr in result.method_outputs.items():
            assert mr.is_valid, f"{name} should be valid"
            assert mr.upper is not None, f"{name} should have upper band"
            assert mr.lower is not None, f"{name} should have lower band"

    def test_pipeline_z_score_in_range(self):
        config = _make_config()
        df = _make_trending_df(100, slope=0.001, noise=0.002)
        request = PipelineRequest(
            df=df, asset="BTCUSDT", timeframe="1h", mode="fit_last", config=config,
        )

        pipeline = RegressionPipeline(config)
        result = pipeline.compute(request)

        # Z-score should be within reasonable range
        assert -5.0 < result.z_score < 5.0

    def test_pipeline_with_confidence_weighted_ensemble(self):
        config = _make_config(
            ensemble=PluginConfig(name="confidence_weighted", params={
                "min_confidence": 0.05,
                "max_method_weight": 0.50,
            }),
        )
        df = _make_trending_df(100, slope=0.002)
        request = PipelineRequest(
            df=df, asset="BTCUSDT", timeframe="1h", mode="fit_last", config=config,
        )

        pipeline = RegressionPipeline(config)
        result = pipeline.compute(request)

        assert result.is_valid
        assert result.ensemble_result.agreement_score >= 0
