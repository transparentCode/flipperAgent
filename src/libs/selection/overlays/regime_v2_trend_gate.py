"""Disabled-by-default RegimeV2 playbook gate for selection candidates.

This module is intentionally conservative:

- disabled config => exact no-op
- missing RegimeV2 feature payload => exact no-op
- inactive RegimeV2 policy => exact no-op
- unsupported mode => exact no-op

The only currently supported live mode is ``gated``. Live behavior remains the
original trend-only gate unless explicitly configured otherwise. Shadow mode can
preview the validated Phase 5A candidate subset without changing live selection
decisions.
"""

from __future__ import annotations

from typing import Any

from libs.contracts.signal import FeatureVector, SelectionCandidate

_DEFAULT_LIVE_TARGET_MODELS = {"Momentum", "MomentumV2", "TrendFollowing", "TrendFollowingModel"}
_VALIDATED_PHASE5A_SHADOW_MODELS = {
    "Momentum",
    "MomentumV2",
    "TrendFollowing",
    "TrendFollowingModel",
    "RegimePullbackScorer",
    "RegimePullback",
    "RegressionPullback",
    "SqueezeBreakout",
    "SqueezeBreakoutModel",
}
_BREAKOUT_MODELS = {"SqueezeBreakout", "SqueezeBreakoutModel"}
_MEAN_REVERSION_MODELS = {"RegimePullbackScorer", "RegimePullback", "RegressionPullback"}


def apply_regime_v2_trend_gate(
    candidates: list[SelectionCandidate],
    feature_vec: FeatureVector,
    config: dict[str, Any],
) -> list[SelectionCandidate]:
    """Apply a guarded RegimeV2 trend gate to live selection candidates."""
    decision = explain_regime_v2_trend_gate(candidates, feature_vec, config)
    if not decision["active"]:
        return candidates
    return _apply_active_gate(candidates, decision)


def preview_regime_v2_trend_gate(
    candidates: list[SelectionCandidate],
    feature_vec: FeatureVector,
    config: dict[str, Any],
) -> tuple[list[SelectionCandidate], dict[str, Any]]:
    """Preview RegimeV2 gating for shadow-mode observability.

    Unlike ``apply_regime_v2_trend_gate``, this treats ``shadow_enabled`` as the
    activation switch and does not require the live ``enabled`` flag. If no
    explicit ``shadow_target_models`` or legacy ``target_models`` are configured,
    the shadow preview uses the validated Phase 5A subset and excludes other
    families, including PriceAction, from the counterfactual shadow selection.
    """
    gate_config = _gate_config(config)
    if not gate_config.get("shadow_enabled", False):
        return candidates, {
            "shadow_enabled": False,
            "active": False,
            "reason": "shadow_disabled",
        }

    decision = explain_regime_v2_trend_gate(
        candidates,
        feature_vec,
        config,
        force_enabled=True,
        use_shadow_targets=True,
    )
    if not decision["active"]:
        if decision.get("shadow_subset_only", False):
            return _filter_shadow_subset(candidates, decision), {**decision, "shadow_enabled": True}
        return candidates, {**decision, "shadow_enabled": True}
    return _apply_active_gate(candidates, decision), {**decision, "shadow_enabled": True}


