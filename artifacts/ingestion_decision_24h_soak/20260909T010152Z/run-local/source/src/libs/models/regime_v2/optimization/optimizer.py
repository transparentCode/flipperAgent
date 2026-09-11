"""Conservative RegimeV2 optimization scaffold."""

from __future__ import annotations

from typing import Any, Callable

import optuna
import pandas as pd

from libs.models.regime_v2.evaluation.comparison import RegimeComparisonConfig, run_regime_comparison
from libs.models.regime_v2.optimization.params import (
    ProfileName,
    get_optimization_param_schema,
    params_to_overrides,
    post_process_params as _post_process_params,
)
from libs.models.regime_v2.optimization.validation import (
    RegimeV2RollingValidationConfig,
    compare_oos_gate,
    evaluate_regime_v2_frame,
)
from libs.optim_utils.objective import build_suggest
from libs.optim_utils.walk_forward import WalkForwardSplit, WalkForwardSplitter

MODEL_NAME = "RegimeV2"

STUDY_DEFAULTS: dict[str, Any] = {
    "n_trials": 80,
    "sampler": "TPE",
    "pruner": "MedianPruner",
    "direction": "maximize",
    "profile": "core",
    "write_back": False,
}

REJECTED_TRIAL_SCORE = -1_000_000.0


def make_objective(
    feature_df: pd.DataFrame,
    *,
    asset: str,
    timeframe: str = "1h",
    profile: ProfileName = "core",
    horizon_bars: int = 12,
    validation_config: RegimeV2RollingValidationConfig | None = None,
    train_ratio: float = 0.60,
    val_ratio: float = 0.20,
    purge_bars: int = 24,
) -> Callable[[optuna.Trial], float]:
    """Return a TPE-friendly scalar objective for RegimeV2.

    The objective evaluates RegimeV2 through the historical ``analyze_series``
    comparison path, then scores only the validation segment with rolling
    downstream/stability metrics.
    """
    cfg = validation_config or RegimeV2RollingValidationConfig()
    splitter = WalkForwardSplitter(
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        oos_ratio=1.0 - train_ratio - val_ratio,
        purge_bars=purge_bars,
    )
    split = splitter.split(len(feature_df))
    schema = get_optimization_param_schema(timeframe, profile=profile)

    def objective(trial: optuna.Trial) -> float:
        raw_params = {name: build_suggest(trial, name, pdef) for name, pdef in schema.items()}
        overrides = params_to_overrides(raw_params, timeframe=timeframe, profile=profile)
        comparison_end = min(len(feature_df), split.val_end + horizon_bars)
        comparison = _comparison_frame(
            feature_df.iloc[:comparison_end],
            asset=asset,
            timeframe=timeframe,
            overrides=overrides,
            horizon_bars=horizon_bars,
        )
        validation_frame = comparison.iloc[split.val_start : split.val_end]
        result = evaluate_regime_v2_frame(validation_frame, config=cfg)
        trial.set_user_attr("regime_v2_validation", result.to_dict())
        if result.rejected:
            return REJECTED_TRIAL_SCORE + result.score
        return result.score

    return objective


def evaluate_oos(
    feature_df: pd.DataFrame,
    params: dict[str, Any],
    *,
    asset: str,
    timeframe: str = "1h",
    profile: ProfileName = "core",
    horizon_bars: int = 12,
    split: WalkForwardSplit | None = None,
    validation_config: RegimeV2RollingValidationConfig | None = None,
    train_ratio: float = 0.60,
    val_ratio: float = 0.20,
    purge_bars: int = 24,
) -> dict[str, Any]:
    """Evaluate optimized params on train, validation, and OOS segments."""
    cfg = validation_config or RegimeV2RollingValidationConfig()
    wf_split = split or WalkForwardSplitter(
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        oos_ratio=1.0 - train_ratio - val_ratio,
        purge_bars=purge_bars,
    ).split(len(feature_df))
    processed = params_to_overrides(params, timeframe=timeframe, profile=profile)
    comparison = _comparison_frame(
        feature_df,
        asset=asset,
        timeframe=timeframe,
        overrides=processed,
        horizon_bars=horizon_bars,
    )
    segments = {
        "train": comparison.iloc[wf_split.train_start : wf_split.train_end],
        "validate": comparison.iloc[wf_split.val_start : wf_split.val_end],
        "oos": comparison.iloc[wf_split.oos_start : wf_split.oos_end],
    }
    results = {name: evaluate_regime_v2_frame(frame, config=cfg) for name, frame in segments.items()}
    oos_rejected, oos_reason = compare_oos_gate(results["validate"], results["oos"], gates=cfg.gates)
    rejection_reasons = list(results["oos"].rejection_reasons)
    if oos_rejected and oos_reason is not None:
        rejection_reasons.append(oos_reason)

    return {
        "train": results["train"].to_dict(),
        "validate": results["validate"].to_dict(),
        "oos": results["oos"].to_dict(),
        "deployed": not rejection_reasons,
        "rejection_reasons": rejection_reasons,
        "params": processed,
    }


def post_process_params(
    params: dict[str, Any],
    *,
    timeframe: str = "1h",
    profile: ProfileName = "core",
) -> dict[str, Any]:
    """Expose RegimeV2 param post-processing with optimizer-local defaults."""
    return _post_process_params(params, timeframe=timeframe, profile=profile)


def format_deploy_params(
    params: dict[str, Any],
    *,
    timeframe: str = "1h",
    profile: ProfileName = "core",
) -> dict[str, Any]:
    """Shape optimized params for RegimeV2 feature-producer YAML review."""
    return {
        "params": params_to_overrides(params, timeframe=timeframe, profile=profile),
    }


def _comparison_frame(
    df: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    overrides: dict[str, Any],
    horizon_bars: int,
) -> pd.DataFrame:
    result = run_regime_comparison(
        df,
        asset=asset,
        timeframe=timeframe,
        config=RegimeComparisonConfig(
            horizon_bars=horizon_bars,
            include_legacy_regime=False,
            include_regime_classification=False,
            regime_v2_overrides=overrides,
        ),
    )
    if result.errors:
        raise RuntimeError(f"RegimeV2 comparison failed during optimization: {result.errors}")
    return result.frame


__all__ = [
    "MODEL_NAME",
    "REJECTED_TRIAL_SCORE",
    "STUDY_DEFAULTS",
    "evaluate_oos",
    "format_deploy_params",
    "get_optimization_param_schema",
    "make_objective",
    "post_process_params",
]
