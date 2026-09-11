"""Immutable zone lineages and lifecycle records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from ..contracts import LifecycleState, ZoneSide, require_utc
from .candidates import Candidate
from .identity import make_zone_id


@dataclass(frozen=True, slots=True, kw_only=True)
class ZoneLineage:
    zone_id: str
    predecessor_id: str | None
    venue: str
    instrument_id: str
    asset: str
    source_timeframe: str
    kernel_id: str
    kernel_version: str
    side: ZoneSide
    center: Decimal
    lower: Decimal
    upper: Decimal
    source_evidence_id: str
    formed_at: datetime
    available_at: datetime
    creation_atr: Decimal
    config_fingerprint: str
    source_candidate_key: str = ""
    identity_schema_version: int = 1

    def __post_init__(self) -> None:
        for name in (
            "zone_id",
            "venue",
            "instrument_id",
            "asset",
            "source_timeframe",
            "kernel_id",
            "kernel_version",
            "source_evidence_id",
            "config_fingerprint",
        ):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        candidate_key = self.source_candidate_key or self.source_evidence_id
        if not candidate_key.strip():
            raise ValueError("source_candidate_key must be non-empty")
        if self.predecessor_id is not None and not self.predecessor_id.strip():
            raise ValueError("predecessor_id must be non-empty when supplied")
        if not isinstance(self.side, ZoneSide):
            raise TypeError("side must be ZoneSide")
        if isinstance(self.identity_schema_version, bool) or self.identity_schema_version <= 0:
            raise ValueError("identity_schema_version must be positive")
        for name in ("center", "lower", "upper", "creation_atr"):
            if not isinstance(getattr(self, name), Decimal) or not getattr(self, name).is_finite():
                raise TypeError(f"{name} must be a finite Decimal")
        if self.creation_atr <= 0 or self.lower > self.center or self.center > self.upper:
            raise ValueError("invalid immutable zone geometry")
        require_utc(self.formed_at, field_name="formed_at")
        require_utc(self.available_at, field_name="available_at")
        if self.available_at < self.formed_at:
            raise ValueError("available_at cannot precede formed_at")
        expected_id = make_zone_id(
            venue=self.venue,
            instrument_id=self.instrument_id,
            asset=self.asset,
            source_timeframe=self.source_timeframe,
            kernel_id=self.kernel_id,
            kernel_version=self.kernel_version,
            source_candidate_key=candidate_key,
            available_at=self.available_at,
            center=self.center,
            lower=self.lower,
            upper=self.upper,
            predecessor_id=self.predecessor_id,
            identity_schema_version=self.identity_schema_version,
        )
        if self.zone_id != expected_id:
            raise ValueError("zone_id does not match canonical lineage identity")


@dataclass(frozen=True, slots=True, kw_only=True)
class ZoneRecord:
    lineage: ZoneLineage
    lifecycle: LifecycleState = LifecycleState.ACTIVE
    touch_count: int = 0
    was_overlapping: bool = False
    last_touch_at: datetime | None = None
    break_pending_count: int = 0
    last_transition_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.lineage, ZoneLineage):
            raise TypeError("lineage must be ZoneLineage")
        if not isinstance(self.lifecycle, LifecycleState):
            raise TypeError("lifecycle must be LifecycleState")
        if not isinstance(self.was_overlapping, bool):
            raise TypeError("was_overlapping must be a bool")
        for name in ("touch_count", "break_pending_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.last_touch_at is not None:
            require_utc(self.last_touch_at, field_name="last_touch_at")
        if self.last_transition_at is not None:
            require_utc(self.last_transition_at, field_name="last_transition_at")


def lineage_from_candidate(
    candidate: Candidate,
    *,
    config_fingerprint: str,
    predecessor_id: str | None = None,
) -> ZoneLineage:
    zone_id = make_zone_id(
        venue=candidate.venue,
        instrument_id=candidate.instrument_id,
        asset=candidate.asset,
        source_timeframe=candidate.source_timeframe,
        kernel_id=candidate.kernel_id,
        kernel_version=candidate.kernel_version,
        source_candidate_key=candidate.candidate_key,
        available_at=candidate.available_at,
        center=candidate.center,
        lower=candidate.lower,
        upper=candidate.upper,
        predecessor_id=predecessor_id,
        identity_schema_version=1,
    )
    return ZoneLineage(
        zone_id=zone_id,
        predecessor_id=predecessor_id,
        venue=candidate.venue,
        instrument_id=candidate.instrument_id,
        asset=candidate.asset,
        source_timeframe=candidate.source_timeframe,
        kernel_id=candidate.kernel_id,
        kernel_version=candidate.kernel_version,
        side=candidate.side,
        center=candidate.center,
        lower=candidate.lower,
        upper=candidate.upper,
        source_evidence_id=candidate.source_evidence_id,
        source_candidate_key=candidate.candidate_key,
        formed_at=candidate.formed_at,
        available_at=candidate.available_at,
        creation_atr=candidate.creation_atr,
        config_fingerprint=config_fingerprint,
    )


__all__ = ["ZoneLineage", "ZoneRecord", "lineage_from_candidate"]
