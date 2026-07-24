"""Independent Trendline V2 foundation package."""

from .api import (
    discover_trendlines,
    select_trendline_candidates,
    track_trendline_families,
)
from .selection import CandidateSelectionSnapshot, LatestValidPredecessorPolicy
from .tracking import (
    ExactSelectedStructureTrackingPolicy,
    TrackedTrendlineFamily,
    TrendlineTrackingSnapshot,
)

__all__ = [
    "CandidateSelectionSnapshot",
    "ExactSelectedStructureTrackingPolicy",
    "LatestValidPredecessorPolicy",
    "TrackedTrendlineFamily",
    "TrendlineTrackingSnapshot",
    "discover_trendlines",
    "select_trendline_candidates",
    "track_trendline_families",
]
