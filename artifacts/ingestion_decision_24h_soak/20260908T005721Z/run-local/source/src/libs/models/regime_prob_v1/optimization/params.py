"""Optimization parameter schema for RegimeProbV1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from libs.contracts.schemas import ParamDef


ProfileName = Literal[
    "state_core",
    "transition",
    "edge_calibration",
    "moe_router",
    "mtf_overlay",
    "external_context",
    "full_shadow_only",
]
ParamType = Literal["float", "int", "categorical"]


@dataclass(frozen=True)
class RegimeProbParamSpec:
    """One tunable RegimeProbV1 parameter."""

    key: str
    type: ParamType
    default: Any
    low: float | int | None = None
    high: float | int | None = None
    step: float | int | None = None
    choices: tuple[Any, ...] | None = None
    profiles: tuple[ProfileName, ...] = ("full_shadow_only",)


REGIME_PROB_OPTIMIZATION_PROFILES: dict[ProfileName, str] = {
    "state_core": "Proxy state overlay on top of calibrated playbook edge probabilities.",
    "transition": "Transition-risk suppression overlay using BCPD/uncertainty features.",
    "edge_calibration": "Empirical calibration of one playbook edge head.",
    "moe_router": "Probability-first MoE routing thresholds and gates.",
    "mtf_overlay": "Higher-timeframe confirmation/conflict overlay weights.",
    "external_context": "Optional external-context weighting and staleness overlay.",
    "full_shadow_only": "Shadow-only composite profile combining calibrated edges, overlays, and MTF.",
}


REGIME_PROB_PARAM_SPECS: tuple[RegimeProbParamSpec, ...] = (
    RegimeProbParamSpec(
        key="n_bins",
        type="int",
        default=10,
        low=4,
        high=20,
        step=1,
        profiles=("edge_calibration", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="min_bin_count",
        type="int",
        default=10,
        low=3,
        high=40,
        step=1,
        profiles=("edge_calibration", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="strategy",
        type="categorical",
        default="quantile",
        choices=("quantile", "equal_width"),
        profiles=("edge_calibration", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="active_probability_threshold",
        type="float",
        default=0.35,
        low=0.25,
        high=0.80,
        step=0.01,
        profiles=("edge_calibration", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="min_edge_probability",
        type="float",
        default=0.35,
        low=0.25,
        high=0.80,
        step=0.01,
        profiles=("state_core", "transition", "moe_router", "external_context", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="min_policy_score",
        type="float",
        default=0.00,
        low=0.00,
        high=0.50,
        step=0.01,
        profiles=("moe_router", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="require_policy_allow",
        type="categorical",
        default=True,
        choices=(True, False),
        profiles=("moe_router", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="top_k",
        type="int",
        default=2,
        low=1,
        high=3,
        step=1,
        profiles=("moe_router", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="recommendation_min_probability",
        type="float",
        default=0.35,
        low=0.25,
        high=0.85,
        step=0.01,
        profiles=("moe_router", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="higher_tf_weight",
        type="float",
        default=1.0,
        low=0.25,
        high=1.50,
        step=0.05,
        profiles=("mtf_overlay", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="confirmation_boost",
        type="float",
        default=0.15,
        low=0.00,
        high=0.40,
        step=0.01,
        profiles=("mtf_overlay", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="conflict_penalty",
        type="float",
        default=0.20,
        low=0.00,
        high=0.50,
        step=0.01,
        profiles=("mtf_overlay", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="transition_max_penalty",
        type="float",
        default=0.25,
        low=0.00,
        high=0.60,
        step=0.01,
        profiles=("mtf_overlay", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="entropy_max_penalty",
        type="float",
        default=0.10,
        low=0.00,
        high=0.30,
        step=0.01,
        profiles=("mtf_overlay", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="entropy_scale",
        type="float",
        default=1.50,
        low=0.50,
        high=3.00,
        step=0.05,
        profiles=("mtf_overlay", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="min_trend_state_prob",
        type="float",
        default=0.45,
        low=0.20,
        high=0.80,
        step=0.01,
        profiles=("state_core", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="min_range_state_prob",
        type="float",
        default=0.45,
        low=0.20,
        high=0.80,
        step=0.01,
        profiles=("state_core", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="min_breakout_state_prob",
        type="float",
        default=0.40,
        low=0.20,
        high=0.80,
        step=0.01,
        profiles=("state_core", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="max_transition_state_prob",
        type="float",
        default=0.55,
        low=0.10,
        high=0.90,
        step=0.01,
        profiles=("state_core", "transition", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="max_state_entropy",
        type="float",
        default=0.80,
        low=0.20,
        high=1.00,
        step=0.05,
        profiles=("state_core", "transition", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="transition_risk_threshold",
        type="float",
        default=0.55,
        low=0.10,
        high=0.90,
        step=0.01,
        profiles=("transition", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="uncertainty_threshold",
        type="float",
        default=0.75,
        low=0.20,
        high=1.00,
        step=0.01,
        profiles=("transition", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="changepoint_prob_threshold",
        type="float",
        default=0.55,
        low=0.10,
        high=0.90,
        step=0.01,
        profiles=("transition", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="max_staleness_bars",
        type="int",
        default=2,
        low=1,
        high=6,
        step=1,
        profiles=("external_context", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="btc_d_conflict_weight",
        type="float",
        default=0.25,
        low=0.00,
        high=1.00,
        step=0.05,
        profiles=("external_context", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="total3_confirmation_weight",
        type="float",
        default=0.25,
        low=0.00,
        high=1.00,
        step=0.05,
        profiles=("external_context", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="market_alignment_weight",
        type="float",
        default=0.20,
        low=0.00,
        high=1.00,
        step=0.05,
        profiles=("external_context", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="beta_weight",
        type="float",
        default=0.10,
        low=0.00,
        high=0.50,
        step=0.05,
        profiles=("external_context", "full_shadow_only"),
    ),
    RegimeProbParamSpec(
        key="context_staleness_penalty",
        type="float",
        default=0.25,
        low=0.00,
        high=1.00,
        step=0.05,
        profiles=("external_context", "full_shadow_only"),
    ),
)


def get_optimization_param_schema(profile: ProfileName) -> dict[str, ParamDef]:
    """Return a ParamDef schema for one RegimeProbV1 optimization profile."""
    _validate_profile(profile)
    schema: dict[str, ParamDef] = {}
    for spec in REGIME_PROB_PARAM_SPECS:
        if profile not in spec.profiles:
            continue
        schema[spec.key] = ParamDef(
            type=spec.type,
            default=spec.default,
            low=spec.low,
            high=spec.high,
            step=spec.step,
            choices=list(spec.choices) if spec.choices is not None else None,
        )
    return schema


def extract_profile_defaults(profile: ProfileName) -> dict[str, Any]:
    """Return default parameter values for one profile."""
    return {name: pdef.default for name, pdef in get_optimization_param_schema(profile).items()}


def post_process_params(
    params: dict[str, Any],
    *,
    profile: ProfileName,
) -> dict[str, Any]:
    """Round/coerce optimized params back onto the declared schema."""
    schema = get_optimization_param_schema(profile)
    processed: dict[str, Any] = {}
    for name, pdef in schema.items():
        value = params.get(name, pdef.default)
        if pdef.type == "int":
            value = int(round(float(value)))
            if pdef.low is not None:
                value = max(value, int(pdef.low))
            if pdef.high is not None:
                value = min(value, int(pdef.high))
        elif pdef.type == "float":
            value = float(value)
            if pdef.low is not None:
                value = max(value, float(pdef.low))
            if pdef.high is not None:
                value = min(value, float(pdef.high))
            if pdef.step is not None and pdef.step > 0:
                value = round(round((value - float(pdef.low or 0.0)) / float(pdef.step)) * float(pdef.step) + float(pdef.low or 0.0), 8)
                if pdef.low is not None:
                    value = max(value, float(pdef.low))
                if pdef.high is not None:
                    value = min(value, float(pdef.high))
        elif pdef.type == "categorical":
            choices = pdef.choices or [pdef.default]
            if value not in choices:
                value = pdef.default
        processed[name] = value
    return processed


def format_deploy_params(
    params: dict[str, Any],
    *,
    profile: ProfileName,
) -> dict[str, Any]:
    """Shape params for review/deploy artifacts."""
    processed = post_process_params(params, profile=profile)
    return {
        "profile": profile,
        "params": processed,
    }


def _validate_profile(profile: str) -> None:
    if profile not in REGIME_PROB_OPTIMIZATION_PROFILES:
        raise KeyError(f"Unsupported RegimeProbV1 optimization profile: {profile}")


__all__ = [
    "ProfileName",
    "REGIME_PROB_OPTIMIZATION_PROFILES",
    "REGIME_PROB_PARAM_SPECS",
    "RegimeProbParamSpec",
    "extract_profile_defaults",
    "format_deploy_params",
    "get_optimization_param_schema",
    "post_process_params",
]
