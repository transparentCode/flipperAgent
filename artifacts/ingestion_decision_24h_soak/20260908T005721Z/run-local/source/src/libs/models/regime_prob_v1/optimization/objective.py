"""Objective builders for RegimeProbV1 optimization."""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import optuna
import pandas as pd

from libs.models.regime_prob_v1.edge import (
    fit_playbook_empirical_calibrator,
    playbook_label_column,
)
from libs.models.regime_prob_v1.moe import (
    PLAYBOOKS,
    MoERouterConfig,
    build_moe_router_frame,
    playbook_probability_column,
)
from libs.models.regime_prob_v1.mtf import (
    MTFFusionConfig,
    build_mtf_fused_weight_frame,
)
from libs.models.regime_prob_v1.overlays import (
    build_probability_overlay as _build_probability_overlay,
    overlay_config_from_params as _overlay_config_from_params,
)
from libs.models.regime_prob_v1.optimization.params import (
    ProfileName,
    format_deploy_params as _format_deploy_params,
    get_optimization_param_schema,
    post_process_params as _post_process_params,
)
from libs.models.regime_prob_v1.optimization.validation import (
    RegimeProbRollingValidationConfig,
    compare_oos_gate,
    evaluate_regime_prob_frame,
)
from libs.optim_utils.objective import build_suggest


MODEL_NAME = "RegimeProbV1"

STUDY_DEFAULTS: dict[str, Any] = {
    "n_trials": 80,
    "sampler": "TPE",
    "pruner": "MedianPruner",
    "direction": "maximize",
    "profile": "edge_calibration",
    "write_back": False,
}

REJECTED_TRIAL_SCORE = -1_000_000.0

_SUPPORTED_PROFILES: set[ProfileName] = {
    "state_core",
    "transition",
    "edge_calibration",
    "moe_router",
    "mtf_overlay",
    "external_context",
    "full_shadow_only",
}
_HMM_STATE_PROFILES: set[ProfileName] = {"state_core", "transition", "full_shadow_only"}
_HMM_SOURCE_COLUMN = "diagnostics_state_source"
_HMM_EVAL_MODE_COLUMN = "hmm_state_eval_mode"
_HMM_SCORING_ELIGIBLE_COLUMN = "hmm_scoring_eligible"
_HMM_SOURCE_MODEL = "hmm_state_model"
_HMM_SOURCE_PROXY_FALLBACK = "deterministic_proxy_fallback"
_HMM_EVAL_MODE_IN_SAMPLE = "in_sample_fit"
_HMM_EVAL_MODE_OOS = "oos_filtered"
_HMM_EVAL_MODE_PROXY = "proxy_fallback"
_HMM_STATE_ERROR_COLUMN = "hmm_state_error"
_HMM_STATE_COLUMNS_MISSING = "hmm_state_columns_missing"
_HMM_STATE_COLUMNS = (
    "p_trend_state",
    "p_range_state",
    "p_chop_state",
    "p_breakout_state",
    "p_vol_shock_state",
    "p_transition_state",
    "state_entropy",
    "dominant_state",
    "dominant_state_prob",
    "hmm_transition_prob",
    "hmm_crisis_prob",
    "transition_matrix_self_prob",
    "latent_state_entropy",
    "posterior_shift",
)
_FULL_SHADOW_AUDIT_PREFIX = "full_shadow_audit_"
_AUDIT_RAW_MAX_PROBABILITY = f"{_FULL_SHADOW_AUDIT_PREFIX}raw_max_playbook_probability"
_AUDIT_HAS_ANY_PROBABILITY = f"{_FULL_SHADOW_AUDIT_PREFIX}has_any_playbook_probability"
_AUDIT_ABOVE_MIN_EDGE = f"{_FULL_SHADOW_AUDIT_PREFIX}above_min_edge_probability"
_AUDIT_OVERLAY_GATE_ACTIVE = f"{_FULL_SHADOW_AUDIT_PREFIX}overlay_gate_active"
_AUDIT_TRANSITION_RISK = f"{_FULL_SHADOW_AUDIT_PREFIX}transition_risk"
_AUDIT_HIGH_ENTROPY_REJECT = f"{_FULL_SHADOW_AUDIT_PREFIX}high_entropy_reject"
_AUDIT_HIGH_TRANSITION_STATE_REJECT = f"{_FULL_SHADOW_AUDIT_PREFIX}high_transition_state_reject"
_AUDIT_MOE_HAS_RECOMMENDATION = f"{_FULL_SHADOW_AUDIT_PREFIX}moe_has_recommendation"
_AUDIT_MOE_RECOMMENDED_PLAYBOOK = f"{_FULL_SHADOW_AUDIT_PREFIX}moe_recommended_playbook"
_AUDIT_MOE_MAX_WEIGHT = f"{_FULL_SHADOW_AUDIT_PREFIX}moe_max_weight"
_AUDIT_MTF_HAS_RECOMMENDATION = f"{_FULL_SHADOW_AUDIT_PREFIX}mtf_has_recommendation"
_AUDIT_MTF_RECOMMENDED_PLAYBOOK = f"{_FULL_SHADOW_AUDIT_PREFIX}mtf_recommended_playbook"
_AUDIT_MTF_MAX_WEIGHT = f"{_FULL_SHADOW_AUDIT_PREFIX}mtf_max_weight"
_AUDIT_FINAL_SCORE = f"{_FULL_SHADOW_AUDIT_PREFIX}final_score"
_AUDIT_FINAL_REASON = f"{_FULL_SHADOW_AUDIT_PREFIX}final_reason"


