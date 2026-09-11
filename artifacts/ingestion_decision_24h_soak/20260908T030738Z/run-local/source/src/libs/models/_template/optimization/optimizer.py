"""Minimal Optuna objective template for _TemplateModel.

Copy this file into your new model's optimization/ directory and customise.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
import optuna
import pandas as pd

from libs.models.registry import ModelRegistry
from libs.optim_utils.cv import purged_kfold_cv
from libs.optim_utils.objective import build_suggest
from libs.optim_utils.scoring import compute_sharpe, compute_signal_weighted_returns

# Replace with your model's registered name
MODEL_NAME = "_TemplateModel"

STUDY_DEFAULTS: dict[str, Any] = {
    "n_trials": 100,
    "sampler": "TPE",
    "pruner": "MedianPruner",
    "direction": "maximize",
}


def make_objective(
    feature_df: pd.DataFrame,
    timeframe: str = "1h",
    cost_bps: float = 10.0,
    n_splits: int = 5,
    embargo_bars: int = 50,
    regularization_lambda: float = 0.5,
) -> Callable[[optuna.Trial], float]:
    """Return an Optuna-compatible objective.

    For each trial:
    1. Suggest params from hyperparameter_schema
    2. For each CV fold:
        a. batch_evaluate(test_df) → scores
        b. compute Sharpe ratio
    3. Objective = mean(sharpe_folds) - λ * std(sharpe_folds)
    """
    model_cls = ModelRegistry.get(MODEL_NAME)
    schema = model_cls.meta.hyperparameter_schema
    folds = purged_kfold_cv(feature_df, n_splits=n_splits, embargo_bars=embargo_bars)

    def objective(trial: optuna.Trial) -> float:
        params = build_suggest(trial, schema)
        model = model_cls(params)

        sharpes: list[float] = []
        for train_df, test_df in folds:
            scores = model.batch_evaluate(test_df)
            returns = compute_signal_weighted_returns(
                scores, test_df, timeframe=timeframe, cost_bps=cost_bps,
            )
            sharpes.append(compute_sharpe(returns))

        mean_s = float(np.mean(sharpes))
        std_s = float(np.std(sharpes))
        return mean_s - regularization_lambda * std_s

    return objective
