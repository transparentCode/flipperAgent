"""Tests for RegimeOrchestrator."""

import numpy as np
import pandas as pd
import pytest

from libs.regime import RegimeOrchestrator
from libs.regime.models import RegimeFeatures
from libs.regime.aggregation.rule_based import ALL_REGIMES

_VALID_REGIMES = set(ALL_REGIMES)


def _make_df(n=500, seed=42):
    np.random.seed(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = 100 + np.random.randn(n).cumsum()
    return pd.DataFrame(
        {"open": 100, "high": 101, "low": 99, "close": close, "volume": 1000},
        index=dates,
    )


class TestRegimeOrchestrator:
    def test_create_factory(self):
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        assert orch is not None
        assert orch.asset == "BTCUSDT"

    def test_create_loads_asset_specific_1h_config(self):
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        assert orch.hmm_classifier.config.retrain_window == 446
        assert orch.vol_overlay.config.lookback == 24
        assert orch.change_detector.config.signal_threshold == pytest.approx(
            0.49610764976231736,
        )

    def test_create_loads_asset_specific_30m_config(self):
        orch = RegimeOrchestrator.create("BTCUSDT", "30m")
        assert orch.hmm_classifier.config.retrain_window == 489
        assert orch.vol_overlay.config.lookback == 54
        assert orch.change_detector.config.signal_threshold == pytest.approx(
            0.40992128148902884,
        )

    def test_analyze_returns_regime_features(self):
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        f = orch.analyze(_make_df())
        assert isinstance(f, RegimeFeatures)

    def test_analyze_regime_is_valid(self):
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        f = orch.analyze(_make_df())
        assert f.regime in _VALID_REGIMES

    def test_analyze_probabilities_in_range(self):
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        f = orch.analyze(_make_df())
        assert 0.0 <= f.p_trending <= 1.0
        assert 0.0 <= f.vol_percentile <= 100.0
        assert 0.0 <= f.changepoint_prob <= 1.0

    def test_analyze_series_correct_columns(self):
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        df_out = orch.analyze_series(_make_df())
        expected = {"regime", "p_trending", "vol_percentile", "changepoint_prob",
                    "adaptive_period", "position_scale", "vol_regime",
                    "hilbert_period", "hilbert_confidence", "bcpd_signal"}
        assert expected.issubset(set(df_out.columns))

    def test_analyze_series_length(self):
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        df = _make_df()
        df_out = orch.analyze_series(df)
        assert len(df_out) == len(df)

    def test_analyze_series_all_regimes_valid(self):
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        df_out = orch.analyze_series(_make_df())
        assert df_out["regime"].isin(_VALID_REGIMES).all()

    def test_reset_state_clears_hmm_model(self):
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        orch.analyze(_make_df())
        assert orch.hmm_classifier._model is not None
        orch.reset_state()
        assert orch.hmm_classifier._model is None

    def test_choppy_exposure_stays_below_high_vol_trend_cap(self):
        """CHOPPY bars should stay within the high-vol trend sizing envelope.

        The runtime intentionally publishes a continuous p_trending-blended
        position_scale, so CHOPPY bars may still carry transition exposure.
        The stable contract is that CHOPPY exposure never exceeds the
        configured volatile-trend cap.
        """
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        df_out = orch.analyze_series(_make_df())
        choppy = df_out[df_out["regime"] == "CHOPPY"]["position_scale"]
        if not choppy.empty:
            scale_cfg = orch.aggregator.config.position_scale
            high_vol_trend_cap = max(
                abs(scale_cfg["VOLATILE_TREND_BULL"]),
                abs(scale_cfg["VOLATILE_TREND_BEAR"]),
                abs(scale_cfg["VOLATILE_TREND_FLAT"]),
            )
            assert choppy.abs().max() <= high_vol_trend_cap + 1e-9

    def test_bear_regimes_have_negative_position_scale(self):
        """BEAR regimes should have negative mean position_scale (short bias)."""
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        df_out = orch.analyze_series(_make_df())
        bear = df_out[df_out["regime"].str.contains("BEAR")]["position_scale"]
        if not bear.empty:
            assert bear.mean() < 0.0

    def test_position_scale_in_long_short_range(self):
        """position_scale should be in [-1, 1] range."""
        orch = RegimeOrchestrator.create("BTCUSDT", "1h")
        df_out = orch.analyze_series(_make_df())
        assert df_out["position_scale"].min() >= -1.01  # small tolerance for blending
        assert df_out["position_scale"].max() <= 1.01
