"""Small provider boundary with explicit data and deterministic outcomes."""

from __future__ import annotations

from dataclasses import dataclass, is_dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from ..configuration.contracts import ResolvedTrendlineV2Config
from ..configuration.provider import ConfirmedExtremaPairConfig, ProviderConfig
from ..domain.candidates import LineCandidate
from ..domain.identity import deterministic_hash, provider_identity
from ..domain.provider_input import ProviderInput
from ..domain.validation import (
    ContractValidationError,
    require_integer,
    require_number,
    require_string,
)
from .provider_evidence import ConfirmedExtremaPairEvidence


class ProviderStatus(str, Enum):
    SUCCESS = "success"
    ABSTAINED = "abstained"
    FAILED = "failed"


class ProviderReason(str, Enum):
    INSUFFICIENT_INPUT = "insufficient_input"
    NO_CANDIDATES = "no_candidates"
    INVALID_INPUT = "invalid_input"
    CONFIGURATION_ERROR = "configuration_error"
    PROVIDER_FAILURE = "provider_failure"
    HYPOTHESIS_LIMIT_EXCEEDED = "hypothesis_limit_exceeded"
    OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"


_EXPECTED_STATUS_BY_REASON = {
    ProviderReason.INSUFFICIENT_INPUT: ProviderStatus.ABSTAINED,
    ProviderReason.NO_CANDIDATES: ProviderStatus.ABSTAINED,
    ProviderReason.INVALID_INPUT: ProviderStatus.ABSTAINED,
    ProviderReason.CONFIGURATION_ERROR: ProviderStatus.ABSTAINED,
    ProviderReason.PROVIDER_FAILURE: ProviderStatus.FAILED,
    ProviderReason.HYPOTHESIS_LIMIT_EXCEEDED: ProviderStatus.ABSTAINED,
    ProviderReason.OUTPUT_LIMIT_EXCEEDED: ProviderStatus.ABSTAINED,
}


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """Explicit immutable input/config boundary for one provider execution."""

    input_data: ProviderInput
    config: ResolvedTrendlineV2Config
    provider_config: ProviderConfig

    def __post_init__(self) -> None:
        if not isinstance(self.input_data, ProviderInput):
            raise ContractValidationError("provider_request.input_data must be ProviderInput")
        if not isinstance(self.config, ResolvedTrendlineV2Config):
            raise ContractValidationError(
                "provider_request.config must be ResolvedTrendlineV2Config"
            )
        provider_params = getattr(self.provider_config, "__dataclass_params__", None)
        if (
            not isinstance(self.provider_config, ProviderConfig)
            or not is_dataclass(self.provider_config)
            or provider_params is None
            or not provider_params.frozen
        ):
            raise ContractValidationError(
                "provider_request.provider_config must be an immutable typed ProviderConfig"
            )

    @property
    def asset(self) -> str:
        return self.input_data.asset

    @property
    def timeframe(self) -> str:
        return self.input_data.timeframe

    @property
    def observed_at(self):
        return self.input_data.observed_at

    @property
    def confirmed_through(self):
        return self.input_data.confirmed_through

    @property
    def input_identity(self) -> str:
        return self.input_data.input_identity

    @property
    def config_identity(self) -> str:
        return deterministic_hash(
            "trendline_v2_combined_configuration",
            {
                "foundation_config_identity": self.config.semantic_hash,
                "provider_config_identity": self.provider_config.semantic_hash,
            },
        )

    @property
    def provider_config_identity(self) -> str:
        return self.provider_config.semantic_hash

    @property
    def request_identity(self) -> str:
        return deterministic_hash(
            "trendline_v2_provider_request",
            {"input_identity": self.input_identity, "config_identity": self.config_identity},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_data": self.input_data.to_dict(),
            "config": self.config.to_dict(),
            "input_identity": self.input_identity,
            "config_identity": self.config_identity,
            "provider_config": self.provider_config.to_dict(),
            "provider_config_identity": self.provider_config_identity,
            "request_identity": self.request_identity,
        }


