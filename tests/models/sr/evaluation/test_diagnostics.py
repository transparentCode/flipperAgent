from __future__ import annotations

from datetime import timedelta

from libs.models.sr import SREventType, ZoneStatus
from libs.models.sr.evaluation import build_evaluation_trace, compute_diagnostics

from .test_trace_builder import _replayed


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
