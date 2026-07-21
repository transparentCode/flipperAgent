"""Typed evidence contract for confirmed-extrema pair candidates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from ..domain.identity import deterministic_hash, require_hash
from ..domain.provider_input import ProviderInput
from ..domain.validation import (
    ContractValidationError,
    primitive,
    require_integer,
    require_string,
)


class ExtremaKind(str, Enum):
    HIGH = "high"
    LOW = "low"


COORDINATE_SYSTEM_VERSION = "elapsed_utc_seconds_v1"
PLATEAU_POLICY_VERSION = "leftmost_strict_left_nonstrict_right_v1"
EVIDENCE_SCHEMA_VERSION = "v1"


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
    result = tuple(
        require_integer(item, field_name=f"{field_name}[{index}]")
        for index, item in enumerate(values)
    )
    if result[0] >= result[1]:
        raise ContractValidationError(f"{field_name} must be strictly ordered")
    return result  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class ConfirmedExtremaPairEvidence:
    """Immutable provider-specific evidence, separate from universal evidence."""

    candidate_id: str
    extrema_kind: ExtremaKind | str
    anchor_source_positions: tuple[int, int]
    confirmation_positions: tuple[int, int]
    validated_intermediate_count: int
    body_violation_count: int
    coordinate_system_version: str
    plateau_policy_version: str
    schema_version: str

    def __post_init__(self) -> None:
        candidate_id = require_hash(self.candidate_id, field_name="evidence.candidate_id")
        try:
            extrema_kind = ExtremaKind(self.extrema_kind)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("invalid evidence.extrema_kind") from exc
        anchors = _positions(
            self.anchor_source_positions, field_name="evidence.anchor_source_positions"
        )
        confirmations = _positions(
            self.confirmation_positions, field_name="evidence.confirmation_positions"
        )
        if any(
            confirmation <= anchor
            for anchor, confirmation in zip(anchors, confirmations)
        ):
            raise ContractValidationError(
                "evidence confirmation positions cannot precede source positions"
            )
        validated = require_integer(
            self.validated_intermediate_count,
            field_name="evidence.validated_intermediate_count",
        )
        violations = require_integer(
            self.body_violation_count,
            field_name="evidence.body_violation_count",
        )
        coordinate = require_string(
            self.coordinate_system_version,
            field_name="evidence.coordinate_system_version",
        )
        plateau = require_string(
            self.plateau_policy_version,
            field_name="evidence.plateau_policy_version",
        )
        schema = require_string(self.schema_version, field_name="evidence.schema_version")
        if coordinate != COORDINATE_SYSTEM_VERSION:
            raise ContractValidationError("unsupported evidence coordinate system")
        if plateau != PLATEAU_POLICY_VERSION:
            raise ContractValidationError("unsupported evidence plateau policy")
        if schema != EVIDENCE_SCHEMA_VERSION:
            raise ContractValidationError("unsupported evidence schema version")
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "extrema_kind", extrema_kind)
        object.__setattr__(self, "anchor_source_positions", anchors)
        object.__setattr__(self, "confirmation_positions", confirmations)
        object.__setattr__(self, "validated_intermediate_count", validated)
        object.__setattr__(self, "body_violation_count", violations)
        object.__setattr__(self, "coordinate_system_version", coordinate)
        object.__setattr__(self, "plateau_policy_version", plateau)
        object.__setattr__(self, "schema_version", schema)

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
        """Validate source/confirmation positions against one causal input."""

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
        if input_data.timestamps[-1] > int(input_data.confirmed_through.timestamp() * 1_000_000_000):
            raise ContractValidationError("evidence input contains future timestamps")

    def to_dict(self) -> dict[str, Any]:
        return {**primitive(self), "evidence_id": self.evidence_id}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ConfirmedExtremaPairEvidence":
        if not isinstance(value, Mapping):
            raise ContractValidationError("provider evidence payload must be a mapping")
        expected = {
            "evidence_id",
            "candidate_id",
            "extrema_kind",
            "anchor_source_positions",
            "confirmation_positions",
            "validated_intermediate_count",
            "body_violation_count",
            "coordinate_system_version",
            "plateau_policy_version",
            "schema_version",
        }
        if set(value) != expected:
            raise ContractValidationError("provider evidence payload keys mismatch")
        try:
            result = cls(
                candidate_id=value["candidate_id"],
                extrema_kind=value["extrema_kind"],
                anchor_source_positions=tuple(value["anchor_source_positions"]),
                confirmation_positions=tuple(value["confirmation_positions"]),
                validated_intermediate_count=value["validated_intermediate_count"],
                body_violation_count=value["body_violation_count"],
                coordinate_system_version=value["coordinate_system_version"],
                plateau_policy_version=value["plateau_policy_version"],
                schema_version=value["schema_version"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid provider evidence payload") from exc
        if value["evidence_id"] != result.evidence_id:
            raise ContractValidationError("provider evidence ID does not match content")
        return result


__all__ = [
    "COORDINATE_SYSTEM_VERSION",
    "ConfirmedExtremaPairEvidence",
    "EVIDENCE_SCHEMA_VERSION",
    "ExtremaKind",
    "PLATEAU_POLICY_VERSION",
]