@dataclass(frozen=True, slots=True)
class ProviderDiagnostics:
    candidate_count: int
    input_row_count: int
    elapsed_ms: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_count",
            require_integer(self.candidate_count, field_name="diagnostics.candidate_count"),
        )
        object.__setattr__(
            self,
            "input_row_count",
            require_integer(
                self.input_row_count, field_name="diagnostics.input_row_count", minimum=1
            ),
        )
        if self.elapsed_ms is not None:
            object.__setattr__(
                self,
                "elapsed_ms",
                require_number(
                    self.elapsed_ms, field_name="diagnostics.elapsed_ms", minimum=0.0
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": self.candidate_count,
            "input_row_count": self.input_row_count,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True, slots=True)
class ProviderResult:
    provider_name: str
    provider_version: str
    request: ProviderRequest
    status: ProviderStatus | str
    candidates: tuple[LineCandidate, ...]
    diagnostics: ProviderDiagnostics
    reason: ProviderReason | str | None = None
    detail: str | None = None
    evidence: tuple[ConfirmedExtremaPairEvidence, ...] = ()

    def __post_init__(self) -> None:
        name = require_string(self.provider_name, field_name="provider_result.provider_name")
        version = require_string(
            self.provider_version, field_name="provider_result.provider_version"
        )
        if not isinstance(self.request, ProviderRequest):
            raise ContractValidationError("provider request must be ProviderRequest")
        try:
            status = ProviderStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("invalid provider status") from exc
        if not isinstance(self.diagnostics, ProviderDiagnostics):
            raise ContractValidationError("provider diagnostics must be ProviderDiagnostics")
        if (
            self.request.provider_config.provider_name != name
            or self.request.provider_config.provider_version != version
        ):
            raise ContractValidationError(
                "provider result identity must match request provider config"
            )
        candidates = tuple(self.candidates)
        if any(not isinstance(candidate, LineCandidate) for candidate in candidates):
            raise ContractValidationError("provider candidates must be LineCandidate values")
        candidate_ids = tuple(candidate.candidate_id for candidate in candidates)
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ContractValidationError("provider candidate IDs must be unique")
        if any(
            candidate.provider_name != name
            or candidate.provider_version != version
            or candidate.asset != self.request.asset
            or candidate.timeframe != self.request.timeframe
            or candidate.observed_at != self.request.observed_at
            for candidate in candidates
        ):
            raise ContractValidationError("candidate provenance or request identity mismatch")
        try:
            evidence = tuple(self.evidence)
        except TypeError as exc:
            raise ContractValidationError("provider evidence must be a sequence") from exc
        if any(not isinstance(item, ConfirmedExtremaPairEvidence) for item in evidence):
            raise ContractValidationError(
                "provider evidence must be ConfirmedExtremaPairEvidence values"
            )
        evidence_candidate_ids = tuple(item.candidate_id for item in evidence)
        if len(set(evidence_candidate_ids)) != len(evidence_candidate_ids):
            raise ContractValidationError("provider evidence candidate IDs must be unique")
        if len({item.evidence_id for item in evidence}) != len(evidence):
            raise ContractValidationError("provider evidence IDs must be unique")
        if evidence_candidate_ids != candidate_ids:
            if set(evidence_candidate_ids) != set(candidate_ids):
                raise ContractValidationError(
                    "provider evidence candidate IDs must match candidates"
                )
            raise ContractValidationError("provider evidence order must match candidate order")
        expected_schema = self.request.provider_config.provider_evidence_schema_version
        if any(item.schema_version != expected_schema for item in evidence):
            raise ContractValidationError(
                "provider evidence schema version must match request configuration"
            )
        if evidence and not isinstance(
            self.request.provider_config, ConfirmedExtremaPairConfig
        ):
            raise ContractValidationError(
                "confirmed extrema evidence requires ConfirmedExtremaPairConfig"
            )
        for candidate, item in zip(candidates, evidence):
            item.validate_candidate(
                candidate,
                self.request.input_data,
                right_confirmation_bars=self.request.provider_config.right_confirmation_bars,
            )
        reason = None
        if self.reason is not None:
            try:
                reason = ProviderReason(self.reason)
            except (TypeError, ValueError) as exc:
                raise ContractValidationError("invalid provider reason") from exc
        detail = (
            require_string(self.detail, field_name="provider_result.detail")
            if self.detail is not None
            else None
        )
        if status is ProviderStatus.SUCCESS and (not candidates or reason is not None):
            raise ContractValidationError(
                "successful provider result requires candidates and no reason"
            )
        if status is ProviderStatus.SUCCESS and len(evidence) != len(candidates):
            raise ContractValidationError(
                "successful provider result requires one evidence item per candidate"
            )
        if status is not ProviderStatus.SUCCESS and (candidates or evidence or reason is None):
            raise ContractValidationError(
                "non-success provider result requires reason, no candidates, and no evidence"
            )
        if reason is not None and _EXPECTED_STATUS_BY_REASON[reason] is not status:
            raise ContractValidationError(
                f"provider reason {reason.value} is incompatible with status {status.value}"
            )
        if self.diagnostics.candidate_count != len(candidates):
            raise ContractValidationError("provider candidate diagnostic count mismatch")
        if self.diagnostics.input_row_count != self.request.input_data.row_count:
            raise ContractValidationError("provider input diagnostic count mismatch")
        object.__setattr__(self, "provider_name", name)
        object.__setattr__(self, "provider_version", version)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "detail", detail)
        object.__setattr__(self, "evidence", evidence)

    @property
    def provider_identity(self) -> str:
        return provider_identity(self.provider_name, self.provider_version)

    @property
    def provider_contract_identity(self) -> str:
        return deterministic_hash(
            "trendline_v2_provider_result_contract",
            {
                "provider_identity": self.provider_identity,
                "provider_config_identity": self.request.provider_config_identity,
                "provider_evidence_schema_version": self.request.provider_config.provider_evidence_schema_version,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "provider_version": self.provider_version,
            "provider_identity": self.provider_identity,
            "provider_contract_identity": self.provider_contract_identity,
            "request": self.request.to_dict(),
            "status": self.status.value,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "evidence": [item.to_dict() for item in self.evidence],
            "diagnostics": self.diagnostics.to_dict(),
            "reason": self.reason.value if self.reason is not None else None,
            "detail": self.detail,
        }


@runtime_checkable
class CandidateProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def provider_version(self) -> str: ...

    def generate(self, request: ProviderRequest) -> ProviderResult: ...


__all__ = [
    "CandidateProvider",
    "ProviderDiagnostics",
    "ProviderInput",
    "ProviderReason",
    "ProviderRequest",
    "ProviderResult",
    "ProviderStatus",
]
