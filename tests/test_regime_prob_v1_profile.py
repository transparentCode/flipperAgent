from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_prob_v1.profile import (
    derive_asset_timeframe_profile_report,
    render_asset_timeframe_profile_markdown,
)


def _make_ohlcv(n: int = 320, *, trend: float = 0.0020, noise: float = 0.0007) -> pd.DataFrame:
    rng = np.random.default_rng(9)
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    returns = trend + rng.normal(0.0, noise, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * 1.004
    low = np.minimum(open_, close) * 0.996
    volume = 2000.0 + rng.normal(0.0, 50.0, n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


def _context_frame(index: pd.Index, *, drift: float) -> pd.DataFrame:
    values = np.linspace(100.0, 100.0 + drift, len(index))
    return pd.DataFrame(
        {
            "open": values,
            "high": values * 1.001,
            "low": values * 0.999,
            "close": values,
            "volume": 1_000.0,
        },
        index=index,
    )


def test_profile_report_derives_expected_contract_and_markdown():
    df = _make_ohlcv()
    context_index = pd.date_range(df.index[0], periods=120, freq="h", tz="UTC")
    context_frames = {
        "CRYPTOCAP:BTC.D": _context_frame(context_index, drift=-5.0),
        "CRYPTOCAP:TOTAL2": _context_frame(context_index, drift=6.0),
        "CRYPTOCAP:TOTAL3": _context_frame(context_index, drift=8.0),
        "BTCUSDT": _context_frame(context_index, drift=9.0),
        "ETHUSDT": _context_frame(context_index, drift=7.0),
    }

    report = derive_asset_timeframe_profile_report(
        df,
        asset="BTCUSDT",
        timeframe="1h",
        external_context_frames=context_frames,
    )
    markdown = render_asset_timeframe_profile_markdown(report)

    assert report.profile.asset == "BTCUSDT"
    assert report.profile.recommended_profile in {"balanced", "trend", "breakout", "mean_reversion", "risk_off"}
    assert report.profile.funding_sensitivity_tier == "unavailable"
    assert report.metrics["external_context_coverage"] > 0.0
    assert "# RegimeProbV1 Profile: BTCUSDT 1h" in markdown
    assert "Recommended profile" in markdown
