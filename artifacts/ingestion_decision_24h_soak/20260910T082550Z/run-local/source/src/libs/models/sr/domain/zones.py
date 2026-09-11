"""SR zone-side, definition, and runtime contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from ._validation import _hash, _integer, _number, _string
from .bars import SRStateKey, _state_key
from .errors import ContractValidationError
from .geometry import ZoneGeometry, _geometry
from .identity import hash_zone_definition, require_utc


class ZoneSide(str, Enum):
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


class ZoneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BREACH_PENDING = "BREACH_PENDING"
    BROKEN = "BROKEN"
    EXPIRED = "EXPIRED"


def _side(value: object) -> ZoneSide:
    try:
        return value if isinstance(value, ZoneSide) else ZoneSide(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid zone side: {value!r}") from exc


def _status(value: object) -> ZoneStatus:
    try:
        return value if isinstance(value, ZoneStatus) else ZoneStatus(value)
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"invalid zone status: {value!r}") from exc


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


__all__ = [
    "ZoneDefinition",
    "ZoneRecord",
    "ZoneRuntimeState",
    "ZoneSide",
    "ZoneStatus",
]
