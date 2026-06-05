"""Tests for the RegimeClassification probabilistic ladder."""

from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_classification.optimization.probability_ladder import (
    run_probability_ladder,
    run_rolling_probability_ladder,
    summarize_probability_panel,
)
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)


def _price_and_regime(n: int = 720) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(31)
    driver = np.linspace(0.05, 1.0, n)
    driver += rng.normal(0.0, 0.04, n)
    driver = np.clip(driver, 0.01, 1.0)
    returns = np.zeros(n)
    for idx in range(1, n):
        lagged = driver[max(idx - 5, 0)]
        returns[idx] = rng.normal(0.0001, 0.002 + 0.025 * lagged)
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
            "cp_entropy": 1.0 - driver / 3.0,
            "hurst": 0.45 + driver / 10.0,
            "hmm_crisis_prob": np.zeros(n),
            "hmm_p_state_0": 1.0 - driver / 2,
            "hmm_p_state_1": driver / 2,
        },
        index=index,
    )
    return price, regime


def _settings() -> dict:
    return load_regime_optimization_settings(
        {
            "benchmark_ladder": {"min_bars": 500, "purge_bars": 12},
            "probability_ladder": {
                "min_bars": 500,
                "purge_bars": 12,
                "null_controls": ["circular_shift", "block_shuffle"],
                "feature_sets": [
                    ["fwd_vol_ewma"],
                    ["fwd_vol_ewma", "vol_percentile"],
                    ["fwd_vol_ewma", "vol_percentile", "changepoint_prob"],
                ],
                "target_kinds": ["fwd_vol", "vol_expansion"],
                "target_horizons": [3, 5],
                "target_vol_lookback": 10,
                "event_quantiles": [0.70],
                "n_bins_grid": [4],
                "risk_budgets": [0.50],
                "min_position_scales": [0.25],
                "min_oos_auc": 0.50,
                "min_auc_lift_vs_null": -1.0,
                "min_brier_lift_vs_null": -1.0,
                "min_sharpe_lift": -10.0,
                "min_null_sharpe_lift": -10.0,
                "min_drawdown_improvement": -1.0,
            },
            "rolling_probability_ladder": {
                "min_folds": 2,
                "min_promoted_folds": 1,
                "min_probability_pass_rate": 0.1,
                "min_median_auc": 0.50,
                "min_median_auc_lift": -1.0,
                "min_median_brier_lift": -1.0,
            },
        }
    )


def test_probability_ladder_returns_calibration_contract():
    price, regime = _price_and_regime()
    report = run_probability_ladder(
        price,
        asset="BTCUSDT",
        timeframe="1h",
        regime_df=regime,
        settings=_settings(),
    )

    assert report["status"] == "ok"
    probability = report["probability"]
    assert probability["selection"]["fitted_config"]["event_threshold"] > 0
    assert probability["selection"]["config"]["target_kind"] in {
        "fwd_vol",
        "vol_expansion",
    }
    assert probability["selection"]["config"]["target_horizon"] in {3, 5}
    assert "bin_probs" in probability["selection"]["fitted_config"]
    assert "feature_models" in probability["selection"]["fitted_config"]
    assert probability["selection"]["fitted_config"]["feature_columns"]
    assert "auc" in probability["metrics"]["oos"]
    assert "top_bottom_event_spread" in probability["metrics"]["oos"]
    assert "bucket_spread_vs_null" in probability["oos_lifts"]
    assert set(probability["null_controls"]) == {"circular_shift", "block_shuffle"}
    overlay = report["strategies"]["buy_and_hold"]["overlays"]["probability_sized"]
    assert overlay["selection"]["config"]["risk_budget"] == 0.50
    assert report["panel_decision"] in {"promote_probability_research", "reject"}
    assert report["sizing_panel_decision"] in {"promote_to_downstream_research", "reject"}


def test_probability_ladder_rejects_insufficient_data():
    price, regime = _price_and_regime(100)
    report = run_probability_ladder(
        price,
        asset="BTCUSDT",
        timeframe="1h",
        regime_df=regime,
        settings=_settings(),
    )

    assert report["status"] == "insufficient_data"
    assert report["bars"] == 100


def test_rolling_probability_ladder_returns_fold_summary():
    price, regime = _price_and_regime(900)
    report = run_rolling_probability_ladder(
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
    assert "median_bucket_spread_lift_vs_null" in report["summary"]
    assert "best_rows" in report["summary"]


def test_probability_panel_summary_counts_decisions():
    summary = summarize_probability_panel(
        [
            {"status": "ok", "panel_decision": "reject"},
            {"status": "ok", "panel_decision": "promote_probability_research"},
            {"status": "insufficient_data"},
        ]
    )

    assert summary["usable_slices"] == 2
    assert summary["total_slices"] == 3
    assert summary["promoted_slices"] == 1
    assert summary["rejected_slices"] == 1
