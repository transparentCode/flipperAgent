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
    backtest_multi_tp,
    compute_multi_tp_metrics,
)
from libs.optim_utils.walk_forward import WalkForwardSplit, WalkForwardSplitter

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
    tp_pcts: tuple[float, ...] = (0.015, 0.03, 0.05),
    tp_portions: tuple[float, ...] = (0.40, 0.30, 0.30),
    sl_pct: float = 0.02,
    trail_to_breakeven: bool = True,
    *,
    train_ratio: float = 0.60,
    val_ratio: float = 0.20,
    purge_bars: int = 24,
) -> callable:
    """Return an Optuna-compatible objective for MeanReversion.

    Scoring: sharpe - 0.5 * |max_drawdown| using multi-TP backtest.
    Trains on train split, scores on validate split (walk-forward).
    """
    splitter = WalkForwardSplitter(
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        oos_ratio=1.0 - train_ratio - val_ratio,
        purge_bars=purge_bars,
    )
    split = splitter.split(len(feature_df))

    val_df = feature_df.iloc[split.val_start : split.val_end]
    val_close = val_df["close"].values
    val_high = val_df["high"].values
    val_low = val_df["low"].values

    model_cls = ModelRegistry.get(MODEL_NAME)
    schema = model_cls.meta.hyperparameter_schema

    def objective(trial: optuna.Trial) -> float:
        # Suggest params from hyperparameter_schema
        params: dict[str, Any] = {}
        for pname, pdef in schema.items():
            params[pname] = build_suggest(trial, pname, pdef)

        # Run model on validate split only
        model = model_cls(params)
        directions = model.batch_evaluate(val_df)

        # Score with multi-TP backtest
        equity_returns, trades = backtest_multi_tp(
            directions.values, val_high, val_low, val_close,
            tp_pcts=tp_pcts, tp_portions=tp_portions,
            sl_pct=sl_pct, commission_bps=cost_bps / 2,
            trail_to_breakeven=trail_to_breakeven,
        )
        metrics = compute_multi_tp_metrics(equity_returns, trades, timeframe)

        return metrics["sharpe"] - 0.5 * abs(metrics["max_drawdown"])

    return objective


def evaluate_oos(
    feature_df: pd.DataFrame,
    params: dict[str, Any],
    split: WalkForwardSplit,
    timeframe: str = "1h",
    cost_bps: float = 10.0,
    tp_pcts: tuple[float, ...] = (0.015, 0.03, 0.05),
    tp_portions: tuple[float, ...] = (0.40, 0.30, 0.30),
    sl_pct: float = 0.02,
    trail_to_breakeven: bool = True,
) -> dict[str, dict[str, float]]:
    """Run best params on train, validate, and OOS segments.

    Returns metrics for each segment and a degradation warning.
    """
    model_cls = ModelRegistry.get(MODEL_NAME)
    segments = {
        "train": feature_df.iloc[split.train_start : split.train_end],
        "validate": feature_df.iloc[split.val_start : split.val_end],
        "oos": feature_df.iloc[split.oos_start : split.oos_end],
    }

    results: dict[str, Any] = {}
    model = model_cls(params)

    for seg_name, seg_df in segments.items():
        directions = model.batch_evaluate(seg_df)
        eq_ret, trades = backtest_multi_tp(
            directions.values,
            seg_df["high"].values,
            seg_df["low"].values,
            seg_df["close"].values,
            tp_pcts=tp_pcts, tp_portions=tp_portions,
            sl_pct=sl_pct, commission_bps=cost_bps / 2,
            trail_to_breakeven=trail_to_breakeven,
        )
        results[seg_name] = compute_multi_tp_metrics(eq_ret, trades, timeframe)

    val_sharpe = results["validate"]["sharpe"]
    oos_sharpe = results["oos"]["sharpe"]
    results["degradation_warning"] = (
        val_sharpe > 0 and oos_sharpe < 0.5 * val_sharpe
    )

    return results


def post_process_params(params: dict[str, Any]) -> dict[str, Any]:
    """Round integer params, enforce constraints."""
    result = dict(params)
    for key in ("rsi_oversold", "rsi_overbought", "holding_period"):
        if key in result:
            result[key] = int(round(result[key]))
    return result