def make_objective(
    feature_frame: pd.DataFrame,
    label_frame: pd.DataFrame,
    *,
    profile: ProfileName = "edge_calibration",
    playbook: str | None = None,
    horizon: int = 3,
    mtf_context_frame: pd.DataFrame | None = None,
    validation_config: RegimeProbRollingValidationConfig | None = None,
) -> Callable[[optuna.Trial], float]:
    """Return a TPE-friendly scalar objective for RegimeProbV1."""
    _validate_profile(profile)
    cfg = validation_config or RegimeProbRollingValidationConfig()
    schema = get_optimization_param_schema(profile)

    def objective(trial: optuna.Trial) -> float:
        raw_params = {name: build_suggest(trial, name, pdef) for name, pdef in schema.items()}
        params = _post_process_params(raw_params, profile=profile)
        decision_frame = build_decision_frame(
            feature_frame,
            label_frame,
            params=params,
            profile=profile,
            playbook=playbook,
            horizon=horizon,
            mtf_context_frame=mtf_context_frame,
        )
        validation_segment = _segment_frame(decision_frame, "validation")
        result = evaluate_regime_prob_frame(validation_segment, config=cfg)
        trial.set_user_attr("regime_prob_validation", result.to_dict())
        hmm_support = _hmm_support_summary(decision_frame)
        if hmm_support is not None:
            trial.set_user_attr("regime_prob_hmm_support", hmm_support)
        if result.rejected:
            return REJECTED_TRIAL_SCORE + result.score
        return result.score

    return objective


def evaluate_oos(
    feature_frame: pd.DataFrame,
    label_frame: pd.DataFrame,
    params: dict[str, Any],
    *,
    profile: ProfileName = "edge_calibration",
    playbook: str | None = None,
    horizon: int = 3,
    mtf_context_frame: pd.DataFrame | None = None,
    validation_config: RegimeProbRollingValidationConfig | None = None,
) -> dict[str, Any]:
    """Evaluate optimized params on train, calibration, validation, and OOS segments."""
    _validate_profile(profile)
    cfg = validation_config or RegimeProbRollingValidationConfig()
    processed = _post_process_params(params, profile=profile)
    decision_frame = build_decision_frame(
        feature_frame,
        label_frame,
        params=processed,
        profile=profile,
        playbook=playbook,
        horizon=horizon,
        mtf_context_frame=mtf_context_frame,
    )
    hmm_support = _hmm_support_summary(decision_frame)
    full_shadow_activation_audit = _full_shadow_activation_audit_summary(decision_frame)
    segments = {
        segment: _segment_frame(decision_frame, segment)
        for segment in ("train", "calibration", "validation", "oos")
    }
    results = {
        name: evaluate_regime_prob_frame(frame, config=cfg)
        for name, frame in segments.items()
        if not frame.empty
    }
    validation = results.get("validation")
    oos = results.get("oos")
    validation_reasons = _segment_rejection_reasons("validation", validation)
    oos_reasons = _segment_rejection_reasons("oos", oos)
    rejection_reasons = [*validation_reasons, *oos_reasons]
    if validation is not None and oos is not None:
        oos_rejected, oos_reason = compare_oos_gate(validation, oos, gates=cfg.gates)
        if oos_rejected and oos_reason is not None:
            rejection_reasons.append(oos_reason)

    payload = {
        "train": results.get("train").to_dict() if results.get("train") else None,
        "calibration": results.get("calibration").to_dict() if results.get("calibration") else None,
        "validation": results.get("validation").to_dict() if results.get("validation") else None,
        "oos": results.get("oos").to_dict() if results.get("oos") else None,
        "validation_rejected": bool(validation.rejected) if validation is not None else True,
        "validation_rejection_reasons": validation_reasons,
        "oos_rejected": bool(oos.rejected) if oos is not None else True,
        "oos_rejection_reasons": oos_reasons,
        "deployed": not rejection_reasons,
        "rejection_reasons": rejection_reasons,
        "params": processed,
    }
    if hmm_support is not None:
        payload.update(hmm_support)
    if full_shadow_activation_audit is not None:
        payload["full_shadow_activation_audit"] = full_shadow_activation_audit
    return payload


def post_process_params(
    params: dict[str, Any],
    *,
    profile: ProfileName,
) -> dict[str, Any]:
    """Expose optimizer-local param post-processing."""
    return _post_process_params(params, profile=profile)


def format_deploy_params(
    params: dict[str, Any],
    *,
    profile: ProfileName,
) -> dict[str, Any]:
    """Shape optimized params for review/deploy artifacts."""
    return _format_deploy_params(params, profile=profile)


