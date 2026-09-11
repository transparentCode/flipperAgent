"""Pure construction of causal SR observation traces."""

from __future__ import annotations

from libs.models.sr.config.models import ResolvedSRConfig
from libs.models.sr.domain.errors import ContractValidationError
from libs.models.sr.domain.events import SREvent
from libs.models.sr.domain.snapshots import SRSnapshot
from libs.models.sr.domain.zones import ZoneRecord, ZoneStatus

from .observations import (
    ObservedEvent,
    SR_EVALUATION_SCHEMA_VERSION,
    SnapshotReference,
    ZoneObservation,
    ZoneRenderKind,
)
from .traces import SREvaluationTrace


def _validate_inputs(
    snapshots: tuple[SRSnapshot, ...],
    resolved_config: ResolvedSRConfig,
) -> None:
    if type(snapshots) is not tuple:
        raise ContractValidationError(
            "snapshots must be exactly tuple[SRSnapshot, ...]"
        )
    if type(resolved_config) is not ResolvedSRConfig:
        raise ContractValidationError(
            "resolved_config must be exactly ResolvedSRConfig"
        )
    if not snapshots:
        raise ContractValidationError("snapshots must not be empty")
    if any(type(snapshot) is not SRSnapshot for snapshot in snapshots):
        raise ContractValidationError(
            "snapshots must contain exactly SRSnapshot values"
        )

    snapshot_ids: set[str] = set()
    previous_as_of = None
    first_snapshot = snapshots[0]
    expected_state_key = first_snapshot.state_key
    expected_schema = first_snapshot.schema_version
    expected_config_hash = first_snapshot.config_hash
    for index, snapshot in enumerate(snapshots):
        if snapshot.snapshot_id in snapshot_ids:
            raise ContractValidationError(
                f"duplicate snapshot_id at snapshots[{index}]"
            )
        snapshot_ids.add(snapshot.snapshot_id)
        if previous_as_of is not None and snapshot.as_of <= previous_as_of:
            raise ContractValidationError(
                "snapshots must be strictly increasing by as_of"
            )
        previous_as_of = snapshot.as_of
        if snapshot.schema_version != expected_schema:
            raise ContractValidationError(
                "snapshots must share one domain schema_version"
            )
        if snapshot.state_key != expected_state_key:
            raise ContractValidationError("snapshots must share one state_key")
        if snapshot.config_hash != expected_config_hash:
            raise ContractValidationError("snapshots must share one config_hash")
        if snapshot.config_hash != resolved_config.resolved_config_hash:
            raise ContractValidationError(
                "snapshot config_hash must match resolved configuration hash"
            )
        if (
            snapshot.state_key.symbol != resolved_config.asset
            or snapshot.state_key.timeframe != resolved_config.timeframe
        ):
            raise ContractValidationError(
                "snapshot symbol/timeframe must match resolved configuration"
            )


def _observation_for_zone(
    snapshot: SRSnapshot,
    record: ZoneRecord,
) -> ZoneObservation:
    definition = record.definition
    runtime = record.runtime
    render_kind = (
        ZoneRenderKind.LINE
        if definition.geometry.half_width == 0.0
        else ZoneRenderKind.BAND
    )
    visible_until = (
        runtime.updated_at
        if runtime.status in {ZoneStatus.BROKEN, ZoneStatus.EXPIRED}
        else None
    )
    return ZoneObservation(
        schema_version=SR_EVALUATION_SCHEMA_VERSION,
        state_key=snapshot.state_key,
        config_hash=snapshot.config_hash,
        snapshot_id=snapshot.snapshot_id,
        as_of=snapshot.as_of,
        zone_id=definition.zone_id,
        side=definition.side,
        source=definition.source,
        atr_at_creation=definition.atr_at_creation,
        render_kind=render_kind,
        lower_bound=definition.geometry.lower_bound,
        center=definition.geometry.center,
        upper_bound=definition.geometry.upper_bound,
        created_at=definition.created_at,
        available_at=definition.available_at,
        visible_from=definition.available_at,
        visible_until=visible_until,
        status=runtime.status,
        touch_count=runtime.touch_count,
        fakeout_count=runtime.fakeout_count,
        pending_breach_count=runtime.pending_breach_count,
        age_bars=runtime.age_bars,
        last_interaction_at=runtime.last_interaction_at,
        runtime_updated_at=runtime.updated_at,
    )


def _event_for_snapshot(snapshot: SRSnapshot, event: SREvent) -> ObservedEvent:
    return ObservedEvent(
        snapshot_id=snapshot.snapshot_id,
        snapshot_as_of=snapshot.as_of,
        event_id=event.event_id,
        zone_id=event.zone_id,
        event_type=event.event_type,
        timestamp=event.timestamp,
        price=event.price,
        bar_id=event.bar_id,
    )


def build_evaluation_trace(
    snapshots: tuple[SRSnapshot, ...],
    resolved_config: ResolvedSRConfig,
) -> SREvaluationTrace:
    """Build immutable causal observations from authoritative snapshots."""
    _validate_inputs(snapshots, resolved_config)

    references: list[SnapshotReference] = []
    observations: list[ZoneObservation] = []
    events: list[ObservedEvent] = []
    for snapshot in snapshots:
        references.append(
            SnapshotReference(
                snapshot_id=snapshot.snapshot_id,
                as_of=snapshot.as_of,
            )
        )
        observations.extend(
            _observation_for_zone(snapshot, record)
            for record in snapshot.zones
        )
        events.extend(
            _event_for_snapshot(snapshot, event)
            for event in snapshot.events
        )

    return SREvaluationTrace(
        schema_version=SR_EVALUATION_SCHEMA_VERSION,
        state_key=snapshots[0].state_key,
        config_hash=resolved_config.resolved_config_hash,
        field_provenance=resolved_config.field_provenance,
        snapshots=tuple(references),
        zone_observations=tuple(observations),
        events=tuple(events),
    )


__all__ = ["build_evaluation_trace"]
