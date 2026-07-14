"""Immutable domain contracts for the SR model.

Contains the language and immutable truth of the model: enums, geometry,
candidates, zones, runtime state, events, snapshots.  No market logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import math
from typing import Any

from .identity import (
    ContractValidationError,
    canonical_json,
    deterministic_hash,
    hash_candidate_level,
    hash_event,
    hash_snapshot,
    hash_zone_definition,
    require_utc,
)


# ---------------------------------------------------------------------------
# String-valued enums
# ---------------------------------------------------------------------------


class ZoneSide(str, Enum):
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


class ZoneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BREACH_PENDING = "BREACH_PENDING"
    BROKEN = "BROKEN"
    EXPIRED = "EXPIRED"


class SREventType(str, Enum):
    CREATED = "CREATED"
    TOUCHED = "TOUCHED"
    BREACH_STARTED = "BREACH_STARTED"
    FALSE_BREAKOUT = "FALSE_BREAKOUT"
    BREAK_CONFIRMED = "BREAK_CONFIRMED"
    EXPIRED = "EXPIRED"


SR_SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Primitive validation helpers
# ---------------------------------------------------------------------------


def _string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def _integer(value: Any, *, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{field_name} must be an integer")
    if value < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    return value


def _number(
    value: Any,
    *,
    field_name: str,
    minimum: float | None = None,
    maximum: float | None = None,
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
        return 0.0
    if minimum is not None and result < minimum:
        raise ContractValidationError(f"{field_name} must be at least {minimum}")
    if maximum is not None and result > maximum:
        raise ContractValidationError(f"{field_name} must be at most {maximum}")
    return result


def _side(value: Any) -> ZoneSide:
    try:
        return value if isinstance(value, ZoneSide) else ZoneSide(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid zone side: {value!r}") from exc


def _status(value: Any) -> ZoneStatus:
    try:
        return value if isinstance(value, ZoneStatus) else ZoneStatus(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid zone status: {value!r}") from exc


def _event_type(value: Any) -> SREventType:
    try:
        return value if isinstance(value, SREventType) else SREventType(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid SR event type: {value!r}") from exc


def _hash(value: Any, *, field_name: str) -> str:
    import re

    text = _string(value, field_name=field_name)
    if re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise ContractValidationError(
            f"{field_name} must be a lowercase SHA-256 hex string"
        )
    return text


def _tuple_of(
    value: Any,
    item_type: type,
    *,
    field_name: str,
) -> tuple[Any, ...]:
    if isinstance(value, (list, tuple)):
        seq = value
    else:
        raise ContractValidationError(
            f"{field_name} must be a list or tuple of {item_type.__name__}"
        )
    for idx, item in enumerate(seq):
        if not isinstance(item, item_type):
            raise ContractValidationError(
                f"{field_name}[{idx}] must be {item_type.__name__}"
            )
    return tuple(seq)


def _zone_sort_key(record: ZoneRecord) -> tuple[float, str, str]:
    """Canonical ordering: lower geometry bound desc, then side, then id."""
    geometry = record.definition.geometry
    lower = geometry.lower_bound
    side = record.definition.side.value
    # SUPPORT zones sort above RESISTANCE at the same lower bound.
    side_rank = "0" if side == "SUPPORT" else "1"
    return (-lower, side_rank, record.definition.zone_id)


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SRStateKey:
    venue: str
    symbol: str
    timeframe: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", _string(self.venue, field_name="venue"))
        object.__setattr__(self, "symbol", _string(self.symbol, field_name="symbol"))
        object.__setattr__(
            self, "timeframe", _string(self.timeframe, field_name="timeframe")
        )


@dataclass(frozen=True)
class ClosedBar:
    state_key: SRStateKey
    bar_id: str
    closed_at: datetime
    open: float
    high: float
    low: float
    close: float
    atr_at_close: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_key", _state_key(self.state_key))
        object.__setattr__(self, "bar_id", _string(self.bar_id, field_name="bar_id"))
        object.__setattr__(
            self,
            "closed_at",
            require_utc(self.closed_at, field_name="closed_at"),
        )
        for field_name in ("open", "high", "low", "close"):
            value = _number(
                getattr(self, field_name),
                field_name=field_name,
                minimum=0.0,
            )
            if value <= 0:
                raise ContractValidationError(f"{field_name} must be positive")
            object.__setattr__(self, field_name, value)
        if self.low > self.high:
            raise ContractValidationError("low must be <= high")
        if not self.low <= self.open <= self.high:
            raise ContractValidationError("open must be between low and high")
        if not self.low <= self.close <= self.high:
            raise ContractValidationError("close must be between low and high")
        atr_at_close = _number(
            self.atr_at_close,
            field_name="atr_at_close",
            minimum=0.0,
        )
        if atr_at_close <= 0:
            raise ContractValidationError("atr_at_close must be positive")
        object.__setattr__(self, "atr_at_close", atr_at_close)


@dataclass(frozen=True)
class ZoneGeometry:
    center: float
    half_width: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "center", _number(self.center, field_name="center", minimum=0.0)
        )
        if self.center <= 0:
            raise ContractValidationError("center must be positive")
        object.__setattr__(
            self,
            "half_width",
            _number(self.half_width, field_name="half_width", minimum=0.0),
        )
        lower_bound = self.lower_bound
        upper_bound = self.upper_bound
        if not math.isfinite(lower_bound) or not math.isfinite(upper_bound):
            raise ContractValidationError("geometry bounds must be finite")
        if lower_bound <= 0:
            raise ContractValidationError("geometry lower_bound must be positive")

    @property
    def lower_bound(self) -> float:
        return self.center - self.half_width

    @property
    def upper_bound(self) -> float:
        return self.center + self.half_width


@dataclass(frozen=True)
class CandidateLevel:
    state_key: SRStateKey
    side: ZoneSide
    geometry: ZoneGeometry
    source: str
    formed_at: datetime
    available_at: datetime
    atr_at_creation: float
    candidate_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_key", _state_key(self.state_key))
        object.__setattr__(self, "side", _side(self.side))
        object.__setattr__(self, "geometry", _geometry(self.geometry))
        object.__setattr__(self, "source", _string(self.source, field_name="source"))
        object.__setattr__(
            self, "formed_at", require_utc(self.formed_at, field_name="formed_at")
        )
        object.__setattr__(
            self,
            "available_at",
            require_utc(self.available_at, field_name="available_at"),
        )
        object.__setattr__(
            self,
            "atr_at_creation",
            _number(
                self.atr_at_creation,
                field_name="atr_at_creation",
                minimum=0.0,
            ),
        )
        if self.atr_at_creation <= 0:
            raise ContractValidationError("atr_at_creation must be positive")
        if self.available_at < self.formed_at:
            raise ContractValidationError("available_at must be >= formed_at")
        object.__setattr__(self, "candidate_id", hash_candidate_level(self))


@dataclass(frozen=True)
class ZoneDefinition:
    state_key: SRStateKey
    side: ZoneSide
    geometry: ZoneGeometry
    source: str
    created_at: datetime
    available_at: datetime
    atr_at_creation: float
    config_hash: str
    zone_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_key", _state_key(self.state_key))
        object.__setattr__(self, "side", _side(self.side))
        object.__setattr__(self, "geometry", _geometry(self.geometry))
        object.__setattr__(self, "source", _string(self.source, field_name="source"))
        object.__setattr__(
            self, "created_at", require_utc(self.created_at, field_name="created_at")
        )
        object.__setattr__(
            self,
            "available_at",
            require_utc(self.available_at, field_name="available_at"),
        )
        object.__setattr__(
            self,
            "atr_at_creation",
            _number(
                self.atr_at_creation,
                field_name="atr_at_creation",
                minimum=0.0,
            ),
        )
        if self.atr_at_creation <= 0:
            raise ContractValidationError("atr_at_creation must be positive")
        object.__setattr__(
            self, "config_hash", _hash(self.config_hash, field_name="config_hash")
        )
        if self.available_at < self.created_at:
            raise ContractValidationError("available_at must be >= created_at")
        object.__setattr__(self, "zone_id", hash_zone_definition(self))


@dataclass(frozen=True)
class ZoneRuntimeState:
    zone_id: str
    status: ZoneStatus
    touch_count: int
    fakeout_count: int
    pending_breach_count: int
    age_bars: int
    last_interaction_at: datetime | None
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "zone_id", _hash(self.zone_id, field_name="zone_id"))
        object.__setattr__(self, "status", _status(self.status))
        object.__setattr__(
            self,
            "touch_count",
            _integer(self.touch_count, field_name="touch_count"),
        )
        object.__setattr__(
            self,
            "fakeout_count",
            _integer(self.fakeout_count, field_name="fakeout_count"),
        )
        object.__setattr__(
            self,
            "pending_breach_count",
            _integer(
                self.pending_breach_count,
                field_name="pending_breach_count",
            ),
        )
        object.__setattr__(
            self,
            "age_bars",
            _integer(self.age_bars, field_name="age_bars", minimum=0),
        )
        if self.status in {
            ZoneStatus.ACTIVE,
            ZoneStatus.BROKEN,
            ZoneStatus.EXPIRED,
        } and self.pending_breach_count != 0:
            raise ContractValidationError(
                "pending_breach_count must be 0 for non-pending statuses"
            )
        if (
            self.status is ZoneStatus.BREACH_PENDING
            and self.pending_breach_count < 1
        ):
            raise ContractValidationError(
                "pending_breach_count must be >= 1 for BREACH_PENDING"
            )
        object.__setattr__(
            self, "updated_at", require_utc(self.updated_at, field_name="updated_at")
        )
        if self.last_interaction_at is not None:
            object.__setattr__(
                self,
                "last_interaction_at",
                require_utc(
                    self.last_interaction_at,
                    field_name="last_interaction_at",
                ),
            )
            if self.last_interaction_at > self.updated_at:
                raise ContractValidationError(
                    "last_interaction_at must be <= updated_at"
                )


@dataclass(frozen=True)
class ZoneRecord:
    definition: ZoneDefinition
    runtime: ZoneRuntimeState

    def __post_init__(self) -> None:
        if not isinstance(self.definition, ZoneDefinition):
            raise ContractValidationError("definition must be ZoneDefinition")
        if not isinstance(self.runtime, ZoneRuntimeState):
            raise ContractValidationError("runtime must be ZoneRuntimeState")
        if self.runtime.zone_id != self.definition.zone_id:
            raise ContractValidationError(
                "runtime.zone_id must match definition.zone_id"
            )
        if self.runtime.updated_at < self.definition.available_at:
            raise ContractValidationError(
                "runtime.updated_at must be >= definition.available_at"
            )
        if (
            self.runtime.last_interaction_at is not None
            and self.runtime.last_interaction_at < self.definition.available_at
        ):
            raise ContractValidationError(
                "last_interaction_at must be >= definition.available_at"
            )


@dataclass(frozen=True)
class SREvent:
    zone_id: str
    event_type: SREventType
    timestamp: datetime
    price: float
    bar_id: str
    event_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "zone_id", _hash(self.zone_id, field_name="zone_id"))
        object.__setattr__(self, "event_type", _event_type(self.event_type))
        object.__setattr__(
            self, "timestamp", require_utc(self.timestamp, field_name="timestamp")
        )
        object.__setattr__(
            self, "price", _number(self.price, field_name="price", minimum=0.0)
        )
        if self.price <= 0:
            raise ContractValidationError("price must be positive")
        object.__setattr__(self, "bar_id", _string(self.bar_id, field_name="bar_id"))
        object.__setattr__(self, "event_id", hash_event(self))


@dataclass(frozen=True)
class SRState:
    schema_version: str
    state_key: SRStateKey
    config_hash: str
    last_processed_bar: str | None
    zones: tuple[ZoneRecord, ...]
    recent_bars: tuple[ClosedBar, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", _string(self.schema_version, field_name="schema_version")
        )
        if self.schema_version != SR_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported SR schema version: {self.schema_version!r}"
            )
        object.__setattr__(self, "state_key", _state_key(self.state_key))
        object.__setattr__(
            self, "config_hash", _hash(self.config_hash, field_name="config_hash")
        )
        object.__setattr__(
            self,
            "last_processed_bar",
            (
                None
                if self.last_processed_bar is None
                else _string(
                    self.last_processed_bar,
                    field_name="last_processed_bar",
                )
            ),
        )
        object.__setattr__(
            self, "zones", _tuple_of(self.zones, ZoneRecord, field_name="zones")
        )
        object.__setattr__(
            self,
            "recent_bars",
            _validate_recent_bars(
                self.recent_bars,
                state_key=self.state_key,
                last_processed_bar=self.last_processed_bar,
            ),
        )
        if self.last_processed_bar is None:
            if self.zones or self.recent_bars:
                raise ContractValidationError(
                    "null last_processed_bar requires empty zones and recent_bars"
                )
        elif not self.recent_bars:
            raise ContractValidationError(
                "non-null last_processed_bar requires non-empty recent_bars"
            )
        _validate_zone_ownership(self.state_key, self.config_hash, self.zones)
        object.__setattr__(self, "zones", tuple(sorted(self.zones, key=_zone_sort_key)))


@dataclass(frozen=True)
class SRSnapshot:
    schema_version: str
    state_key: SRStateKey
    config_hash: str
    as_of: datetime
    zones: tuple[ZoneRecord, ...]
    events: tuple[SREvent, ...]
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "schema_version", _string(self.schema_version, field_name="schema_version")
        )
        if self.schema_version != SR_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported SR schema version: {self.schema_version!r}"
            )
        object.__setattr__(self, "state_key", _state_key(self.state_key))
        object.__setattr__(
            self, "config_hash", _hash(self.config_hash, field_name="config_hash")
        )
        object.__setattr__(self, "as_of", require_utc(self.as_of, field_name="as_of"))
        object.__setattr__(
            self, "zones", _tuple_of(self.zones, ZoneRecord, field_name="zones")
        )
        object.__setattr__(
            self, "events", _tuple_of(self.events, SREvent, field_name="events")
        )
        _validate_zone_ownership(self.state_key, self.config_hash, self.zones)
        zone_records = {
            record.definition.zone_id: record for record in self.zones
        }
        for record in self.zones:
            if record.runtime.updated_at > self.as_of:
                raise ContractValidationError(
                    "zone runtime.updated_at must be <= snapshot.as_of"
                )
        seen_event_ids: set[str] = set()
        for event in self.events:
            if event.event_id in seen_event_ids:
                raise ContractValidationError(
                    f"duplicate event_id in snapshot: {event.event_id}"
                )
            seen_event_ids.add(event.event_id)
            # V1.0 has no tombstone or lineage representation, so every
            # snapshot event must belong to a zone present in that snapshot.
            if event.zone_id not in zone_records:
                raise ContractValidationError(
                    "snapshot event references an unknown zone_id"
                )
            if (
                event.timestamp
                < zone_records[event.zone_id].definition.available_at
            ):
                raise ContractValidationError(
                    "event.timestamp must be >= zone.definition.available_at"
                )
            if event.timestamp > self.as_of:
                raise ContractValidationError(
                    "event.timestamp must be <= snapshot.as_of"
                )
        object.__setattr__(self, "zones", tuple(sorted(self.zones, key=_zone_sort_key)))
        event_order = _canonical_event_order(self.events)
        object.__setattr__(self, "events", event_order)
        object.__setattr__(self, "snapshot_id", hash_snapshot(self))


# ---------------------------------------------------------------------------
# Composite validation helpers used above
# ---------------------------------------------------------------------------


def _state_key(value: Any) -> SRStateKey:
    if isinstance(value, SRStateKey):
        return value
    raise ContractValidationError("value must be SRStateKey")


def _geometry(value: Any) -> ZoneGeometry:
    if isinstance(value, ZoneGeometry):
        return value
    raise ContractValidationError("value must be ZoneGeometry")


def _validate_recent_bars(
    value: Any,
    *,
    state_key: SRStateKey,
    last_processed_bar: str | None,
) -> tuple[ClosedBar, ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractValidationError(
            "recent_bars must be a list or tuple of ClosedBar"
        )
    bars = tuple(value)
    seen_bar_ids: set[str] = set()
    previous_timestamp: datetime | None = None
    for idx, bar in enumerate(bars):
        if type(bar) is not ClosedBar:
            raise ContractValidationError(
                f"recent_bars[{idx}] must be exactly ClosedBar"
            )
        if bar.state_key != state_key:
            raise ContractValidationError(
                f"recent_bars[{idx}].state_key must match aggregate state_key"
            )
        if bar.bar_id in seen_bar_ids:
            raise ContractValidationError(
                f"duplicate bar_id in recent_bars: {bar.bar_id}"
            )
        seen_bar_ids.add(bar.bar_id)
        if (
            previous_timestamp is not None
            and bar.closed_at <= previous_timestamp
        ):
            raise ContractValidationError(
                "recent_bars.closed_at values must be strictly increasing"
            )
        previous_timestamp = bar.closed_at
    if bars and last_processed_bar is None:
        raise ContractValidationError(
            "recent_bars require non-null last_processed_bar"
        )
    if bars and bars[-1].bar_id != last_processed_bar:
        raise ContractValidationError(
            "recent_bars final bar_id must match last_processed_bar"
        )
    return bars


def _validate_zone_ownership(
    state_key: SRStateKey,
    config_hash: str,
    zones: tuple[ZoneRecord, ...],
) -> None:
    seen_ids: set[str] = set()
    for idx, record in enumerate(zones):
        definition = record.definition
        if definition.state_key != state_key:
            raise ContractValidationError(
                f"zones[{idx}].definition.state_key must match aggregate state_key"
            )
        if definition.config_hash != config_hash:
            raise ContractValidationError(
                f"zones[{idx}].definition.config_hash must match aggregate config_hash"
            )
        zone_id = definition.zone_id
        if zone_id in seen_ids:
            raise ContractValidationError(
                f"duplicate zone_id in zones: {zone_id}"
            )
        seen_ids.add(zone_id)


def _canonical_event_order(events: tuple[SREvent, ...]) -> tuple[SREvent, ...]:
    """Return events sorted by timestamp, then zone_id, then event_type, then id."""
    return tuple(
        sorted(
            events,
            key=lambda e: (
                e.timestamp,
                e.zone_id,
                e.event_type.value,
                e.event_id,
            ),
        )
    )


# ---------------------------------------------------------------------------
# Public domain boundary
# ---------------------------------------------------------------------------

__all__ = [
    "ContractValidationError",
    "ZoneSide",
    "ZoneStatus",
    "SR_SCHEMA_VERSION",
    "SREventType",
    "SRStateKey",
    "ClosedBar",
    "ZoneGeometry",
    "CandidateLevel",
    "ZoneDefinition",
    "ZoneRuntimeState",
    "ZoneRecord",
    "SREvent",
    "SRState",
    "SRSnapshot",
    "canonical_json",
    "deterministic_hash",
]
