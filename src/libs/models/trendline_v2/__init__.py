"""Independent Trendline V2 foundation package."""

from .api import (
    build_trendline_interaction_bar,
    discover_trendlines,
    observe_trendline_family_interactions,
    select_trendline_candidates,
    track_trendline_families,
)
from .interaction import (
    CandleDirection,
    ConfirmedInteractionBar,
    ExactLineBarObservation,
    ExactLineObservationPolicy,
    InteractionObservationDiagnostics,
    LinePriceRelation,
    TrendlineInteractionSnapshot,
)
from .selection import CandidateSelectionSnapshot, LatestValidPredecessorPolicy
from .tracking import (
    ExactSelectedStructureTrackingPolicy,
    TrackedTrendlineFamily,
    TrendlineTrackingSnapshot,
)

__all__ = [
    "CandidateSelectionSnapshot",
    "CandleDirection",
    "ConfirmedInteractionBar",
    "ExactSelectedStructureTrackingPolicy",
    "ExactLineBarObservation",
    "ExactLineObservationPolicy",
    "InteractionObservationDiagnostics",
    "LatestValidPredecessorPolicy",
    "LinePriceRelation",
    "TrackedTrendlineFamily",
    "TrendlineTrackingSnapshot",
    "TrendlineInteractionSnapshot",
    "build_trendline_interaction_bar",
    "discover_trendlines",
    "observe_trendline_family_interactions",
    "select_trendline_candidates",
    "track_trendline_families",
]