def explain_regime_v2_trend_gate(
    candidates: list[SelectionCandidate],
    feature_vec: FeatureVector,
    config: dict[str, Any],
    *,
    force_enabled: bool = False,
    use_shadow_targets: bool = False,
) -> dict[str, Any]:
    """Explain whether the gate is active and why."""
    gate_config = _gate_config(config)
    enabled = bool(gate_config.get("enabled", False)) or force_enabled
    if not enabled:
        return _inactive_decision("disabled", candidates, gate_config, use_shadow_targets=use_shadow_targets)

    mode = str(gate_config.get("mode", "gated"))
    if mode != "gated":
        return _inactive_decision(
            "unsupported_mode",
            candidates,
            gate_config,
            mode=mode,
            use_shadow_targets=use_shadow_targets,
        )

    regime_v2 = feature_vec.features.get("regime_v2")
    if not isinstance(regime_v2, dict):
        return _inactive_decision(
            "missing_regime_v2_payload",
            candidates,
            gate_config,
            mode=mode,
            use_shadow_targets=use_shadow_targets,
        )

    policy_active, policy_context = (
        _shadow_playbook_policy_active(regime_v2, gate_config)
        if use_shadow_targets
        else _trend_policy_active(regime_v2, gate_config)
    )
    if not policy_active:
        return _inactive_decision(
            "inactive_playbook_policy" if use_shadow_targets else "inactive_trend_policy",
            candidates,
            gate_config,
            mode=mode,
            use_shadow_targets=use_shadow_targets,
            **policy_context,
        )

    regime_side = _regime_side(regime_v2)
    if regime_side == 0:
        return _inactive_decision(
            "neutral_regime_side",
            candidates,
            gate_config,
            mode=mode,
            use_shadow_targets=use_shadow_targets,
            **policy_context,
        )

    target_models, subset_name, shadow_subset_only = _target_models(gate_config, use_shadow_targets=use_shadow_targets)
    include_non_targets = _include_non_targets(
        gate_config,
        use_shadow_targets=use_shadow_targets,
        shadow_subset_only=shadow_subset_only,
    )
    active_playbooks = set(policy_context.get("active_playbooks", ("trend",)))
    playbook_by_model = {model: _candidate_playbook(model) for model in target_models}
    target_count = sum(1 for candidate in candidates if candidate.model_name in target_models)
    aligned_targets = [
        candidate.model_name
        for candidate in candidates
        if candidate.model_name in target_models
        and _candidate_allowed_by_playbook(candidate, regime_side, active_playbooks, playbook_by_model[candidate.model_name])
    ]
    conflict_targets = [
        candidate.model_name
        for candidate in candidates
        if candidate.model_name in target_models
        and not _candidate_allowed_by_playbook(candidate, regime_side, active_playbooks, playbook_by_model[candidate.model_name])
    ]
    non_target_models = [candidate.model_name for candidate in candidates if candidate.model_name not in target_models]

    return {
        "active": True,
        "reason": "active",
        "mode": mode,
        "baseline_candidate_count": len(candidates),
        "target_candidate_count": target_count,
        "regime_side": regime_side,
        "target_models": sorted(target_models),
        "shadow_subset_name": subset_name if use_shadow_targets else None,
        "shadow_subset_only": shadow_subset_only if use_shadow_targets else False,
        "include_non_target_models": include_non_targets,
        "candidate_playbooks": {model: playbook_by_model[model] for model in sorted(playbook_by_model)},
        "aligned_target_models": aligned_targets,
        "conflict_target_models": conflict_targets,
        "non_target_models": non_target_models,
        **policy_context,
    }


def _apply_active_gate(
    candidates: list[SelectionCandidate],
    decision: dict[str, Any],
) -> list[SelectionCandidate]:
    regime_side = int(decision["regime_side"])
    target_models = set(decision.get("target_models") or _DEFAULT_LIVE_TARGET_MODELS)
    active_playbooks = set(decision.get("active_playbooks") or ("trend",))
    candidate_playbooks = dict(decision.get("candidate_playbooks") or {})
    keep_conflicts = bool(decision.get("keep_conflicts_with_penalty", False))
    include_non_targets = bool(decision.get("include_non_target_models", True))
    kept: list[SelectionCandidate] = []
    for candidate in candidates:
        if candidate.model_name not in target_models:
            if include_non_targets:
                kept.append(candidate)
            continue

        playbook = str(candidate_playbooks.get(candidate.model_name, _candidate_playbook(candidate.model_name)))
        allowed = _candidate_allowed_by_playbook(candidate, regime_side, active_playbooks, playbook)
        if allowed:
            kept.append(
                candidate.model_copy(
                    update={
                        "metadata": {
                            **candidate.metadata,
                            "regime_v2_trend_gate": "passed",
                            "regime_v2_playbook_gate": "passed",
                            "regime_v2_active_playbook": playbook,
                            "regime_v2_trend_side": regime_side,
                        }
                    }
                )
            )
        elif keep_conflicts:
            kept.append(
                candidate.model_copy(
                    update={
                        "metadata": {
                            **candidate.metadata,
                            "regime_v2_trend_gate": "conflict",
                            "regime_v2_playbook_gate": "conflict",
                            "regime_v2_active_playbook": playbook,
                            "regime_v2_trend_side": regime_side,
                        }
                    }
                )
            )
    return kept


