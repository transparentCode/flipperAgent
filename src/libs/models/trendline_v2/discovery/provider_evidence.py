"""Typed dynamic evidence for confirmed-extrema pair candidates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from ..configuration.provider import (
    COORDINATE_SYSTEM,
    EVIDENCE_SCHEMA_VERSION,
    PLATEAU_POLICY,
)
from ..domain.identity import deterministic_hash, require_hash
from ..domain.provider_input import ProviderInput
from ..domain.validation import ContractValidationError, require_integer


class ExtremaKind(str, Enum):
    HIGH = "high"
    LOW = "low"


def _positions(value: Any, *, field_name: str) -> tuple[int, int]:
    if isinstance(value, (str, bytes)):
        raise ContractValidationError(f"{field_name} must contain exactly two positions")
    try:
        values = tuple(value)
    except TypeError as exc:
        raise ContractValidationError(
            f"{field_name} must contain exactly two positions"
        ) from exc
    if len(values) != 2:
        raise ContractValidationError(f"{field_name} must contain exactly two positions")
    first = require_integer(values[0], field_name=f"{field_name}[0]")
    second = require_integer(values[1], field_name=f"{field_name}[1]")
    if first >= second:
        raise ContractValidationError(f"{field_name} must be strictly ordered")
    return first, second


@dataclass(frozen=True, slots=True)
class ConfirmedExtremaPairEvidence:
    """Immutable per-candidate evidence. Fixed semantics are code-owned."""

    candidate_id: str
    extrema_kind: ExtremaKind | str
    anchor_source_positions: tuple[int, int]
    confirmation_positions: tuple[int, int]
    validated_intermediate_count: int
    body_violation_count: int

    def __post_init__(self) -> None:
        candidate_id = require_hash(self.candidate_id, field_name="evidence.candidate_id")
        try:
            kind = ExtremaKind(self.extrema_kind)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("invalid evidence.extrema_kind") from exc
        anchors = _positions(
            self.anchor_source_positions, field_name="evidence.anchor_source_positions"
        )
        confirmations = _positions(
            self.confirmation_positions, field_name="evidence.confirmation_positions"
        )
        if any(confirmation <= anchor for anchor, confirmation in zip(anchors, confirmations)):
            raise ContractValidationError(
                "evidence confirmation positions cannot precede source positions"
            )
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "extrema_kind", kind)
        object.__setattr__(self, "anchor_source_positions", anchors)
        object.__setattr__(self, "confirmation_positions", confirmations)
        object.__setattr__(
            self,
            "validated_intermediate_count",
            require_integer(
                self.validated_intermediate_count,
                field_name="evidence.validated_intermediate_count",
            ),
        )
        object.__setattr__(
            self,
            "body_violation_count",
            require_integer(
                self.body_violation_count,
                field_name="evidence.body_violation_count",
            ),
        )

    @property
    def coordinate_system_version(self) -> str:
        return COORDINATE_SYSTEM

    @property
    def plateau_policy_version(self) -> str:
        return PLATEAU_POLICY

    @property
    def schema_version(self) -> str:
        return EVIDENCE_SCHEMA_VERSION

    @property
    def evidence_id(self) -> str:
        return deterministic_hash("trendline_v2_provider_evidence", self._payload())

    def _payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "extrema_kind": self.extrema_kind.value,
            "anchor_source_positions": self.anchor_source_positions,
            "confirmation_positions": self.confirmation_positions,
            "validated_intermediate_count": self.validated_intermediate_count,
            "body_violation_count": self.body_violation_count,
            "coordinate_system_version": self.coordinate_system_version,
            "plateau_policy_version": self.plateau_policy_version,
            "schema_version": self.schema_version,
        }

    def validate_against(self, input_data: ProviderInput) -> None:
        if not isinstance(input_data, ProviderInput):
            raise ContractValidationError("evidence requires ProviderInput")
        for field_name, positions in (
            ("anchor_source_positions", self.anchor_source_positions),
            ("confirmation_positions", self.confirmation_positions),
        ):
            if any(position >= input_data.row_count for position in positions):
                raise ContractValidationError(
                    f"evidence {field_name} contains a future or missing position"
                )
        for anchor, confirmation in zip(
            self.anchor_source_positions, self.confirmation_positions
        ):
            if input_data.timestamps[confirmation] < input_data.timestamps[anchor]:
                raise ContractValidationError(
                    "evidence confirmation timestamp precedes source timestamp"
                )

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "evidence_id": self.evidence_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConfirmedExtremaPairEvidence":
        if not isinstance(value, Mapping):
            raise ContractValidationError("provider evidence payload must be a mapping")
        expected = {
            "candidate_id",
            "extrema_kind",
            "anchor_source_positions",
            "confirmation_positions",
            "validated_intermediate_count",
            "body_violation_count",
            "coordinate_system_version",
            "plateau_policy_version",
            "schema_version",
            "evidence_id",
        }
        if set(value) != expected:
            raise ContractValidationError("provider evidence payload keys mismatch")
        if (
            value["coordinate_system_version"] != COORDINATE_SYSTEM
            or value["plateau_policy_version"] != PLATEAU_POLICY
            or value["schema_version"] != EVIDENCE_SCHEMA_VERSION
        ):
            raise ContractValidationError("provider evidence fixed semantics mismatch")
        try:
            result = cls(
                candidate_id=value["candidate_id"],
                extrema_kind=value["extrema_kind"],
                anchor_source_positions=tuple(value["anchor_source_positions"]),
                confirmation_positions=tuple(value["confirmation_positions"]),
                validated_intermediate_count=value["validated_intermediate_count"],
                body_violation_count=value["body_violation_count"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid provider evidence payload") from exc
        if value["evidence_id"] != result.evidence_id:
            raise ContractValidationError("provider evidence ID does not match content")
        return result


__all__ = ["ConfirmedExtremaPairEvidence", "ExtremaKind"]
