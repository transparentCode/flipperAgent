"""Safety gating for RegimeProbV1 MoE routing."""

from __future__ import annotations

from dataclasses import dataclass

from libs.models.regime_prob_v1.moe.experts import PLAYBOOKS


@dataclass(frozen=True)
class PolicyOverlayResult:
    """Gated probabilities plus explicit block reasons."""

    gated_probabilities: dict[str, float]
    gate_reasons: dict[str, tuple[str, ...]]


def apply_policy_overlay(
    probabilities: dict[str, float],
    *,
    policy_allows: dict[str, bool] | None = None,
    policy_scores: dict[str, float] | None = None,
    min_edge_probability: float = 0.55,
    min_policy_score: float = 0.0,
    require_policy_allow: bool = True,
) -> PolicyOverlayResult:
    """Apply deterministic runtime safety gates to calibrated edge probabilities."""
    gated: dict[str, float] = {}
    reasons: dict[str, tuple[str, ...]] = {}
    allows = dict(policy_allows or {})
    scores = dict(policy_scores or {})

    for playbook in PLAYBOOKS:
        raw = _clip01(probabilities.get(playbook, 0.0))
        blocked: list[str] = []
        if raw < float(min_edge_probability):
            blocked.append("edge_below_minimum")
        if require_policy_allow and not bool(allows.get(playbook, False)):
            blocked.append("policy_disallow")
        if float(scores.get(playbook, 0.0)) < float(min_policy_score):
            blocked.append("policy_score_below_minimum")
        gated[playbook] = 0.0 if blocked else raw
        reasons[playbook] = tuple(blocked)

    return PolicyOverlayResult(
        gated_probabilities=gated,
        gate_reasons=reasons,
    )


def _clip01(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return float(min(max(number, 0.0), 1.0))


__all__ = [
    "PolicyOverlayResult",
    "apply_policy_overlay",
]
