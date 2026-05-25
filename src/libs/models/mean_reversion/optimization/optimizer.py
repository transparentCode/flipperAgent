"""MeanReversion optimization — custom objective function and study config.

This optimizer uses TPE single-objective with a combined Sharpe + drawdown
penalty score. Different models can use entirely different approaches.
"""

from __future__ import annotations

from typing import Any

import optuna
import pandas as pd

from libs.models.registry import ModelRegistry
from libs.optim_utils.objective import build_suggest
from libs.optim_utils.scoring import (
    compute_max_drawdown,
    compute_returns,
    compute_sharpe,
)

MODEL_NAME = "MeanReversion"

# Study defaults for this model — the CLI merges with global defaults.
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
) -> callable:
    """Return an Optuna-compatible objective for MeanReversion.

    Scoring: sharpe - 0.5 * |max_drawdown|
    The penalty factor reflects mean-reversion's sensitivity to drawdown.
    """
    close = feature_df["close"].values
    model_cls = ModelRegistry.get(MODEL_NAME)
    schema = model_cls.meta.hyperparameter_schema

    def objective(trial: optuna.Trial) -> float:
        # Suggest params from hyperparameter_schema
        params: dict[str, Any] = {}
        for pname, pdef in schema.items():
            params[pname] = build_suggest(trial, pname, pdef)

        # Run model
        model = model_cls(params)
        directions = model.batch_evaluate(feature_df)

        # Score
        returns, _ = compute_returns(directions.values, close, cost_bps)
        sharpe = compute_sharpe(returns, timeframe)
        max_dd = compute_max_drawdown(returns)

        return sharpe - 0.5 * abs(max_dd)

    return objective


def post_process_params(params: dict[str, Any]) -> dict[str, Any]:
    """Round integer params, enforce constraints."""
    result = dict(params)
    for key in ("rsi_oversold", "rsi_overbought", "holding_period"):
        if key in result:
            result[key] = int(round(result[key]))
    return result
