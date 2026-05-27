"""RegimePullbackScorer optimization — Optuna objective with purged k-fold CV."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import optuna
import pandas as pd

from libs.models.scoring_registry import ScoringModelRegistry
from libs.optim_utils.cv import purged_kfold_cv
from libs.optim_utils.objective import build_suggest
from libs.optim_utils.scoring import compute_sharpe, compute_signal_weighted_returns

# Trigger registration
import libs.models.regime_pullback.model  # noqa: F401

MODEL_NAME = "RegimePullbackScorer"

STUDY_DEFAULTS: dict[str, Any] = {
    "n_trials": 200,
    "sampler": "TPE",
    "pruner": "MedianPruner",
    "direction": "maximize",
}

# Params that depend on TradingView data — fixed at defaults during Phase 1.
FIXED_PARAMS: dict[str, Any] = {
    "breadth_weight": 0.2,
    "btc_dom_weight": 0.3,
}


def make_objective(
    feature_df: pd.DataFrame,
    timeframe: str = "1h",
    cost_bps: float = 10.0,
    n_splits: int = 5,
    embargo_bars: int = 50,
    regularization_lambda: float = 0.5,
) -> Callable[[optuna.Trial], float]:
    """Return an Optuna-compatible objective for RegimePullbackScorer.

    For each trial:
    1. Suggest params (excluding FIXED_PARAMS)
    2. Merge with FIXED_PARAMS defaults
    3. For each CV fold:
        a. batch_evaluate(test_df) → edge_scores
        b. compute_signal_weighted_returns → returns
        c. compute_sharpe → sharpe_i
    4. Objective = mean(sharpe_folds) - λ * std(sharpe_folds)
    """
    close = feature_df["close"].values
    model_cls = ScoringModelRegistry.get(MODEL_NAME)
    schema = model_cls.meta.hyperparameter_schema
    folds = purged_kfold_cv(feature_df, n_splits=n_splits, embargo_bars=embargo_bars)

    if not folds:
        raise ValueError("Not enough data for cross-validation")

    def objective(trial: optuna.Trial) -> float:
        params: dict[str, Any] = {}
        for pname, pdef in schema.items():
            if pname in FIXED_PARAMS:
                params[pname] = FIXED_PARAMS[pname]
            else:
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
    for key in ("rsi_oversold_gate", "rsi_overbought_gate"):
        if key in result:
            result[key] = int(round(result[key]))
    return result
