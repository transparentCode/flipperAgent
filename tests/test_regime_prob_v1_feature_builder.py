from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_prob_v1 import (
    RegimeProbFeatureBuilder,
    RegimeProbFeatureFrameConfig,
    build_regime_prob_feature_frame,
)


def _make_ohlcv(n: int = 260, *, trend: float = 0.003, noise: float = 0.001) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    returns = trend + rng.normal(0.0, noise, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    volume = 1000.0 + rng.normal(0.0, 25.0, n).clip(-100.0, 100.0)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )


def test_feature_builder_flattens_regime_v2_and_adds_pit_fields():
    df = _make_ohlcv()

    result = build_regime_prob_feature_frame(
        df,
        asset="BTCUSDT",
        timeframe="1h",
    )

    required = {
        "asset",
        "timeframe",
        "summary_label",
        "policy_trend_score",
        "row_quality_warmup_complete",
        "row_quality_usable",
        "breakout_direction",
        "range_expansion_z",
        "volume_confirmation",
        "changepoint_prob",
        "cp_entropy",
        "hurst",
        "hurst_trend_bias",
    }
    assert required.issubset(result.columns)
    assert len(result) == len(df)
    assert result.index.equals(df.index)
    assert bool(result.iloc[0]["row_quality_warmup_complete"]) is False
    assert bool(result.iloc[118]["row_quality_warmup_complete"]) is False
    assert bool(result.iloc[119]["row_quality_warmup_complete"]) is True
    assert bool(result.iloc[-1]["row_quality_usable"]) is True
    assert set(result["breakout_direction"].dropna().unique()).issubset({"up", "down", "none"})
    assert "fwd_return" not in result.columns
    assert "edge_positive_12" not in result.columns


def test_feature_builder_can_drop_policy_and_raw_break_columns():
    df = _make_ohlcv()
    config = RegimeProbFeatureFrameConfig(
        include_policy_scores=False,
        include_raw_break_features=False,
        include_bcpd=False,
        include_hurst=False,
    )

    result = build_regime_prob_feature_frame(
        df,
        asset="ETHUSDT",
        timeframe="1h",
        config=config,
    )

    assert "summary_label" in result.columns
    assert "policy_trend_score" not in result.columns
    assert "breakout_direction" not in result.columns
    assert "changepoint_prob" not in result.columns
    assert "hurst" not in result.columns
    assert "row_quality_warmup_complete" in result.columns


def test_feature_builder_deduplicates_final_timestamp_like_regime_v2():
    df = _make_ohlcv(130, trend=0.0015, noise=0.0001)
    duplicated = pd.concat([df, df.iloc[[-1]]])

    result = RegimeProbFeatureBuilder.create("BTCUSDT", "1h").build(duplicated)

    assert len(result) == len(df)
    assert result.index.equals(df.index)
    assert bool(result.iloc[-1]["row_quality_usable"]) is True


def test_feature_builder_returns_empty_frame_for_empty_input():
    df = _make_ohlcv().iloc[:0]

    result = RegimeProbFeatureBuilder.create("SOLUSDT", "1h").build(df)

    assert result.empty
    assert result.index.equals(df.index)


def test_feature_builder_reports_reserved_feature_flags_as_noops():
    df = _make_ohlcv()
    builder = RegimeProbFeatureBuilder.create(
        "BTCUSDT",
        "1h",
        config=RegimeProbFeatureFrameConfig(
            include_hilbert=True,
            include_regime_classification=True,
            include_mtf=True,
        ),
    )

    builder.build(df)

    assert builder.last_diagnostics["reserved_feature_flags"]["status"] == "reserved_noop"
    assert builder.last_diagnostics["reserved_feature_flags"]["requested"] == (
        "include_hilbert",
        "include_mtf",
        "include_regime_classification",
    )
