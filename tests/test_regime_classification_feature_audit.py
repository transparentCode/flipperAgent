"""Tests for RegimeClassification feature ablation audit."""

from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_classification.optimization.feature_audit import (
    run_feature_ablation_audit,
)
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)


def _price_and_regime(n: int = 620) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(71)
    driver = np.linspace(0.05, 1.0, n)
    returns = rng.normal(0.0, 0.002 + 0.02 * driver, n)
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
            "vol_percentile": driver * 100.0,
            "changepoint_prob": np.full(n, 0.05),
        },
        index=index,
    )
    return price, regime


def test_feature_ablation_returns_machine_readable_actions():
    price, regime = _price_and_regime()
    settings = load_regime_optimization_settings(
        {
            "benchmark_ladder": {"min_bars": 500, "purge_bars": 12},
            "probability_ladder": {
                "min_bars": 500,
                "purge_bars": 12,
                "null_controls": ["circular_shift"],
                "feature_sets": [
                    ["fwd_vol_ewma", "vol_percentile"],
                    ["changepoint_prob"],
                ],
                "target_kinds": ["vol_expansion"],
                "target_horizons": [3],
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
            "feature_ablation": {
                "min_probability_lift": -1.0,
                "min_null_control_lift": -10.0,
                "min_fold_stability": 0.0,
            },
        }
    )

    report = run_feature_ablation_audit(
        price,
        asset="BTCUSDT",
        timeframe="1h",
        regime_df=regime,
        settings=settings,
    )

    assert report["status"] == "ok"
    assert report["summary"]["total_features"] == 3
    assert {row["feature"] for row in report["features"]} == {
        "fwd_vol_ewma",
        "vol_percentile",
        "changepoint_prob",
    }
    assert all(
        row["action"] in {"keep", "drop", "conditional_by_asset_tf"}
        for row in report["features"]
    )
    assert "probability_information_lift" in report["features"][0]["metrics"]
