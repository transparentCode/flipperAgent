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
from .provider_evidence import (
    COORDINATE_SYSTEM_VERSION,
    EVIDENCE_SCHEMA_VERSION,
    PLATEAU_POLICY_VERSION,
    ConfirmedExtremaPairEvidence,
    ExtremaKind,
)

__all__ = [
    "CandidateProvider",
    "COORDINATE_SYSTEM_VERSION",
    "ConfirmedExtremaPairEvidence",
    "ProviderDiagnostics",
    "ProviderInput",
    "ProviderReason",
    "ProviderRequest",
    "ProviderResult",
    "ProviderStatus",
    "EVIDENCE_SCHEMA_VERSION",
    "ExtremaKind",
    "PLATEAU_POLICY_VERSION",
]
