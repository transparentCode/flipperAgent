from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_prob_v1 import (
    ExternalContextConfig,
    RegimeProbFeatureBuilder,
    RegimeProbFeatureFrameConfig,
    build_regime_prob_feature_frame,
)


def _make_ohlcv(
    n: int = 260,
    *,
    trend: float = 0.003,
    noise: float = 0.001,
    freq: str = "h",
) -> pd.DataFrame:
    rng = np.random.default_rng(123)
    idx = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    returns = trend + rng.normal(0.0, noise, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    volume = 1000.0 + rng.normal(0.0, 15.0, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def test_feature_builder_external_context_adds_cross_asset_columns():
    asset = _make_ohlcv()
    external = {
        "CRYPTOCAP:BTC.D": _make_ohlcv(trend=0.0003, noise=0.0002),
        "CRYPTOCAP:TOTAL2": _make_ohlcv(trend=0.0025, noise=0.0009),
        "CRYPTOCAP:TOTAL3": _make_ohlcv(trend=0.0035, noise=0.0012),
        "BINANCE:BTCUSDT": _make_ohlcv(trend=0.0028, noise=0.0010),
        "BINANCE:ETHUSDT": _make_ohlcv(trend=0.0031, noise=0.0011),
    }

    result = build_regime_prob_feature_frame(
        asset,
        asset="SOLUSDT",
        timeframe="1h",
        config=RegimeProbFeatureFrameConfig(include_external_context=True),
        external_context_frames=external,
    )

    required = {
        "external_context_available",
        "external_context_coverage_ratio",
        "btc_d_trend",
        "btc_d_momentum",
        "total2_trend",
        "total3_trend",
        "asset_return_corr_btc",
        "asset_beta_total3",
        "relative_strength_vs_total3",
        "market_alignment_score",
        "asset_vs_total3_divergence",
        "asset_breakout_without_market_confirmation",
    }
    assert required.issubset(result.columns)
    assert bool(result.iloc[-1]["external_context_available"]) is True
    assert result.iloc[-1]["external_context_coverage_ratio"] == 1.0
    assert result["market_alignment_score"].abs().max() > 0.0


def test_feature_builder_external_context_degrades_neutrally_when_missing():
    asset = _make_ohlcv()

    result = build_regime_prob_feature_frame(
        asset,
        asset="SOLUSDT",
        timeframe="1h",
        config=RegimeProbFeatureFrameConfig(include_external_context=True),
        external_context_frames=None,
    )

    assert "external_context_available" in result.columns
    assert result["external_context_available"].eq(False).all()
    assert result["market_alignment_score"].eq(0.0).all()
    assert result["asset_return_corr_total3"].eq(0.0).all()


def test_feature_builder_external_context_marks_stale_rows_unavailable():
    asset = _make_ohlcv()
    stale_total3 = _make_ohlcv(n=252).iloc[:-8]
    external = {
        "CRYPTOCAP:BTC.D": _make_ohlcv(),
        "CRYPTOCAP:TOTAL2": _make_ohlcv(),
        "CRYPTOCAP:TOTAL3": stale_total3,
    }

    builder = RegimeProbFeatureBuilder(
        "SOLUSDT",
        "1h",
        config=RegimeProbFeatureFrameConfig(include_external_context=True),
        external_context_config=ExternalContextConfig(max_staleness_bars=1),
    )
    result = builder.build(asset, external_context_frames=external)

    tail = result.iloc[-5:]
    assert tail["external_context_available"].eq(False).all()
    assert tail["market_alignment_score"].eq(0.0).all()
    assert tail["total3_available"].eq(False).all()
