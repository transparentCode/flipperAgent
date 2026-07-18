"""Immutable SR snapshot, event, and zone-observation contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from libs.models.sr.domain.bars import SRStateKey
from libs.models.sr.domain.errors import ContractValidationError
from libs.models.sr.domain.events import SREvent, SREventType
from libs.models.sr.domain.zones import ZoneSide, ZoneStatus

from ._validation import (
    _enum,
    _finite_number,
    _hash,
    _nonnegative_integer,
    _state_key,
    _state_key_payload,
    _string,
    _timestamp,
)
from .identity import canonical_timestamp, evaluation_hash


SR_EVALUATION_SCHEMA_VERSION = "1.0"


class ZoneRenderKind(str, Enum):
    LINE = "LINE"
    BAND = "BAND"


def _observation_identity_payload(observation: ZoneObservation) -> dict[str, Any]:
    return {
        "schema_version": observation.schema_version,
        "state_key": _state_key_payload(observation.state_key),
        "config_hash": observation.config_hash,
        "snapshot_id": observation.snapshot_id,
        "as_of": canonical_timestamp(observation.as_of, field_name="as_of"),
        "zone_id": observation.zone_id,
        "side": observation.side.value,
        "source": observation.source,
        "atr_at_creation": observation.atr_at_creation,
        "render_kind": observation.render_kind.value,
        "lower_bound": observation.lower_bound,
        "center": observation.center,
        "upper_bound": observation.upper_bound,
        "created_at": canonical_timestamp(
            observation.created_at,
            field_name="created_at",
        ),
        "available_at": canonical_timestamp(
            observation.available_at,
            field_name="available_at",
        ),
        "visible_from": canonical_timestamp(
            observation.visible_from,
            field_name="visible_from",
        ),
        "visible_until": (
            None
            if observation.visible_until is None
            else canonical_timestamp(
                observation.visible_until,
                field_name="visible_until",
            )
        ),
        "status": observation.status.value,
        "touch_count": observation.touch_count,
        "fakeout_count": observation.fakeout_count,
        "pending_breach_count": observation.pending_breach_count,
        "age_bars": observation.age_bars,
        "last_interaction_at": (
            None
            if observation.last_interaction_at is None
            else canonical_timestamp(
                observation.last_interaction_at,
                field_name="last_interaction_at",
            )
        ),
        "runtime_updated_at": canonical_timestamp(
            observation.runtime_updated_at,
            field_name="runtime_updated_at",
        ),
    }


@dataclass(frozen=True)
class SnapshotReference:
    snapshot_id: str
    as_of: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "snapshot_id",
            _hash(self.snapshot_id, field_name="snapshot_id"),
        )
        object.__setattr__(
            self,
            "as_of",
            _timestamp(self.as_of, field_name="as_of"),
        )


@dataclass(frozen=True)
class ObservedEvent:
    snapshot_id: str
    snapshot_as_of: datetime
    event_id: str
    zone_id: str
    event_type: SREventType
    timestamp: datetime
    price: float
    bar_id: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "snapshot_id",
            _hash(self.snapshot_id, field_name="snapshot_id"),
        )
        snapshot_as_of = _timestamp(
            self.snapshot_as_of,
            field_name="snapshot_as_of",
        )
        timestamp = _timestamp(self.timestamp, field_name="timestamp")
        if timestamp > snapshot_as_of:
            raise ContractValidationError(
                "event timestamp must be <= snapshot_as_of"
            )
        object.__setattr__(self, "snapshot_as_of", snapshot_as_of)
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(
            self,
            "event_id",
            _hash(self.event_id, field_name="event_id"),
        )
        object.__setattr__(
            self,
            "zone_id",
            _hash(self.zone_id, field_name="zone_id"),
        )
        object.__setattr__(
            self,
            "event_type",
            _enum(self.event_type, SREventType, field_name="event_type"),
        )
        object.__setattr__(
            self,
            "price",
            _finite_number(self.price, field_name="price", minimum=0.0),
        )
        if self.price <= 0:
            raise ContractValidationError("price must be positive")
        object.__setattr__(self, "bar_id", _string(self.bar_id, field_name="bar_id"))
        expected_event_id = SREvent(
            zone_id=self.zone_id,
            event_type=self.event_type,
            timestamp=self.timestamp,
            price=self.price,
            bar_id=self.bar_id,
        ).event_id
        if self.event_id != expected_event_id:
            raise ContractValidationError(
                "event_id must match the authoritative domain event identity"
            )


@dataclass(frozen=True)
class ZoneObservation:
    schema_version: str
    state_key: SRStateKey
    config_hash: str
    snapshot_id: str
    as_of: datetime
    zone_id: str
    side: ZoneSide
    source: str
    atr_at_creation: float
    render_kind: ZoneRenderKind
    lower_bound: float
    center: float
    upper_bound: float
    created_at: datetime
    available_at: datetime
    visible_from: datetime
    visible_until: datetime | None
    status: ZoneStatus
    touch_count: int
    fakeout_count: int
    pending_breach_count: int
    age_bars: int
    last_interaction_at: datetime | None
    runtime_updated_at: datetime
    observation_id: str = field(init=False)

    def __post_init__(self) -> None:
        schema_version = _string(
            self.schema_version,
            field_name="schema_version",
        )
        if schema_version != SR_EVALUATION_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported SR evaluation schema version: {schema_version!r}"
            )
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "state_key", _state_key(self.state_key))
        object.__setattr__(
            self,
            "config_hash",
            _hash(self.config_hash, field_name="config_hash"),
        )
        object.__setattr__(
            self,
            "snapshot_id",
            _hash(self.snapshot_id, field_name="snapshot_id"),
        )
        as_of = _timestamp(self.as_of, field_name="as_of")
        created_at = _timestamp(self.created_at, field_name="created_at")
        available_at = _timestamp(
            self.available_at,
            field_name="available_at",
        )
        visible_from = _timestamp(
            self.visible_from,
            field_name="visible_from",
        )
        runtime_updated_at = _timestamp(
            self.runtime_updated_at,
            field_name="runtime_updated_at",
        )
        if created_at > available_at:
            raise ContractValidationError("created_at must be <= available_at")
        if visible_from != available_at:
            raise ContractValidationError("visible_from must equal available_at")
        if visible_from > as_of:
            raise ContractValidationError("visible_from must be <= as_of")
        if runtime_updated_at > as_of:
            raise ContractValidationError("runtime_updated_at must be <= as_of")
        object.__setattr__(self, "as_of", as_of)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(self, "visible_from", visible_from)
        object.__setattr__(self, "runtime_updated_at", runtime_updated_at)

        visible_until = self.visible_until
        if visible_until is not None:
            visible_until = _timestamp(
                visible_until,
                field_name="visible_until",
            )
            if visible_until > as_of:
                raise ContractValidationError(
                    "visible_until must be <= observation.as_of"
                )
        object.__setattr__(self, "visible_until", visible_until)

        object.__setattr__(
            self,
            "zone_id",
            _hash(self.zone_id, field_name="zone_id"),
        )
        object.__setattr__(
            self,
            "side",
            _enum(self.side, ZoneSide, field_name="side"),
        )
        object.__setattr__(self, "source", _string(self.source, field_name="source"))
        atr_at_creation = _finite_number(
            self.atr_at_creation,
            field_name="atr_at_creation",
            minimum=0.0,
        )
        if atr_at_creation <= 0:
            raise ContractValidationError("atr_at_creation must be positive")
        object.__setattr__(self, "atr_at_creation", atr_at_creation)
        object.__setattr__(
            self,
            "render_kind",
            _enum(self.render_kind, ZoneRenderKind, field_name="render_kind"),
        )
        lower_bound = _finite_number(
            self.lower_bound,
            field_name="lower_bound",
            minimum=0.0,
        )
        center = _finite_number(self.center, field_name="center", minimum=0.0)
        upper_bound = _finite_number(
            self.upper_bound,
            field_name="upper_bound",
            minimum=0.0,
        )
        if lower_bound <= 0 or center <= 0 or upper_bound <= 0:
            raise ContractValidationError("observation prices must be positive")
        if not lower_bound <= center <= upper_bound:
            raise ContractValidationError(
                "observation bounds must satisfy lower_bound <= center <= upper_bound"
            )
        if self.render_kind is ZoneRenderKind.LINE:
            if not lower_bound == center == upper_bound:
                raise ContractValidationError(
                    "LINE observations must have zero-width geometry"
                )
        elif not lower_bound < center < upper_bound:
            raise ContractValidationError(
                "BAND observations must have positive-width geometry"
            )
        object.__setattr__(self, "lower_bound", lower_bound)
        object.__setattr__(self, "center", center)
        object.__setattr__(self, "upper_bound", upper_bound)

        object.__setattr__(
            self,
            "status",
            _enum(self.status, ZoneStatus, field_name="status"),
        )
        for field_name in (
            "touch_count",
            "fakeout_count",
            "pending_breach_count",
            "age_bars",
        ):
            object.__setattr__(
                self,
                field_name,
                _nonnegative_integer(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        last_interaction_at = self.last_interaction_at
        if last_interaction_at is not None:
            last_interaction_at = _timestamp(
                last_interaction_at,
                field_name="last_interaction_at",
            )
            if last_interaction_at < available_at:
                raise ContractValidationError(
                    "last_interaction_at must be >= available_at"
                )
            if last_interaction_at > runtime_updated_at:
                raise ContractValidationError(
                    "last_interaction_at must be <= runtime_updated_at"
                )
        object.__setattr__(self, "last_interaction_at", last_interaction_at)

        if self.status in {ZoneStatus.ACTIVE, ZoneStatus.BREACH_PENDING}:
            if visible_until is not None:
                raise ContractValidationError(
                    "live observations must not have visible_until"
                )
        else:
            if visible_until != runtime_updated_at:
                raise ContractValidationError(
                    "terminal visible_until must equal runtime_updated_at"
                )
        object.__setattr__(
            self,
            "observation_id",
            evaluation_hash(_observation_identity_payload(self)),
        )


__all__ = [
    "ObservedEvent",
    "SR_EVALUATION_SCHEMA_VERSION",
    "SnapshotReference",
    "ZoneObservation",
    "ZoneRenderKind",
]
