"""TrendFollowing optimization — multi-objective NSGA-II example.

Demonstrates a completely different technique from MeanReversion.
Uses NSGA-II with two objectives: Sharpe + win_rate.
Custom param constraint: ema_fast_period < ema_slow_period.
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
    compute_win_rate,
)

MODEL_NAME = "TrendFollowing"

STUDY_DEFAULTS: dict[str, Any] = {
    "n_trials": 300,
    "sampler": "NSGA-II",
    "direction": None,  # multi-objective — use directions list
    "directions": ["maximize", "maximize"],
}


def make_objective(
    feature_df: pd.DataFrame,
    timeframe: str = "1h",
    cost_bps: float = 10.0,
) -> callable:
    """Multi-objective: (sharpe, win_rate)."""
    close = feature_df["close"].values
    model_cls = ModelRegistry.get(MODEL_NAME)
    schema = model_cls.meta.hyperparameter_schema

    def objective(trial: optuna.Trial) -> tuple[float, float]:
        params: dict[str, Any] = {}
        for pname, pdef in schema.items():
            params[pname] = build_suggest(trial, pname, pdef)

        # Enforce constraint: fast < slow
        if params.get("ema_fast_period", 0) >= params.get("ema_slow_period", 1):
            params["ema_slow_period"] = params["ema_fast_period"] + 1

        model = model_cls(params)
        directions = model.batch_evaluate(feature_df)

        returns, trade_mask = compute_returns(directions.values, close, cost_bps)
        sharpe = compute_sharpe(returns, timeframe)
        win_rate = compute_win_rate(returns, trade_mask)

        return sharpe, win_rate

    return objective


def post_process_params(params: dict[str, Any]) -> dict[str, Any]:
    result = dict(params)
    for key in ("ema_fast_period", "ema_slow_period"):
        if key in result:
            result[key] = int(round(result[key]))
    return result
