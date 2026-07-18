"""Immutable metric contracts shared by SR research studies."""

from .first_touch import FirstTouchOutcome
from .first_touch_windows import CandidateMetrics, WindowMetrics, compute_candidate_metrics


__all__ = ["CandidateMetrics", "FirstTouchOutcome", "WindowMetrics", "compute_candidate_metrics"]
