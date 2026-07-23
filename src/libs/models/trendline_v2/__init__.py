"""Independent Trendline V2 foundation package."""

from .api import discover_trendlines, select_trendline_candidates
from .selection import CandidateSelectionSnapshot, LatestValidPredecessorPolicy

__all__ = [
    "CandidateSelectionSnapshot",
    "LatestValidPredecessorPolicy",
    "discover_trendlines",
    "select_trendline_candidates",
]
