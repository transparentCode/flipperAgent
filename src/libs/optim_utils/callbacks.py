"""Optuna callbacks for optimization convergence detection."""

from __future__ import annotations

import logging
from typing import Optional

import optuna

logger = logging.getLogger("app.optimization")


class ConvergenceCallback:
    """Early-stop when optimization stagnates.

    For single-objective: stops when best value hasn't improved for
    ``patience`` consecutive trials.

    For multi-objective: stops when the Pareto front size hasn't
    grown for ``patience`` consecutive trials.

    Does NOT trigger when no feasible trials exist yet — the optimizer
    should keep exploring rather than stop early with zero results.
    """

    def __init__(self, patience: int = 50):
        self._patience = patience
        self._best_value: Optional[float] = None
        self._best_front_size: int = 0
        self._stale_count: int = 0

    def __call__(
        self, study: optuna.Study, trial: optuna.trial.FrozenTrial
    ) -> None:
        is_multi = len(study.directions) > 1

        if is_multi:
            n_pareto = len(study.best_trials)
            if n_pareto == 0:
                return  # no feasible region yet
            if n_pareto > self._best_front_size:
                self._best_front_size = n_pareto
                self._stale_count = 0
            else:
                self._stale_count += 1
        else:
            if trial.value is None:
                return  # pruned or failed trial
            if self._best_value is None or trial.value > self._best_value:
                self._best_value = trial.value
                self._stale_count = 0
            else:
                self._stale_count += 1

        if self._stale_count >= self._patience:
            obj_type = "Pareto front" if is_multi else "best value"
            logger.info(
                f"Early stopping: {obj_type} unchanged for "
                f"{self._patience} trials"
            )
            study.stop()
