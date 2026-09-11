"""Tests for supplemental truthfulness diagnostics."""

from __future__ import annotations

import numpy as np
import pandas as pd

from libs.regime.optimization.benchmarks import truthfulness


def _make_features(regimes: list[str], p_trending: list[float], position_scale: list[float]):
    idx = pd.date_range("2025-01-01", periods=len(regimes), freq="1h")
    return pd.DataFrame(
        {
            "regime": regimes,
            "p_trending": p_trending,
            "position_scale": position_scale,
        },
        index=idx,
    )


def _make_price_df(n: int):
    idx = pd.date_range("2025-01-01", periods=n, freq="1h")
    close = 100 + np.linspace(0.0, 5.0, n)
    return pd.DataFrame(
        {
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
        },
        index=idx,
    )


def test_truthfulness_prefers_well_aligned_probabilities():
    returns = np.array(
        [0.02] * 20 + [-0.02, 0.02] * 10 + [0.015] * 20,
        dtype=float,
    )
    n = len(returns)
    good = _make_features(
        ["CLEAN_TREND_BULL"] * 20 + ["CHOPPY"] * 20 + ["CLEAN_TREND_BULL"] * 20,
        [0.95] * 20 + [0.10] * 20 + [0.90] * 20,
        [1.0] * 20 + [0.0] * 20 + [1.0] * 20,
    )
    bad = _make_features(
        ["CHOPPY"] * 20 + ["CLEAN_TREND_BULL"] * 20 + ["CHOPPY"] * 20,
        [0.05] * 20 + [0.95] * 20 + [0.10] * 20,
        [0.0] * n,
    )

    price = _make_price_df(n)
    good_metrics = truthfulness.compute(good, returns, price_df=price, primary_horizon=4)
    bad_metrics = truthfulness.compute(bad, returns, price_df=price, primary_horizon=4)

    assert good_metrics["proxy_trend_brier_score"] < bad_metrics["proxy_trend_brier_score"]
    assert good_metrics["proxy_trend_ece"] < bad_metrics["proxy_trend_ece"]
    assert good_metrics["baseline_sharpe_lift"] > bad_metrics["baseline_sharpe_lift"]


def test_truthfulness_outputs_are_bounded():
    returns = np.array([0.01] * 30 + [0.0] * 10 + [-0.01] * 30, dtype=float)
    features = _make_features(
        ["CLEAN_TREND_BULL"] * 30 + ["CHOPPY"] * 10 + ["CLEAN_TREND_BEAR"] * 30,
        [0.9] * 30 + [0.2] * 10 + [0.9] * 30,
        [1.0] * 30 + [0.0] * 10 + [-1.0] * 30,
    )

    metrics = truthfulness.compute(
        features,
        returns,
        price_df=_make_price_df(len(returns)),
        primary_horizon=4,
    )

    assert metrics["proxy_trend_brier_score"] >= 0.0
    assert 0.0 <= metrics["proxy_trend_ece"] <= 1.0
    assert isinstance(metrics["passed_baseline_gate"], bool)
    assert isinstance(metrics["passed_strict_baseline_gate"], bool)
    assert metrics["strict_baseline_failure_count"] >= 0
    assert "adx_baseline_sharpe_lift" in metrics
    assert "shuffled_ic_lift" in metrics


def test_truthfulness_returns_empty_when_columns_missing():
    features = pd.DataFrame({"regime": ["CHOPPY"] * 30})
    returns = np.array([0.0] * 30, dtype=float)

    metrics = truthfulness.compute(features, returns)

    assert metrics["baseline_sharpe_lift"] == 0.0
    assert metrics["proxy_trend_brier_score"] == 1.0
    assert metrics["passed_baseline_gate"] is False
    assert metrics["passed_strict_baseline_gate"] is False


def test_truthfulness_strict_gate_counts_failed_nulls():
    returns = np.array([0.015] * 80, dtype=float)
    features = _make_features(
        ["CHOPPY"] * 80,
        [0.05] * 80,
        [0.0] * 80,
    )

    metrics = truthfulness.compute(
        features,
        returns,
        price_df=_make_price_df(len(returns)),
        primary_horizon=4,
    )

    assert metrics["strict_baseline_failure_count"] > 0
    assert metrics["passed_strict_baseline_gate"] is False
