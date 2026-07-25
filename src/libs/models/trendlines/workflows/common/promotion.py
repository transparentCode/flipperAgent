"""Promotion helpers for trendlines workflow results."""

from __future__ import annotations

from typing import Any, Mapping

from libs.models.trendlines.workflows.common.contracts import WorkflowPromotionDecision


TRENDLINE_PIPELINE_PROMOTION_FITNESS_THRESHOLD = 0.05


def decide_pipeline_promotion(
    result: Mapping[str, Any],
    *,
    fitness_threshold: float = TRENDLINE_PIPELINE_PROMOTION_FITNESS_THRESHOLD,
) -> WorkflowPromotionDecision:
    """Produce a deterministic promotion decision from workflow result metrics."""

    best_fitness = float(result.get("best_fitness", 0.0) or 0.0)
    n_windows = int(result.get("n_windows", 0) or 0)
    selected_candidate = result.get("timeframe") or result.get("selected_candidate")

    if n_windows <= 0:
        return WorkflowPromotionDecision(
            status="failed_no_windows",
            should_promote=False,
            selected_candidate=selected_candidate,
            reason="temporal split resolution produced no evaluation windows",
            metadata={
                "minimum_best_fitness": fitness_threshold,
                "best_fitness": best_fitness,
                "n_windows": n_windows,
                "temporal_split_locked": True,
                "config_apply_requires_explicit_call": True,
                "requires_manual_review": True,
                "can_recurse": False,
            },
        )

    should_promote = best_fitness > fitness_threshold
    return WorkflowPromotionDecision(
        status="promotion_recommended" if should_promote else "promotion_blocked",
        should_promote=should_promote,
        selected_candidate=selected_candidate,
        reason=(
            "best_fitness exceeded the promotion threshold"
            if should_promote
            else "best_fitness did not exceed the promotion threshold"
        ),
        metadata={
            "minimum_best_fitness": fitness_threshold,
            "best_fitness": best_fitness,
            "best_fitness_std": float(result.get("best_fitness_std", 0.0) or 0.0),
            "n_windows": n_windows,
            "temporal_split_locked": True,
            "config_apply_requires_explicit_call": True,
            "requires_manual_review": True,
            "can_recurse": False,
        },
    )


__all__ = [
    "TRENDLINE_PIPELINE_PROMOTION_FITNESS_THRESHOLD",
    "decide_pipeline_promotion",
]