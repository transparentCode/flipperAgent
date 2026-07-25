"""Consumer-facing structural boundary contracts for trendlines."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


BOUNDARY_INTERACTION_DIRECTION: Dict[str, float] = {
    "GEOMETRIC_BOUNCE_SUPPORT": 1.0,
    "GEOMETRIC_BOUNCE_RESISTANCE": -1.0,
    "STRUCTURAL_BREAKOUT": 1.0,
    "STRUCTURAL_BREAKDOWN": -1.0,
}


def boundary_interaction_direction(interaction: str) -> float:
    """Map a boundary interaction label to a directional float."""

    return BOUNDARY_INTERACTION_DIRECTION.get(interaction, 0.0)


@dataclass
class Ray:
    """A consumer-facing structural ray projected in timestamp space."""

    start_time: pd.Timestamp
    end_time: pd.Timestamp
    start_price: float
    end_price: float
    slope: float
    intercept: float
    touch_count: int
    is_support: bool
    kernel: str = ""
    score: float = 0.0
    r_squared: float = 0.0
    metadata: dict = field(default_factory=dict)

    @property
    def slope_per_bar(self) -> float:
        return self.slope

    @property
    def raw_touch_count(self) -> int:
        return int(self.metadata.get("raw_touch_count", self.touch_count))

    @property
    def effective_touch_count(self) -> int:
        return int(self.metadata.get("effective_touch_count", self.touch_count))

    @property
    def normalized_quality_score(self) -> float:
        return float(self.metadata.get("normalized_quality_score", self.score))

    @property
    def quality_components(self) -> Dict[str, Any]:
        components = self.metadata.get("quality_components", {})
        return dict(components) if isinstance(components, dict) else {}

    def value_at(self, bar_index: float) -> float:
        return self.slope * bar_index + self.intercept

    def project(self, bars_ahead: int) -> float:
        return self.end_price + self.slope * bars_ahead

    def to_dict(self) -> dict:
        return {
            "start_time": str(self.start_time),
            "end_time": str(self.end_time),
            "start_price": self.start_price,
            "end_price": self.end_price,
            "slope": self.slope,
            "intercept": self.intercept,
            "touch_count": self.touch_count,
            "raw_touch_count": self.raw_touch_count,
            "effective_touch_count": self.effective_touch_count,
            "is_support": self.is_support,
            "kernel": self.kernel,
            "score": self.score,
            "normalized_quality_score": self.normalized_quality_score,
            "quality_components": self.quality_components,
            "r_squared": self.r_squared,
            "metadata": dict(self.metadata),
        }


@dataclass
class QualityMetrics:
    """Aggregate quality statistics for a boundary result."""

    n_support_rays: int = 0
    n_resistance_rays: int = 0
    mean_score: float = 0.0
    mean_normalized_quality: float = 0.0
    mean_support_quality: float = 0.0
    mean_resistance_quality: float = 0.0
    mean_touch_count: float = 0.0
    mean_r_squared: float = 0.0
    hull_width_atr: float = 0.0

    @classmethod
    def from_result(
        cls,
        support_rays: list[Ray],
        resistance_rays: list[Ray],
        hull_floor: float,
        hull_ceiling: float,
        mean_atr: float,
    ) -> "QualityMetrics":
        all_rays = support_rays + resistance_rays
        n_rays = len(all_rays)
        if n_rays == 0:
            return cls()

        import math

        scores = [ray.score for ray in all_rays]
        normalized = [ray.normalized_quality_score for ray in all_rays]
        support_quality = [ray.normalized_quality_score for ray in support_rays]
        resistance_quality = [ray.normalized_quality_score for ray in resistance_rays]
        touches = [ray.touch_count for ray in all_rays]
        r_squared_values = [ray.r_squared for ray in all_rays]

        hull_width = 0.0
        if not (math.isnan(hull_floor) or math.isnan(hull_ceiling)) and mean_atr > 1e-9:
            hull_width = abs(hull_ceiling - hull_floor) / mean_atr

        return cls(
            n_support_rays=len(support_rays),
            n_resistance_rays=len(resistance_rays),
            mean_score=round(sum(scores) / n_rays, 4),
            mean_normalized_quality=round(sum(normalized) / n_rays, 4),
            mean_support_quality=round(sum(support_quality) / len(support_quality), 4) if support_quality else 0.0,
            mean_resistance_quality=round(sum(resistance_quality) / len(resistance_quality), 4) if resistance_quality else 0.0,
            mean_touch_count=round(sum(touches) / n_rays, 2),
            mean_r_squared=round(sum(r_squared_values) / n_rays, 4),
            hull_width_atr=round(hull_width, 2),
        )


@dataclass
class BoundaryResult:
    """Final consumer-facing structural output for one asset and timeframe."""

    asset: str
    timeframe: str
    timestamp: datetime
    active_support_rays: List[Ray] = field(default_factory=list)
    active_resistance_rays: List[Ray] = field(default_factory=list)
    convex_hull_floor: float = np.nan
    convex_hull_ceiling: float = np.nan
    interaction: str = "NONE"
    is_valid: bool = False
    quality_metrics: Optional[QualityMetrics] = None
    metadata: dict = field(default_factory=dict)

    @property
    def has_support(self) -> bool:
        return bool(self.active_support_rays)

    @property
    def has_resistance(self) -> bool:
        return bool(self.active_resistance_rays)

    @property
    def has_both_sides(self) -> bool:
        return self.has_support and self.has_resistance

    @property
    def has_closed_channel(self) -> bool:
        return bool(
            self.has_both_sides
            and np.isfinite(self.convex_hull_floor)
            and np.isfinite(self.convex_hull_ceiling)
        )

    @property
    def is_one_sided_structure(self) -> bool:
        return self.has_support != self.has_resistance

    @property
    def structure_state(self) -> str:
        if self.has_closed_channel:
            return "closed_channel"
        if self.has_both_sides:
            return "two_sided_unbounded"
        if self.has_support:
            return "support_only"
        if self.has_resistance:
            return "resistance_only"
        return "empty"

    def structure_summary(self) -> Dict[str, Any]:
        return {
            "n_support_rays": len(self.active_support_rays),
            "n_resistance_rays": len(self.active_resistance_rays),
            "has_support": self.has_support,
            "has_resistance": self.has_resistance,
            "has_both_sides": self.has_both_sides,
            "has_closed_channel": self.has_closed_channel,
            "is_one_sided_structure": self.is_one_sided_structure,
            "structure_state": self.structure_state,
        }

    @property
    def boundary_context(self) -> Dict[str, Any]:
        context = self.metadata.get("context", {})
        return dict(context) if isinstance(context, dict) else {}

    @property
    def market_position_state(self) -> str:
        return str(self.boundary_context.get("market_position_state", "unknown"))

    @property
    def hull_position(self) -> float:
        return float(self.boundary_context.get("hull_position", np.nan))

    @property
    def is_inside_channel(self) -> bool:
        return bool(self.boundary_context.get("inside_channel", False))

    @property
    def is_above_channel(self) -> bool:
        return bool(self.boundary_context.get("above_channel", False))

    @property
    def is_below_channel(self) -> bool:
        return bool(self.boundary_context.get("below_channel", False))

    @property
    def is_near_support(self) -> bool:
        return bool(self.boundary_context.get("near_support", False))

    @property
    def is_near_resistance(self) -> bool:
        return bool(self.boundary_context.get("near_resistance", False))

    @property
    def is_mid_channel_noise(self) -> bool:
        return bool(self.boundary_context.get("mid_channel_noise", False))

    @property
    def has_channel_compression(self) -> bool:
        return bool(self.boundary_context.get("channel_compression", False))

    @property
    def has_upper_channel_pressure(self) -> bool:
        return bool(self.boundary_context.get("upper_channel_pressure", False))

    @property
    def has_lower_channel_pressure(self) -> bool:
        return bool(self.boundary_context.get("lower_channel_pressure", False))

    @property
    def mean_normalized_quality(self) -> float:
        if self.quality_metrics is None:
            return 0.0
        return float(self.quality_metrics.mean_normalized_quality)

    @property
    def best_support_quality(self) -> float:
        support = self.best_support
        return support.normalized_quality_score if support is not None else 0.0

    @property
    def best_resistance_quality(self) -> float:
        resistance = self.best_resistance
        return resistance.normalized_quality_score if resistance is not None else 0.0

    @property
    def best_support(self) -> Optional[Ray]:
        if not self.active_support_rays:
            return None
        return max(self.active_support_rays, key=lambda ray: ray.score)

    @property
    def best_resistance(self) -> Optional[Ray]:
        if not self.active_resistance_rays:
            return None
        return max(self.active_resistance_rays, key=lambda ray: ray.score)

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "timestamp": str(self.timestamp),
            "support_rays": [ray.to_dict() for ray in self.active_support_rays],
            "resistance_rays": [ray.to_dict() for ray in self.active_resistance_rays],
            "convex_hull_floor": self.convex_hull_floor,
            "convex_hull_ceiling": self.convex_hull_ceiling,
            "interaction": self.interaction,
            "is_valid": self.is_valid,
            "has_support": self.has_support,
            "has_resistance": self.has_resistance,
            "has_both_sides": self.has_both_sides,
            "has_closed_channel": self.has_closed_channel,
            "is_one_sided_structure": self.is_one_sided_structure,
            "structure_state": self.structure_state,
            "boundary_context": self.boundary_context,
            "market_position_state": self.market_position_state,
            "hull_position": self.hull_position,
            "inside_channel": self.is_inside_channel,
            "above_channel": self.is_above_channel,
            "below_channel": self.is_below_channel,
            "near_support": self.is_near_support,
            "near_resistance": self.is_near_resistance,
            "mid_channel_noise": self.is_mid_channel_noise,
            "channel_compression": self.has_channel_compression,
            "upper_channel_pressure": self.has_upper_channel_pressure,
            "lower_channel_pressure": self.has_lower_channel_pressure,
            "mean_normalized_quality": self.mean_normalized_quality,
            "best_support_quality": self.best_support_quality,
            "best_resistance_quality": self.best_resistance_quality,
            "quality_metrics": asdict(self.quality_metrics) if self.quality_metrics is not None else None,
            "metadata": dict(self.metadata),
        }


__all__ = [
    "BOUNDARY_INTERACTION_DIRECTION",
    "BoundaryResult",
    "QualityMetrics",
    "Ray",
    "boundary_interaction_direction",
]