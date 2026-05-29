"""Tests for ConvergenceCallback."""

from unittest.mock import MagicMock, PropertyMock, patch

import optuna
import pytest

from libs.optim_utils.callbacks import ConvergenceCallback


def _make_trial(value=None, values=None):
    trial = MagicMock(spec=optuna.trial.FrozenTrial)
    trial.value = value
    trial.values = values
    return trial


class TestConvergenceCallbackSingleObjective:
    def test_single_objective_early_stop(self):
        """patience=5, 5 stale trials → study.stop() called."""
        cb = ConvergenceCallback(patience=5)
        study = optuna.create_study(direction="maximize")

        # First trial sets the best
        cb(study, _make_trial(value=1.0))
        assert cb._stale_count == 0

        # 4 non-improving trials (not yet at patience)
        for _ in range(4):
            cb(study, _make_trial(value=0.5))
        assert cb._stale_count == 4

        # 5th stale trial triggers stop — mock study.stop to avoid RuntimeError
        with patch.object(study, "stop") as mock_stop:
            cb(study, _make_trial(value=0.5))
            mock_stop.assert_called_once()

    def test_single_objective_no_stop(self):
        """Improving trials → no stop."""
        cb = ConvergenceCallback(patience=5)
        study = optuna.create_study(direction="maximize")

        for v in [0.1, 0.2, 0.3, 0.4, 0.5]:
            cb(study, _make_trial(value=v))

        assert cb._stale_count == 0

    def test_callback_resets_on_improvement(self):
        """Improvement resets stale counter."""
        cb = ConvergenceCallback(patience=5)
        study = optuna.create_study(direction="maximize")

        cb(study, _make_trial(value=1.0))
        # 3 stale
        for _ in range(3):
            cb(study, _make_trial(value=0.5))
        assert cb._stale_count == 3

        # Improvement resets
        cb(study, _make_trial(value=1.5))
        assert cb._stale_count == 0


class TestConvergenceCallbackMultiObjective:
    def test_multi_objective_early_stop(self):
        """Pareto front stagnates → stop."""
        cb = ConvergenceCallback(patience=3)
        study = optuna.create_study(directions=["maximize", "maximize"])

        # Simulate Pareto front of size 2
        mock_best_trials = [MagicMock(), MagicMock()]
        type(study).best_trials = PropertyMock(return_value=mock_best_trials)

        # First call sets baseline
        cb(study, _make_trial(values=(1.0, 0.5)))
        assert cb._best_front_size == 2

        # 2 stale trials (not yet at patience)
        for _ in range(2):
            cb(study, _make_trial(values=(0.5, 0.3)))
        assert cb._stale_count == 2

        # 3rd stale triggers stop
        with patch.object(study, "stop") as mock_stop:
            cb(study, _make_trial(values=(0.5, 0.3)))
            mock_stop.assert_called_once()

    def test_multi_objective_no_stop_empty(self):
        """Empty front → no stop (keep exploring)."""
        cb = ConvergenceCallback(patience=3)
        study = optuna.create_study(directions=["maximize", "maximize"])

        type(study).best_trials = PropertyMock(return_value=[])

        for _ in range(10):
            cb(study, _make_trial(values=(0.5, 0.3)))

        # Counter should not have incremented — early return on empty front
        assert cb._stale_count == 0
