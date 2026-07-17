from __future__ import annotations

from datetime import timedelta

import pytest

from libs.models.sr import ContractValidationError, SREventType, ZoneSide, ZoneStatus
from libs.models.sr.evaluation import (
    SRDiagnostics,
    SnapshotDiagnostics,
    ZoneDiagnostics,
    ZoneRenderKind,
    build_evaluation_trace,
    compute_diagnostics,
)

from .test_contracts import _T0
from .test_trace_builder import _replayed


def _zone_diagnostic(
    *,
    zone_id: str = "a" * 64,
    final_status: ZoneStatus = ZoneStatus.ACTIVE,
    terminal_at=None,
    first_touch_at=None,
    time_to_first_touch_bars=None,
    left_censored: bool = False,
    right_censored: bool = True,
) -> ZoneDiagnostics:
    if final_status is ZoneStatus.BROKEN:
        status_bar_counts = (
            (ZoneStatus.ACTIVE, 0),
            (ZoneStatus.BREACH_PENDING, 0),
            (ZoneStatus.BROKEN, 1),
            (ZoneStatus.EXPIRED, 0),
        )
    elif final_status is ZoneStatus.EXPIRED:
        status_bar_counts = (
            (ZoneStatus.ACTIVE, 0),
            (ZoneStatus.BREACH_PENDING, 0),
            (ZoneStatus.BROKEN, 0),
            (ZoneStatus.EXPIRED, 1),
        )
    else:
        status_bar_counts = (
            (ZoneStatus.ACTIVE, 1),
            (ZoneStatus.BREACH_PENDING, 0),
            (ZoneStatus.BROKEN, 0),
            (ZoneStatus.EXPIRED, 0),
        )
    return ZoneDiagnostics(
        zone_id=zone_id,
        side=ZoneSide.SUPPORT,
        render_kind=ZoneRenderKind.LINE,
        available_at=_T0,
        terminal_at=terminal_at,
        final_status=final_status,
        lifetime_bars=1,
        touch_count=0,
        fakeout_count=0,
        first_touch_at=first_touch_at,
        time_to_first_touch_bars=time_to_first_touch_bars,
        status_bar_counts=status_bar_counts,
        left_censored=left_censored,
        right_censored=right_censored,
    )


def _snapshot_diagnostic(
    *,
    snapshot_id: str = "b" * 64,
    new_terminal_zone_count: int = 0,
    event_count: int = 0,
) -> SnapshotDiagnostics:
    return SnapshotDiagnostics(
        snapshot_id=snapshot_id,
        as_of=_T0,
        active_zone_count=0,
        pending_zone_count=0,
        live_zone_count=0,
        new_terminal_zone_count=new_terminal_zone_count,
        event_count=event_count,
    )


def _sr_diagnostics(
    *,
    snapshots: tuple[SnapshotDiagnostics, ...] = (),
    zones: tuple[ZoneDiagnostics, ...] = (),
    created_event_count: int = 0,
    break_confirmed_event_count: int = 0,
    expired_event_count: int = 0,
) -> SRDiagnostics:
    return SRDiagnostics(
        trace_id="c" * 64,
        snapshot_count=len(snapshots),
        zone_count=len(zones),
        support_zone_count=sum(zone.side is ZoneSide.SUPPORT for zone in zones),
        resistance_zone_count=sum(
            zone.side is ZoneSide.RESISTANCE for zone in zones
        ),
        created_event_count=created_event_count,
        touched_event_count=0,
        breach_started_event_count=0,
        false_breakout_event_count=0,
        break_confirmed_event_count=break_confirmed_event_count,
        expired_event_count=expired_event_count,
        max_live_zone_count=max(
            (snapshot.live_zone_count for snapshot in snapshots),
            default=0,
        ),
        final_live_zone_count=snapshots[-1].live_zone_count if snapshots else 0,
        left_censored_zone_count=sum(zone.left_censored for zone in zones),
        right_censored_zone_count=sum(zone.right_censored for zone in zones),
        snapshots=snapshots,
        zones=zones,
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        (
            {
                "final_status": ZoneStatus.BROKEN,
                "terminal_at": _T0,
                "right_censored": True,
            },
            "right-censored",
        ),
        (
            {
                "final_status": ZoneStatus.BROKEN,
                "right_censored": False,
            },
            "terminal_at",
        ),
        (
            {
                "left_censored": True,
                "first_touch_at": _T0,
                "time_to_first_touch_bars": 0,
            },
            "first-touch",
        ),
    ),
)
def test_zone_diagnostics_reject_contradictory_censoring(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ContractValidationError, match=message):
        _zone_diagnostic(**kwargs)


def test_snapshot_diagnostics_reject_terminal_count_above_event_count() -> None:
    with pytest.raises(ContractValidationError, match="new_terminal_zone_count"):
        _snapshot_diagnostic(new_terminal_zone_count=2, event_count=1)


def test_sr_diagnostics_reject_duplicate_snapshot_ids() -> None:
    snapshot = _snapshot_diagnostic()

    with pytest.raises(ContractValidationError, match="snapshot IDs"):
        _sr_diagnostics(snapshots=(snapshot, snapshot))


def test_sr_diagnostics_reject_duplicate_zone_ids() -> None:
    snapshot = _snapshot_diagnostic()
    zone = _zone_diagnostic()

    with pytest.raises(ContractValidationError, match="zone IDs"):
        _sr_diagnostics(snapshots=(snapshot,), zones=(zone, zone))


