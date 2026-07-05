"""Integration test: full fit_and_signal pipeline with synthetic OHLCV."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.trendlines.api import fit_and_signal, fit_trendlines_to_boundary, TrendlineOutput
from app.trendlines.config import TrendlinesConfig, load_trendlines_config, TrendlinePipelineConfig


def _make_trending_ohlcv(n_bars: int = 500) -> pd.DataFrame:
    """Build a synthetic trending DataFrame that produces valid trendlines."""
    rng = np.random.default_rng(42)
    # Uptrend with mean-reverting noise
    trend = np.linspace(100, 130, n_bars)
    noise = np.cumsum(rng.normal(0, 0.3, n_bars))
    noise -= np.linspace(noise[0], noise[-1], n_bars)  # detrend noise
    close = trend + noise
    high = close + rng.uniform(0.5, 2.0, n_bars)
    low = close - rng.uniform(0.5, 2.0, n_bars)
    opn = close + rng.normal(0, 0.5, n_bars)
    volume = rng.uniform(100, 1000, n_bars)
    idx = pd.date_range("2025-01-01", periods=n_bars, freq="1h")
    return pd.DataFrame(
        {"open": opn, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


class TestFitAndSignalIntegration:
    """End-to-end test of the full pipeline with config resolution."""

    def test_produces_valid_output(self):
        df = _make_trending_ohlcv()
        cfg = TrendlinesConfig()
        output = fit_and_signal(
            df, asset="BTCUSDT", timeframe="1h", trendlines_config=cfg
        )

        assert isinstance(output, TrendlineOutput)
        assert output.is_valid
        assert output.fit_result is not None
        assert output.boundary_result is not None
        assert output.signal_output is not None

    def test_signal_output_structure(self):
        df = _make_trending_ohlcv()
        output = fit_and_signal(
            df, asset="BTCUSDT", timeframe="1h", trendlines_config=TrendlinesConfig()
        )

        so = output.signal_output
        assert "signals" in so
        assert "composite_direction" in so
        assert "composite_confidence" in so
        assert isinstance(so["signals"], list)
        assert -1.0 <= output.composite_direction <= 1.0
        assert 0.0 <= output.composite_confidence <= 1.0

    def test_asset_profile_in_metadata(self):
        df = _make_trending_ohlcv()
        output = fit_and_signal(
            df, asset="BTCUSDT", timeframe="1h", trendlines_config=TrendlinesConfig()
        )

        ap = output.metadata.get("asset_profile")
        assert ap is not None
        assert ap["tf_minutes"] == 60
        assert ap["mean_atr"] > 0
        assert ap["n_bars"] == 500

    def test_yaml_config_works(self):
        df = _make_trending_ohlcv()
        cfg = load_trendlines_config()
        output = fit_and_signal(
            df, asset="BTCUSDT", timeframe="1h", trendlines_config=cfg
        )
        assert output.is_valid

    def test_without_trendlines_config(self):
        """fit_and_signal loads default config automatically."""
        df = _make_trending_ohlcv()
        output = fit_and_signal(df, asset="BTCUSDT", timeframe="1h")
        assert output.is_valid

    def test_different_timeframe(self):
        df = _make_trending_ohlcv()
        output = fit_and_signal(
            df, asset="BTCUSDT", timeframe="4h", trendlines_config=TrendlinesConfig()
        )
        assert output.is_valid
        ap = output.metadata.get("asset_profile")
        assert ap["tf_minutes"] == 240

    def test_to_dict(self):
        df = _make_trending_ohlcv()
        output = fit_and_signal(
            df, asset="BTCUSDT", timeframe="1h", trendlines_config=TrendlinesConfig()
        )
        d = output.to_dict()
        assert "fit_result" in d
        assert "signal_output" in d
        assert d["is_valid"] is True


class TestFitTrendlinesToBoundaryIntegration:
    def test_basic(self):
        df = _make_trending_ohlcv()
        output = fit_trendlines_to_boundary(
            df, asset="BTCUSDT", timeframe="1h"
        )
        assert output.is_valid
        assert output.boundary_result is not None
        assert output.signal_output is None

    def test_with_trendlines_config(self):
        df = _make_trending_ohlcv()
        cfg = TrendlinesConfig()
        output = fit_trendlines_to_boundary(
            df, asset="BTCUSDT", timeframe="1h", trendlines_config=cfg
        )
        assert output.is_valid
        ap = output.metadata.get("asset_profile")
        assert ap is not None

    def test_backward_compat_without_config(self):
        df = _make_trending_ohlcv()
        output = fit_trendlines_to_boundary(
            df, asset="BTCUSDT", timeframe="1h"
        )
        assert output.is_valid


class TestBackwardCompat:
    def test_pipeline_config_from_dict(self):
        cfg = TrendlinePipelineConfig.from_dict({
            "extractor": "fractal",
            "fitter": "pathfinding",
            "extractor_params": {"window_left": 5},
        })
        assert cfg.extractor_params.get("window_left") == 5

    def test_trendlines_config_default_construction(self):
        cfg = TrendlinesConfig()
        assert cfg.extractor == "fractal"
        assert cfg.fitter == "pathfinding"
        assert cfg.defaults.interaction_tolerance_atr == 0.25

    def test_trendlines_config_dataclass_replace(self):
        from dataclasses import replace
        from app.trendlines.config import OptimizableDefaults
        cfg = TrendlinesConfig()
        cfg2 = replace(cfg, extractor="rdp_zigzag")
        assert cfg2.extractor == "rdp_zigzag"
        assert cfg.extractor == "fractal"  # original unchanged