def _filter_shadow_subset(
    candidates: list[SelectionCandidate],
    decision: dict[str, Any],
) -> list[SelectionCandidate]:
    if not decision.get("shadow_subset_only", False):
        return candidates
    target_models = set(decision.get("target_models") or _VALIDATED_PHASE5A_SHADOW_MODELS)
    return [candidate for candidate in candidates if candidate.model_name in target_models]


def _gate_config(config: dict[str, Any]) -> dict[str, Any]:
    overlays = config.get("overlays", {})
    if not isinstance(overlays, dict):
        return {}
    gate = overlays.get("regime_v2_trend_gate", {})
    return gate if isinstance(gate, dict) else {}


def _target_models(
    gate_config: dict[str, Any],
    *,
    use_shadow_targets: bool,
) -> tuple[set[str], str, bool]:
    if not use_shadow_targets:
        return set(gate_config.get("target_models") or _DEFAULT_LIVE_TARGET_MODELS), "live_trend_gate", False

    if gate_config.get("shadow_target_models"):
        return set(gate_config["shadow_target_models"]), "configured_shadow_subset", bool(
            gate_config.get("shadow_subset_only", True)
        )
    if gate_config.get("target_models"):
        return set(gate_config["target_models"]), "legacy_target_models", bool(
            gate_config.get("shadow_subset_only", False)
        )
    return set(_VALIDATED_PHASE5A_SHADOW_MODELS), "validated_phase5a_subset", bool(
        gate_config.get("shadow_subset_only", True)
    )


def _include_non_targets(
    gate_config: dict[str, Any],
    *,
    use_shadow_targets: bool,
    shadow_subset_only: bool,
) -> bool:
    if not use_shadow_targets:
        return True
    if "shadow_include_non_targets" in gate_config:
        return bool(gate_config["shadow_include_non_targets"])
    return not shadow_subset_only


