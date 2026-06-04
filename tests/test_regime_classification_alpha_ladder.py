"""Tests for RegimeClassification alpha ladder."""

from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_classification.optimization.alpha_ladder import (
    run_alpha_ladder,
)
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)


def _price_frame(n: int = 650) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    returns = rng.normal(0.0005, 0.008, n)
    close = 100 * np.cumprod(1.0 + returns)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": rng.uniform(1000, 2000, n),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
    )


def _regime_frame(n: int = 650) -> pd.DataFrame:
    trend = np.zeros(n)
    trend[350:] = 0.9
    return pd.DataFrame(
        {
            "trend_strength": trend,
            "vol_percentile": np.full(n, 45.0),
            "changepoint_prob": np.full(n, 0.05),
            "hmm_crisis_prob": np.full(n, 0.0),
            "hmm_p_state_0": np.full(n, 0.75),
            "hmm_p_state_1": np.full(n, 0.25),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
    )


def _settings(n_trials: int = 8) -> dict:
    return load_regime_optimization_settings(
        {
            "benchmark_ladder": {"min_bars": 500, "purge_bars": 12},
            "alpha_ladder": {"n_trials": n_trials, "min_bars": 500},
        }
    )


def test_alpha_ladder_returns_optimized_policy_contract():
    report = run_alpha_ladder(
        _price_frame(),
        asset="BTCUSDT",
        timeframe="1h",
        regime_df=_regime_frame(),
        settings=_settings(),
    )

    assert report["status"] == "ok"
    overlay = report["strategies"]["ema_cross"]["overlays"]["optimized_policy"]
    assert overlay["selection"]["n_trials"] == 8
    assert "policy_kind" in overlay["selection"]["policy"]
    assert "shuffled_control" in overlay
    assert report["panel_decision"] in {"promote_to_downstream_research", "reject"}


def test_alpha_ladder_rejects_insufficient_data():
    report = run_alpha_ladder(
        _price_frame(100),
        asset="BTCUSDT",
        timeframe="1h",
        regime_df=_regime_frame(100),
        settings=_settings(),
    )

    assert report["status"] == "insufficient_data"
    assert report["bars"] == 100
