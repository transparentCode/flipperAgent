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
            "r_squared": self.r_squared,
            "metadata": dict(self.metadata),
        }


@dataclass
class QualityMetrics:
    """Aggregate quality statistics for a boundary result."""

    n_support_rays: int = 0
    n_resistance_rays: int = 0
    mean_score: float = 0.0
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
        touches = [ray.touch_count for ray in all_rays]
        r_squared_values = [ray.r_squared for ray in all_rays]

        hull_width = 0.0
        if not (math.isnan(hull_floor) or math.isnan(hull_ceiling)) and mean_atr > 1e-9:
            hull_width = (hull_ceiling - hull_floor) / mean_atr

        return cls(
            n_support_rays=len(support_rays),
            n_resistance_rays=len(resistance_rays),
            mean_score=round(sum(scores) / n_rays, 4),
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