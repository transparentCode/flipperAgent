from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_prob_v1.kernels import HurstAdapterConfig, compute_hurst_features


def _make_ohlcv(n: int = 260, *, trend: float = 0.0025, noise: float = 0.001) -> pd.DataFrame:
    rng = np.random.default_rng(321)
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


def test_hurst_adapter_aligns_outputs_and_surfaces_diagnostics():
    df = _make_ohlcv()

    result = compute_hurst_features(df, timeframe="1h")

    expected = {
        "hurst",
        "hurst_trend_bias",
        "hurst_mr_bias",
        "hurst_stability",
    }
    assert expected.issubset(result.frame.columns)
    assert result.frame.index.equals(df.index)
    assert len(result.frame) == len(df)
    assert result.frame["hurst"].between(0.0, 1.0).all()
    assert result.frame["hurst_trend_bias"].between(0.0, 1.0).all()
    assert result.frame["hurst_mr_bias"].between(0.0, 1.0).all()
    assert result.frame["hurst_stability"].between(0.0, 1.0).all()
    assert result.diagnostics["status"] == "ok"


def test_hurst_adapter_returns_neutral_frame_on_short_history():
    df = _make_ohlcv(20)

    result = compute_hurst_features(df, timeframe="1h", config=HurstAdapterConfig(min_periods=50))

    assert result.diagnostics["status"] == "insufficient_data"
    assert result.frame["hurst"].eq(0.5).all()
    assert result.frame["hurst_trend_bias"].eq(0.0).all()
    assert result.frame["hurst_mr_bias"].eq(0.0).all()
