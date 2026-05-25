"""Momentum optimization — single-objective TPE.

Custom param constraint: rsi_short_threshold < rsi_long_threshold.
"""

from __future__ import annotations

from typing import Any

import optuna
import pandas as pd

from libs.models.registry import ModelRegistry
from libs.optimization.objective import build_suggest
from libs.optimization.scoring import (
    compute_max_drawdown,
    compute_returns,
    compute_sharpe,
    compute_win_rate,
)

MODEL_NAME = "Momentum"

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
    """Single-objective: sharpe - 0.3 * |max_drawdown|."""
    close = feature_df["close"].values
    model_cls = ModelRegistry.get(MODEL_NAME)
    schema = model_cls.meta.hyperparameter_schema

    def objective(trial: optuna.Trial) -> float:
        params: dict[str, Any] = {}
        for pname, pdef in schema.items():
            params[pname] = build_suggest(trial, pname, pdef)

        # Enforce constraint: short < long
        if params.get("rsi_short_threshold", 0) >= params.get("rsi_long_threshold", 1):
            params["rsi_long_threshold"] = params["rsi_short_threshold"] + 1

        model = model_cls(params)
        directions = model.batch_evaluate(feature_df)

        returns, trade_mask = compute_returns(directions.values, close, cost_bps)
        sharpe = compute_sharpe(returns, timeframe)
        max_dd = compute_max_drawdown(returns)

        return sharpe - 0.3 * abs(max_dd)

    return objective


def post_process_params(params: dict[str, Any]) -> dict[str, Any]:
    result = dict(params)
    for key in ("rsi_long_threshold", "rsi_short_threshold"):
        if key in result:
            result[key] = int(round(result[key]))
    return result
