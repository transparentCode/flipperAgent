"""Immutable aggregate SR evaluation-trace contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from libs.models.sr.domain.bars import SRStateKey
from libs.models.sr.domain.errors import ContractValidationError
from libs.models.sr.domain.zones import ZoneStatus

from ._validation import _hash, _state_key, _state_key_payload, _string
from .identity import evaluation_hash
from .observations import (
    ObservedEvent,
    SR_EVALUATION_SCHEMA_VERSION,
    SnapshotReference,
    ZoneObservation,
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
                observation.atr_at_creation,
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

        for event in self.events:
            if event.snapshot_id not in snapshot_position:
                raise ContractValidationError(
                    "event references an unknown snapshot"
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


__all__ = ["SREvaluationTrace"]
