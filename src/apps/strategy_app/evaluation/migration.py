from __future__ import annotations

from typing import Any

from libs.contracts.signal import ModelOutput, ScoringOutput


def log_migration_comparison(
    logger: Any,
    *,
    asset: str,
    timeframe: str,
    adapted: list[ScoringOutput],
    shadow: list[ModelOutput],
) -> None:
    """Log comparison between adapted scoring output and shadow binary output."""
    shadow_by_name = {model.model_name: model for model in shadow}
    for adapted_out in adapted:
        name = adapted_out.model_name
        shadow_out = shadow_by_name.get(name)
        if shadow_out is None:
            continue
        implied_edge = float(shadow_out.direction) * shadow_out.conviction
        match = abs(implied_edge - adapted_out.edge_score) < 1e-9
        logger.info(
            "legacy_migration_comparison",
            extra={
                "model_name": name,
                "asset": asset,
                "timeframe": timeframe,
                "timestamp": adapted_out.timestamp,
                "legacy_direction": shadow_out.direction,
                "legacy_conviction": shadow_out.conviction,
                "legacy_edge_implied": implied_edge,
                "adapted_edge": adapted_out.edge_score,
                "adapted_conviction": adapted_out.conviction,
                "match": match,
            },
        )
        if not match:
            logger.warning(
                f"Migration mismatch for {name}: "
                f"legacy={implied_edge:.6f} vs adapted={adapted_out.edge_score:.6f}"
            )
