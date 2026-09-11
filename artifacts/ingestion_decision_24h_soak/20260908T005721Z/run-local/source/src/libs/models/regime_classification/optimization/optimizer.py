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

from libs.contracts.schemas import ParamDef
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
from libs.models.regime_classification.optimization.settings import (
    load_regime_optimization_settings,
)
from libs.optim_utils.objective import build_suggest
from libs.optim_utils.walk_forward import WalkForwardSplit, WalkForwardSplitter

logger = logging.getLogger("app.optimization.regime_classification")

MODEL_NAME = "RegimeClassification"

QUALITY_BASED_GATING: bool = True
OOS_GATE_RATIO: float = float(
    load_regime_optimization_settings()["quality"].get(
        "oos_quality_ratio",
        OOS_QUALITY_RATIO,
    )
)

_KERNEL_KEY_MAP: dict[str, str] = {
    "retrain_window": "hmm_retrain_window",
    "vol_lookback": "vol_lookback",
    "trend_lookback": "trend_lookback",
}

def get_kernel_param_schema(settings: dict[str, Any] | None = None) -> dict[str, ParamDef]:
    """Build kernel-search schema from YAML-backed settings."""
    cfg = settings or load_regime_optimization_settings()
    search = cfg.get("kernel_search", {})

    def _param(name: str, defaults: tuple[int, int, int, int]) -> ParamDef:
        default, low, high, step = defaults
        node = search.get(name, {})
        return ParamDef(
            type="int",
            default=int(node.get("default", default)),
            low=float(node.get("low", low)),
            high=float(node.get("high", high)),
            step=float(node.get("step", step)),
        )

    return {
        "retrain_window": _param(
            "retrain_window",
            (500, RETRAIN_WINDOW_LOW, RETRAIN_WINDOW_HIGH, RETRAIN_WINDOW_STEP),
        ),
        "vol_lookback": _param(
            "vol_lookback",
            (168, VOL_LOOKBACK_LOW, VOL_LOOKBACK_HIGH, VOL_LOOKBACK_STEP),
        ),
        "trend_lookback": _param(
            "trend_lookback",
            (20, TREND_LOOKBACK_LOW, TREND_LOOKBACK_HIGH, TREND_LOOKBACK_STEP),
        ),
    }


def get_optimization_param_schema(
    settings: dict[str, Any] | None = None,
) -> dict[str, ParamDef]:
    """Return full optimization schema: structural params + kernel knobs."""
    return {
        **RegimeClassificationModel.meta.hyperparameter_schema,
        **get_kernel_param_schema(settings),
    }


OPTIMIZATION_PARAM_SCHEMA: dict[str, ParamDef] = get_optimization_param_schema()


def get_study_defaults(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return Optuna study defaults from YAML-backed settings."""
    cfg = settings or load_regime_optimization_settings()
    study = cfg.get("study", {})
    return {
        "n_trials": int(study.get("main_trials", MAIN_TRIALS)),
        "sampler": str(study.get("sampler", STUDY_SAMPLER)),
        "pruner": str(study.get("pruner", STUDY_PRUNER)),
        "direction": str(study.get("direction", STUDY_DIRECTION)),
    }


STUDY_DEFAULTS: dict[str, Any] = get_study_defaults()


def split_model_config(
    params: dict[str, Any],
    calibrated_overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split flat optimizer params into live ``params`` and ``frozen_overrides``."""
    schema_keys = set(RegimeClassificationModel.meta.hyperparameter_schema.keys())
    model_params = {k: v for k, v in params.items() if k in schema_keys}
    frozen = dict(calibrated_overrides or {})
    for trial_key, override_key in _KERNEL_KEY_MAP.items():
        if trial_key in params:
            frozen[override_key] = params[trial_key]
    return model_params, frozen


def format_deploy_params(params: dict[str, Any]) -> dict[str, Any]:
    """Shape optimized params exactly like ``feature_producers`` YAML expects."""
    model_params, frozen = split_model_config(params)
    return {
        "params": model_params,
        "frozen_overrides": frozen,
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
    settings = load_regime_optimization_settings()

    train_df = feature_df.iloc[split.train_start : split.train_end]
    score_df = feature_df.iloc[split.train_start : split.val_end]
    val_df = feature_df.iloc[split.val_start : split.val_end]
    score_input = score_df[["close", "volume"]].copy()

    # Auto-calibrate if not provided
    if calibrated_overrides is None:
        calibrated_overrides = calibrate_frozen_overrides(
            train_df["close"],
            timeframe=timeframe,
            settings=settings,
        )

    schema = get_optimization_param_schema(settings)
    base_overrides = dict(calibrated_overrides)

    def objective(trial: optuna.Trial) -> float:
        # Suggest tunable params from the full optimization schema. Kernel
        # params are split back into frozen_overrides before model creation.
        params: dict[str, Any] = {}
        for pname, pdef in schema.items():
            params[pname] = build_suggest(trial, pname, pdef)

        model_params, frozen = split_model_config(params, base_overrides)

        # Enforce hilbert constraint
        if model_params.get("hilbert_min_period", 10) >= model_params.get("hilbert_max_period", 40):
            return 0.0

        try:
            model = RegimeClassificationModel(
                params=model_params,
                timeframe=timeframe,
                frozen_overrides=frozen,
            )
            regime_series = model.batch_evaluate(score_input)
            regime_df = pd.DataFrame(regime_series.tolist(), index=score_input.index)
            regime_df = regime_df.loc[val_df.index]
            quality = compute_regime_quality(regime_df, val_df, settings=settings)
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
    settings = load_regime_optimization_settings()
    train_df = feature_df.iloc[split.train_start : split.train_end]

    # Auto-calibrate on train only; validation and OOS must not influence
    # frozen asset/timeframe thresholds.
    if calibrated_overrides is None:
        calibrated_overrides = calibrate_frozen_overrides(
            train_df["close"],
            timeframe=timeframe,
            settings=settings,
        )

    schema_params, frozen = split_model_config(params, calibrated_overrides)

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

    full_df = feature_df.iloc[split.train_start : split.oos_end]
    full_input = full_df[["close", "volume"]].copy()
    regime_series = model.batch_evaluate(full_input)
    regime_all = pd.DataFrame(regime_series.tolist(), index=full_input.index)

    for seg_name, seg_df in segments.items():
        regime_df = regime_all.loc[seg_df.index]
        quality = compute_regime_quality(regime_df, seg_df, settings=settings)
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