@pytest.mark.parametrize(
    ("new_terminal_zone_count", "break_confirmed_event_count"),
    ((1, 0), (0, 1)),
)
def test_sr_diagnostics_reconcile_nested_terminal_counts(
    new_terminal_zone_count: int,
    break_confirmed_event_count: int,
) -> None:
    snapshot = _snapshot_diagnostic(
        new_terminal_zone_count=new_terminal_zone_count,
        event_count=1,
    )

    with pytest.raises(ContractValidationError, match="terminal counts"):
        _sr_diagnostics(
            snapshots=(snapshot,),
            created_event_count=1 - break_confirmed_event_count,
            break_confirmed_event_count=break_confirmed_event_count,
        )


def test_diagnostics_reconcile_trace_events_and_zone_sides() -> None:
    config, snapshots = _replayed()
    trace = build_evaluation_trace(snapshots, config)

    diagnostics = compute_diagnostics(trace)

    assert diagnostics.trace_id == trace.trace_id
    assert diagnostics.snapshot_count == len(snapshots)
    assert diagnostics.zone_count == len(
        {observation.zone_id for observation in trace.zone_observations}
    )
    assert diagnostics.support_zone_count + diagnostics.resistance_zone_count == (
        diagnostics.zone_count
    )
    assert diagnostics.created_event_count == sum(
        event.event_type is SREventType.CREATED for event in trace.events
    )
    assert diagnostics.touched_event_count == sum(
        event.event_type is SREventType.TOUCHED for event in trace.events
    )
    assert diagnostics.breach_started_event_count == sum(
        event.event_type is SREventType.BREACH_STARTED for event in trace.events
    )
    assert diagnostics.false_breakout_event_count == sum(
        event.event_type is SREventType.FALSE_BREAKOUT for event in trace.events
    )
    assert diagnostics.break_confirmed_event_count == sum(
        event.event_type is SREventType.BREAK_CONFIRMED for event in trace.events
    )
    assert diagnostics.expired_event_count == sum(
        event.event_type is SREventType.EXPIRED for event in trace.events
    )
    assert diagnostics.max_live_zone_count == max(
        snapshot.live_zone_count for snapshot in diagnostics.snapshots
    )
    assert diagnostics.final_live_zone_count == diagnostics.snapshots[-1].live_zone_count


def test_snapshot_diagnostics_preserve_order_and_live_definitions() -> None:
    config, snapshots = _replayed()
    trace = build_evaluation_trace(snapshots, config)
    diagnostics = compute_diagnostics(trace)

    assert [item.snapshot_id for item in diagnostics.snapshots] == [
        snapshot.snapshot_id for snapshot in snapshots
    ]
    assert all(
        item.live_zone_count == item.active_zone_count + item.pending_zone_count
        for item in diagnostics.snapshots
    )
    assert any(
        item.new_terminal_zone_count > 0 for item in diagnostics.snapshots
    )


def test_zone_diagnostics_count_status_bars_only_through_terminal() -> None:
    config, snapshots = _replayed()
    trace = build_evaluation_trace(snapshots, config)
    diagnostics = compute_diagnostics(trace)
    observations_by_zone = {}
    for observation in trace.zone_observations:
        observations_by_zone.setdefault(observation.zone_id, []).append(observation)

    for zone in diagnostics.zones:
        observations = observations_by_zone[zone.zone_id]
        counted_bars = sum(count for _, count in zone.status_bar_counts)
        expected_bars = sum(
            observation.as_of <= zone.terminal_at
            if zone.terminal_at is not None
            else True
            for observation in observations
        )
        assert counted_bars == expected_bars
        assert zone.lifetime_bars == observations[-1].age_bars
        assert zone.touch_count == observations[-1].touch_count
        assert zone.fakeout_count == observations[-1].fakeout_count

    assert any(zone.final_status is ZoneStatus.BROKEN for zone in diagnostics.zones)


def test_terminal_status_duration_excludes_later_retained_observations() -> None:
    from .test_contracts import _T0, _config, _key, _record, _snapshot

    key = _key()
    config = _config(key)
    active = _record(config, updated_at=_T0)
    broken_at = _T0 + timedelta(minutes=1)
    broken = _record(
        config,
        status=ZoneStatus.BROKEN,
        updated_at=broken_at,
    )
    retained = _record(
        config,
        status=ZoneStatus.BROKEN,
        updated_at=broken_at,
    )
    trace = build_evaluation_trace(
        (
            _snapshot(config, as_of=_T0, zones=(active,)),
            _snapshot(config, as_of=broken_at, zones=(broken,)),
            _snapshot(
                config,
                as_of=broken_at + timedelta(minutes=1),
                zones=(retained,),
            ),
        ),
        config,
    )

    diagnostic = compute_diagnostics(trace).zones[0]

    assert diagnostic.terminal_at == broken_at
    assert sum(count for _, count in diagnostic.status_bar_counts) == 2
    assert diagnostic.status_bar_counts[0][1] == 1
    assert diagnostic.status_bar_counts[2][1] == 1


def test_left_and_right_censoring_are_explicit_for_suffix_trace() -> None:
    config, snapshots = _replayed()
    suffix = snapshots[4:]
    trace = build_evaluation_trace(suffix, config)

    diagnostics = compute_diagnostics(trace)

    assert diagnostics.left_censored_zone_count > 0
    assert all(
        zone.first_touch_at is None and zone.time_to_first_touch_bars is None
        for zone in diagnostics.zones
        if zone.left_censored
    )
    assert diagnostics.right_censored_zone_count >= 0


def test_diagnostics_are_deterministic_and_without_quality_metrics() -> None:
    config, snapshots = _replayed()
    trace = build_evaluation_trace(snapshots, config)

    first = compute_diagnostics(trace)
    second = compute_diagnostics(trace)

    assert first == second
    assert first.diagnostics_id == second.diagnostics_id
    assert not hasattr(first, "score")
    assert not hasattr(first, "quality")
