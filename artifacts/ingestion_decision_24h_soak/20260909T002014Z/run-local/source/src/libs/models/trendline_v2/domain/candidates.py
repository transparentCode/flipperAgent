"""Immutable candidate and anchor contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .enums import LineRole
from .geometry import LineGeometry
from .identity import deterministic_hash, require_hash
from .validation import (
    ContractValidationError,
    parse_utc_isoformat,
    primitive,
    require_integer,
    require_number,
    require_string,
    require_utc,
)


@dataclass(frozen=True, slots=True)
class AnchorRef:
    anchor_id: str
    pivot_time: datetime
    confirmation_time: datetime
    price: float

    def __post_init__(self) -> None:
        anchor_id = require_string(self.anchor_id, field_name="anchor_id")
        pivot = require_utc(self.pivot_time, field_name="anchor.pivot_time")
        confirmation = require_utc(
            self.confirmation_time, field_name="anchor.confirmation_time"
        )
        if confirmation < pivot:
            raise ContractValidationError(
                "anchor.confirmation_time cannot precede anchor.pivot_time"
            )
        object.__setattr__(self, "anchor_id", anchor_id)
        object.__setattr__(self, "pivot_time", pivot)
        object.__setattr__(self, "confirmation_time", confirmation)
        object.__setattr__(
            self, "price", require_number(self.price, field_name="anchor.price")
        )

    def to_dict(self) -> dict[str, Any]:
        return primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnchorRef":
        if not isinstance(value, Mapping):
            raise ContractValidationError("anchor payload must be a mapping")
        if set(value) != {"anchor_id", "pivot_time", "confirmation_time", "price"}:
            raise ContractValidationError("anchor payload keys mismatch")
        try:
            return cls(
                anchor_id=value["anchor_id"],
                pivot_time=parse_utc_isoformat(value["pivot_time"], field_name="anchor.pivot_time"),
                confirmation_time=parse_utc_isoformat(value["confirmation_time"], field_name="anchor.confirmation_time"),
                price=value["price"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid anchor payload") from exc


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    anchor_count: int
    distinct_anchor_timestamps: int
    anchor_span_seconds: float

    def __post_init__(self) -> None:
        anchor_count = require_integer(
            self.anchor_count, field_name="evidence.anchor_count", minimum=2
        )
        distinct = require_integer(
            self.distinct_anchor_timestamps,
            field_name="evidence.distinct_anchor_timestamps",
            minimum=2,
        )
        if distinct > anchor_count:
            raise ContractValidationError(
                "distinct anchor timestamps cannot exceed anchor count"
            )
        span = require_number(
            self.anchor_span_seconds,
            field_name="evidence.anchor_span_seconds",
            minimum=0.0,
        )
        if span <= 0.0:
            raise ContractValidationError("anchor span must be positive")
        object.__setattr__(self, "anchor_count", anchor_count)
        object.__setattr__(self, "distinct_anchor_timestamps", distinct)
        object.__setattr__(self, "anchor_span_seconds", span)

    def to_dict(self) -> dict[str, Any]:
        return primitive(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CandidateEvidence":
        if not isinstance(value, Mapping):
            raise ContractValidationError("evidence payload must be a mapping")
        if set(value) != {
            "anchor_count",
            "distinct_anchor_timestamps",
            "anchor_span_seconds",
        }:
            raise ContractValidationError("evidence payload keys mismatch")
        try:
            return cls(**value)
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid evidence payload") from exc


@dataclass(frozen=True, slots=True)
class LineCandidate:
    asset: str
    timeframe: str
    candidate_id: str
    role: LineRole | str
    geometry: LineGeometry
    anchors: tuple[AnchorRef, ...]
    evidence: CandidateEvidence
    observed_at: datetime
    provider_name: str
    provider_version: str

    def __post_init__(self) -> None:
        asset = require_string(self.asset, field_name="candidate.asset")
        timeframe = require_string(self.timeframe, field_name="candidate.timeframe")
        candidate_id = require_hash(self.candidate_id, field_name="candidate_id")
        try:
            role = LineRole(self.role)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(f"invalid line role: {self.role!r}") from exc
        if not isinstance(self.geometry, LineGeometry):
            raise ContractValidationError("candidate.geometry must be LineGeometry")
        if not isinstance(self.evidence, CandidateEvidence):
            raise ContractValidationError("candidate.evidence must be CandidateEvidence")
        anchors = tuple(self.anchors)
        if len(anchors) < 2 or any(not isinstance(anchor, AnchorRef) for anchor in anchors):
            raise ContractValidationError("candidate requires at least two AnchorRef values")
        if len({anchor.anchor_id for anchor in anchors}) != len(anchors):
            raise ContractValidationError("candidate anchor IDs must be unique")
        if tuple(sorted(anchors, key=lambda anchor: anchor.pivot_time)) != anchors:
            raise ContractValidationError("candidate anchors must be pivot-time ordered")
        observed = require_utc(self.observed_at, field_name="candidate.observed_at")
        if any(anchor.confirmation_time > observed for anchor in anchors):
            raise ContractValidationError("candidate contains an unconfirmed anchor")
        if self.evidence.anchor_count != len(anchors):
            raise ContractValidationError("evidence.anchor_count must match anchors")
        if self.evidence.distinct_anchor_timestamps != len({anchor.pivot_time for anchor in anchors}):
            raise ContractValidationError("evidence distinct timestamp count mismatch")
        expected_span = (anchors[-1].pivot_time - anchors[0].pivot_time).total_seconds()
        if abs(self.evidence.anchor_span_seconds - expected_span) > 1e-9:
            raise ContractValidationError("evidence anchor span mismatch")
        provider_name = require_string(self.provider_name, field_name="provider_name")
        provider_version = require_string(
            self.provider_version, field_name="provider_version"
        )
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "anchors", anchors)
        object.__setattr__(self, "observed_at", observed)
        object.__setattr__(self, "provider_name", provider_name)
        object.__setattr__(self, "provider_version", provider_version)
        if self.expected_candidate_id != candidate_id:
            raise ContractValidationError("candidate_id does not match canonical content")

    @property
    def expected_candidate_id(self) -> str:
        return deterministic_hash("trendline_v2_candidate", self._identity_payload())

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "role": self.role.value if isinstance(self.role, LineRole) else self.role,
            "geometry": self.geometry.to_dict(),
            "anchors": [anchor.to_dict() for anchor in self.anchors],
            "evidence": self.evidence.to_dict(),
            "observed_at": self.observed_at,
            "provider_name": self.provider_name,
            "provider_version": self.provider_version,
        }

    @classmethod
    def create(
        cls,
        *,
        asset: str,
        timeframe: str,
        role: LineRole | str,
        geometry: LineGeometry,
        anchors: tuple[AnchorRef, ...],
        evidence: CandidateEvidence,
        observed_at: datetime,
        provider_name: str,
        provider_version: str,
    ) -> "LineCandidate":
        if not isinstance(geometry, LineGeometry):
            raise ContractValidationError("candidate.geometry must be LineGeometry")
        if not isinstance(evidence, CandidateEvidence):
            raise ContractValidationError("candidate.evidence must be CandidateEvidence")
        anchors = tuple(anchors)
        if any(not isinstance(anchor, AnchorRef) for anchor in anchors):
            raise ContractValidationError("candidate anchors must be AnchorRef values")
        try:
            role_value = LineRole(role).value
        except (TypeError, ValueError) as exc:
            raise ContractValidationError(f"invalid line role: {role!r}") from exc
        payload = {
            "asset": require_string(asset, field_name="candidate.asset"),
            "timeframe": require_string(timeframe, field_name="candidate.timeframe"),
            "role": role_value,
            "geometry": geometry.to_dict(),
            "anchors": [anchor.to_dict() for anchor in anchors],
            "evidence": evidence.to_dict(),
            "observed_at": require_utc(observed_at),
            "provider_name": provider_name,
            "provider_version": provider_version,
        }
        return cls(
            asset=asset,
            timeframe=timeframe,
            candidate_id=deterministic_hash("trendline_v2_candidate", payload),
            role=role,
            geometry=geometry,
            anchors=anchors,
            evidence=evidence,
            observed_at=observed_at,
            provider_name=provider_name,
            provider_version=provider_version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"candidate_id": self.candidate_id, **primitive(self)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LineCandidate":
        if not isinstance(value, Mapping):
            raise ContractValidationError("candidate payload must be a mapping")
        if set(value) != {
            "asset",
            "timeframe",
            "candidate_id",
            "role",
            "geometry",
            "anchors",
            "evidence",
            "observed_at",
            "provider_name",
            "provider_version",
        }:
            raise ContractValidationError("candidate payload keys mismatch")
        try:
            return cls(
                asset=value["asset"],
                timeframe=value["timeframe"],
                candidate_id=value["candidate_id"],
                role=value["role"],
                geometry=LineGeometry.from_dict(value["geometry"]),
                anchors=tuple(AnchorRef.from_dict(item) for item in value["anchors"]),
                evidence=CandidateEvidence.from_dict(value["evidence"]),
                observed_at=parse_utc_isoformat(value["observed_at"], field_name="candidate.observed_at"),
                provider_name=value["provider_name"],
                provider_version=value["provider_version"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractValidationError("invalid candidate payload") from exc


__all__ = ["AnchorRef", "CandidateEvidence", "LineCandidate"]
