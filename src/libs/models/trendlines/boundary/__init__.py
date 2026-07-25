"""Consumer-facing structural boundary contracts for trendlines.

This bounded subpackage owns richer downstream-facing result, policy, and
adapter contracts built on top of the narrow core fitter contracts in
``app.trendlines.models``.
"""

from app.trendlines.boundary.adapters import (
    build_boundary_result_from_trendline_result,
    trendline_to_boundary_ray,
)
from app.trendlines.boundary.contracts import (
    BOUNDARY_INTERACTION_DIRECTION,
    BoundaryResult,
    QualityMetrics,
    Ray,
    boundary_interaction_direction,
)
from app.trendlines.boundary.history import (
    SnapshotKey,
    TrendlineSnapshot,
    TrendlineSnapshotHistory,
)
from app.trendlines.boundary.policy import (
    ConfluenceGateConfig,
    ConfluenceQualitySnapshot,
    RayTrackerConfig,
    TouchDeclusterConfig,
    TouchDiagnostics,
    TrackedRayState,
)
from app.trendlines.boundary.touches import decluster_touch_indices

INTERACTION_DIRECTION = BOUNDARY_INTERACTION_DIRECTION
interaction_direction = boundary_interaction_direction

__all__ = [
    "BOUNDARY_INTERACTION_DIRECTION",
    "INTERACTION_DIRECTION",
    "BoundaryResult",
    "ConfluenceGateConfig",
    "ConfluenceQualitySnapshot",
    "QualityMetrics",
    "Ray",
    "RayTrackerConfig",
    "SnapshotKey",
    "TouchDeclusterConfig",
    "TouchDiagnostics",
    "TrackedRayState",
    "TrendlineSnapshot",
    "TrendlineSnapshotHistory",
    "boundary_interaction_direction",
    "build_boundary_result_from_trendline_result",
    "decluster_touch_indices",
    "interaction_direction",
    "trendline_to_boundary_ray",
]