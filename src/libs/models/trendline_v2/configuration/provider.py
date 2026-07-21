"""Typed provider-specific configuration contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from ..domain.identity import deterministic_hash
from ..domain.validation import (
    ContractValidationError,
    primitive,
    require_integer,
    require_number,
    require_string,
)


class PlateauPolicy(str, Enum):
    LEFTMOST_STRICT_LEFT_NONSTRICT_RIGHT_V1 = (
        "leftmost_strict_left_nonstrict_right_v1"
    )


class HistoryHorizon(str, Enum):
    LOOKBACK_DURATION_SECONDS_V1 = "lookback_duration_seconds_v1"


class BodyValidationPolicy(str, Enum):
    EXACT_SIDE_V1 = "exact_side_v1"


class PairEnumerationOrder(str, Enum):
    CHRONOLOGICAL_V1 = "chronological_v1"


@runtime_checkable
class ProviderConfig(Protocol):
    """Explicit immutable semantic configuration supplied to a provider."""

    provider_name: str
    provider_version: str
    provider_evidence_schema_version: str

    @property
    def semantic_payload(self) -> dict[str, Any]: ...

    @property
    def semantic_hash(self) -> str: ...

    @property
    def provider_contract_identity(self) -> str: ...

    def to_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ConfirmedExtremaPairConfig:
    """Fully explicit v1 contract for confirmed-extrema pair discovery.

    No field has a Python default. Values are fixture/request inputs until a
    later scope study authorizes canonical configuration.
    """

    provider_name: str
    provider_version: str
    plateau_policy: PlateauPolicy | str
    history_horizon: HistoryHorizon | str
    lookback_duration_seconds: float
    left_confirmation_bars: int
    right_confirmation_bars: int
    min_extrema_per_role: int
    body_validation_policy: BodyValidationPolicy | str
    pair_enumeration_order: PairEnumerationOrder | str
    candidate_order_version: str
    structural_validation_version: str
    max_hypotheses: int
    max_output_candidates: int
    provider_evidence_schema_version: str

    def __post_init__(self) -> None:
        provider_name = require_string(self.provider_name, field_name="provider.name")
        provider_version = require_string(
            self.provider_version, field_name="provider.version"
        )
        if provider_name != "confirmed_extrema_pair":
            raise ContractValidationError("provider.name must be confirmed_extrema_pair")
        if provider_version != "v1":
            raise ContractValidationError("provider.version must be v1")

        def _enum(value: Enum | str, enum_type: type[Enum], field_name: str) -> Enum:
            try:
                return enum_type(value)
            except (TypeError, ValueError) as exc:
                raise ContractValidationError(f"invalid {field_name}") from exc

        plateau_policy = _enum(
            self.plateau_policy, PlateauPolicy, "provider.plateau_policy"
        )
        history_horizon = _enum(
            self.history_horizon, HistoryHorizon, "provider.history_horizon"
        )
        body_validation_policy = _enum(
            self.body_validation_policy,
            BodyValidationPolicy,
            "provider.body_validation_policy",
        )
        pair_enumeration_order = _enum(
            self.pair_enumeration_order,
            PairEnumerationOrder,
            "provider.pair_enumeration_order",
        )
        lookback_duration_seconds = require_number(
            self.lookback_duration_seconds,
            field_name="provider.lookback_duration_seconds",
            minimum=0.0,
        )
        if lookback_duration_seconds <= 0.0:
            raise ContractValidationError(
                "provider.lookback_duration_seconds must be positive"
            )
        left_confirmation_bars = require_integer(
            self.left_confirmation_bars,
            field_name="provider.left_confirmation_bars",
            minimum=1,
        )
        right_confirmation_bars = require_integer(
            self.right_confirmation_bars,
            field_name="provider.right_confirmation_bars",
            minimum=1,
        )
        min_extrema_per_role = require_integer(
            self.min_extrema_per_role,
            field_name="provider.min_extrema_per_role",
            minimum=2,
        )
        candidate_order_version = require_string(
            self.candidate_order_version,
            field_name="provider.candidate_order_version",
        )
        structural_validation_version = require_string(
            self.structural_validation_version,
            field_name="provider.structural_validation_version",
        )
        max_hypotheses = require_integer(
            self.max_hypotheses, field_name="provider.max_hypotheses", minimum=1
        )
        max_output_candidates = require_integer(
            self.max_output_candidates,
            field_name="provider.max_output_candidates",
            minimum=1,
        )
        evidence_schema = require_string(
            self.provider_evidence_schema_version,
            field_name="provider.provider_evidence_schema_version",
        )

        object.__setattr__(self, "provider_name", provider_name)
        object.__setattr__(self, "provider_version", provider_version)
        object.__setattr__(self, "plateau_policy", plateau_policy)
        object.__setattr__(self, "history_horizon", history_horizon)
        object.__setattr__(self, "lookback_duration_seconds", lookback_duration_seconds)
        object.__setattr__(self, "left_confirmation_bars", left_confirmation_bars)
        object.__setattr__(self, "right_confirmation_bars", right_confirmation_bars)
        object.__setattr__(self, "min_extrema_per_role", min_extrema_per_role)
        object.__setattr__(self, "body_validation_policy", body_validation_policy)
        object.__setattr__(self, "pair_enumeration_order", pair_enumeration_order)
        object.__setattr__(self, "candidate_order_version", candidate_order_version)
        object.__setattr__(
            self, "structural_validation_version", structural_validation_version
        )
        object.__setattr__(self, "max_hypotheses", max_hypotheses)
        object.__setattr__(self, "max_output_candidates", max_output_candidates)
        object.__setattr__(self, "provider_evidence_schema_version", evidence_schema)

    @property
    def semantic_payload(self) -> dict[str, Any]:
        return {
            "provider": {
                "name": self.provider_name,
                "version": self.provider_version,
                "plateau_policy": self.plateau_policy.value,
                "history_horizon": self.history_horizon.value,
                "lookback_duration_seconds": self.lookback_duration_seconds,
                "left_confirmation_bars": self.left_confirmation_bars,
                "right_confirmation_bars": self.right_confirmation_bars,
                "min_extrema_per_role": self.min_extrema_per_role,
                "body_validation_policy": self.body_validation_policy.value,
                "pair_enumeration_order": self.pair_enumeration_order.value,
                "candidate_order_version": self.candidate_order_version,
                "structural_validation_version": self.structural_validation_version,
                "max_hypotheses": self.max_hypotheses,
                "max_output_candidates": self.max_output_candidates,
                "provider_evidence_schema_version": self.provider_evidence_schema_version,
            }
        }

    @property
    def semantic_hash(self) -> str:
        return deterministic_hash("trendline_v2_provider_configuration", self.semantic_payload)

    @property
    def provider_contract_identity(self) -> str:
        return deterministic_hash(
            "trendline_v2_provider_contract",
            {
                "provider_name": self.provider_name,
                "provider_version": self.provider_version,
                "provider_evidence_schema_version": self.provider_evidence_schema_version,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            **primitive(self),
            "semantic_hash": self.semantic_hash,
            "provider_contract_identity": self.provider_contract_identity,
        }


__all__ = [
    "BodyValidationPolicy",
    "ConfirmedExtremaPairConfig",
    "HistoryHorizon",
    "PairEnumerationOrder",
    "PlateauPolicy",
    "ProviderConfig",
]
