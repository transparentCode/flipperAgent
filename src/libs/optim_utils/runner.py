"""OptunaRunner — single and multi-objective optimization harness."""

from __future__ import annotations

import time
from typing import Any, Callable

import optuna

from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import StudyConfig, TrialResult
from libs.models.base import BaseModel
from libs.optim_utils.objective import make_objective

logger = bind_logger(__name__, system_component=SystemComponent.OPTIMIZATION)


class OptunaRunner:
    """Wraps Optuna study creation, execution, and result extraction."""

    def __init__(self, config: StudyConfig) -> None:
        self.config = config
        self.study: optuna.Study | None = None

    def _build_sampler(self) -> optuna.samplers.BaseSampler:
        if self.config.sampler == "NSGA-II":
            return optuna.samplers.NSGAIISampler()
        return optuna.samplers.TPESampler()

    def _build_pruner(self) -> optuna.pruners.BasePruner:
        if self.config.pruner == "MedianPruner":
            return optuna.pruners.MedianPruner()
        return optuna.pruners.NopPruner()

    def create_study(self, study_name: str | None = None) -> optuna.Study:
        name = study_name or f"{self.config.model_name}_{self.config.asset}_{self.config.timeframe}"

        if len(self.config.directions) > 1:
            self.study = optuna.create_study(
                study_name=name,
                directions=self.config.directions,
                sampler=self._build_sampler(),
                pruner=self._build_pruner(),
            )
        else:
            direction = self.config.directions[0] if self.config.directions else "maximize"
            self.study = optuna.create_study(
                study_name=name,
                direction=direction,
                sampler=self._build_sampler(),
                pruner=self._build_pruner(),
            )
        return self.study

    def run(
        self,
        backtest_fn: Callable[[BaseModel], dict[str, float]] | None = None,
        objective_fn: Callable[["optuna.Trial"], float | tuple[float, ...]] | None = None,
        study_name: str | None = None,
        callbacks: list | None = None,
    ) -> list[TrialResult]:
        """Execute the optimization study and return results.

        Accepts either a ``backtest_fn`` (legacy — wraps via make_objective)
        or a raw ``objective_fn`` (new — used directly by per-model optimizers).
        Exactly one must be provided.
        """
        if backtest_fn is None and objective_fn is None:
            raise ValueError("Either backtest_fn or objective_fn must be provided")
        if backtest_fn is not None and objective_fn is not None:
            raise ValueError("Provide only one of backtest_fn or objective_fn")

        study = self.create_study(study_name)

        if objective_fn is not None:
            objective = objective_fn
        else:
            objective = make_objective(self.config.model_name, backtest_fn)

        logger.info(
            f"Starting optimization: model={self.config.model_name} "
            f"asset={self.config.asset} tf={self.config.timeframe} "
            f"trials={self.config.n_trials}"
        )

        study.optimize(objective, n_trials=self.config.n_trials, show_progress_bar=False, callbacks=callbacks or [])

        return self._extract_results(study)

    def _extract_results(self, study: optuna.Study) -> list[TrialResult]:
        results: list[TrialResult] = []
        objectives = self.config.objectives

        for trial in study.trials:
            if trial.values is not None:
                values_dict = {
                    objectives[i] if i < len(objectives) else f"obj_{i}": v
                    for i, v in enumerate(trial.values)
                }
            elif trial.value is not None:
                obj_name = objectives[0] if objectives else "objective"
                values_dict = {obj_name: trial.value}
            else:
                values_dict = {}

            results.append(
                TrialResult(
                    study_name=study.study_name or "",
                    trial_number=trial.number,
                    params=trial.params,
                    values=values_dict,
                    state=trial.state.name,
                    duration_seconds=(
                        (trial.datetime_complete - trial.datetime_start).total_seconds()
                        if trial.datetime_complete and trial.datetime_start
                        else 0.0
                    ),
                    timestamp=time.time(),
                )
            )
        return results
