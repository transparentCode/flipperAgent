"""Objective function wrappers for Optuna studies."""

from __future__ import annotations

from typing import Any, Callable

import optuna

from libs.contracts.schemas import ParamDef
from libs.models.base import BaseModel
from libs.models.registry import ModelRegistry

# Ensure concrete models are registered.
import libs.models  # noqa: F401


def build_suggest(trial: optuna.Trial, name: str, pdef: ParamDef) -> Any:
    """Map a ParamDef to the appropriate ``trial.suggest_*`` call."""
    if pdef.type == "float":
        return trial.suggest_float(name, pdef.low, pdef.high, step=pdef.step)
    elif pdef.type == "int":
        return trial.suggest_int(name, int(pdef.low), int(pdef.high), step=int(pdef.step or 1))
    elif pdef.type == "categorical":
        return trial.suggest_categorical(name, pdef.choices or [pdef.default])
    return pdef.default


def make_objective(
    model_name: str,
    backtest_fn: Callable[[BaseModel], dict[str, float]],
) -> Callable[[optuna.Trial], float | tuple[float, ...]]:
    """
    Return an Optuna-compatible objective function.

    *backtest_fn* receives a fully-instantiated model and returns a dict of
    metric names → values (e.g. ``{"sharpe": 1.2, "max_drawdown": -0.1}``).
    """
    model_cls = ModelRegistry.get(model_name)

    def objective(trial: optuna.Trial) -> float | tuple[float, ...]:
        params: dict[str, Any] = {}
        for pname, pdef in model_cls.meta.hyperparameter_schema.items():
            params[pname] = build_suggest(trial, pname, pdef)

        model = model_cls(params)
        metrics = backtest_fn(model)

        values = list(metrics.values())
        if len(values) == 1:
            return values[0]
        return tuple(values)

    return objective
