"""Active configuration and fixed semantics for extrema-pair provider v1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..domain.identity import deterministic_hash
from ..domain.validation import (
    ContractValidationError,
    require_integer,
    require_number,
)


# Provider-v1 semantics. Changing any value requires a new provider version.
PROVIDER_NAME = "confirmed_extrema_pair"
PROVIDER_VERSION = "v1"
PLATEAU_POLICY = "leftmost_strict_left_nonstrict_right_v1"
HISTORY_POLICY = "lookback_duration_seconds_v1"
BODY_VALIDATION_POLICY = "exact_side_v1"
PAIR_ORDER = "chronological_v1"
EVIDENCE_SCHEMA_VERSION = "v1"
COORDINATE_SYSTEM = "elapsed_utc_seconds_v1"


@runtime_checkable
class ProviderConfig(Protocol):
    """Explicit immutable semantic configuration supplied to one provider."""

    @property
    def provider_name(self) -> str: ...

    @property
    def provider_version(self) -> str: ...

    @property
    def provider_evidence_schema_version(self) -> str: ...

    @property
    def semantic_payload(self) -> dict[str, Any]: ...

    @property
    def semantic_hash(self) -> str: ...

    @property
    def provider_contract_identity(self) -> str: ...

    def to_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ConfirmedExtremaPairConfig:
    """Only execution-varying values for confirmed-extrema pair v1."""

    lookback_duration_seconds: float
    left_confirmation_bars: int
    right_confirmation_bars: int
    min_extrema_per_role: int
    max_hypotheses: int
    max_output_candidates: int

    def __post_init__(self) -> None:
        duration = require_number(
            self.lookback_duration_seconds,
            field_name="provider.lookback_duration_seconds",
            minimum=0.0,
        )
        if duration <= 0.0:
            raise ContractValidationError(
                "provider.lookback_duration_seconds must be positive"
            )
        object.__setattr__(self, "lookback_duration_seconds", duration)
        for field_name, minimum in (
            ("left_confirmation_bars", 1),
            ("right_confirmation_bars", 1),
            ("min_extrema_per_role", 2),
            ("max_hypotheses", 1),
            ("max_output_candidates", 1),
        ):
            object.__setattr__(
                self,
                field_name,
                require_integer(
                    getattr(self, field_name),
                    field_name=f"provider.{field_name}",
                    minimum=minimum,
                ),
            )

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    @property
    def provider_version(self) -> str:
        return PROVIDER_VERSION

    @property
    def provider_evidence_schema_version(self) -> str:
        return EVIDENCE_SCHEMA_VERSION

    @property
    def semantic_payload(self) -> dict[str, Any]:
        return {
            "provider": {
                "name": PROVIDER_NAME,
                "version": PROVIDER_VERSION,
                "plateau_policy": PLATEAU_POLICY,
                "history_policy": HISTORY_POLICY,
                "body_validation_policy": BODY_VALIDATION_POLICY,
                "pair_order": PAIR_ORDER,
                "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
                "coordinate_system": COORDINATE_SYSTEM,
            },
            "active_config": {
                "lookback_duration_seconds": self.lookback_duration_seconds,
                "left_confirmation_bars": self.left_confirmation_bars,
                "right_confirmation_bars": self.right_confirmation_bars,
                "min_extrema_per_role": self.min_extrema_per_role,
                "max_hypotheses": self.max_hypotheses,
                "max_output_candidates": self.max_output_candidates,
            },
        }

    @property
    def semantic_hash(self) -> str:
        return deterministic_hash("trendline_v2_provider_configuration", self.semantic_payload)

    @property
    def provider_contract_identity(self) -> str:
        return deterministic_hash("trendline_v2_provider_contract", self.semantic_payload["provider"])

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.semantic_payload,
            "semantic_hash": self.semantic_hash,
            "provider_contract_identity": self.provider_contract_identity,
        }


__all__ = [
    "BODY_VALIDATION_POLICY",
    "COORDINATE_SYSTEM",
    "ConfirmedExtremaPairConfig",
    "EVIDENCE_SCHEMA_VERSION",
    "HISTORY_POLICY",
    "PAIR_ORDER",
    "PLATEAU_POLICY",
    "PROVIDER_NAME",
    "PROVIDER_VERSION",
    "ProviderConfig",
]
