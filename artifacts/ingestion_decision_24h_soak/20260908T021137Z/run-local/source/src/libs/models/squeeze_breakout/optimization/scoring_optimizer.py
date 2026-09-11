"""SqueezeBreakoutScorer optimization — Optuna objective with purged k-fold CV."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import optuna
import pandas as pd

from libs.models.registry import ModelRegistry
from libs.optim_utils.cv import purged_kfold_cv
from libs.optim_utils.objective import build_suggest
from libs.optim_utils.scoring import compute_sharpe, compute_signal_weighted_returns

# Trigger registration
import libs.models.squeeze_breakout.scorer  # noqa: F401

MODEL_NAME = "SqueezeBreakoutScorer"

STUDY_DEFAULTS: dict[str, Any] = {
    "n_trials": 200,
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
    """Return an Optuna-compatible objective for SqueezeBreakoutScorer.

    For each trial:
    1. Suggest params from hyperparameter_schema
    2. For each CV fold:
        a. batch_evaluate(test_df) → edge_scores
        b. compute_signal_weighted_returns → returns
        c. compute_sharpe → sharpe_i
    4. Objective = mean(sharpe_folds) - λ * std(sharpe_folds)
    """
    model_cls = ModelRegistry.get(MODEL_NAME)
    schema = model_cls.meta.hyperparameter_schema
    folds = purged_kfold_cv(feature_df, n_splits=n_splits, embargo_bars=embargo_bars)

    if not folds:
        raise ValueError("Not enough data for cross-validation")

    def objective(trial: optuna.Trial) -> float:
        params: dict[str, Any] = {}
        for pname, pdef in schema.items():
            params[pname] = build_suggest(trial, pname, pdef)

        sharpes: list[float] = []
        for fold in folds:
            model = model_cls(params)
            edge_scores = model.batch_evaluate(fold.test_df)
            test_close = fold.test_df["close"].values

            returns = compute_signal_weighted_returns(
                edge_scores.values, test_close, cost_bps=cost_bps,
            )
            sharpe = compute_sharpe(returns, timeframe)
            sharpes.append(sharpe)

        mean_sharpe = float(np.mean(sharpes))
        std_sharpe = float(np.std(sharpes))
        return mean_sharpe - regularization_lambda * std_sharpe

    return objective


def post_process_params(params: dict[str, Any]) -> dict[str, Any]:
    """Round integer params, enforce constraints."""
    result = dict(params)
    for key in (
        "kama_fast_period", "kama_slow_period",
        "mom_period", "squeeze_lookback", "ss_threshold",
        "cci_period", "adx_period", "ad_sma_period",
        "mfi_period", "mfi_sma_period",
        "mom_lr_period", "mom_lr_mom_period",
    ):
        if key in result:
            result[key] = int(round(result[key]))
    return result
