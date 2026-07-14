"""Descriptive diagnostics derived solely from SR evaluation traces."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any

from .contracts import (
    ContractValidationError,
    ObservedEvent,
    SREvaluationTrace,
    SREventType,
    ZoneSide,
    ZoneObservation,
    ZoneRenderKind,
    ZoneStatus,
)
from .identity import canonical_timestamp, evaluation_hash, normalize_utc


_HASH_RE = re.compile(r"[0-9a-f]{64}")
_STATUS_ORDER = (
    ZoneStatus.ACTIVE,
    ZoneStatus.BREACH_PENDING,
    ZoneStatus.BROKEN,
    ZoneStatus.EXPIRED,
)
_EVENT_TYPES = (
    SREventType.CREATED,
    SREventType.TOUCHED,
    SREventType.BREACH_STARTED,
    SREventType.FALSE_BREAKOUT,
    SREventType.BREAK_CONFIRMED,
    SREventType.EXPIRED,
)


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


def _timestamp(value: Any, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ContractValidationError(f"{field_name} must be a datetime")
    return normalize_utc(value, field_name=field_name)


def _count(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or type(value) is not int:
        raise ContractValidationError(f"{field_name} must be an integer")
    if value < 0:
        raise ContractValidationError(f"{field_name} must be non-negative")
    return value


def _boolean(value: Any, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise ContractValidationError(f"{field_name} must be a boolean")
    return value


def _enum(value: Any, enum_type: type, *, field_name: str) -> Any:
    if type(value) is not enum_type:
        raise ContractValidationError(
            f"{field_name} must be exactly {enum_type.__name__}"
        )
    return value


def _zone_diagnostic_payload(diagnostic: ZoneDiagnostics) -> dict[str, Any]:
    return {
        "zone_id": diagnostic.zone_id,
        "side": diagnostic.side.value,
        "render_kind": diagnostic.render_kind.value,
        "available_at": canonical_timestamp(
            diagnostic.available_at,
            field_name="available_at",
        ),
        "terminal_at": (
            None
            if diagnostic.terminal_at is None
            else canonical_timestamp(
                diagnostic.terminal_at,
                field_name="terminal_at",
            )
        ),
        "final_status": diagnostic.final_status.value,
        "lifetime_bars": diagnostic.lifetime_bars,
        "touch_count": diagnostic.touch_count,
        "fakeout_count": diagnostic.fakeout_count,
        "first_touch_at": (
            None
            if diagnostic.first_touch_at is None
            else canonical_timestamp(
                diagnostic.first_touch_at,
                field_name="first_touch_at",
            )
        ),
        "time_to_first_touch_bars": diagnostic.time_to_first_touch_bars,
        "status_bar_counts": [
            [status.value, count] for status, count in diagnostic.status_bar_counts
        ],
        "left_censored": diagnostic.left_censored,
        "right_censored": diagnostic.right_censored,
    }


@dataclass(frozen=True)
class ZoneDiagnostics:
    zone_id: str
    side: ZoneSide
    render_kind: ZoneRenderKind
    available_at: datetime
    terminal_at: datetime | None
    final_status: ZoneStatus
    lifetime_bars: int
    touch_count: int
    fakeout_count: int
    first_touch_at: datetime | None
    time_to_first_touch_bars: int | None
    status_bar_counts: tuple[tuple[ZoneStatus, int], ...]
    left_censored: bool
    right_censored: bool
    diagnostic_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "zone_id", _hash(self.zone_id, field_name="zone_id"))
        object.__setattr__(
            self,
            "side",
            _enum(self.side, ZoneSide, field_name="side"),
        )
        object.__setattr__(
            self,
            "render_kind",
            _enum(self.render_kind, ZoneRenderKind, field_name="render_kind"),
        )
        object.__setattr__(
            self,
            "available_at",
            _timestamp(self.available_at, field_name="available_at"),
        )
        terminal_at = self.terminal_at
        if terminal_at is not None:
            terminal_at = _timestamp(terminal_at, field_name="terminal_at")
        object.__setattr__(self, "terminal_at", terminal_at)
        object.__setattr__(
            self,
            "final_status",
            _enum(self.final_status, ZoneStatus, field_name="final_status"),
        )
        for field_name in (
            "lifetime_bars",
            "touch_count",
            "fakeout_count",
        ):
            object.__setattr__(
                self,
                field_name,
                _count(getattr(self, field_name), field_name=field_name),
            )
        first_touch_at = self.first_touch_at
        if first_touch_at is not None:
            first_touch_at = _timestamp(
                first_touch_at,
                field_name="first_touch_at",
            )
        object.__setattr__(self, "first_touch_at", first_touch_at)
        if self.time_to_first_touch_bars is not None:
            object.__setattr__(
                self,
                "time_to_first_touch_bars",
                _count(
                    self.time_to_first_touch_bars,
                    field_name="time_to_first_touch_bars",
                ),
            )
        if type(self.status_bar_counts) is not tuple:
            raise ContractValidationError("status_bar_counts must be exactly a tuple")
        if len(self.status_bar_counts) != len(_STATUS_ORDER):
            raise ContractValidationError(
                "status_bar_counts must contain all four zone statuses"
            )
        normalized_counts: list[tuple[ZoneStatus, int]] = []
        for index, entry in enumerate(self.status_bar_counts):
            if type(entry) is not tuple or len(entry) != 2:
                raise ContractValidationError(
                    f"status_bar_counts[{index}] must be a pair tuple"
                )
            status = _enum(
                entry[0],
                ZoneStatus,
                field_name=f"status_bar_counts[{index}].status",
            )
            count = _count(
                entry[1],
                field_name=f"status_bar_counts[{index}].count",
            )
            normalized_counts.append((status, count))
        if tuple(status for status, _ in normalized_counts) != _STATUS_ORDER:
            raise ContractValidationError(
                "status_bar_counts must use fixed status order"
            )
        object.__setattr__(self, "status_bar_counts", tuple(normalized_counts))
        object.__setattr__(
            self,
            "left_censored",
            _boolean(self.left_censored, field_name="left_censored"),
        )
        object.__setattr__(
            self,
            "right_censored",
            _boolean(self.right_censored, field_name="right_censored"),
        )
        object.__setattr__(
            self,
            "diagnostic_id",
            evaluation_hash(_zone_diagnostic_payload(self)),
        )


@dataclass(frozen=True)
class SnapshotDiagnostics:
    snapshot_id: str
    as_of: datetime
    active_zone_count: int
    pending_zone_count: int
    live_zone_count: int
    new_terminal_zone_count: int
    event_count: int

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
        for field_name in (
            "active_zone_count",
            "pending_zone_count",
            "live_zone_count",
            "new_terminal_zone_count",
            "event_count",
        ):
            object.__setattr__(
                self,
                field_name,
                _count(getattr(self, field_name), field_name=field_name),
            )
        if self.live_zone_count != (
            self.active_zone_count + self.pending_zone_count
        ):
            raise ContractValidationError(
                "live_zone_count must equal active_zone_count + pending_zone_count"
            )


def _diagnostics_payload(diagnostics: SRDiagnostics) -> dict[str, Any]:
    scalar_fields = (
        "trace_id",
        "snapshot_count",
        "zone_count",
        "support_zone_count",
        "resistance_zone_count",
        "created_event_count",
        "touched_event_count",
        "breach_started_event_count",
        "false_breakout_event_count",
        "break_confirmed_event_count",
        "expired_event_count",
        "max_live_zone_count",
        "final_live_zone_count",
        "left_censored_zone_count",
        "right_censored_zone_count",
    )
    payload = {field_name: getattr(diagnostics, field_name) for field_name in scalar_fields}
    payload["snapshots"] = [
        {
            "snapshot_id": snapshot.snapshot_id,
            "as_of": canonical_timestamp(snapshot.as_of, field_name="as_of"),
            "active_zone_count": snapshot.active_zone_count,
            "pending_zone_count": snapshot.pending_zone_count,
            "live_zone_count": snapshot.live_zone_count,
            "new_terminal_zone_count": snapshot.new_terminal_zone_count,
            "event_count": snapshot.event_count,
        }
        for snapshot in diagnostics.snapshots
    ]
    payload["zones"] = [zone.diagnostic_id for zone in diagnostics.zones]
    return payload


@dataclass(frozen=True)
class SRDiagnostics:
    trace_id: str
    snapshot_count: int
    zone_count: int
    support_zone_count: int
    resistance_zone_count: int
    created_event_count: int
    touched_event_count: int
    breach_started_event_count: int
    false_breakout_event_count: int
    break_confirmed_event_count: int
    expired_event_count: int
    max_live_zone_count: int
    final_live_zone_count: int
    left_censored_zone_count: int
    right_censored_zone_count: int
    snapshots: tuple[SnapshotDiagnostics, ...]
    zones: tuple[ZoneDiagnostics, ...]
    diagnostics_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _hash(self.trace_id, field_name="trace_id"))
        scalar_fields = (
            "snapshot_count",
            "zone_count",
            "support_zone_count",
            "resistance_zone_count",
            "created_event_count",
            "touched_event_count",
            "breach_started_event_count",
            "false_breakout_event_count",
            "break_confirmed_event_count",
            "expired_event_count",
            "max_live_zone_count",
            "final_live_zone_count",
            "left_censored_zone_count",
            "right_censored_zone_count",
        )
        for field_name in scalar_fields:
            object.__setattr__(
                self,
                field_name,
                _count(getattr(self, field_name), field_name=field_name),
            )
        if type(self.snapshots) is not tuple or type(self.zones) is not tuple:
            raise ContractValidationError("diagnostic collections must be tuples")
        if any(type(item) is not SnapshotDiagnostics for item in self.snapshots):
            raise ContractValidationError(
                "snapshots must contain exactly SnapshotDiagnostics values"
            )
        if any(type(item) is not ZoneDiagnostics for item in self.zones):
            raise ContractValidationError(
                "zones must contain exactly ZoneDiagnostics values"
            )
        if self.snapshot_count != len(self.snapshots):
            raise ContractValidationError("snapshot_count does not reconcile")
        if self.zone_count != len(self.zones):
            raise ContractValidationError("zone_count does not reconcile")
        support_count = sum(zone.side is ZoneSide.SUPPORT for zone in self.zones)
        resistance_count = sum(
            zone.side is ZoneSide.RESISTANCE for zone in self.zones
        )
        if self.support_zone_count != support_count:
            raise ContractValidationError("support_zone_count does not reconcile")
        if self.resistance_zone_count != resistance_count:
            raise ContractValidationError(
                "resistance_zone_count does not reconcile"
            )
        event_counts = {
            SREventType.CREATED: self.created_event_count,
            SREventType.TOUCHED: self.touched_event_count,
            SREventType.BREACH_STARTED: self.breach_started_event_count,
            SREventType.FALSE_BREAKOUT: self.false_breakout_event_count,
            SREventType.BREAK_CONFIRMED: self.break_confirmed_event_count,
            SREventType.EXPIRED: self.expired_event_count,
        }
        if sum(event_counts.values()) != sum(
            snapshot.event_count for snapshot in self.snapshots
        ):
            raise ContractValidationError("event counts do not reconcile")
        if self.snapshots:
            max_live = max(snapshot.live_zone_count for snapshot in self.snapshots)
            final_live = self.snapshots[-1].live_zone_count
        else:
            max_live = 0
            final_live = 0
        if self.max_live_zone_count != max_live:
            raise ContractValidationError("max_live_zone_count does not reconcile")
        if self.final_live_zone_count != final_live:
            raise ContractValidationError("final_live_zone_count does not reconcile")
        left_count = sum(zone.left_censored for zone in self.zones)
        right_count = sum(zone.right_censored for zone in self.zones)
        if self.left_censored_zone_count != left_count:
            raise ContractValidationError(
                "left_censored_zone_count does not reconcile"
            )
        if self.right_censored_zone_count != right_count:
            raise ContractValidationError(
                "right_censored_zone_count does not reconcile"
            )
        object.__setattr__(
            self,
            "diagnostics_id",
            evaluation_hash(_diagnostics_payload(self)),
        )


def _zone_diagnostics(
    trace: SREvaluationTrace,
    observations: tuple[ZoneObservation, ...],
    events: tuple[ObservedEvent, ...],
    snapshot_positions: dict[str, int],
) -> ZoneDiagnostics:
    first = observations[0]
    final = observations[-1]
    terminal_values = [
        observation.visible_until
        for observation in observations
        if observation.visible_until is not None
    ]
    terminal_at = terminal_values[0] if terminal_values else None
    if any(value != terminal_at for value in terminal_values):
        raise ContractValidationError(
            "zone terminal_at must remain unchanged across observations"
        )
    left_censored = first.available_at < trace.snapshots[0].as_of
    first_touch_at = None
    time_to_first_touch_bars = None
    if not left_censored:
        touch_events = [
            event
            for event in events
            if event.event_type is SREventType.TOUCHED
        ]
        if touch_events:
            first_touch = touch_events[0]
            first_touch_at = first_touch.timestamp
            first_index = snapshot_positions[first.snapshot_id]
            touch_index = snapshot_positions[first_touch.snapshot_id]
            if touch_index < first_index:
                raise ContractValidationError(
                    "first touch cannot precede first zone observation"
                )
            time_to_first_touch_bars = touch_index - first_index

    status_counts = {status: 0 for status in _STATUS_ORDER}
    for observation in observations:
        if terminal_at is not None and observation.as_of > terminal_at:
            continue
        status_counts[observation.status] += 1
    return ZoneDiagnostics(
        zone_id=first.zone_id,
        side=first.side,
        render_kind=first.render_kind,
        available_at=first.available_at,
        terminal_at=terminal_at,
        final_status=final.status,
        lifetime_bars=final.age_bars,
        touch_count=final.touch_count,
        fakeout_count=final.fakeout_count,
        first_touch_at=first_touch_at,
        time_to_first_touch_bars=time_to_first_touch_bars,
        status_bar_counts=tuple(
            (status, status_counts[status]) for status in _STATUS_ORDER
        ),
        left_censored=left_censored,
        right_censored=final.status
        in {ZoneStatus.ACTIVE, ZoneStatus.BREACH_PENDING},
    )


def compute_diagnostics(trace: SREvaluationTrace) -> SRDiagnostics:
    """Compute descriptive, non-predictive diagnostics from one trace."""
    if type(trace) is not SREvaluationTrace:
        raise ContractValidationError("trace must be exactly SREvaluationTrace")

    snapshot_positions = {
        reference.snapshot_id: index
        for index, reference in enumerate(trace.snapshots)
    }
    observations_by_zone: dict[str, list[ZoneObservation]] = {}
    events_by_zone: dict[str, list[ObservedEvent]] = {}
    observations_by_snapshot: dict[str, list[ZoneObservation]] = {}
    events_by_snapshot: dict[str, list[ObservedEvent]] = {}
    for observation in trace.zone_observations:
        observations_by_zone.setdefault(observation.zone_id, []).append(observation)
        observations_by_snapshot.setdefault(observation.snapshot_id, []).append(
            observation
        )
    for event in trace.events:
        events_by_zone.setdefault(event.zone_id, []).append(event)
        events_by_snapshot.setdefault(event.snapshot_id, []).append(event)

    snapshot_diagnostics = tuple(
        SnapshotDiagnostics(
            snapshot_id=reference.snapshot_id,
            as_of=reference.as_of,
            active_zone_count=sum(
                observation.status is ZoneStatus.ACTIVE
                for observation in observations_by_snapshot.get(
                    reference.snapshot_id,
                    (),
                )
            ),
            pending_zone_count=sum(
                observation.status is ZoneStatus.BREACH_PENDING
                for observation in observations_by_snapshot.get(
                    reference.snapshot_id,
                    (),
                )
            ),
            live_zone_count=sum(
                observation.status
                in {ZoneStatus.ACTIVE, ZoneStatus.BREACH_PENDING}
                for observation in observations_by_snapshot.get(
                    reference.snapshot_id,
                    (),
                )
            ),
            new_terminal_zone_count=sum(
                event.event_type
                in {SREventType.BREAK_CONFIRMED, SREventType.EXPIRED}
                for event in events_by_snapshot.get(reference.snapshot_id, ())
            ),
            event_count=len(events_by_snapshot.get(reference.snapshot_id, ())),
        )
        for reference in trace.snapshots
    )
    ordered_zone_observations = sorted(
        observations_by_zone.items(),
        key=lambda item: (
            snapshot_positions[item[1][0].snapshot_id],
            item[0],
        ),
    )
    zone_diagnostics = tuple(
        _zone_diagnostics(
            trace,
            tuple(observations),
            tuple(events_by_zone.get(zone_id, ())),
            snapshot_positions,
        )
        for zone_id, observations in ordered_zone_observations
    )
    event_counts = {
        event_type: sum(event.event_type is event_type for event in trace.events)
        for event_type in _EVENT_TYPES
    }
    return SRDiagnostics(
        trace_id=trace.trace_id,
        snapshot_count=len(trace.snapshots),
        zone_count=len(zone_diagnostics),
        support_zone_count=sum(
            diagnostic.side is ZoneSide.SUPPORT for diagnostic in zone_diagnostics
        ),
        resistance_zone_count=sum(
            diagnostic.side is ZoneSide.RESISTANCE for diagnostic in zone_diagnostics
        ),
        created_event_count=event_counts[SREventType.CREATED],
        touched_event_count=event_counts[SREventType.TOUCHED],
        breach_started_event_count=event_counts[SREventType.BREACH_STARTED],
        false_breakout_event_count=event_counts[SREventType.FALSE_BREAKOUT],
        break_confirmed_event_count=event_counts[SREventType.BREAK_CONFIRMED],
        expired_event_count=event_counts[SREventType.EXPIRED],
        max_live_zone_count=max(
            snapshot.live_zone_count for snapshot in snapshot_diagnostics
        ),
        final_live_zone_count=snapshot_diagnostics[-1].live_zone_count,
        left_censored_zone_count=sum(
            diagnostic.left_censored for diagnostic in zone_diagnostics
        ),
        right_censored_zone_count=sum(
            diagnostic.right_censored for diagnostic in zone_diagnostics
        ),
        snapshots=snapshot_diagnostics,
        zones=zone_diagnostics,
    )


__all__ = [
    "SRDiagnostics",
    "SnapshotDiagnostics",
    "ZoneDiagnostics",
    "compute_diagnostics",
]
