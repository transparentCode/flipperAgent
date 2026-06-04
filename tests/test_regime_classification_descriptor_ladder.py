"""Tests for the RegimeClassification descriptor information ladder."""

from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_classification.optimization.descriptor_ladder import (
    run_descriptor_ladder,
    run_rolling_descriptor_ladder,
    summarize_descriptor_panel,
)
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)


def _price_and_regime(n: int = 700) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(17)
    driver = rng.uniform(0.0, 1.0, n)
    returns = np.zeros(n)
    for idx in range(1, n):
        future_driver = driver[max(idx - 5, 0)]
        returns[idx] = rng.normal(0.0001, 0.002 + 0.03 * future_driver)
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
            "trend_strength": driver,
            "vol_percentile": driver * 100.0,
            "fwd_vol_ewma": driver,
            "changepoint_prob": driver,
            "hmm_crisis_prob": driver,
            "cp_entropy": driver,
            "hurst": driver,
            "hmm_p_state_0": 1.0 - driver,
            "hmm_p_state_1": driver,
        },
        index=index,
    )
    return price, regime


def _settings() -> dict:
    return load_regime_optimization_settings(
        {
            "descriptor_ladder": {
                "min_bars": 500,
                "purge_bars": 12,
                "null_controls": ["circular_shift", "block_shuffle"],
                "min_abs_oos_ic": 0.02,
                "min_stable_descriptor_pairs": 1,
                "min_median_abs_oos_ic": 0.01,
                "descriptor_targets": [
                    {"descriptor": "vol_percentile", "target": "fwd_vol_5"},
                ],
            },
            "rolling_descriptor_ladder": {
                "min_folds": 2,
                "min_promoted_folds": 1,
                "min_pass_rate": 0.1,
                "min_median_abs_oos_ic": 0.01,
            },
        }
    )


def test_descriptor_ladder_returns_information_contract():
    price, regime = _price_and_regime()
    report = run_descriptor_ladder(
        price,
        asset="BTCUSDT",
        timeframe="1h",
        regime_df=regime,
        settings=_settings(),
    )

    assert report["status"] == "ok"
    assert report["descriptor_rows"]
    row = report["descriptor_rows"][0]
    assert row["descriptor"] == "vol_percentile"
    assert set(row["null_controls"]) == {"circular_shift", "block_shuffle"}
    assert row["null_control_mode"] in {"circular_shift", "block_shuffle"}
    assert row["decision"] == "promote_to_alpha_research"
    assert report["panel_decision"] == "promote_to_alpha_research"


def test_descriptor_ladder_rejects_insufficient_data():
    price, regime = _price_and_regime(100)
    report = run_descriptor_ladder(
        price,
        asset="BTCUSDT",
        timeframe="1h",
        regime_df=regime,
        settings=_settings(),
    )

    assert report["status"] == "insufficient_data"
    assert report["bars"] == 100


def test_rolling_descriptor_ladder_returns_fold_summary():
    price, regime = _price_and_regime(900)
    report = run_rolling_descriptor_ladder(
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
    assert report["panel_decision"] in {"promote_to_alpha_research", "reject"}


def test_descriptor_panel_summary_counts_decisions():
    summary = summarize_descriptor_panel(
        [
            {"status": "ok", "panel_decision": "reject"},
            {"status": "ok", "panel_decision": "promote_to_alpha_research"},
            {"status": "insufficient_data"},
        ]
    )

    assert summary["usable_slices"] == 2
    assert summary["total_slices"] == 3
    assert summary["promoted_slices"] == 1
    assert summary["rejected_slices"] == 1
