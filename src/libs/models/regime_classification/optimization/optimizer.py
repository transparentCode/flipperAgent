"""RegimeClassification optimization — quality-based objective and OOS gate.

Follows the same per-model optimizer interface as MeanReversion:
  - STUDY_DEFAULTS: dict
  - make_objective(**kwargs) -> Callable[[Trial], float]
  - evaluate_oos(**kwargs) -> dict
  - post_process_params(params) -> dict
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import optuna
import pandas as pd

from libs.models.regime_classification.model import RegimeClassificationModel
from libs.models.regime_classification.optimization.calibration import (
    calibrate_frozen_overrides,
)
from libs.models.regime_classification.optimization.constants import (
    CONVERGENCE_PATIENCE,
    MAIN_TRIALS,
    OOS_QUALITY_RATIO,
    RETRAIN_WINDOW_HIGH,
    RETRAIN_WINDOW_LOW,
    RETRAIN_WINDOW_STEP,
    SCREENING_TRIALS,
    SEED,
    STUDY_DIRECTION,
    STUDY_PRUNER,
    STUDY_SAMPLER,
    TREND_LOOKBACK_HIGH,
    TREND_LOOKBACK_LOW,
    TREND_LOOKBACK_STEP,
    VOL_LOOKBACK_HIGH,
    VOL_LOOKBACK_LOW,
    VOL_LOOKBACK_STEP,
)
from libs.models.regime_classification.optimization.quality import (
    compute_regime_quality,
)
from libs.models.registry import ModelRegistry
from libs.optim_utils.objective import build_suggest
from libs.optim_utils.walk_forward import WalkForwardSplit, WalkForwardSplitter

logger = logging.getLogger("app.optimization.regime_classification")

MODEL_NAME = "RegimeClassification"

QUALITY_BASED_GATING: bool = True

STUDY_DEFAULTS: dict[str, Any] = {
    "n_trials": MAIN_TRIALS,
    "sampler": STUDY_SAMPLER,
    "pruner": STUDY_PRUNER,
    "direction": STUDY_DIRECTION,
}


def make_objective(
    feature_df: pd.DataFrame,
    timeframe: str = "1h",
    calibrated_overrides: dict[str, Any] | None = None,
    *,
    train_ratio: float = 0.60,
    val_ratio: float = 0.20,
    purge_bars: int = 24,
    # Accepted but unused — maintain interface compatibility with TwoStageOptimizer
    cost_bps: float = 10.0,
    tp_pcts: tuple[float, ...] | None = None,
    tp_portions: tuple[float, ...] | None = None,
    sl_pct: float | None = None,
    trail_to_breakeven: bool | None = None,
) -> Callable[[optuna.Trial], float]:
    """Return an Optuna-compatible objective for RegimeClassification.

    Scoring: composite_quality from quality.py.
    Trains on train split, scores on validate split (walk-forward).

    Parameters cost_bps, tp_pcts, tp_portions, sl_pct, trail_to_breakeven
    are accepted for interface compatibility with TwoStageOptimizer.run()
    but are unused — regime is scored on quality, not returns.
    """
    splitter = WalkForwardSplitter(
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        oos_ratio=1.0 - train_ratio - val_ratio,
        purge_bars=purge_bars,
    )
    split = splitter.split(len(feature_df))

    val_df = feature_df.iloc[split.val_start : split.val_end]
    val_input = val_df[["close", "volume"]].copy()

    # Auto-calibrate if not provided
    if calibrated_overrides is None:
        calibrated_overrides = calibrate_frozen_overrides(feature_df["close"])

    model_cls = ModelRegistry.get(MODEL_NAME)
    schema = model_cls.meta.hyperparameter_schema
    base_overrides = dict(calibrated_overrides)

    def objective(trial: optuna.Trial) -> float:
        # Suggest tunable params from hyperparameter_schema
        params: dict[str, Any] = {}
        for pname, pdef in schema.items():
            params[pname] = build_suggest(trial, pname, pdef)

        # Suggest kernel params (not in hyperparameter_schema)
        retrain_window = trial.suggest_int(
            "retrain_window", RETRAIN_WINDOW_LOW, RETRAIN_WINDOW_HIGH, step=RETRAIN_WINDOW_STEP
        )
        vol_lookback = trial.suggest_int(
            "vol_lookback", VOL_LOOKBACK_LOW, VOL_LOOKBACK_HIGH, step=VOL_LOOKBACK_STEP
        )
        trend_lookback = trial.suggest_int(
            "trend_lookback", TREND_LOOKBACK_LOW, TREND_LOOKBACK_HIGH, step=TREND_LOOKBACK_STEP
        )

        # Build frozen_overrides merging calibrated + kernel trial params
        frozen = dict(base_overrides)
        frozen["hmm_retrain_window"] = retrain_window
        frozen["vol_lookback"] = vol_lookback
        frozen["trend_lookback"] = trend_lookback

        # Enforce hilbert constraint
        if params.get("hilbert_min_period", 10) >= params.get("hilbert_max_period", 40):
            return 0.0

        try:
            model = RegimeClassificationModel(
                params=params,
                timeframe=timeframe,
                frozen_overrides=frozen,
            )
            regime_series = model.batch_evaluate(val_input)
            regime_df = pd.DataFrame(regime_series.tolist(), index=val_input.index)
            quality = compute_regime_quality(regime_df, val_df)
            return quality["composite_quality"]
        except Exception:
            return 0.0

    return objective


def evaluate_oos(
    feature_df: pd.DataFrame,
    params: dict[str, Any],
    split: WalkForwardSplit,
    timeframe: str = "1h",
    calibrated_overrides: dict[str, Any] | None = None,
    # Interface compat — accepted but unused for regime
    cost_bps: float = 10.0,
    tp_pcts: tuple[float, ...] | None = None,
    tp_portions: tuple[float, ...] | None = None,
    sl_pct: float | None = None,
    trail_to_breakeven: bool | None = None,
) -> dict[str, Any]:
    """Run best params on train, validate, and OOS segments.

    Returns quality metrics for each segment.

    Parameters cost_bps, tp_pcts, tp_portions, sl_pct, trail_to_breakeven
    are accepted for interface compatibility with TwoStageOptimizer but
    are unused — regime is scored on quality, not returns.
    """
    # Auto-calibrate if not provided
    if calibrated_overrides is None:
        calibrated_overrides = calibrate_frozen_overrides(feature_df["close"])

    # Separate schema params from kernel params
    model_cls = ModelRegistry.get(MODEL_NAME)
    schema_keys = set(model_cls.meta.hyperparameter_schema.keys())
    schema_params = {k: v for k, v in params.items() if k in schema_keys}
    kernel_params = {k: v for k, v in params.items() if k not in schema_keys}

    # Build frozen overrides
    frozen = dict(calibrated_overrides)
    # Map kernel trial params to their frozen_overrides keys
    kernel_key_map = {
        "retrain_window": "hmm_retrain_window",
        "vol_lookback": "vol_lookback",
        "trend_lookback": "trend_lookback",
    }
    for trial_key, override_key in kernel_key_map.items():
        if trial_key in kernel_params:
            frozen[override_key] = kernel_params[trial_key]

    segments = {
        "train": feature_df.iloc[split.train_start : split.train_end],
        "validate": feature_df.iloc[split.val_start : split.val_end],
        "oos": feature_df.iloc[split.oos_start : split.oos_end],
    }

    results: dict[str, Any] = {}
    model = RegimeClassificationModel(
        params=schema_params,
        timeframe=timeframe,
        frozen_overrides=frozen,
    )

    for seg_name, seg_df in segments.items():
        seg_input = seg_df[["close", "volume"]].copy()
        regime_series = model.batch_evaluate(seg_input)
        regime_df = pd.DataFrame(regime_series.tolist(), index=seg_input.index)
        quality = compute_regime_quality(regime_df, seg_df)
        results[seg_name] = quality

    # Degradation flag for OOS gate compatibility
    val_q = results["validate"].get("composite_quality", 0.0)
    oos_q = results["oos"].get("composite_quality", 0.0)
    results["degradation_warning"] = (
        val_q > 0 and oos_q < OOS_QUALITY_RATIO * val_q
    )

    return results


def post_process_params(params: dict[str, Any]) -> dict[str, Any]:
    """Round integer params, enforce constraints."""
    result = dict(params)
    int_keys = ("hurst_lookback", "hilbert_min_period", "hilbert_max_period",
                "retrain_window", "vol_lookback", "trend_lookback")
    for key in int_keys:
        if key in result:
            result[key] = int(round(result[key]))

    # Enforce hilbert constraint
    if result.get("hilbert_min_period", 10) >= result.get("hilbert_max_period", 40):
        result["hilbert_max_period"] = result.get("hilbert_min_period", 10) + 10

    return result
