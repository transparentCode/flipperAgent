"""Typed dynamic evidence for confirmed-extrema pair candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Mapping

from ..configuration.provider import (
    COORDINATE_SYSTEM,
    EVIDENCE_SCHEMA_VERSION,
    PLATEAU_POLICY,
    PROVIDER_NAME,
    PROVIDER_VERSION,
)
from ..domain.candidates import LineCandidate
from ..domain.enums import LineRole
from ..domain.identity import deterministic_hash, require_hash
from ..domain.provider_input import ProviderInput
from ..domain.validation import ContractValidationError, require_integer


class ExtremaKind(str, Enum):
    HIGH = "high"
    LOW = "low"


_UTC = timezone.utc
_MICROSECOND_NS = 1_000


def _datetime_from_microsecond_ns(timestamp_ns: int) -> datetime:
    seconds, remainder_ns = divmod(timestamp_ns, 1_000_000_000)
    return datetime.fromtimestamp(seconds, tz=_UTC) + timedelta(
        microseconds=remainder_ns // _MICROSECOND_NS
    )


def confirmed_extrema_anchor_id(
    *,
    asset: str,
    timeframe: str,
    extrema_kind: ExtremaKind,
    source_timestamp: datetime,
    confirmation_timestamp: datetime,
    source_price: float,
) -> str:
    """Canonical confirmed-extrema anchor identity shared by build and audit."""

    return deterministic_hash(
        "trendline_v2_confirmed_extrema_anchor",
        {
            "asset": asset,
            "timeframe": timeframe,
            "extrema_kind": extrema_kind.value,
            "source_timestamp": source_timestamp,
            "confirmation_timestamp": confirmation_timestamp,
            "source_price": source_price,
            "provider_name": PROVIDER_NAME,
            "provider_version": PROVIDER_VERSION,
        },
    )


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

    def validate_candidate(
        self,
        candidate: LineCandidate,
        input_data: ProviderInput,
        *,
        right_confirmation_bars: int,
    ) -> None:
        """Bind provider-specific evidence to exact candidate and input facts."""

        self.validate_against(input_data)
        if not isinstance(candidate, LineCandidate):
            raise ContractValidationError("evidence requires LineCandidate")
        if self.candidate_id != candidate.candidate_id:
            raise ContractValidationError("evidence candidate ID must match candidate")
        if len(candidate.anchors) != 2:
            raise ContractValidationError("confirmed extrema evidence requires two anchors")
        expected_role = (
            LineRole.SUPPORT if self.extrema_kind is ExtremaKind.LOW else LineRole.RESISTANCE
        )
        if candidate.role is not expected_role:
            raise ContractValidationError("evidence extrema kind does not match candidate role")
        if any(timestamp % _MICROSECOND_NS for timestamp in input_data.timestamps):
            raise ContractValidationError(
                "confirmed extrema evidence requires microsecond-aligned timestamps"
            )
        right = require_integer(
            right_confirmation_bars,
            field_name="evidence.right_confirmation_bars",
            minimum=1,
        )
        if any(
            confirmation != source + right
            for source, confirmation in zip(
                self.anchor_source_positions, self.confirmation_positions
            )
        ):
            raise ContractValidationError(
                "evidence confirmation positions do not match configured right window"
            )

        source_prices = (
            input_data.low if self.extrema_kind is ExtremaKind.LOW else input_data.high
        )
        anchors = candidate.anchors
        for index, (anchor, source_position, confirmation_position) in enumerate(
            zip(anchors, self.anchor_source_positions, self.confirmation_positions)
        ):
            expected_pivot = _datetime_from_microsecond_ns(input_data.timestamps[source_position])
            expected_confirmation = _datetime_from_microsecond_ns(
                input_data.timestamps[confirmation_position]
            )
            if anchor.pivot_time != expected_pivot:
                raise ContractValidationError(
                    f"evidence source position does not match anchor {index} timestamp"
                )
            if anchor.confirmation_time != expected_confirmation:
                raise ContractValidationError(
                    f"evidence confirmation position does not match anchor {index} timestamp"
                )
            if anchor.price != source_prices[source_position]:
                raise ContractValidationError(
                    f"evidence source position does not match anchor {index} price"
                )
            expected_anchor_id = confirmed_extrema_anchor_id(
                asset=candidate.asset,
                timeframe=candidate.timeframe,
                extrema_kind=self.extrema_kind,
                source_timestamp=expected_pivot,
                confirmation_timestamp=expected_confirmation,
                source_price=source_prices[source_position],
            )
            if anchor.anchor_id != expected_anchor_id:
                raise ContractValidationError(
                    f"evidence source position does not match anchor {index} ID"
                )

        first, second = anchors
        if (
            candidate.geometry.start_time != first.pivot_time
            or candidate.geometry.end_time != second.pivot_time
            or candidate.geometry.start_price != first.price
            or candidate.geometry.end_price != second.price
        ):
            raise ContractValidationError(
                "confirmed extrema geometry must equal source extrema endpoints"
            )
        expected_intermediate_count = (
            self.anchor_source_positions[1] - self.anchor_source_positions[0] - 1
        )
        if self.validated_intermediate_count != expected_intermediate_count:
            raise ContractValidationError("evidence intermediate count does not match anchors")
        if self.body_violation_count != 0:
            raise ContractValidationError("successful evidence cannot contain body violations")

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


__all__ = [
    "ConfirmedExtremaPairEvidence",
    "ExtremaKind",
    "confirmed_extrema_anchor_id",
]
