"""Tests for MetaFilterSelector: selection logic, edge cases."""
import pytest

from app.regression.optimization.meta_filter import MetaFilterSelector
from app.regression.optimization.models import RegressionBenchmarkResults, RegressionTrialResult


def _make_trial(trial_id: int, max_drawdowns: list[float]) -> RegressionTrialResult:
    """Helper to create a trial with fold_results having specified max_drawdown values."""
    fold_results = [
        RegressionBenchmarkResults(max_drawdown=dd) for dd in max_drawdowns
    ]
    return RegressionTrialResult(
        trial_id=trial_id,
        params={"window_size": 100 + trial_id},
        objective_values=(0.5, 0.5, 0.5),
        benchmark_results=fold_results[0] if fold_results else RegressionBenchmarkResults(),
        passed_gate=True,
        passed_constraint=True,
        fold_results=fold_results,
    )


class TestMetaFilterSelector:
    def test_single_candidate(self):
        selector = MetaFilterSelector(metric="max_drawdown", minimize=True)
        trial = _make_trial(0, [0.1, 0.2])
        result = selector.select_best_candidate([trial])
        assert result.trial_id == 0

    def test_selects_min_worst_case_drawdown(self):
        selector = MetaFilterSelector(metric="max_drawdown", minimize=True)
        t1 = _make_trial(1, [0.05, 0.20])  # worst-case = 0.20
        t2 = _make_trial(2, [0.10, 0.12])  # worst-case = 0.12
        t3 = _make_trial(3, [0.08, 0.25])  # worst-case = 0.25
        result = selector.select_best_candidate([t1, t2, t3])
        assert result.trial_id == 2  # 0.12 is smallest worst-case

    def test_maximize_mode(self):
        selector = MetaFilterSelector(metric="confidence_sharpe", minimize=False)
        t1 = _make_trial(1, [])
        t1.fold_results = [RegressionBenchmarkResults(confidence_sharpe=1.5),
                           RegressionBenchmarkResults(confidence_sharpe=2.0)]
        t2 = _make_trial(2, [])
        t2.fold_results = [RegressionBenchmarkResults(confidence_sharpe=0.8),
                           RegressionBenchmarkResults(confidence_sharpe=3.0)]
        # minimize=False → best-case is min(scores), select max of mins
        # t1: min=1.5, t2: min=0.8 → t1 wins
        result = selector.select_best_candidate([t1, t2])
        assert result.trial_id == 1

    def test_empty_fold_results_skipped(self):
        selector = MetaFilterSelector(metric="max_drawdown", minimize=True)
        t1 = _make_trial(1, [])
        t1.fold_results = []  # No folds
        t2 = _make_trial(2, [0.1, 0.15])
        result = selector.select_best_candidate([t1, t2])
        assert result.trial_id == 2

    def test_empty_pareto_raises(self):
        selector = MetaFilterSelector(metric="max_drawdown")
        try:
            selector.select_best_candidate([])
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_invalid_metric_raises(self):
        with pytest.raises(ValueError, match="Invalid meta_filter_metric"):
            MetaFilterSelector(metric="nonexistent_field")