def _trend_policy_active(
    regime_v2: dict[str, Any],
    gate_config: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    policy = regime_v2.get("policy", {})
    evidence = regime_v2.get("evidence", {})
    if not isinstance(policy, dict):
        policy = {}
    if not isinstance(evidence, dict):
        evidence = {}

    allow_trend = bool(policy.get("allow_trend_following", False))
    trend_score = float(policy.get("trend_score", 0.0) or 0.0)
    confidence = float(evidence.get("confidence", regime_v2.get("confidence", 0.0)) or 0.0)
    uncertainty = float(evidence.get("uncertainty", regime_v2.get("uncertainty", 1.0)) or 1.0)
    min_trend_score = float(gate_config.get("min_trend_score", 0.24))
    min_confidence = float(gate_config.get("min_confidence", 0.0))
    trend_active = allow_trend and trend_score >= min_trend_score and confidence >= min_confidence
    context = {
        "allow_trend_following": allow_trend,
        "allow_breakout": bool(policy.get("allow_breakout", False)),
        "allow_mean_reversion": bool(policy.get("allow_mean_reversion", False)),
        "active_playbooks": ["trend"] if trend_active else [],
        "trend_score": trend_score,
        "breakout_score": float(policy.get("breakout_score", 0.0) or 0.0),
        "mean_reversion_score": float(policy.get("mean_reversion_score", 0.0) or 0.0),
        "confidence": confidence,
        "uncertainty": uncertainty,
        "min_trend_score": min_trend_score,
        "min_breakout_score": float(gate_config.get("min_breakout_score", 0.24)),
        "min_mean_reversion_score": float(gate_config.get("min_mean_reversion_score", 0.24)),
        "min_confidence": min_confidence,
        "keep_conflicts_with_penalty": bool(gate_config.get("keep_conflicts_with_penalty", False)),
    }
    return trend_active, context


def _shadow_playbook_policy_active(
    regime_v2: dict[str, Any],
    gate_config: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    policy = regime_v2.get("policy", {})
    evidence = regime_v2.get("evidence", {})
    if not isinstance(policy, dict):
        policy = {}
    if not isinstance(evidence, dict):
        evidence = {}

    confidence = float(evidence.get("confidence", regime_v2.get("confidence", 0.0)) or 0.0)
    uncertainty = float(evidence.get("uncertainty", regime_v2.get("uncertainty", 1.0)) or 1.0)
    min_confidence = float(gate_config.get("min_confidence", 0.0))
    min_trend_score = float(gate_config.get("min_trend_score", 0.24))
    min_breakout_score = float(gate_config.get("min_breakout_score", 0.24))
    min_mean_reversion_score = float(gate_config.get("min_mean_reversion_score", 0.24))

    allow_trend = bool(policy.get("allow_trend_following", False))
    allow_breakout = bool(policy.get("allow_breakout", False))
    allow_mean_reversion = bool(policy.get("allow_mean_reversion", False))
    trend_score = float(policy.get("trend_score", 0.0) or 0.0)
    breakout_score = float(policy.get("breakout_score", 0.0) or 0.0)
    mean_reversion_score = float(policy.get("mean_reversion_score", 0.0) or 0.0)

    active_playbooks: list[str] = []
    if allow_trend and trend_score >= min_trend_score and confidence >= min_confidence:
        active_playbooks.append("trend")
    if allow_breakout and breakout_score >= min_breakout_score and confidence >= min_confidence:
        active_playbooks.append("breakout")
    if allow_mean_reversion and mean_reversion_score >= min_mean_reversion_score and confidence >= min_confidence:
        active_playbooks.append("mean_reversion")

    context = {
        "allow_trend_following": allow_trend,
        "allow_breakout": allow_breakout,
        "allow_mean_reversion": allow_mean_reversion,
        "active_playbooks": active_playbooks,
        "trend_score": trend_score,
        "breakout_score": breakout_score,
        "mean_reversion_score": mean_reversion_score,
        "confidence": confidence,
        "uncertainty": uncertainty,
        "min_trend_score": min_trend_score,
        "min_breakout_score": min_breakout_score,
        "min_mean_reversion_score": min_mean_reversion_score,
        "min_confidence": min_confidence,
        "keep_conflicts_with_penalty": bool(gate_config.get("keep_conflicts_with_penalty", False)),
    }
    return bool(active_playbooks), context


def _candidate_playbook(model_name: str) -> str:
    if model_name in _BREAKOUT_MODELS:
        return "breakout"
    if model_name in _MEAN_REVERSION_MODELS:
        return "mean_reversion"
    return "trend"


def _candidate_allowed_by_playbook(
    candidate: SelectionCandidate,
    regime_side: int,
    active_playbooks: set[str],
    playbook: str,
) -> bool:
    direction = int(candidate.direction)
    if playbook == "mean_reversion":
        return "mean_reversion" in active_playbooks and direction != 0
    if playbook == "breakout":
        return "breakout" in active_playbooks and direction == regime_side
    return "trend" in active_playbooks and direction == regime_side


def _regime_side(regime_v2: dict[str, Any]) -> int:
    evidence = regime_v2.get("evidence", {})
    if not isinstance(evidence, dict):
        return 0
    direction = str(evidence.get("trend_direction", "neutral")).lower()
    if direction == "bull":
        return 1
    if direction == "bear":
        return -1
    return 0


def _inactive_decision(
    reason: str,
    candidates: list[SelectionCandidate],
    gate_config: dict[str, Any],
    *,
    use_shadow_targets: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    target_models, subset_name, shadow_subset_only = _target_models(gate_config, use_shadow_targets=use_shadow_targets)
    include_non_targets = _include_non_targets(
        gate_config,
        use_shadow_targets=use_shadow_targets,
        shadow_subset_only=shadow_subset_only,
    )
    return {
        "active": False,
        "reason": reason,
        "baseline_candidate_count": len(candidates),
        "target_models": sorted(target_models),
        "target_candidate_count": sum(1 for candidate in candidates if candidate.model_name in target_models),
        "shadow_subset_name": subset_name if use_shadow_targets else None,
        "shadow_subset_only": shadow_subset_only if use_shadow_targets else False,
        "include_non_target_models": include_non_targets,
        "candidate_playbooks": {model: _candidate_playbook(model) for model in sorted(target_models)},
        "keep_conflicts_with_penalty": bool(gate_config.get("keep_conflicts_with_penalty", False)),
        **extra,
    }


__all__ = [
    "apply_regime_v2_trend_gate",
    "explain_regime_v2_trend_gate",
    "preview_regime_v2_trend_gate",
]
