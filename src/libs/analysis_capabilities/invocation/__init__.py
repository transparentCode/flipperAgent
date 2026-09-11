"""Opt-in checked invocation and provenance envelopes."""

from .contracts import (
    AnalysisBindingError,
    AnalysisInvocationContext,
    AnalysisInvocationResult,
    AnalysisSeriesIdentity,
    AnalysisSourceAttestation,
)
from .executor import execute_bound_analysis_capability

__all__ = (
    "AnalysisBindingError",
    "AnalysisInvocationContext",
    "AnalysisInvocationResult",
    "AnalysisSeriesIdentity",
    "AnalysisSourceAttestation",
    "execute_bound_analysis_capability",
)
