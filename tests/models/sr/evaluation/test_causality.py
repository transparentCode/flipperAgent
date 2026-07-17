from __future__ import annotations

from libs.models.sr import SREventType, ZoneStatus
from libs.models.sr.evaluation import build_evaluation_trace

from .test_trace_builder import _replayed


def _restricted(trace, snapshot_ids):
    snapshot_ids = set(snapshot_ids)
    return (
        tuple(
            observation
            for observation in trace.zone_observations
            if observation.snapshot_id in snapshot_ids
        ),
        tuple(event for event in trace.events if event.snapshot_id in snapshot_ids),
    )


def test_nonempty_prefix_preserves_prior_observations_and_events() -> None:
    config, snapshots = _replayed()
    full = build_evaluation_trace(snapshots, config)
    prefix = build_evaluation_trace(snapshots[:5], config)

    snapshot_ids = [reference.snapshot_id for reference in prefix.snapshots]
    expected_observations, expected_events = _restricted(full, snapshot_ids)
    assert prefix.zone_observations == expected_observations
    assert prefix.events == expected_events
    assert [item.observation_id for item in prefix.zone_observations] == [
        item.observation_id for item in expected_observations
    ]
    assert [item.event_id for item in prefix.events] == [
        item.event_id for item in expected_events
    ]


def test_extending_trace_does_not_rewrite_prior_records() -> None:
    config, snapshots = _replayed()
    prefix = build_evaluation_trace(snapshots[:4], config)
    extended = build_evaluation_trace(snapshots[:6], config)
    snapshot_ids = [reference.snapshot_id for reference in prefix.snapshots]

    expected_observations, expected_events = _restricted(extended, snapshot_ids)
    assert prefix.zone_observations == expected_observations
    assert prefix.events == expected_events
    assert all(
        reference.as_of <= prefix.snapshots[-1].as_of
        for reference in prefix.snapshots
    )


def test_fakeout_keeps_geometry_and_zone_identity_frozen() -> None:
    config, snapshots = _replayed()
    trace = build_evaluation_trace(snapshots, config)
    fakeout_events = [
        event
        for event in trace.events
        if event.event_type is SREventType.FALSE_BREAKOUT
    ]
    assert fakeout_events
    zone_id = fakeout_events[0].zone_id
    observations = [
        observation
        for observation in trace.zone_observations
        if observation.zone_id == zone_id
    ]
    assert any(observation.status is ZoneStatus.BREACH_PENDING for observation in observations)
    assert any(observation.status is ZoneStatus.ACTIVE for observation in observations)
    assert max(observation.fakeout_count for observation in observations) > 0
    assert len(
        {
            (
                observation.zone_id,
                observation.lower_bound,
                observation.center,
                observation.upper_bound,
                observation.created_at,
                observation.available_at,
                observation.visible_from,
            )
            for observation in observations
        }
    ) == 1
