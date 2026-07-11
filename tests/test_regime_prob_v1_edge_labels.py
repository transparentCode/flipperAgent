from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_prob_v1 import (
    PurgedFourWaySplitConfig,
    RegimeProbLabelConfig,
    build_regime_prob_edge_labels,
    build_regime_prob_feature_frame,
)


def _make_ohlcv(n: int = 260, *, trend: float = 0.003, noise: float = 0.001) -> pd.DataFrame:
    rng = np.random.default_rng(99)
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    returns = trend + rng.normal(0.0, noise, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    volume = 1000.0 + rng.normal(0.0, 20.0, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def test_edge_labels_generate_columns_and_purged_segments():
    df = _make_ohlcv()
    features = build_regime_prob_feature_frame(df, asset="BTCUSDT", timeframe="1h")

    result = build_regime_prob_edge_labels(
        features,
        df,
        timeframe="1h",
        config=RegimeProbLabelConfig(horizons=(3, 6), fee_bps=5.0),
        split_config=PurgedFourWaySplitConfig(purge_bars=24),
    )

    expected = {
        "temporal_segment",
        "trend_following_side",
        "breakout_side",
        "mean_reversion_side",
        "scalping_side",
        "countertrend_side",
        "fwd_log_return_h3",
        "trend_following_edge_return_h3",
        "trend_following_edge_positive_h3",
        "breakout_edge_positive_h6",
        "countertrend_adverse_excursion_h6",
    }
    assert expected.issubset(result.frame.columns)
    assert set(result.frame["temporal_segment"].unique()).issubset(
        {"train", "calibration", "validation", "oos", "purge"}
    )
    assert result.split.calibration_start - result.split.train_end == result.split.purge_bars
    assert result.split.validation_start - result.split.calibration_end == result.split.purge_bars
    assert result.split.oos_start - result.split.validation_end == result.split.purge_bars
    assert result.frame["trend_following_edge_positive_h3"].notna().sum() > 0
    assert result.frame["trend_following_edge_positive_h3"].iloc[-3:].isna().all()


def test_edge_labels_require_directional_breakout_when_raw_breakout_missing():
    df = _make_ohlcv()
    features = build_regime_prob_feature_frame(
        df,
        asset="ETHUSDT",
        timeframe="1h",
    ).drop(columns=["breakout_direction"])

    result = build_regime_prob_edge_labels(
        features,
        df,
        timeframe="1h",
        config=RegimeProbLabelConfig(horizons=(3,), require_directional_breakout=True),
    )

    assert result.frame["breakout_side"].eq(0.0).all()
    assert result.frame["breakout_edge_positive_h3"].isna().all()
