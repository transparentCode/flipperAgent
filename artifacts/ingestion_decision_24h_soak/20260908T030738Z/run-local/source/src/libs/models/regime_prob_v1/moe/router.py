"""Probability-first MoE routing for RegimeProbV1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from libs.models.regime_prob_v1.moe.experts import (
    PLAYBOOKS,
    extract_edge_probabilities,
    extract_policy_allows,
    extract_policy_scores,
    playbook_weight_column,
)
from libs.models.regime_prob_v1.moe.policy_overlay import apply_policy_overlay


@dataclass(frozen=True)
class MoERouterConfig:
    """Conservative initial router settings."""

    min_edge_probability: float = 0.55
    min_policy_score: float = 0.0
    require_policy_allow: bool = True
    top_k: int | None = None
    recommendation_min_probability: float = 0.55


@dataclass(frozen=True)
class MoERouteDecision:
    """Normalized expert weights and playbook recommendation."""

    weights: dict[str, float]
    recommended_playbook: str | None
    diagnostics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def route_playbooks(
    probabilities: dict[str, float],
    *,
    policy_allows: dict[str, bool] | None = None,
    policy_scores: dict[str, float] | None = None,
    config: MoERouterConfig | None = None,
) -> MoERouteDecision:
    """Route using calibrated edge probabilities first, deterministic policy second."""
    cfg = config or MoERouterConfig()
    raw = {playbook: _clip01(probabilities.get(playbook, 0.0)) for playbook in PLAYBOOKS}
    allows = {playbook: bool((policy_allows or {}).get(playbook, False)) for playbook in PLAYBOOKS}
    scores = {playbook: _clip01((policy_scores or {}).get(playbook, 0.0)) for playbook in PLAYBOOKS}

    overlay = apply_policy_overlay(
        raw,
        policy_allows=allows,
        policy_scores=scores,
        min_edge_probability=cfg.min_edge_probability,
        min_policy_score=cfg.min_policy_score,
        require_policy_allow=cfg.require_policy_allow,
    )
    gated = dict(overlay.gated_probabilities)
    if cfg.top_k is not None and cfg.top_k > 0:
        ranked = sorted(gated.items(), key=lambda item: item[1], reverse=True)
        keep = {name for name, value in ranked[: int(cfg.top_k)] if value > 0.0}
        gated = {playbook: value if playbook in keep else 0.0 for playbook, value in gated.items()}

    mass = float(sum(value for value in gated.values() if value > 0.0))
    if mass > 0.0:
        weights = {
            playbook: round(float(gated[playbook] / mass), 6) if gated[playbook] > 0.0 else 0.0
            for playbook in PLAYBOOKS
        }
    else:
        weights = {playbook: 0.0 for playbook in PLAYBOOKS}

    recommended = _recommended_playbook(
        gated,
        policy_scores=scores,
        min_probability=cfg.recommendation_min_probability,
    )
    diagnostics = {
        "raw_probabilities": raw,
        "policy_allows": allows,
        "policy_scores": scores,
        "gated_probabilities": gated,
        "gate_reasons": overlay.gate_reasons,
        "normalization_mass": mass,
        "eligible_playbooks": tuple(playbook for playbook in PLAYBOOKS if gated[playbook] > 0.0),
        "blocked_playbooks": tuple(playbook for playbook in PLAYBOOKS if gated[playbook] <= 0.0),
    }
    return MoERouteDecision(
        weights=weights,
        recommended_playbook=recommended,
        diagnostics=diagnostics,
    )


def build_moe_router_frame(
    frame: pd.DataFrame,
    *,
    horizon: int,
    config: MoERouterConfig | None = None,
) -> pd.DataFrame:
    """Route every bar in a probability-enriched feature frame."""
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        decision = route_playbooks(
            extract_edge_probabilities(row, horizon=horizon),
            policy_allows=extract_policy_allows(row),
            policy_scores=extract_policy_scores(row),
            config=config,
        )
        payload: dict[str, Any] = {
            playbook_weight_column(playbook): float(decision.weights[playbook])
            for playbook in PLAYBOOKS
        }
        payload["recommended_playbook"] = decision.recommended_playbook
        payload["moe_active_count"] = int(sum(weight > 0.0 for weight in decision.weights.values()))
        payload["moe_has_recommendation"] = bool(decision.recommended_playbook)
        rows.append(payload)
    out = pd.DataFrame(rows, index=frame.index)
    out["recommended_playbook"] = pd.Series(
        [row["recommended_playbook"] for row in rows],
        index=frame.index,
        dtype=object,
    )
    return out


def _recommended_playbook(
    probabilities: dict[str, float],
    *,
    policy_scores: dict[str, float],
    min_probability: float,
) -> str | None:
    eligible = [
        playbook
        for playbook in PLAYBOOKS
        if probabilities.get(playbook, 0.0) >= float(min_probability)
    ]
    if not eligible:
        return None
    ranked = sorted(
        eligible,
        key=lambda playbook: (
            float(probabilities.get(playbook, 0.0)),
            float(policy_scores.get(playbook, 0.0)),
            playbook,
        ),
        reverse=True,
    )
    return ranked[0]


def _clip01(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return float(min(max(number, 0.0), 1.0))


__all__ = [
    "MoERouteDecision",
    "MoERouterConfig",
    "build_moe_router_frame",
    "route_playbooks",
]
