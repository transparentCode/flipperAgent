"""SR immutable snapshot contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ._validation import _hash, _string, _tuple_of
from .bars import SRStateKey, _state_key
from .errors import ContractValidationError
from .events import SREvent
from .identity import hash_snapshot, require_utc
from .state import SR_SCHEMA_VERSION, _zone_sort_key
from .zones import ZoneRecord, _validate_zone_ownership


def _canonical_event_order(events: tuple[SREvent, ...]) -> tuple[SREvent, ...]:
    """Return events sorted by timestamp, then zone_id, then event_type, then id."""
    return tuple(
        sorted(
            events,
            key=lambda event: (
                event.timestamp,
                event.zone_id,
                event.event_type.value,
                event.event_id,
            ),
        )
    )


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


__all__ = ["SRSnapshot"]
