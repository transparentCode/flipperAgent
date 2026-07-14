"""Immutable observation and diagnostic contracts for SR evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math
import re
from typing import Any

from libs.models.sr.domain.contracts import (
    ContractValidationError,
    SREvent,
    SREventType,
    SRStateKey,
    ZoneSide,
    ZoneStatus,
)

from .identity import canonical_timestamp, evaluation_hash, normalize_utc


SR_EVALUATION_SCHEMA_VERSION = "1.0"
_HASH_RE = re.compile(r"[0-9a-f]{64}")


class ZoneRenderKind(str, Enum):
    LINE = "LINE"
    BAND = "BAND"


def _string(value: Any, *, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _hash(value: Any, *, field_name: str) -> str:
    value = _string(value, field_name=field_name)
    if _HASH_RE.fullmatch(value) is None:
        raise ContractValidationError(
            f"{field_name} must be a lowercase SHA-256 hex string"
        )
    return value


def _finite_number(
    value: Any,
    *,
    field_name: str,
    minimum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractValidationError(f"{field_name} must be numeric")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ContractValidationError(f"{field_name} must be finite") from exc
    if not math.isfinite(result):
        raise ContractValidationError(f"{field_name} must be finite")
    if result == 0.0:
        result = 0.0
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    return result


def _nonnegative_integer(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or type(value) is not int:
        raise ContractValidationError(f"{field_name} must be an integer")
    if value < 0:
        raise ContractValidationError(f"{field_name} must be non-negative")
    return value


def _boolean(value: Any, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise ContractValidationError(f"{field_name} must be a boolean")
    return value


def _state_key(value: Any, *, field_name: str = "state_key") -> SRStateKey:
    if type(value) is not SRStateKey:
        raise ContractValidationError(f"{field_name} must be exactly SRStateKey")
    return value


def _enum(value: Any, enum_type: type[Enum], *, field_name: str) -> Enum:
    if type(value) is not enum_type:
        raise ContractValidationError(
            f"{field_name} must be exactly {enum_type.__name__}"
        )
    return value


def _timestamp(value: Any, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ContractValidationError(f"{field_name} must be a datetime")
    return normalize_utc(value, field_name=field_name)


def _state_key_payload(state_key: SRStateKey) -> dict[str, str]:
    return {
        "venue": state_key.venue,
        "symbol": state_key.symbol,
        "timeframe": state_key.timeframe,
    }


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


def _trace_identity_payload(trace: SREvaluationTrace) -> dict[str, Any]:
    return {
        "schema_version": trace.schema_version,
        "state_key": _state_key_payload(trace.state_key),
        "config_hash": trace.config_hash,
        "field_provenance": [list(pair) for pair in trace.field_provenance],
        "snapshot_ids": [reference.snapshot_id for reference in trace.snapshots],
        "observation_ids": [
            observation.observation_id
            for observation in trace.zone_observations
        ],
        "event_ids": [event.event_id for event in trace.events],
    }


@dataclass(frozen=True)
class SREvaluationTrace:
    schema_version: str
    state_key: SRStateKey
    config_hash: str
    field_provenance: tuple[tuple[str, str], ...]
    snapshots: tuple[SnapshotReference, ...]
    zone_observations: tuple[ZoneObservation, ...]
    events: tuple[ObservedEvent, ...]
    trace_id: str = field(init=False)

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
        if type(self.field_provenance) is not tuple:
            raise ContractValidationError("field_provenance must be exactly a tuple")
        if not self.field_provenance:
            raise ContractValidationError("field_provenance must not be empty")
        provenance: list[tuple[str, str]] = []
        for index, entry in enumerate(self.field_provenance):
            if type(entry) is not tuple or len(entry) != 2:
                raise ContractValidationError(
                    f"field_provenance[{index}] must be a pair tuple"
                )
            path = _string(entry[0], field_name=f"field_provenance[{index}].path")
            source = _string(
                entry[1],
                field_name=f"field_provenance[{index}].source",
            )
            provenance.append((path, source))
        normalized_provenance = tuple(provenance)
        if len(set(normalized_provenance)) != len(normalized_provenance):
            raise ContractValidationError("field_provenance must be unique")
        if normalized_provenance != tuple(sorted(normalized_provenance)):
            raise ContractValidationError(
                "field_provenance must be canonically ordered"
            )
        object.__setattr__(self, "field_provenance", normalized_provenance)

        for field_name in ("snapshots", "zone_observations", "events"):
            if type(getattr(self, field_name)) is not tuple:
                raise ContractValidationError(f"{field_name} must be exactly a tuple")
        if not self.snapshots:
            raise ContractValidationError("snapshots must not be empty")
        if any(type(item) is not SnapshotReference for item in self.snapshots):
            raise ContractValidationError(
                "snapshots must contain exactly SnapshotReference values"
            )
        if any(
            type(item) is not ZoneObservation for item in self.zone_observations
        ):
            raise ContractValidationError(
                "zone_observations must contain exactly ZoneObservation values"
            )
        if any(type(item) is not ObservedEvent for item in self.events):
            raise ContractValidationError(
                "events must contain exactly ObservedEvent values"
            )

        snapshot_ids = [reference.snapshot_id for reference in self.snapshots]
        if len(set(snapshot_ids)) != len(snapshot_ids):
            raise ContractValidationError("snapshot IDs must be unique")
        snapshot_by_id = {
            reference.snapshot_id: reference for reference in self.snapshots
        }
        snapshot_position = {
            reference.snapshot_id: index
            for index, reference in enumerate(self.snapshots)
        }
        for previous, current in zip(self.snapshots, self.snapshots[1:]):
            if current.as_of <= previous.as_of:
                raise ContractValidationError(
                    "snapshot references must be strictly increasing by as_of"
                )

        for observation in self.zone_observations:
            reference = snapshot_by_id.get(observation.snapshot_id)
            if reference is None:
                raise ContractValidationError(
                    "zone observation references an unknown snapshot"
                )
            if observation.as_of != reference.as_of:
                raise ContractValidationError(
                    "zone observation as_of must match snapshot reference"
                )
            if observation.schema_version != self.schema_version:
                raise ContractValidationError(
                    "zone observation schema_version must match trace"
                )
            if observation.state_key != self.state_key:
                raise ContractValidationError(
                    "zone observation state_key must match trace"
                )
            if observation.config_hash != self.config_hash:
                raise ContractValidationError(
                    "zone observation config_hash must match trace"
                )

        observation_positions = [
            snapshot_position[observation.snapshot_id]
            for observation in self.zone_observations
        ]
        if observation_positions != sorted(observation_positions):
            raise ContractValidationError(
                "zone observations must preserve snapshot order"
            )
        observation_ids = [
            observation.observation_id for observation in self.zone_observations
        ]
        if len(set(observation_ids)) != len(observation_ids):
            raise ContractValidationError("observation IDs must be unique")
        observations_by_snapshot: dict[str, set[str]] = {}
        for observation in self.zone_observations:
            zone_ids = observations_by_snapshot.setdefault(observation.snapshot_id, set())
            if observation.zone_id in zone_ids:
                raise ContractValidationError(
                    "duplicate zone observation in snapshot"
                )
            zone_ids.add(observation.zone_id)

        invariant_by_zone: dict[str, tuple[Any, ...]] = {}
        terminal_until_by_zone: dict[str, datetime] = {}
        terminal_status_by_zone: dict[str, ZoneStatus] = {}
        for observation in self.zone_observations:
            invariant = (
                observation.state_key,
                observation.config_hash,
                observation.side,
                observation.source,
                observation.render_kind,
                observation.lower_bound,
                observation.center,
                observation.upper_bound,
                observation.created_at,
                observation.available_at,
                observation.visible_from,
            )
            previous_invariant = invariant_by_zone.setdefault(
                observation.zone_id,
                invariant,
            )
            if previous_invariant != invariant:
                raise ContractValidationError(
                    "zone definition fields must remain unchanged in trace"
                )
            if observation.visible_until is not None:
                if observation.zone_id in terminal_until_by_zone:
                    if (
                        terminal_until_by_zone[observation.zone_id]
                        != observation.visible_until
                        or terminal_status_by_zone[observation.zone_id]
                        != observation.status
                    ):
                        raise ContractValidationError(
                            "terminal zone visible window must remain unchanged"
                        )
                else:
                    terminal_until_by_zone[observation.zone_id] = (
                        observation.visible_until
                    )
                    terminal_status_by_zone[observation.zone_id] = observation.status
            elif observation.zone_id in terminal_until_by_zone:
                raise ContractValidationError(
                    "terminal zone cannot become live again in a trace"
                )

        event_positions = [
            snapshot_position[event.snapshot_id] for event in self.events
        ]
        if event_positions != sorted(event_positions):
            raise ContractValidationError("events must preserve snapshot order")
        event_ids = [event.event_id for event in self.events]
        if len(set(event_ids)) != len(event_ids):
            raise ContractValidationError("event IDs must be unique")
        for event in self.events:
            reference = snapshot_by_id.get(event.snapshot_id)
            if reference is None:
                raise ContractValidationError(
                    "event references an unknown snapshot"
                )
            if event.snapshot_as_of != reference.as_of:
                raise ContractValidationError(
                    "event snapshot_as_of must match snapshot reference"
                )
            if event.zone_id not in observations_by_snapshot.get(
                event.snapshot_id,
                set(),
            ):
                raise ContractValidationError(
                    "event must reference a zone observed in the same snapshot"
                )

        object.__setattr__(
            self,
            "trace_id",
            evaluation_hash(_trace_identity_payload(self)),
        )


__all__ = [
    "ObservedEvent",
    "SREvaluationTrace",
    "SR_EVALUATION_SCHEMA_VERSION",
    "SnapshotReference",
    "ZoneObservation",
    "ZoneRenderKind",
]
