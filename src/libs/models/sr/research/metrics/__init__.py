"""Immutable metric contracts shared by SR research studies."""

from .first_touch import FirstTouchOutcome
from .first_touch_windows import CandidateMetrics, WindowMetrics, compute_candidate_metrics
from .first_revisit import first_revisit_outcome, intersects_band, prior_close_control_candidate


__all__ = [
    "CandidateMetrics", "FirstTouchOutcome", "WindowMetrics", "compute_candidate_metrics",
    "first_revisit_outcome", "intersects_band", "prior_close_control_candidate",
]