def build_decision_frame(
    feature_frame: pd.DataFrame,
    label_frame: pd.DataFrame,
    *,
    params: dict[str, Any],
    profile: ProfileName,
    playbook: str | None,
    horizon: int,
    mtf_context_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build the generic decision frame scored by the validation layer."""
    if profile == "edge_calibration":
        if not playbook:
            raise ValueError("playbook is required for edge_calibration optimization")
        decision_frame = _edge_calibration_frame(
            feature_frame,
            label_frame,
            params=params,
            playbook=playbook,
            horizon=horizon,
        )
        return _attach_hmm_scoring_metadata(decision_frame, feature_frame, profile=profile)
    if profile == "state_core":
        decision_frame = _state_core_frame(feature_frame, label_frame, params=params, horizon=horizon)
        return _attach_hmm_scoring_metadata(decision_frame, feature_frame, profile=profile)
    if profile == "transition":
        decision_frame = _transition_frame(feature_frame, label_frame, params=params, horizon=horizon)
        return _attach_hmm_scoring_metadata(decision_frame, feature_frame, profile=profile)
    if profile == "moe_router":
        decision_frame = _moe_router_frame(feature_frame, label_frame, params=params, horizon=horizon)
        return _attach_hmm_scoring_metadata(decision_frame, feature_frame, profile=profile)
    if profile == "mtf_overlay":
        if mtf_context_frame is None:
            raise ValueError("mtf_context_frame is required for mtf_overlay optimization")
        decision_frame = _mtf_overlay_frame(
            feature_frame,
            label_frame,
            params=params,
            horizon=horizon,
            mtf_context_frame=mtf_context_frame,
        )
        return _attach_hmm_scoring_metadata(decision_frame, feature_frame, profile=profile)
    if profile == "external_context":
        decision_frame = _external_context_frame(feature_frame, label_frame, params=params, horizon=horizon)
        return _attach_hmm_scoring_metadata(decision_frame, feature_frame, profile=profile)
    if profile == "full_shadow_only":
        decision_frame = _full_shadow_frame(
            feature_frame,
            label_frame,
            params=params,
            horizon=horizon,
            mtf_context_frame=mtf_context_frame,
        )
        return _attach_hmm_scoring_metadata(decision_frame, feature_frame, profile=profile)
    raise NotImplementedError(
        f"Built-in decision-frame builder is not implemented for profile={profile}. "
        "Use one of the declared RegimeProbV1 optimization profiles."
    )


def _edge_calibration_frame(
    feature_frame: pd.DataFrame,
    label_frame: pd.DataFrame,
    *,
    params: dict[str, Any],
    playbook: str,
    horizon: int,
) -> pd.DataFrame:
    calibration = fit_playbook_empirical_calibrator(
        feature_frame,
        label_frame,
        playbook=playbook,
        horizon=horizon,
        n_bins=int(params["n_bins"]),
        min_bin_count=int(params["min_bin_count"]),
        strategy=str(params["strategy"]),
    )
    probability = calibration.probabilities.astype(float)
    label_col = calibration.label_column
    edge_return_col = f"{playbook}_edge_return_h{int(horizon)}"
    threshold = float(params["active_probability_threshold"])
    decision_active = probability >= threshold
    out = pd.DataFrame(index=feature_frame.index)
    out["temporal_segment"] = _temporal_segment(label_frame)
    out["selected_probability"] = probability
    out["selected_label"] = pd.to_numeric(label_frame[label_col], errors="coerce")
    out["selected_edge_return"] = pd.to_numeric(label_frame[edge_return_col], errors="coerce")
    out["decision_active"] = decision_active.fillna(False).astype(bool)
    out["decision_key"] = np.where(out["decision_active"], playbook, "flat")
    out["selected_playbook"] = np.where(out["decision_active"], playbook, None)
    return out


def _moe_router_frame(
    feature_frame: pd.DataFrame,
    label_frame: pd.DataFrame,
    *,
    params: dict[str, Any],
    horizon: int,
) -> pd.DataFrame:
    router = build_moe_router_frame(
        feature_frame,
        horizon=horizon,
        config=MoERouterConfig(
            min_edge_probability=float(params["min_edge_probability"]),
            min_policy_score=float(params["min_policy_score"]),
            require_policy_allow=bool(params["require_policy_allow"]),
            top_k=int(params["top_k"]),
            recommendation_min_probability=float(params["recommendation_min_probability"]),
        ),
    )
    out = pd.DataFrame(index=feature_frame.index)
    out["temporal_segment"] = _temporal_segment(label_frame)
    recommended = router["recommended_playbook"].astype(object)
    selected_probability: list[float] = []
    selected_label: list[float] = []
    selected_edge_return: list[float] = []
    decision_key: list[str] = []
    decision_active: list[bool] = []
    selected_playbook: list[str | None] = []
    for idx in feature_frame.index:
        playbook = recommended.loc[idx]
        if not isinstance(playbook, str):
            selected_probability.append(np.nan)
            selected_label.append(np.nan)
            selected_edge_return.append(np.nan)
            decision_key.append("flat")
            decision_active.append(False)
            selected_playbook.append(None)
            continue
        pcol = playbook_probability_column(playbook, horizon)
        lcol = playbook_label_column(playbook, horizon)
        rcol = f"{playbook}_edge_return_h{int(horizon)}"
        selected_probability.append(float(feature_frame.at[idx, pcol]))
        selected_label.append(float(label_frame.at[idx, lcol]) if pd.notna(label_frame.at[idx, lcol]) else np.nan)
        selected_edge_return.append(float(label_frame.at[idx, rcol]) if pd.notna(label_frame.at[idx, rcol]) else np.nan)
        decision_key.append(playbook)
        decision_active.append(True)
        selected_playbook.append(playbook)
    out["selected_probability"] = selected_probability
    out["selected_label"] = selected_label
    out["selected_edge_return"] = selected_edge_return
    out["decision_active"] = pd.Series(decision_active, index=feature_frame.index, dtype=bool)
    out["decision_key"] = decision_key
    out["selected_playbook"] = selected_playbook
    return out


def _mtf_overlay_frame(
    feature_frame: pd.DataFrame,
    label_frame: pd.DataFrame,
    *,
    params: dict[str, Any],
    horizon: int,
    mtf_context_frame: pd.DataFrame,
) -> pd.DataFrame:
    router = build_moe_router_frame(feature_frame, horizon=horizon, config=MoERouterConfig())
    fused = build_mtf_fused_weight_frame(
        router,
        mtf_context_frame,
        config=MTFFusionConfig(
            higher_tf_weight=float(params["higher_tf_weight"]),
            confirmation_boost=float(params["confirmation_boost"]),
            conflict_penalty=float(params["conflict_penalty"]),
            transition_max_penalty=float(params["transition_max_penalty"]),
            entropy_max_penalty=float(params["entropy_max_penalty"]),
            entropy_scale=float(params["entropy_scale"]),
        ),
    )
    out = pd.DataFrame(index=feature_frame.index)
    out["temporal_segment"] = _temporal_segment(label_frame)
    recommended = fused["mtf_recommended_playbook"].astype(object)
    selected_probability: list[float] = []
    selected_label: list[float] = []
    selected_edge_return: list[float] = []
    decision_key: list[str] = []
    decision_active: list[bool] = []
    selected_playbook: list[str | None] = []
    for idx in feature_frame.index:
        playbook = recommended.loc[idx]
        if not isinstance(playbook, str):
            selected_probability.append(np.nan)
            selected_label.append(np.nan)
            selected_edge_return.append(np.nan)
            decision_key.append("flat")
            decision_active.append(False)
            selected_playbook.append(None)
            continue
        weight_col = f"mtf_moe_weight_{playbook}"
        lcol = playbook_label_column(playbook, horizon)
        rcol = f"{playbook}_edge_return_h{int(horizon)}"
        selected_probability.append(float(fused.at[idx, weight_col]))
        selected_label.append(float(label_frame.at[idx, lcol]) if pd.notna(label_frame.at[idx, lcol]) else np.nan)
        selected_edge_return.append(float(label_frame.at[idx, rcol]) if pd.notna(label_frame.at[idx, rcol]) else np.nan)
        decision_key.append(playbook)
        decision_active.append(True)
        selected_playbook.append(playbook)
    out["selected_probability"] = selected_probability
    out["selected_label"] = selected_label
    out["selected_edge_return"] = selected_edge_return
    out["decision_active"] = pd.Series(decision_active, index=feature_frame.index, dtype=bool)
    out["decision_key"] = decision_key
    out["selected_playbook"] = selected_playbook
    return out


def _state_core_frame(
    feature_frame: pd.DataFrame,
    label_frame: pd.DataFrame,
    *,
    params: dict[str, Any],
    horizon: int,
) -> pd.DataFrame:
    state_error = _hmm_state_error(feature_frame, profile="state_core")
    if state_error is not None:
        return _error_decision_frame(feature_frame.index, label_frame, error=state_error)
    probability_frame = _ensure_probability_frame(feature_frame, label_frame, horizon=horizon)
    state_frame = _optimization_state_frame(feature_frame, profile="state_core")
    overlay = _build_probability_overlay(
        probability_frame,
        horizon=horizon,
        config=_overlay_config_from_params(params),
        state_frame=state_frame,
        use_state_support=True,
        use_transition_gate=False,
        use_external_context=False,
    )
    return _decision_frame_from_probabilities(
        overlay.adjusted_probabilities,
        label_frame,
        horizon=horizon,
    )


def _transition_frame(
    feature_frame: pd.DataFrame,
    label_frame: pd.DataFrame,
    *,
    params: dict[str, Any],
    horizon: int,
) -> pd.DataFrame:
    state_error = _hmm_state_error(feature_frame, profile="transition")
    if state_error is not None:
        return _error_decision_frame(feature_frame.index, label_frame, error=state_error)
    probability_frame = _ensure_probability_frame(feature_frame, label_frame, horizon=horizon)
    state_frame = _optimization_state_frame(feature_frame, profile="transition")
    overlay = _build_probability_overlay(
        probability_frame,
        horizon=horizon,
        config=_overlay_config_from_params(params),
        state_frame=state_frame,
        use_state_support=False,
        use_transition_gate=True,
        use_external_context=False,
    )
    return _decision_frame_from_probabilities(overlay.adjusted_probabilities, label_frame, horizon=horizon)


def _external_context_frame(
    feature_frame: pd.DataFrame,
    label_frame: pd.DataFrame,
    *,
    params: dict[str, Any],
    horizon: int,
) -> pd.DataFrame:
    probability_frame = _ensure_probability_frame(feature_frame, label_frame, horizon=horizon)
    overlay = _build_probability_overlay(
        probability_frame,
        horizon=horizon,
        config=_overlay_config_from_params(params),
        use_state_support=False,
        use_transition_gate=False,
        use_external_context=True,
    )
    adjusted = overlay.adjusted_probabilities.where(
        overlay.adjusted_probabilities >= float(params["min_edge_probability"]),
        0.0,
    )
    return _decision_frame_from_probabilities(adjusted, label_frame, horizon=horizon)


def _full_shadow_frame(
    feature_frame: pd.DataFrame,
    label_frame: pd.DataFrame,
    *,
    params: dict[str, Any],
    horizon: int,
    mtf_context_frame: pd.DataFrame | None,
) -> pd.DataFrame:
    state_error = _hmm_state_error(feature_frame, profile="full_shadow_only")
    if state_error is not None:
        return _error_decision_frame(feature_frame.index, label_frame, error=state_error)
    probability_frame = _ensure_probability_frame(
        feature_frame,
        label_frame,
        horizon=horizon,
        calibration_params=params,
    )
    min_edge_probability = float(params["min_edge_probability"])
    probability_columns = [playbook_probability_column(playbook, horizon) for playbook in PLAYBOOKS]
    raw_probabilities = probability_frame.loc[:, [column for column in probability_columns if column in probability_frame.columns]]
    raw_max_probability = raw_probabilities.max(axis=1) if not raw_probabilities.empty else pd.Series(0.0, index=probability_frame.index)
    audit_frame = pd.DataFrame(index=probability_frame.index)
    audit_frame[_AUDIT_RAW_MAX_PROBABILITY] = raw_max_probability.fillna(0.0).astype(float)
    audit_frame[_AUDIT_HAS_ANY_PROBABILITY] = audit_frame[_AUDIT_RAW_MAX_PROBABILITY] > 0.0
    audit_frame[_AUDIT_ABOVE_MIN_EDGE] = audit_frame[_AUDIT_RAW_MAX_PROBABILITY] >= min_edge_probability

    state_frame = _optimization_state_frame(feature_frame, profile="full_shadow_only")
    overlay_config = _overlay_config_from_params(params)
    overlay = _build_probability_overlay(
        probability_frame,
        horizon=horizon,
        config=overlay_config,
        state_frame=state_frame,
        use_state_support=True,
        use_transition_gate=True,
        use_external_context=True,
    )
    state_frame = overlay.state_frame
    audit_frame[_AUDIT_OVERLAY_GATE_ACTIVE] = overlay.gate_active.reindex(probability_frame.index).fillna(False).astype(bool)
    audit_frame[_AUDIT_TRANSITION_RISK] = pd.to_numeric(
        overlay.transition_risk.reindex(probability_frame.index),
        errors="coerce",
    )
    audit_frame[_AUDIT_HIGH_ENTROPY_REJECT] = (
        pd.to_numeric(state_frame.get("state_entropy"), errors="coerce").reindex(probability_frame.index).fillna(0.0)
        > float(overlay_config.max_state_entropy)
    )
    audit_frame[_AUDIT_HIGH_TRANSITION_STATE_REJECT] = (
        pd.to_numeric(state_frame.get("p_transition_state"), errors="coerce").reindex(probability_frame.index).fillna(0.0)
        > float(overlay_config.max_transition_state_prob)
    )

    router_input = probability_frame.drop(columns=[column for column in state_frame.columns if column in probability_frame.columns]).join(
        state_frame,
        how="left",
    )
    for playbook in PLAYBOOKS:
        router_input[playbook_probability_column(playbook, horizon)] = overlay.adjusted_probabilities[playbook]
    router = build_moe_router_frame(
        router_input,
        horizon=horizon,
        config=MoERouterConfig(
            min_edge_probability=min_edge_probability,
            min_policy_score=float(params.get("min_policy_score", 0.0)),
            require_policy_allow=bool(params.get("require_policy_allow", True)),
            top_k=int(params.get("top_k", 2)),
            recommendation_min_probability=float(params.get("recommendation_min_probability", params["min_edge_probability"])),
        ),
    )

    recommended = router["recommended_playbook"].astype(object)
    selection_scores = pd.DataFrame(index=router.index)
    for playbook in PLAYBOOKS:
        selection_scores[playbook] = pd.to_numeric(
            router.get(f"moe_weight_{playbook}"),
            errors="coerce",
        ).fillna(0.0)
    audit_frame[_AUDIT_MOE_HAS_RECOMMENDATION] = router.get("moe_has_recommendation", recommended.notna()).fillna(False).astype(bool)
    audit_frame[_AUDIT_MOE_RECOMMENDED_PLAYBOOK] = router.get("recommended_playbook", pd.Series(index=router.index, dtype=object))
    audit_frame[_AUDIT_MOE_MAX_WEIGHT] = selection_scores.max(axis=1).fillna(0.0).astype(float)
    audit_frame[_AUDIT_MTF_HAS_RECOMMENDATION] = pd.NA
    audit_frame[_AUDIT_MTF_RECOMMENDED_PLAYBOOK] = pd.NA
    audit_frame[_AUDIT_MTF_MAX_WEIGHT] = np.nan
    if mtf_context_frame is not None:
        fused = build_mtf_fused_weight_frame(
            selection_scores.rename(columns={playbook: f"moe_weight_{playbook}" for playbook in PLAYBOOKS}),
            mtf_context_frame,
            config=MTFFusionConfig(
                higher_tf_weight=float(params.get("higher_tf_weight", 1.0)),
                confirmation_boost=float(params.get("confirmation_boost", 0.15)),
                conflict_penalty=float(params.get("conflict_penalty", 0.20)),
                transition_max_penalty=float(params.get("transition_max_penalty", 0.25)),
                entropy_max_penalty=float(params.get("entropy_max_penalty", 0.10)),
                entropy_scale=float(params.get("entropy_scale", 1.50)),
            ),
        )
        recommended = fused["mtf_recommended_playbook"].astype(object)
        selection_scores = pd.DataFrame(
            {
                playbook: pd.to_numeric(
                    fused.get(f"mtf_moe_weight_{playbook}"),
                    errors="coerce",
                ).fillna(0.0)
                for playbook in PLAYBOOKS
            },
            index=fused.index,
        )
        audit_frame[_AUDIT_MTF_HAS_RECOMMENDATION] = recommended.map(lambda value: isinstance(value, str)).astype(bool)
        audit_frame[_AUDIT_MTF_RECOMMENDED_PLAYBOOK] = recommended
        audit_frame[_AUDIT_MTF_MAX_WEIGHT] = selection_scores.max(axis=1).fillna(0.0).astype(float)

    selected_probability = []
    selected_playbook = []
    final_score = []
    final_reason = []
    for idx in probability_frame.index:
        playbook = recommended.loc[idx]
        if not isinstance(playbook, str):
            selected_probability.append(np.nan)
            selected_playbook.append(None)
            final_score.append(np.nan)
            final_reason.append("no_recommendation")
            continue
        if playbook not in selection_scores.columns:
            selected_probability.append(np.nan)
            selected_playbook.append(None)
            final_score.append(np.nan)
            final_reason.append("missing_probability_column")
            continue
        score = float(selection_scores.at[idx, playbook])
        final_score.append(score)
        if not bool(overlay.gate_active.loc[idx]):
            selected_probability.append(np.nan)
            selected_playbook.append(None)
            final_reason.append("overlay_gate_inactive")
            continue
        if score < min_edge_probability:
            selected_probability.append(np.nan)
            selected_playbook.append(None)
            final_reason.append("score_below_min_edge_probability")
            continue
        selected_probability.append(score)
        selected_playbook.append(playbook)
        final_reason.append("active")
    audit_frame[_AUDIT_FINAL_SCORE] = final_score
    audit_frame[_AUDIT_FINAL_REASON] = final_reason
    decision = _decision_frame_from_selected_playbooks(
        probability_frame.index,
        label_frame,
        horizon=horizon,
        selected_playbook=selected_playbook,
        selected_probability=selected_probability,
    )
    return decision.join(audit_frame, how="left")


def _temporal_segment(label_frame: pd.DataFrame) -> pd.Series:
    if "temporal_segment" not in label_frame.columns:
        raise KeyError("label_frame must contain temporal_segment for optimization")
    return label_frame["temporal_segment"].astype(str).reindex(label_frame.index)


def _segment_frame(frame: pd.DataFrame, segment: str) -> pd.DataFrame:
    return frame.loc[frame["temporal_segment"].astype(str) == str(segment)].copy()


def _ensure_probability_frame(
    feature_frame: pd.DataFrame,
    label_frame: pd.DataFrame,
    *,
    horizon: int,
    calibration_params: dict[str, Any] | None = None,
) -> pd.DataFrame:
    out = feature_frame.copy()
    n_bins = int((calibration_params or {}).get("n_bins", 10))
    min_bin_count = int((calibration_params or {}).get("min_bin_count", 10))
    strategy = str((calibration_params or {}).get("strategy", "quantile"))
    for playbook in PLAYBOOKS:
        pcol = playbook_probability_column(playbook, horizon)
        if pcol in out.columns:
            out[pcol] = pd.to_numeric(out[pcol], errors="coerce").fillna(0.0).clip(0.0, 1.0)
            continue
        calibration = fit_playbook_empirical_calibrator(
            feature_frame,
            label_frame,
            playbook=playbook,
            horizon=horizon,
            n_bins=n_bins,
            min_bin_count=min_bin_count,
            strategy=strategy,
        )
        out[pcol] = pd.to_numeric(calibration.probabilities, errors="coerce").fillna(0.0).clip(0.0, 1.0)
    return out


def _decision_frame_from_probabilities(
    probabilities: pd.DataFrame,
    label_frame: pd.DataFrame,
    *,
    horizon: int,
) -> pd.DataFrame:
    selected_playbook = probabilities.idxmax(axis=1).where(probabilities.max(axis=1) > 0.0, None)
    selected_probability = probabilities.max(axis=1).where(probabilities.max(axis=1) > 0.0, np.nan)
    return _decision_frame_from_selected_playbooks(
        probabilities.index,
        label_frame,
        horizon=horizon,
        selected_playbook=selected_playbook.tolist(),
        selected_probability=selected_probability.tolist(),
    )


def _decision_frame_from_selected_playbooks(
    index: pd.Index,
    label_frame: pd.DataFrame,
    *,
    horizon: int,
    selected_playbook: list[str | None],
    selected_probability: list[float],
) -> pd.DataFrame:
    out = pd.DataFrame(index=index)
    out["temporal_segment"] = _temporal_segment(label_frame).reindex(index)
    selected_label: list[float] = []
    selected_edge_return: list[float] = []
    decision_key: list[str] = []
    decision_active: list[bool] = []
    normalized_probability: list[float] = []
    normalized_playbook: list[str | None] = []
    for idx, playbook, probability in zip(index, selected_playbook, selected_probability):
        if not isinstance(playbook, str) or probability != probability or float(probability) <= 0.0:
            selected_label.append(np.nan)
            selected_edge_return.append(np.nan)
            decision_key.append("flat")
            decision_active.append(False)
            normalized_probability.append(np.nan)
            normalized_playbook.append(None)
            continue
        lcol = playbook_label_column(playbook, horizon)
        rcol = f"{playbook}_edge_return_h{int(horizon)}"
        selected_label.append(float(label_frame.at[idx, lcol]) if pd.notna(label_frame.at[idx, lcol]) else np.nan)
        selected_edge_return.append(float(label_frame.at[idx, rcol]) if pd.notna(label_frame.at[idx, rcol]) else np.nan)
        decision_key.append(playbook)
        decision_active.append(True)
        normalized_probability.append(float(probability))
        normalized_playbook.append(playbook)
    out["selected_probability"] = normalized_probability
    out["selected_label"] = selected_label
    out["selected_edge_return"] = selected_edge_return
    out["decision_active"] = pd.Series(decision_active, index=index, dtype=bool)
    out["decision_key"] = decision_key
    out["selected_playbook"] = normalized_playbook
    return out


def _error_decision_frame(
    index: pd.Index,
    label_frame: pd.DataFrame,
    *,
    error: str,
) -> pd.DataFrame:
    out = pd.DataFrame(index=index)
    out["temporal_segment"] = _temporal_segment(label_frame).reindex(index)
    out["selected_probability"] = np.nan
    out["selected_label"] = np.nan
    out["selected_edge_return"] = np.nan
    out["decision_active"] = False
    out["decision_key"] = "flat"
    out["selected_playbook"] = None
    out[_HMM_STATE_ERROR_COLUMN] = str(error)
    return out


def _optimization_state_frame(
    feature_frame: pd.DataFrame,
    *,
    profile: ProfileName,
) -> pd.DataFrame | None:
    if not _hmm_scoring_requested(feature_frame, profile=profile):
        return None
    available = [column for column in _HMM_STATE_COLUMNS if column in feature_frame.columns]
    required = {
        "p_trend_state",
        "p_range_state",
        "p_chop_state",
        "p_breakout_state",
        "p_vol_shock_state",
        "p_transition_state",
        "state_entropy",
    }
    if not required.issubset(available):
        return None
    return feature_frame.loc[:, available].copy()


def _hmm_state_error(
    feature_frame: pd.DataFrame,
    *,
    profile: ProfileName,
) -> str | None:
    if not _hmm_scoring_requested(feature_frame, profile=profile):
        return None
    required = {
        "p_trend_state",
        "p_range_state",
        "p_chop_state",
        "p_breakout_state",
        "p_vol_shock_state",
        "p_transition_state",
        "state_entropy",
    }
    if not required.issubset(feature_frame.columns):
        return _HMM_STATE_COLUMNS_MISSING
    return None


def _attach_hmm_scoring_metadata(
    decision_frame: pd.DataFrame,
    feature_frame: pd.DataFrame,
    *,
    profile: ProfileName,
) -> pd.DataFrame:
    if not _hmm_scoring_requested(feature_frame, profile=profile):
        return decision_frame
    out = decision_frame.copy()
    eval_mode = (
        feature_frame.get(_HMM_EVAL_MODE_COLUMN, pd.Series(_HMM_EVAL_MODE_PROXY, index=feature_frame.index))
        .reindex(out.index)
        .fillna(_HMM_EVAL_MODE_PROXY)
        .astype(str)
    )
    source = (
        feature_frame.get(_HMM_SOURCE_COLUMN, pd.Series(_HMM_SOURCE_PROXY_FALLBACK, index=feature_frame.index))
        .reindex(out.index)
        .fillna(_HMM_SOURCE_PROXY_FALLBACK)
        .astype(str)
    )
    out[_HMM_SOURCE_COLUMN] = source
    out[_HMM_EVAL_MODE_COLUMN] = eval_mode
    out[_HMM_SCORING_ELIGIBLE_COLUMN] = eval_mode.eq(_HMM_EVAL_MODE_OOS)
    return out


def _hmm_scoring_requested(
    feature_frame: pd.DataFrame,
    *,
    profile: ProfileName,
) -> bool:
    if profile not in _HMM_STATE_PROFILES:
        return False
    if _HMM_SOURCE_COLUMN not in feature_frame.columns or _HMM_EVAL_MODE_COLUMN not in feature_frame.columns:
        return False
    sources = {
        str(value)
        for value in feature_frame[_HMM_SOURCE_COLUMN].dropna().astype(str).unique().tolist()
    }
    return bool(sources & {_HMM_SOURCE_MODEL, _HMM_SOURCE_PROXY_FALLBACK})


def _hmm_support_summary(decision_frame: pd.DataFrame) -> dict[str, Any] | None:
    if _HMM_EVAL_MODE_COLUMN not in decision_frame.columns:
        return None
    eval_mode = decision_frame[_HMM_EVAL_MODE_COLUMN].fillna(_HMM_EVAL_MODE_PROXY).astype(str)
    total_rows = int(len(decision_frame))
    in_sample = int(eval_mode.eq(_HMM_EVAL_MODE_IN_SAMPLE).sum())
    oos_filtered = int(eval_mode.eq(_HMM_EVAL_MODE_OOS).sum())
    proxy_fallback = int(eval_mode.eq(_HMM_EVAL_MODE_PROXY).sum())
    source = None
    if _HMM_SOURCE_COLUMN in decision_frame.columns:
        sources = sorted(
            {
                str(value)
                for value in decision_frame[_HMM_SOURCE_COLUMN].dropna().astype(str).unique().tolist()
            }
        )
        if sources:
            source = sources[0] if len(sources) == 1 else ",".join(sources)
    return {
        "hmm_state_source": source,
        "hmm_in_sample_rows": in_sample,
        "hmm_oos_filtered_rows": oos_filtered,
        "hmm_proxy_fallback_rows": proxy_fallback,
        "hmm_oos_filtered_support_rate": round(oos_filtered / total_rows, 8) if total_rows else 0.0,
    }


def _full_shadow_activation_audit_summary(decision_frame: pd.DataFrame) -> dict[str, Any] | None:
    if _AUDIT_FINAL_REASON not in decision_frame.columns:
        return None
    segments = {
        segment: _full_shadow_activation_audit_segment(_segment_frame(decision_frame, segment))
        for segment in ("train", "calibration", "validation", "oos")
    }
    return {
        "overall": _full_shadow_activation_audit_segment(decision_frame),
        "by_segment": segments,
    }


def _full_shadow_activation_audit_segment(frame: pd.DataFrame) -> dict[str, Any]:
    total = int(len(frame))
    raw_max = _numeric_audit_series(frame, _AUDIT_RAW_MAX_PROBABILITY)
    overlay_gate = _bool_audit_series(frame, _AUDIT_OVERLAY_GATE_ACTIVE)
    moe_has_recommendation = _bool_audit_series(frame, _AUDIT_MOE_HAS_RECOMMENDATION)
    mtf_has_recommendation = _bool_audit_series(frame, _AUDIT_MTF_HAS_RECOMMENDATION)
    final_active = _bool_audit_series(frame, "decision_active")
    final_reason = frame.get(_AUDIT_FINAL_REASON, pd.Series(index=frame.index, dtype=object)).fillna("unknown").astype(str)

    summary: dict[str, Any] = {
        "rows": total,
        "probability_stage": {
            **_count_rate("rows_with_any_playbook_probability", _bool_audit_series(frame, _AUDIT_HAS_ANY_PROBABILITY), total),
            **_count_rate("rows_above_min_edge_probability", _bool_audit_series(frame, _AUDIT_ABOVE_MIN_EDGE), total),
            "max_playbook_probability_quantiles": _quantiles(raw_max),
        },
        "overlay_stage": {
            **_count_rate("overlay_gate_active", overlay_gate, total),
            "overlay_gate_inactive_count": int(total - int(overlay_gate.sum())) if total else 0,
            "transition_gate_reject_count": int(total - int(overlay_gate.sum())) if total else 0,
            "high_entropy_reject_count": int(_bool_audit_series(frame, _AUDIT_HIGH_ENTROPY_REJECT).sum()),
            "high_transition_state_reject_count": int(_bool_audit_series(frame, _AUDIT_HIGH_TRANSITION_STATE_REJECT).sum()),
            "transition_risk_quantiles": _quantiles(_numeric_audit_series(frame, _AUDIT_TRANSITION_RISK)),
        },
        "moe_stage": {
            **_count_rate("moe_has_recommendation", moe_has_recommendation, total),
            "recommended_playbook_distribution": _value_counts(frame.get(_AUDIT_MOE_RECOMMENDED_PLAYBOOK)),
            "max_moe_weight_quantiles": _quantiles(_numeric_audit_series(frame, _AUDIT_MOE_MAX_WEIGHT)),
            "below_recommendation_min_probability_count": int((~moe_has_recommendation).sum()) if total else 0,
        },
        "final_selection_stage": {
            "final_selected_probability_count": int(pd.to_numeric(frame.get("selected_probability"), errors="coerce").notna().sum()),
            **_count_rate("final_decision_active", final_active, total),
            "final_reason_distribution": _value_counts(final_reason),
            "final_score_quantiles": _quantiles(_numeric_audit_series(frame, _AUDIT_FINAL_SCORE)),
        },
    }
    if _AUDIT_MTF_HAS_RECOMMENDATION in frame.columns and not frame[_AUDIT_MTF_HAS_RECOMMENDATION].isna().all():
        summary["mtf_stage"] = {
            **_count_rate("mtf_has_recommendation", mtf_has_recommendation, total),
            "mtf_recommended_playbook_distribution": _value_counts(frame.get(_AUDIT_MTF_RECOMMENDED_PLAYBOOK)),
            "mtf_max_weight_quantiles": _quantiles(_numeric_audit_series(frame, _AUDIT_MTF_MAX_WEIGHT)),
        }
    return summary


def _numeric_audit_series(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame.get(column, pd.Series(index=frame.index, dtype=float)), errors="coerce")


def _bool_audit_series(frame: pd.DataFrame, column: str) -> pd.Series:
    series = frame.get(column, pd.Series(False, index=frame.index, dtype=bool))
    return series.fillna(False).astype(bool)


def _count_rate(name: str, mask: pd.Series, total: int) -> dict[str, Any]:
    count = int(mask.sum()) if total else 0
    return {
        f"{name}_count": count,
        f"{name}_rate": round(count / total, 8) if total else 0.0,
    }


def _quantiles(series: pd.Series) -> dict[str, float | None]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return {"p0": None, "p25": None, "p50": None, "p75": None, "p90": None, "p95": None, "p99": None, "p100": None}
    return {
        "p0": round(float(clean.quantile(0.00)), 8),
        "p25": round(float(clean.quantile(0.25)), 8),
        "p50": round(float(clean.quantile(0.50)), 8),
        "p75": round(float(clean.quantile(0.75)), 8),
        "p90": round(float(clean.quantile(0.90)), 8),
        "p95": round(float(clean.quantile(0.95)), 8),
        "p99": round(float(clean.quantile(0.99)), 8),
        "p100": round(float(clean.quantile(1.00)), 8),
    }


def _value_counts(series: pd.Series | None) -> dict[str, int]:
    if series is None:
        return {}
    counts = series.dropna().astype(str).value_counts().sort_index()
    return {str(key): int(value) for key, value in counts.items()}


def _validate_profile(profile: ProfileName) -> None:
    if profile not in _SUPPORTED_PROFILES:
        raise NotImplementedError(
            f"Built-in optimization support is available for {sorted(_SUPPORTED_PROFILES)}; got profile={profile}."
        )


def _segment_rejection_reasons(segment: str, result: Any) -> list[str]:
    if result is None:
        return [f"missing_{segment}_segment"]
    if not result.rejected:
        return []
    return [f"{segment}:{reason}" for reason in result.rejection_reasons]


__all__ = [
    "MODEL_NAME",
    "REJECTED_TRIAL_SCORE",
    "STUDY_DEFAULTS",
    "build_decision_frame",
    "evaluate_oos",
    "format_deploy_params",
    "make_objective",
    "post_process_params",
]
