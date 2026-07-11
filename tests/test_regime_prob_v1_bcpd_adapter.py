from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_prob_v1.kernels import BCPDAdapterConfig, compute_bcpd_features


def _make_ohlcv(n: int = 260, *, trend: float = 0.0025, noise: float = 0.001) -> pd.DataFrame:
    rng = np.random.default_rng(123)
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


def test_bcpd_adapter_aligns_outputs_and_surfaces_diagnostics():
    df = _make_ohlcv()

    result = compute_bcpd_features(df, timeframe="1h")

    expected = {
        "changepoint_prob",
        "run_length",
        "cp_entropy",
        "cp_recent_max",
        "cp_decay_score",
        "transition_risk_raw",
    }
    assert expected.issubset(result.frame.columns)
    assert result.frame.index.equals(df.index)
    assert len(result.frame) == len(df)
    assert result.frame["changepoint_prob"].between(0.0, 1.0).all()
    assert result.frame["transition_risk_raw"].between(0.0, 1.0).all()
    assert (result.frame["run_length"] >= 0).all()
    assert result.diagnostics["status"] == "ok"
    assert result.diagnostics["truncation"] > 0


def test_bcpd_adapter_returns_neutral_frame_on_short_history():
    df = _make_ohlcv(10)

    result = compute_bcpd_features(df, timeframe="1h", config=BCPDAdapterConfig(min_returns=20))

    assert result.diagnostics["status"] == "insufficient_data"
    assert float(result.frame["changepoint_prob"].sum()) == 0.0
    assert int(result.frame["run_length"].sum()) == 0
    assert float(result.frame["transition_risk_raw"].sum()) == 0.0
