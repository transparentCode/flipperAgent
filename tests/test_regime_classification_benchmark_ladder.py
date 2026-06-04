"""Tests for the RegimeClassification benchmark ladder."""

from __future__ import annotations

import numpy as np
import pandas as pd

from libs.models.regime_classification.optimization.benchmark_ladder import (
    compute_information_metrics,
    run_benchmark_ladder,
    summarize_ladder_panel,
)
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)


def _price_frame(n: int = 650) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    returns = rng.normal(0.0006, 0.01, n)
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
    trend[350:] = 1.0
    return pd.DataFrame(
        {
            "trend_strength": trend,
            "vol_percentile": np.full(n, 40.0),
            "changepoint_prob": np.full(n, 0.05),
            "hmm_crisis_prob": np.full(n, 0.0),
            "hmm_p_state_0": np.full(n, 0.8),
            "hmm_p_state_1": np.full(n, 0.2),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"),
    )


def test_benchmark_ladder_returns_expected_contract():
    report = run_benchmark_ladder(
        _price_frame(),
        asset="BTCUSDT",
        timeframe="1h",
        regime_df=_regime_frame(),
        settings=load_regime_optimization_settings(
            {
                "benchmark_ladder": {
                    "min_bars": 500,
                    "purge_bars": 12,
                }
            }
        ),
    )

    assert report["status"] == "ok"
    assert report["strategies"]["buy_and_hold"]["baseline"]["oos"]["trades"] >= 1
    assert "combined" in report["strategies"]["ema_cross"]["overlays"]
    assert "shuffled_control" in report["strategies"]["sma_cross"]["overlays"]["combined"]
    assert report["panel_decision"] in {"promote_to_downstream_research", "reject"}


def test_benchmark_ladder_rejects_insufficient_data():
    report = run_benchmark_ladder(
        _price_frame(100),
        asset="BTCUSDT",
        timeframe="1h",
        regime_df=_regime_frame(100),
        settings=load_regime_optimization_settings({"benchmark_ladder": {"min_bars": 500}}),
    )

    assert report["status"] == "insufficient_data"
    assert report["bars"] == 100


def test_information_metrics_are_json_safe():
    metrics = compute_information_metrics(_regime_frame(), _price_frame())
    assert set(metrics) == {
        "trend_strength_fwd_abs_return_spearman",
        "vol_percentile_fwd_vol_spearman",
        "changepoint_fwd_abs_return_spearman",
        "crisis_prob_fwd_abs_return_spearman",
    }
    assert all(isinstance(value, float) for value in metrics.values())


def test_panel_summary_counts_decisions():
    rows = [
        {"status": "ok", "panel_decision": "reject"},
        {"status": "ok", "panel_decision": "promote_to_downstream_research"},
        {"status": "insufficient_data"},
    ]
    summary = summarize_ladder_panel(rows)

    assert summary["usable_slices"] == 2
    assert summary["total_slices"] == 3
    assert summary["promoted_slices"] == 1
    assert summary["rejected_slices"] == 1
