"""Tests for the RegimeClassification volatility-aware ladder."""

from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)
from libs.models.regime_classification.optimization.volatility_ladder import (
    run_rolling_volatility_ladder,
    run_volatility_ladder,
    summarize_volatility_panel,
)


def _price_and_regime(n: int = 700) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(23)
    driver = np.zeros(n)
    for start in range(0, n, 80):
        driver[start : start + 40] = 0.15
        driver[start + 40 : start + 80] = 1.0

    returns = np.zeros(n)
    for idx in range(1, n):
        forecast = driver[idx - 1]
        drift = 0.0012 - 0.0035 * forecast
        returns[idx] = drift + rng.normal(0.0, 0.002 + 0.012 * forecast)
    close = 100 * np.cumprod(1.0 + returns)
    index = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    price = pd.DataFrame(
        {
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": rng.uniform(1000, 2000, n),
        },
        index=index,
    )
    regime = pd.DataFrame(
        {
            "fwd_vol_ewma": driver,
            "trend_strength": np.full(n, 0.5),
            "vol_percentile": driver * 100.0,
            "changepoint_prob": np.full(n, 0.05),
            "hmm_crisis_prob": np.zeros(n),
            "hmm_p_state_0": np.full(n, 0.7),
            "hmm_p_state_1": np.full(n, 0.3),
        },
        index=index,
    )
    return price, regime


def _settings() -> dict:
    return load_regime_optimization_settings(
        {
            "benchmark_ladder": {"min_bars": 500, "purge_bars": 12},
            "volatility_ladder": {
                "min_bars": 500,
                "purge_bars": 12,
                "null_controls": ["circular_shift", "block_shuffle"],
                "policy_kinds": ["high_vol_throttle", "vol_rank_scaled"],
                "high_vol_quantiles": [0.50, 0.75],
                "high_vol_scales": [0.10, 0.25],
                "min_position_scales": [0.10, 0.25],
                "min_sharpe_lift": 0.0,
                "min_calmar_lift": -10.0,
                "min_drawdown_improvement": -1.0,
            },
            "rolling_volatility_ladder": {
                "min_folds": 2,
                "min_promoted_folds": 1,
                "min_pass_rate": 0.1,
                "min_median_sharpe_lift": -10.0,
                "min_median_null_sharpe_lift": -10.0,
                "min_median_drawdown_improvement": -1.0,
            },
        }
    )


def test_volatility_ladder_returns_policy_contract():
    price, regime = _price_and_regime()
    report = run_volatility_ladder(
        price,
        asset="BTCUSDT",
        timeframe="1h",
        regime_df=regime,
        settings=_settings(),
    )

    assert report["status"] == "ok"
    overlay = report["strategies"]["buy_and_hold"]["overlays"]["volatility_sized"]
    assert overlay["selection"]["policy"]["policy_kind"] in {
        "high_vol_throttle",
        "vol_rank_scaled",
    }
    assert set(overlay["null_controls"]) == {"circular_shift", "block_shuffle"}
    assert overlay["null_control_mode"] in {"circular_shift", "block_shuffle"}
    assert overlay["decision"] in {"promote_to_downstream_research", "reject"}
    assert report["panel_decision"] in {"promote_to_downstream_research", "reject"}


def test_volatility_ladder_rejects_insufficient_data():
    price, regime = _price_and_regime(100)
    report = run_volatility_ladder(
        price,
        asset="BTCUSDT",
        timeframe="1h",
        regime_df=regime,
        settings=_settings(),
    )

    assert report["status"] == "insufficient_data"
    assert report["bars"] == 100


def test_rolling_volatility_ladder_returns_fold_summary():
    price, regime = _price_and_regime(900)
    report = run_rolling_volatility_ladder(
        price,
        asset="BTCUSDT",
        timeframe="1h",
        regime_df=regime,
        settings=_settings(),
        fold_bars=500,
        step_bars=200,
    )

    assert report["status"] == "ok"
    assert report["summary"]["total_folds"] == 3
    assert report["summary"]["usable_folds"] == 3
    assert "best_rows" in report["summary"]


def test_volatility_panel_summary_counts_decisions():
    summary = summarize_volatility_panel(
        [
            {"status": "ok", "panel_decision": "reject"},
            {"status": "ok", "panel_decision": "promote_to_downstream_research"},
            {"status": "insufficient_data"},
        ]
    )

    assert summary["usable_slices"] == 2
    assert summary["total_slices"] == 3
    assert summary["promoted_slices"] == 1
    assert summary["rejected_slices"] == 1
