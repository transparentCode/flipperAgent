"""Technique-independent candidate provider contracts."""

from .contracts import (
    CandidateProvider,
    ProviderDiagnostics,
    ProviderInput,
    ProviderReason,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)
from .extrema_pair import ConfirmedExtremaPairProvider

__all__ = [
    "CandidateProvider",
    "ConfirmedExtremaPairProvider",
    "ProviderDiagnostics",
    "ProviderInput",
    "ProviderReason",
    "ProviderRequest",
    "ProviderResult",
    "ProviderStatus",
]
