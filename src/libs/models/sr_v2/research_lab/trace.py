"""Compact structural research trace and lifecycle tables."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any

from ..config.schema import validate_ladder
from ..contracts import LifecycleState, require_utc
from ..domain.bars import SRBar
from ..domain.identity import canonical_hash, canonical_json
from ..domain.zones import ZoneRecord
from ..lifecycle.transitions import LifecycleTransition, TransitionType


@dataclass(frozen=True, slots=True, kw_only=True)
class LifecycleInterval:
    zone_id: str
    source_timeframe: str
    lifecycle: str
    entered_at: datetime
    exited_at: datetime | None
    predecessor_id: str | None = None
    successor_id: str | None = None

    def __post_init__(self) -> None:
        if not self.zone_id.strip() or not self.source_timeframe.strip() or not self.lifecycle.strip():
            raise ValueError("lifecycle interval identity must be non-empty")
        require_utc(self.entered_at, field_name="entered_at")
        if self.exited_at is not None:
            require_utc(self.exited_at, field_name="exited_at")
            if self.exited_at < self.entered_at:
                raise ValueError("lifecycle interval must be half-open and ordered")

    @property
    def interval(self) -> tuple[datetime, datetime | None]:
        return self.entered_at, self.exited_at


@dataclass(frozen=True, slots=True, kw_only=True)
class TouchEpisode:
    zone_id: str
    source_timeframe: str
    episode_number: int
    started_at: datetime
    ended_at: datetime | None
    close_reason: str | None

    def __post_init__(self) -> None:
        if not self.zone_id.strip() or not self.source_timeframe.strip():
            raise ValueError("touch episode identity must be non-empty")
        if isinstance(self.episode_number, bool) or self.episode_number <= 0:
            raise ValueError("episode_number must be positive")
        require_utc(self.started_at, field_name="started_at")
        if self.ended_at is not None:
            require_utc(self.ended_at, field_name="ended_at")
            if self.ended_at < self.started_at:
                raise ValueError("touch episode must be ordered")
        if self.ended_at is None and self.close_reason is not None:
            raise ValueError("open touch episodes cannot have a close reason")


@dataclass(frozen=True, slots=True, kw_only=True)
class SnapshotZoneState:
    """Compact current state retained only for the final as-of snapshot."""

    zone_id: str
    source_timeframe: str
    lifecycle: LifecycleState
    touch_count: int
    was_overlapping: bool
    break_pending_count: int
    last_touch_at: datetime | None
    last_transition_at: datetime | None

    @classmethod
    def from_zone_record(cls, record: ZoneRecord) -> SnapshotZoneState:
        if not isinstance(record, ZoneRecord):
            raise TypeError("snapshot state requires ZoneRecord")
        return cls(
            zone_id=record.lineage.zone_id,
            source_timeframe=record.lineage.source_timeframe,
            lifecycle=record.lifecycle,
            touch_count=record.touch_count,
            was_overlapping=record.was_overlapping,
            break_pending_count=record.break_pending_count,
            last_touch_at=record.last_touch_at,
            last_transition_at=record.last_transition_at,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class ReplaySnapshot:
    cutoff: datetime
    current_price: object
    zones_by_timeframe: Mapping[str, tuple[SnapshotZoneState, ...]]
    candidates_by_timeframe: Mapping[str, tuple[object, ...]]
    transitions: tuple[LifecycleTransition, ...]
    replay_point_id: str

    def __post_init__(self) -> None:
        require_utc(self.cutoff, field_name="snapshot cutoff")
        if not self.replay_point_id.strip():
            raise ValueError("replay_point_id must be non-empty")
        zones = {key: tuple(value) for key, value in self.zones_by_timeframe.items()}
        if any(not isinstance(item, SnapshotZoneState) for values in zones.values() for item in values):
            raise TypeError("research snapshots must contain SnapshotZoneState values")
        object.__setattr__(self, "zones_by_timeframe", MappingProxyType(zones))
        object.__setattr__(self, "candidates_by_timeframe", MappingProxyType({key: tuple(value) for key, value in self.candidates_by_timeframe.items()}))
        object.__setattr__(self, "transitions", tuple(self.transitions))


@dataclass(frozen=True, slots=True, kw_only=True)
class SRV2ResearchTrace:
    schema_version: int
    source_manifest_id: str
    source_sha256: str
    config_fingerprint: str
    replay_id: str
    identity_mode: str
    analysis_start: datetime
    knowledge_cutoff: datetime
    reconstruction_start: datetime | None = None
    snapshots: tuple[ReplaySnapshot, ...] = ()
    lifecycle_intervals: tuple[LifecycleInterval, ...] = ()
    touch_episodes: tuple[TouchEpisode, ...] = ()
    configured_timeframes: tuple[str, ...] = ()
    transitions: tuple[LifecycleTransition, ...] = ()
    feature_rows: tuple[Mapping[str, Any], ...] = ()
    candidate_rows: tuple[Mapping[str, Any], ...] = ()
    lineage_records: Mapping[str, ZoneRecord] = field(default_factory=dict)
    bars_by_timeframe: Mapping[str, tuple[SRBar, ...]] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    _trace_id: str = field(default="", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.schema_version != 2:
            raise ValueError("unsupported research trace schema")
        if self.identity_mode not in {"EXACT_CHECKPOINT", "WINDOW_RELATIVE"}:
            raise ValueError("unsupported replay identity mode")
        require_utc(self.analysis_start, field_name="analysis_start")
        require_utc(self.knowledge_cutoff, field_name="knowledge_cutoff")
        if self.analysis_start >= self.knowledge_cutoff:
            raise ValueError("analysis_start must precede knowledge_cutoff")
        if self.reconstruction_start is None:
            object.__setattr__(self, "reconstruction_start", self.analysis_start)
        require_utc(self.reconstruction_start, field_name="reconstruction_start")
        if self.reconstruction_start > self.analysis_start:
            raise ValueError("reconstruction_start cannot follow analysis_start")
        configured = validate_ladder(tuple(self.configured_timeframes), "trace.configured_timeframes")
        object.__setattr__(self, "configured_timeframes", configured)
        snapshots = tuple(self.snapshots)
        if not snapshots:
            raise ValueError("research trace must contain a final snapshot")
        if snapshots[-1].cutoff != self.knowledge_cutoff:
            raise ValueError("research trace final snapshot must end at knowledge_cutoff")
        if any(not isinstance(item, LifecycleTransition) for item in self.transitions):
            raise TypeError("research transitions must contain LifecycleTransition values")
        if any(item.ordinal != index for index, item in enumerate(self.transitions)):
            raise ValueError("research transition ordinals must be contiguous")
        if set(self.bars_by_timeframe) != set(configured):
            raise ValueError("trace bars must cover the configured timeframe ladder")
        object.__setattr__(self, "snapshots", snapshots)
        object.__setattr__(self, "feature_rows", tuple(MappingProxyType(dict(row)) for row in self.feature_rows))
        object.__setattr__(self, "candidate_rows", tuple(MappingProxyType(dict(row)) for row in self.candidate_rows))
        object.__setattr__(self, "lineage_records", MappingProxyType(dict(self.lineage_records)))
        object.__setattr__(self, "bars_by_timeframe", MappingProxyType({key: tuple(value) for key, value in self.bars_by_timeframe.items()}))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        identity = {
            "schema_version": self.schema_version,
            "source_manifest_id": self.source_manifest_id,
            "source_sha256": self.source_sha256,
            "config_fingerprint": self.config_fingerprint,
            "replay_id": self.replay_id,
            "identity_mode": self.identity_mode,
            "analysis_start": self.analysis_start,
            "reconstruction_start": self.reconstruction_start,
            "knowledge_cutoff": self.knowledge_cutoff,
            "configured_timeframes": self.configured_timeframes,
            "snapshot": (snapshots[-1].cutoff, snapshots[-1].replay_point_id),
            "transitions": tuple((item.transition_id, item.ordinal) for item in self.transitions),
            "feature_rows_sha256": canonical_hash(self.feature_rows),
            "candidate_rows_sha256": canonical_hash(self.candidate_rows),
            "lifecycle_intervals_sha256": canonical_hash(self.lifecycle_intervals),
            "touch_episodes_sha256": canonical_hash(self.touch_episodes),
            "lineage_ids": tuple(sorted(self.lineage_records)),
            "bars_sha256": canonical_hash(self.bars_by_timeframe),
            "metadata_sha256": canonical_hash(self.metadata),
        }
        object.__setattr__(self, "_trace_id", canonical_hash(identity))

    @property
    def trace_id(self) -> str:
        return self._trace_id

    def to_mapping(self) -> Mapping[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_manifest_id": self.source_manifest_id,
            "source_sha256": self.source_sha256,
            "config_fingerprint": self.config_fingerprint,
            "replay_id": self.replay_id,
            "identity_mode": self.identity_mode,
            "analysis_start": self.analysis_start,
            "reconstruction_start": self.reconstruction_start,
            "knowledge_cutoff": self.knowledge_cutoff,
            "configured_timeframes": self.configured_timeframes,
            "snapshots": self.snapshots,
            "lifecycle_intervals": self.lifecycle_intervals,
            "touch_episodes": self.touch_episodes,
            "transitions": self.transitions,
            "feature_rows": self.feature_rows,
            "candidate_rows": self.candidate_rows,
            "lineage_records": self.lineage_records,
            "bars_by_timeframe": self.bars_by_timeframe,
            "metadata": self.metadata,
        }

    def to_json_bytes(self) -> bytes:
        return canonical_json(self.to_mapping()).encode("utf-8")


def build_lifecycle_tables(
    transitions: Sequence[LifecycleTransition],
    *,
    zones_by_id: Mapping[str, ZoneRecord],
    trace_end: datetime,
) -> tuple[tuple[LifecycleInterval, ...], tuple[TouchEpisode, ...]]:
    """Build half-open lifecycle/touch tables from typed transitions."""

    require_utc(trace_end, field_name="trace_end")
    interval_open: dict[str, LifecycleInterval] = {}
    intervals: list[LifecycleInterval] = []
    touch_open: dict[str, TouchEpisode] = {}
    touch_counts: dict[str, int] = {}
    episodes: list[TouchEpisode] = []
    for transition in transitions:
        zone = zones_by_id.get(transition.zone_id)
        if zone is None:
            raise ValueError(f"transition {transition.transition_id} has no retained lineage record")
        source_timeframe = zone.lineage.source_timeframe
        current = interval_open.get(transition.zone_id)
        if transition.transition_type is TransitionType.CREATED and transition.after_lifecycle is not None:
            interval_open[transition.zone_id] = LifecycleInterval(
                zone_id=transition.zone_id,
                source_timeframe=source_timeframe,
                lifecycle=transition.after_lifecycle.value,
                entered_at=transition.event_at,
                exited_at=None,
                predecessor_id=transition.predecessor_id,
                successor_id=transition.successor_id,
            )
        elif transition.after_lifecycle != transition.before_lifecycle and transition.after_lifecycle is not None:
            if current is not None:
                intervals.append(
                    LifecycleInterval(
                        zone_id=current.zone_id,
                        source_timeframe=current.source_timeframe,
                        lifecycle=current.lifecycle,
                        entered_at=current.entered_at,
                        exited_at=transition.event_at,
                        predecessor_id=current.predecessor_id,
                        successor_id=transition.successor_id,
                    )
                )
            interval_open[transition.zone_id] = LifecycleInterval(
                zone_id=transition.zone_id,
                source_timeframe=source_timeframe,
                lifecycle=transition.after_lifecycle.value,
                entered_at=transition.event_at,
                exited_at=None,
                predecessor_id=transition.predecessor_id,
                successor_id=transition.successor_id,
            )
        if transition.transition_type is TransitionType.TOUCH_STARTED:
            number = touch_counts.get(transition.zone_id, 0) + 1
            touch_counts[transition.zone_id] = number
            touch_open[transition.zone_id] = TouchEpisode(
                zone_id=transition.zone_id,
                source_timeframe=source_timeframe,
                episode_number=number,
                started_at=transition.event_at,
                ended_at=None,
                close_reason=None,
            )
        elif transition.transition_type is TransitionType.TOUCH_ENDED:
            current_touch = touch_open.pop(transition.zone_id, None)
            if current_touch is not None:
                episodes.append(
                    TouchEpisode(
                        zone_id=current_touch.zone_id,
                        source_timeframe=current_touch.source_timeframe,
                        episode_number=current_touch.episode_number,
                        started_at=current_touch.started_at,
                        ended_at=transition.event_at,
                        close_reason="OVERLAP_EXIT",
                    )
                )
        if transition.transition_type in {TransitionType.BROKEN, TransitionType.EXPIRED, TransitionType.SUPERSEDED}:
            terminal_touch = touch_open.pop(transition.zone_id, None)
            if terminal_touch is not None:
                episodes.append(
                    TouchEpisode(
                        zone_id=terminal_touch.zone_id,
                        source_timeframe=terminal_touch.source_timeframe,
                        episode_number=terminal_touch.episode_number,
                        started_at=terminal_touch.started_at,
                        ended_at=transition.event_at,
                        close_reason=transition.transition_type.value,
                    )
                )
    intervals.extend(interval_open.values())
    episodes.extend(touch_open.values())
    return tuple(intervals), tuple(episodes)


__all__ = [
    "LifecycleInterval",
    "ReplaySnapshot",
    "SRV2ResearchTrace",
    "SnapshotZoneState",
    "TouchEpisode",
    "build_lifecycle_tables",
]
