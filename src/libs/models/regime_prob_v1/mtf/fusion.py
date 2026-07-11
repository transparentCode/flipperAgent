"""MTF overlays for playbook probabilities and MoE weights."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from libs.models.regime_prob_v1.moe.experts import PLAYBOOKS, playbook_weight_column


@dataclass(frozen=True)
class MTFFusionConfig:
    """Conservative MTF overlay defaults."""

    higher_tf_weight: float = 1.0
    confirmation_boost: float = 0.15
    conflict_penalty: float = 0.20
    transition_max_penalty: float = 0.25
    entropy_max_penalty: float = 0.10
    entropy_scale: float = 1.50
    normalize_output: bool = True


def apply_mtf_probability_overlay(
    probabilities: Mapping[str, float],
    mtf_context: Mapping[str, float],
    *,
    config: MTFFusionConfig | None = None,
) -> dict[str, float]:
    """Adjust playbook probabilities using HTF confirmation/conflict."""
    cfg = config or MTFFusionConfig()
    trend_conf = _clip01(mtf_context.get("mtf_trend_confirmation", 0.0))
    breakout_conf = _clip01(mtf_context.get("mtf_breakout_confirmation", 0.0))
    mr_conf = _clip01(mtf_context.get("mtf_mr_confirmation", 0.0))
    conflict = _clip01(mtf_context.get("mtf_conflict_score", 0.0))
    transition = _clip01(mtf_context.get("mtf_transition_max", 0.0))
    entropy = _clip01(float(mtf_context.get("mtf_entropy_max", 0.0)) / max(cfg.entropy_scale, 1e-6))
    global_penalty = max(
        0.0,
        (1.0 - cfg.transition_max_penalty * transition) * (1.0 - cfg.entropy_max_penalty * entropy),
    )
    weight = max(float(cfg.higher_tf_weight), 0.0)

    adjusted = {
        "trend_following": _clip01(
            probabilities.get("trend_following", 0.0)
            * (1.0 + weight * cfg.confirmation_boost * trend_conf)
            * (1.0 - weight * cfg.conflict_penalty * max(conflict, mr_conf * 0.5))
            * global_penalty
        ),
        "breakout": _clip01(
            probabilities.get("breakout", 0.0)
            * (1.0 + weight * cfg.confirmation_boost * breakout_conf)
            * (1.0 - weight * cfg.conflict_penalty * max(conflict, transition))
            * global_penalty
        ),
        "mean_reversion": _clip01(
            probabilities.get("mean_reversion", 0.0)
            * (1.0 + weight * cfg.confirmation_boost * mr_conf)
            * (1.0 - weight * cfg.conflict_penalty * max(conflict, trend_conf))
            * global_penalty
        ),
        "countertrend": _clip01(
            probabilities.get("countertrend", 0.0)
            * (1.0 + weight * cfg.confirmation_boost * mr_conf * 0.5)
            * (1.0 - weight * cfg.conflict_penalty * max(conflict, trend_conf))
            * global_penalty
        ),
        "scalping": _clip01(
            probabilities.get("scalping", 0.0)
            * (1.0 - 0.5 * weight * cfg.conflict_penalty * max(conflict, transition))
            * global_penalty
        ),
    }
    return _normalize(adjusted) if cfg.normalize_output else adjusted


def apply_mtf_weight_overlay(
    weights: Mapping[str, float],
    mtf_context: Mapping[str, float],
    *,
    config: MTFFusionConfig | None = None,
) -> dict[str, float]:
    """Adjust normalized router weights using HTF context."""
    return apply_mtf_probability_overlay(weights, mtf_context, config=config)


def build_mtf_fused_weight_frame(
    router_frame: pd.DataFrame,
    mtf_context_frame: pd.DataFrame,
    *,
    config: MTFFusionConfig | None = None,
) -> pd.DataFrame:
    """Apply MTF overlays row-wise to an MoE router output frame."""
    joined = router_frame.join(mtf_context_frame, how="left")
    rows: list[dict[str, float | str | None | int]] = []
    for _, row in joined.iterrows():
        weights = {
            playbook: float(row.get(playbook_weight_column(playbook), 0.0))
            for playbook in PLAYBOOKS
        }
        context = {
            key: float(row.get(key, 0.0))
            for key in (
                "mtf_trend_confirmation",
                "mtf_breakout_confirmation",
                "mtf_mr_confirmation",
                "mtf_conflict_score",
                "mtf_entropy_max",
                "mtf_transition_max",
            )
        }
        fused = apply_mtf_weight_overlay(weights, context, config=config)
        recommendation = max(fused.items(), key=lambda item: item[1])[0] if any(value > 0.0 for value in fused.values()) else None
        payload = {f"mtf_{playbook_weight_column(playbook)}": fused[playbook] for playbook in PLAYBOOKS}
        payload["mtf_recommended_playbook"] = recommendation
        payload["mtf_active_count"] = int(sum(value > 0.0 for value in fused.values()))
        rows.append(payload)
    return pd.DataFrame(rows, index=joined.index)


def _normalize(values: dict[str, float]) -> dict[str, float]:
    mass = sum(max(value, 0.0) for value in values.values())
    if mass <= 0.0:
        return {key: 0.0 for key in values}
    return {key: max(value, 0.0) / mass for key, value in values.items()}


def _clip01(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number:
        return 0.0
    return min(max(number, 0.0), 1.0)


__all__ = [
    "MTFFusionConfig",
    "apply_mtf_probability_overlay",
    "apply_mtf_weight_overlay",
    "build_mtf_fused_weight_frame",
]
