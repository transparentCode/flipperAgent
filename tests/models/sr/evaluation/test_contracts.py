from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import fields, replace

import pytest

from libs.models.sr import (
    AssociationConfig,
    ContractValidationError,
    DetectionConfig,
    LifecycleConfig,
    ResolvedSRConfig,
    RuntimeConfig,
    SREvent,
    SREventType,
    SRSnapshot,
    SRStateKey,
    ZoneDefinition,
    ZoneGeometry,
    ZoneRecord,
    ZoneRuntimeState,
    ZoneSide,
    ZoneStatus,
)
from libs.models.sr.evaluation import (
    ObservedEvent,
    SREvaluationTrace,
    SR_EVALUATION_SCHEMA_VERSION,
    SnapshotReference,
    ZoneObservation,
    ZoneRenderKind,
    build_evaluation_trace,
)


_T0 = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
_PATHS = (
    "detection.pivot_span_bars",
    "detection.zone_half_width_atr",
    "association.merge_distance_atr",
    "lifecycle.touch_tolerance_atr",
    "lifecycle.break_buffer_atr",
    "lifecycle.break_confirm_closes",
    "lifecycle.max_age_bars",
    "runtime.max_active_zones",
)


def _key(*, symbol: str = "BTCUSDT", timeframe: str = "1h") -> SRStateKey:
    return SRStateKey(venue="binance", symbol=symbol, timeframe=timeframe)


def _config(key: SRStateKey) -> ResolvedSRConfig:
    return ResolvedSRConfig.create(
        version="1",
        asset=key.symbol,
        timeframe=key.timeframe,
        detection=DetectionConfig(pivot_span_bars=1, zone_half_width_atr=0.25),
        association=AssociationConfig(merge_distance_atr=0.5),
        lifecycle=LifecycleConfig(
            touch_tolerance_atr=0.25,
            break_buffer_atr=0.5,
            break_confirm_closes=2,
            max_age_bars=50,
        ),
        runtime=RuntimeConfig(max_active_zones=8),
        field_provenance={path: "defaults" for path in _PATHS},
    )


def _record(
    config: ResolvedSRConfig,
    *,
    center: float = 100.0,
    half_width: float = 0.0,
    side: ZoneSide = ZoneSide.SUPPORT,
    status: ZoneStatus = ZoneStatus.ACTIVE,
    created_at: datetime = _T0,
    available_at: datetime = _T0,
    updated_at: datetime | None = None,
    age_bars: int = 0,
    touch_count: int = 0,
    fakeout_count: int = 0,
    pending_breach_count: int | None = None,
) -> ZoneRecord:
    definition = ZoneDefinition(
        state_key=_key(symbol=config.asset, timeframe=config.timeframe),
        side=side,
        geometry=ZoneGeometry(center=center, half_width=half_width),
        source="test",
        created_at=created_at,
        available_at=available_at,
        atr_at_creation=1.0,
        config_hash=config.resolved_config_hash,
    )
    updated_at = updated_at or available_at
    if pending_breach_count is None:
        pending_breach_count = 1 if status is ZoneStatus.BREACH_PENDING else 0
    return ZoneRecord(
        definition=definition,
        runtime=ZoneRuntimeState(
            zone_id=definition.zone_id,
            status=status,
            touch_count=touch_count,
            fakeout_count=fakeout_count,
            pending_breach_count=pending_breach_count,
            age_bars=age_bars,
            last_interaction_at=(
                updated_at if status is ZoneStatus.BREACH_PENDING else None
            ),
            updated_at=updated_at,
        ),
    )


def _snapshot(
    config: ResolvedSRConfig,
    *,
    as_of: datetime = _T0,
    zones: tuple[ZoneRecord, ...] = (),
    events: tuple[SREvent, ...] = (),
) -> SRSnapshot:
    return SRSnapshot(
        schema_version="1.0",
        state_key=_key(symbol=config.asset, timeframe=config.timeframe),
        config_hash=config.resolved_config_hash,
        as_of=as_of,
        zones=zones,
        events=events,
    )


def _event(
    zone_id: str,
    *,
    event_type: SREventType = SREventType.CREATED,
    timestamp: datetime = _T0,
    bar_id: str = "bar-1",
) -> SREvent:
    return SREvent(
        zone_id=zone_id,
        event_type=event_type,
        timestamp=timestamp,
        price=100.0,
        bar_id=bar_id,
    )


def test_evaluation_schema_and_render_kind_contracts() -> None:
    key = _key()
    config = _config(key)
    line = _record(config, center=100.0, half_width=0.0)
    band = _record(config, center=110.0, half_width=2.0, side=ZoneSide.RESISTANCE)
    trace = build_evaluation_trace(
        (_snapshot(config, zones=(line, band)),),
        config,
    )

    assert trace.schema_version == SR_EVALUATION_SCHEMA_VERSION
    assert {observation.render_kind for observation in trace.zone_observations} == {
        ZoneRenderKind.LINE,
        ZoneRenderKind.BAND,
    }
    line_observation = next(
        observation
        for observation in trace.zone_observations
        if observation.zone_id == line.definition.zone_id
    )
    assert line_observation.lower_bound == line_observation.center == 100.0
    assert line_observation.visible_from == line.definition.available_at


