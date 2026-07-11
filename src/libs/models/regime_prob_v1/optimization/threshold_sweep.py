"""Local threshold sweep audits for RegimeProbV1 optimization."""

from __future__ import annotations

from typing import Any, Iterable

import pandas as pd

from libs.models.regime_prob_v1.optimization import objective as regime_prob_objective
from libs.models.regime_prob_v1.optimization.params import (
    ProfileName,
    get_optimization_param_schema,
    post_process_params,
)
from libs.models.regime_prob_v1.optimization.validation import RegimeProbRollingValidationConfig

DEFAULT_THRESHOLD_PARAMS: dict[ProfileName, tuple[str, ...]] = {
    "edge_calibration": ("active_probability_threshold",),
    "state_core": (
        "min_edge_probability",
        "min_trend_state_prob",
        "min_range_state_prob",
        "min_breakout_state_prob",
        "max_transition_state_prob",
        "max_state_entropy",
    ),
    "transition": (
        "min_edge_probability",
        "transition_risk_threshold",
        "uncertainty_threshold",
        "changepoint_prob_threshold",
        "max_transition_state_prob",
        "max_state_entropy",
    ),
    "moe_router": ("min_edge_probability", "recommendation_min_probability", "min_policy_score"),
    "mtf_overlay": (
        "higher_tf_weight",
        "confirmation_boost",
        "conflict_penalty",
        "transition_max_penalty",
        "entropy_max_penalty",
    ),
    "external_context": (
        "min_edge_probability",
        "total3_confirmation_weight",
        "market_alignment_weight",
        "btc_d_conflict_weight",
        "context_staleness_penalty",
        "max_staleness_bars",
    ),
    "full_shadow_only": (
        "min_edge_probability",
        "recommendation_min_probability",
        "transition_risk_threshold",
        "max_transition_state_prob",
        "max_state_entropy",
        "higher_tf_weight",
        "total3_confirmation_weight",
        "context_staleness_penalty",
    ),
}


def run_threshold_sweep(
    feature_frame: pd.DataFrame,
    label_frame: pd.DataFrame,
    base_params: dict[str, Any],
    *,
    profile: ProfileName,
    playbook: str | None = None,
    horizon: int = 3,
    mtf_context_frame: pd.DataFrame | None = None,
    validation_config: RegimeProbRollingValidationConfig | None = None,
    params: Iterable[str] | None = None,
    step: float = 0.02,
    radius: int = 2,
) -> dict[str, Any]:
    """Evaluate a local one-parameter-at-a-time sweep around best params."""
    processed_base = post_process_params(base_params, profile=profile)
    schema = get_optimization_param_schema(profile)
    param_names = list(params or DEFAULT_THRESHOLD_PARAMS.get(profile, ()))
    rows: list[dict[str, Any]] = []
    for param in param_names:
        if param not in processed_base or param not in schema:
            continue
        base_value = processed_base[param]
        if not isinstance(base_value, int | float):
            continue
        for value in _candidate_values(
            base_value,
            step=float(step if schema[param].type == "float" else 1.0),
            radius=radius,
            is_int=schema[param].type == "int",
        ):
            candidate = dict(processed_base)
            candidate[param] = value
            processed_candidate = post_process_params(candidate, profile=profile)
            oos = regime_prob_objective.evaluate_oos(
                feature_frame,
                label_frame,
                processed_candidate,
                profile=profile,
                playbook=playbook,
                horizon=horizon,
                mtf_context_frame=mtf_context_frame,
                validation_config=validation_config,
            )
            rows.append(
                {
                    "param": param,
                    "value": processed_candidate[param],
                    "delta": round(float(processed_candidate[param]) - float(base_value), 8),
                    "oos_score": _score(oos),
                    "validation_score": _score(oos, segment="validation"),
                    "deployed": bool(oos.get("deployed")),
                    "rejection_reasons": list(oos.get("rejection_reasons") or []),
                }
            )

    rows.sort(key=lambda row: (not row["deployed"], -(row["oos_score"] or -1_000_000.0)))
    return {
        "params": [param for param in param_names if param in processed_base],
        "step": float(step),
        "radius": int(radius),
        "rows": rows,
    }


def _candidate_values(base: int | float, *, step: float, radius: int, is_int: bool) -> list[int | float]:
    values = []
    for offset in range(-int(radius), int(radius) + 1):
        value = float(base) + offset * float(step)
        values.append(int(round(value)) if is_int else round(value, 8))
    unique = sorted(dict.fromkeys(values))
    return unique


def _score(oos: dict[str, Any], *, segment: str = "oos") -> float | None:
    value = (((oos.get(segment) or {}).get("aggregate") or {}).get("score"))
    if value is None:
        return None
    return float(value)


__all__ = ["DEFAULT_THRESHOLD_PARAMS", "run_threshold_sweep"]
