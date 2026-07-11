"""Study runner for RegimeProbV1 optimization."""

from __future__ import annotations

from typing import Any

import optuna
import pandas as pd

from libs.models.regime_prob_v1.optimization import objective as regime_prob_objective
from libs.models.regime_prob_v1.optimization.params import (
    ProfileName,
    extract_profile_defaults,
)
from libs.models.regime_prob_v1.optimization.reports import (
    build_promotion_gate,
    summarize_oos_delta,
)
from libs.models.regime_prob_v1.optimization.threshold_sweep import run_threshold_sweep
from libs.models.regime_prob_v1.optimization.validation import (
    RegimeProbRollingValidationConfig,
)


def run_study(
    feature_frame: pd.DataFrame,
    label_frame: pd.DataFrame,
    *,
    asset: str,
    timeframe: str,
    profile: ProfileName = "edge_calibration",
    playbook: str | None = None,
    horizon: int = 3,
    mtf_context_frame: pd.DataFrame | None = None,
    n_trials: int = 80,
    study_name: str | None = None,
    storage: str | None = None,
    load_if_exists: bool = False,
    seed: int = 42,
    validation_config: RegimeProbRollingValidationConfig | None = None,
    include_baseline: bool = True,
    include_threshold_sweep: bool = False,
    threshold_sweep_step: float = 0.02,
    threshold_sweep_radius: int = 2,
) -> dict[str, Any]:
    """Run a RegimeProbV1 Optuna study and return a JSON-serializable report."""
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    cfg = validation_config or RegimeProbRollingValidationConfig()
    objective = regime_prob_objective.make_objective(
        feature_frame,
        label_frame,
        profile=profile,
        playbook=playbook,
        horizon=horizon,
        mtf_context_frame=mtf_context_frame,
        validation_config=cfg,
    )
    study = optuna.create_study(
        study_name=study_name or _study_name(asset, timeframe, profile, playbook=playbook, horizon=horizon),
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=seed),
        pruner=optuna.pruners.MedianPruner(),
        storage=storage,
        load_if_exists=load_if_exists,
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    completed = [trial for trial in study.trials if trial.state == optuna.trial.TrialState.COMPLETE]
    if not completed:
        raise RuntimeError("No completed RegimeProbV1 optimization trials")
    best = study.best_trial
    processed_params = regime_prob_objective.post_process_params(best.params, profile=profile)
    oos = regime_prob_objective.evaluate_oos(
        feature_frame,
        label_frame,
        processed_params,
        profile=profile,
        playbook=playbook,
        horizon=horizon,
        mtf_context_frame=mtf_context_frame,
        validation_config=cfg,
    )

    baseline_oos = None
    if include_baseline:
        default_params = extract_profile_defaults(profile)
        baseline_oos = regime_prob_objective.evaluate_oos(
            feature_frame,
            label_frame,
            default_params,
            profile=profile,
            playbook=playbook,
            horizon=horizon,
            mtf_context_frame=mtf_context_frame,
            validation_config=cfg,
        )

    default_vs_tuned = summarize_oos_delta(baseline_oos, oos)
    promotion_gate = build_promotion_gate(baseline_oos, oos)
    final_oos = dict(oos)
    raw_reasons = list(final_oos.get("rejection_reasons") or [])
    final_oos["oos_gate_passed"] = bool(final_oos.get("deployed"))
    final_oos["deployed"] = bool(promotion_gate.get("ready"))
    final_oos["promotion_rejection_reasons"] = list(promotion_gate.get("rejection_reasons") or [])
    if not final_oos["deployed"]:
        merged_reasons = raw_reasons + [f"promotion:{reason}" for reason in final_oos["promotion_rejection_reasons"]]
        final_oos["rejection_reasons"] = list(dict.fromkeys(merged_reasons))

    threshold_sweep = None
    if include_threshold_sweep:
        threshold_sweep = run_threshold_sweep(
            feature_frame,
            label_frame,
            processed_params,
            profile=profile,
            playbook=playbook,
            horizon=horizon,
            mtf_context_frame=mtf_context_frame,
            validation_config=cfg,
            step=threshold_sweep_step,
            radius=threshold_sweep_radius,
        )

    return {
        "model_name": regime_prob_objective.MODEL_NAME,
        "asset": asset.upper(),
        "timeframe": timeframe,
        "profile": profile,
        "playbook": playbook,
        "horizon": int(horizon),
        "n_trials": int(n_trials),
        "completed_trials": len(completed),
        "rejected_trials": _rejected_trial_count(completed),
        "study_name": study.study_name,
        "storage": storage,
        "load_if_exists": bool(load_if_exists),
        "seed": int(seed),
        "data": {
            "rows": int(len(feature_frame)),
            "start": _format_index_value(feature_frame.index[0]) if len(feature_frame) else None,
            "end": _format_index_value(feature_frame.index[-1]) if len(feature_frame) else None,
        },
        "best_trial": {
            "number": best.number,
            "value": best.value,
            "params": processed_params,
            "validation": best.user_attrs.get("regime_prob_validation"),
        },
        "oos": final_oos,
        "baseline_oos": baseline_oos,
        "default_vs_tuned": default_vs_tuned,
        "promotion_gate": promotion_gate,
        "threshold_sweep": threshold_sweep,
        "deploy_params": regime_prob_objective.format_deploy_params(processed_params, profile=profile),
        "study_defaults": dict(regime_prob_objective.STUDY_DEFAULTS),
        "validation_config": _validation_config_to_dict(cfg),
    }


def _study_name(asset: str, timeframe: str, profile: str, *, playbook: str | None, horizon: int) -> str:
    target = playbook or "multi"
    return f"RegimeProbV1_{str(asset).upper()}_{timeframe}_{profile}_{target}_h{int(horizon)}"


def _rejected_trial_count(completed: list[optuna.trial.FrozenTrial]) -> int:
    rejected = 0
    for trial in completed:
        validation = trial.user_attrs.get("regime_prob_validation") or {}
        if validation.get("rejected"):
            rejected += 1
    return rejected


def _validation_config_to_dict(cfg: RegimeProbRollingValidationConfig) -> dict[str, Any]:
    return {
        "window_bars": cfg.window_bars,
        "step_bars": cfg.step_bars,
        "min_window_bars": cfg.min_window_bars,
        "calibration_bins": cfg.calibration_bins,
        "gates": cfg.gates.__dict__,
        "weights": cfg.weights.__dict__,
    }


def _format_index_value(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return str(value)


__all__ = ["run_study"]
