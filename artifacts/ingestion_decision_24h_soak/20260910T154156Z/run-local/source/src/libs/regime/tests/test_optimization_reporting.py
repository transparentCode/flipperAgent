"""Tests for additive optimization reporting fields."""

from __future__ import annotations

from datetime import datetime

import pytest

from libs.regime.optimization.models import (
    BenchmarkResults,
    OptimizationConfig,
    OptimizationResult,
    TrialResult,
)
from libs.regime.optimization.optimizer import RegimeOptimizer


def test_benchmark_results_round_trip_preserves_truthfulness_fields():
    bench = BenchmarkResults(
        sharpe_improvement=0.2,
        baseline_sharpe_lift=0.15,
        baseline_ic_lift=0.05,
        persistence_sharpe_lift=0.10,
        adx_baseline_sharpe_lift=0.08,
        proxy_trend_brier_score=0.22,
        proxy_trend_ece=0.08,
        passed_baseline_gate=True,
        passed_strict_baseline_gate=False,
        strict_baseline_failure_count=1,
        hmm_fit_failure_rate=0.05,
        hmm_unstable_fit_rate=0.10,
    )

    restored = BenchmarkResults.from_dict(bench.to_dict())

    assert restored.baseline_sharpe_lift == 0.15
    assert restored.baseline_ic_lift == 0.05
    assert restored.persistence_sharpe_lift == 0.10
    assert restored.adx_baseline_sharpe_lift == 0.08
    assert restored.proxy_trend_brier_score == 0.22
    assert restored.proxy_trend_ece == 0.08
    assert restored.passed_baseline_gate is True
    assert restored.passed_strict_baseline_gate is False
    assert restored.strict_baseline_failure_count == 1
    assert restored.hmm_fit_failure_rate == 0.05
    assert restored.hmm_unstable_fit_rate == 0.10


def test_aggregate_benchmarks_averages_truthfulness_metrics():
    fold_a = BenchmarkResults(
        baseline_sharpe_lift=0.10,
        baseline_ic_lift=0.02,
        persistence_sharpe_lift=0.08,
        proxy_trend_brier_score=0.20,
        proxy_trend_ece=0.05,
        passed_baseline_gate=True,
        passed_strict_baseline_gate=True,
        strict_baseline_failure_count=0,
    )
    fold_b = BenchmarkResults(
        baseline_sharpe_lift=0.30,
        baseline_ic_lift=0.06,
        persistence_sharpe_lift=0.18,
        proxy_trend_brier_score=0.40,
        proxy_trend_ece=0.15,
        passed_baseline_gate=False,
        passed_strict_baseline_gate=False,
        strict_baseline_failure_count=2,
    )

    agg = RegimeOptimizer._aggregate_benchmarks([fold_a, fold_b])

    assert agg.baseline_sharpe_lift == pytest.approx(0.20)
    assert agg.baseline_ic_lift == pytest.approx(0.04)
    assert agg.persistence_sharpe_lift == pytest.approx(0.13)
    assert agg.proxy_trend_brier_score == pytest.approx(0.30)
    assert agg.proxy_trend_ece == pytest.approx(0.10)
    assert agg.passed_baseline_gate is False
    assert agg.passed_strict_baseline_gate is False
    assert agg.strict_baseline_failure_count == pytest.approx(1.0)


def test_optimization_result_save_load_preserves_truthfulness_fields(tmp_path):
    bench = BenchmarkResults(
        baseline_sharpe_lift=0.12,
        baseline_ic_lift=0.03,
        shuffled_sharpe_lift=0.07,
        proxy_trend_brier_score=0.18,
        proxy_trend_ece=0.07,
        passed_baseline_gate=True,
        passed_strict_baseline_gate=True,
        strict_baseline_failure_count=0,
        hmm_zero_transition_fit_rate=0.11,
    )
    trial = TrialResult(
        trial_id=1,
        params={"bcpd_hazard_lambda": 150.0},
        objective_value=0.42,
        benchmark_results=bench,
        passed_gate=True,
        fold_results=[bench],
        timestamp=datetime(2026, 1, 1, 0, 0, 0),
    )
    result = OptimizationResult(
        asset="BTCUSDT",
        timeframe="1h",
        best_params={"bcpd_hazard_lambda": 150.0},
        best_objective=0.42,
        best_benchmarks=bench,
        n_trials_passed_gate=1,
        n_trials_total=1,
        total_time_seconds=1.23,
        config=OptimizationConfig(n_trials=1, timeout_seconds=10),
        all_trials=[trial],
        timestamp=datetime(2026, 1, 1, 0, 0, 0),
    )

    path = tmp_path / "result.json"
    result.save(str(path))
    loaded = OptimizationResult.load(str(path))

    assert loaded.best_benchmarks.baseline_sharpe_lift == 0.12
    assert loaded.best_benchmarks.baseline_ic_lift == 0.03
    assert loaded.best_benchmarks.shuffled_sharpe_lift == 0.07
    assert loaded.best_benchmarks.proxy_trend_brier_score == 0.18
    assert loaded.best_benchmarks.proxy_trend_ece == 0.07
    assert loaded.best_benchmarks.passed_baseline_gate is True
    assert loaded.best_benchmarks.passed_strict_baseline_gate is True
    assert loaded.best_benchmarks.strict_baseline_failure_count == 0
    assert loaded.best_benchmarks.hmm_zero_transition_fit_rate == 0.11
    assert loaded.all_trials[0].benchmark_results.passed_baseline_gate is True