def test_terminal_and_live_visibility_windows_are_strict() -> None:
    key = _key()
    config = _config(key)
    live = _record(config, updated_at=_T0)
    terminal = _record(
        config,
        center=110.0,
        status=ZoneStatus.BROKEN,
        updated_at=_T0,
    )
    expired = _record(
        config,
        center=120.0,
        status=ZoneStatus.EXPIRED,
        updated_at=_T0,
    )
    trace = build_evaluation_trace(
        (_snapshot(config, zones=(live, terminal, expired)),),
        config,
    )
    by_zone = {observation.zone_id: observation for observation in trace.zone_observations}
    assert by_zone[live.definition.zone_id].visible_until is None
    assert by_zone[terminal.definition.zone_id].visible_until == _T0
    assert by_zone[expired.definition.zone_id].visible_until == _T0

    observation = by_zone[live.definition.zone_id]
    observation_fields = {
        field.name: getattr(observation, field.name)
        for field in fields(observation)
        if field.init
    }
    observation_fields["visible_until"] = _T0
    with pytest.raises(ContractValidationError):
        ZoneObservation(**observation_fields)


def test_snapshot_reference_and_observed_event_validate_causality() -> None:
    with pytest.raises(ContractValidationError):
        SnapshotReference("not-a-hash", _T0)

    snapshot_id = "a" * 64
    zone_id = "b" * 64
    future_event = SREvent(
        zone_id=zone_id,
        event_type=SREventType.TOUCHED,
        timestamp=_T0 + timedelta(seconds=1),
        price=100.0,
        bar_id="bar-1",
    )
    with pytest.raises(ContractValidationError, match="snapshot_as_of"):
        ObservedEvent(
            snapshot_id=snapshot_id,
            snapshot_as_of=_T0,
            event_id=future_event.event_id,
            zone_id=zone_id,
            event_type=SREventType.TOUCHED,
            timestamp=_T0 + timedelta(seconds=1),
            price=100.0,
            bar_id="bar-1",
        )


def test_trace_rejects_duplicate_identity_and_orphan_event() -> None:
    key = _key()
    config = _config(key)
    record = _record(config)
    snapshot = _snapshot(config, zones=(record,))
    reference = SnapshotReference(snapshot.snapshot_id, snapshot.as_of)
    orphan_event = SREvent(
        zone_id="d" * 64,
        event_type=SREventType.CREATED,
        timestamp=_T0,
        price=100.0,
        bar_id="bar-1",
    )
    event = ObservedEvent(
        snapshot_id=snapshot.snapshot_id,
        snapshot_as_of=snapshot.as_of,
        event_id=orphan_event.event_id,
        zone_id="d" * 64,
        event_type=SREventType.CREATED,
        timestamp=_T0,
        price=100.0,
        bar_id="bar-1",
    )
    with pytest.raises(ContractValidationError, match="unknown snapshot"):
        SREvaluationTrace(
            schema_version=SR_EVALUATION_SCHEMA_VERSION,
            state_key=key,
            config_hash=config.resolved_config_hash,
            field_provenance=config.field_provenance,
            snapshots=(reference,),
            zone_observations=(),
            events=(replace(event, snapshot_id="e" * 64),),
        )

    with pytest.raises(ContractValidationError, match="same snapshot"):
        SREvaluationTrace(
            schema_version=SR_EVALUATION_SCHEMA_VERSION,
            state_key=key,
            config_hash=config.resolved_config_hash,
            field_provenance=config.field_provenance,
            snapshots=(reference,),
            zone_observations=(),
            events=(event,),
        )

    with pytest.raises(ContractValidationError, match="snapshot IDs"):
        SREvaluationTrace(
            schema_version=SR_EVALUATION_SCHEMA_VERSION,
            state_key=key,
            config_hash=config.resolved_config_hash,
            field_provenance=config.field_provenance,
            snapshots=(reference, reference),
            zone_observations=(),
            events=(),
        )


def test_trace_freezes_atr_at_creation_for_each_zone_id() -> None:
    key = _key()
    config = _config(key)
    record = _record(config)
    first_snapshot = _snapshot(config, as_of=_T0, zones=(record,))
    second_snapshot = _snapshot(
        config,
        as_of=_T0 + timedelta(minutes=1),
        zones=(record,),
    )
    trace = build_evaluation_trace((first_snapshot, second_snapshot), config)
    first_observation, second_observation = trace.zone_observations
    changed_atr = replace(
        second_observation,
        atr_at_creation=second_observation.atr_at_creation + 1.0,
    )

    with pytest.raises(
        ContractValidationError,
        match="definition fields must remain unchanged",
    ):
        SREvaluationTrace(
            schema_version=trace.schema_version,
            state_key=trace.state_key,
            config_hash=trace.config_hash,
            field_provenance=trace.field_provenance,
            snapshots=trace.snapshots,
            zone_observations=(first_observation, changed_atr),
            events=trace.events,
        )


def test_observation_and_trace_ids_are_deterministic() -> None:
    key = _key()
    config = _config(key)
    snapshot = _snapshot(config, zones=(_record(config),))
    first = build_evaluation_trace((snapshot,), config)
    second = build_evaluation_trace((snapshot,), config)

    assert first == second
    assert first.trace_id == second.trace_id
    assert first.zone_observations[0].observation_id == (
        second.zone_observations[0].observation_id
    )
