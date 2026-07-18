"""Compatibility exports for shared first-touch research metrics."""

from libs.models.sr.research.metrics.first_touch_windows import (
    CandidateMetrics,
    FirstTouchOutcome,
    WINDOW_POLICY,
    WindowMetrics,
    compute_candidate_metrics,
    compute_window_metrics,
    median_absolute_deviation,
)


__all__ = [
    "CandidateMetrics",
    "FirstTouchOutcome",
    "WindowMetrics",
    "WINDOW_POLICY",
    "compute_candidate_metrics",
    "compute_window_metrics",
    "median_absolute_deviation",
]
