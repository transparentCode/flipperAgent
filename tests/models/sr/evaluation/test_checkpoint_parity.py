from __future__ import annotations

from libs.models.sr import create_initial_state
from libs.models.sr.evaluation import (
    build_evaluation_trace,
    compute_diagnostics,
)
from libs.models.sr.replay import replay_bars
from libs.models.sr.serialization import decode_state, encode_state

from .test_trace_builder import _bars
from .test_contracts import _config, _key


def test_checkpoint_resume_matches_full_trace_suffix_exactly() -> None:
    key = _key()
    config = _config(key)
    bars = _bars(key)
    initial = create_initial_state(key, config)
    full_state, full_snapshots = replay_bars(initial, bars, config)
    checkpoint_state, _ = replay_bars(initial, bars[:4], config)
    resumed_state = decode_state(encode_state(checkpoint_state))
    _, suffix_snapshots = replay_bars(resumed_state, bars[4:], config)

    full_trace = build_evaluation_trace(full_snapshots, config)
    suffix_trace = build_evaluation_trace(suffix_snapshots, config)
    full_suffix_ids = {
        reference.snapshot_id for reference in suffix_trace.snapshots
    }
    expected_observations = tuple(
        observation
        for observation in full_trace.zone_observations
        if observation.snapshot_id in full_suffix_ids
    )
    expected_events = tuple(
        event for event in full_trace.events if event.snapshot_id in full_suffix_ids
    )

    assert suffix_trace.snapshots == full_trace.snapshots[4:]
    assert suffix_trace.zone_observations == expected_observations
    assert suffix_trace.events == expected_events
    assert [item.observation_id for item in suffix_trace.zone_observations] == [
        item.observation_id for item in expected_observations
    ]
    assert [item.event_id for item in suffix_trace.events] == [
        item.event_id for item in expected_events
    ]


def test_checkpoint_suffix_snapshot_diagnostics_are_exact() -> None:
    key = _key()
    config = _config(key)
    bars = _bars(key)
    initial = create_initial_state(key, config)
    _, full_snapshots = replay_bars(initial, bars, config)
    full_checkpoint, _ = replay_bars(initial, bars[:4], config)
    resumed = decode_state(encode_state(full_checkpoint))
    _, suffix_snapshots = replay_bars(resumed, bars[4:], config)

    full_diagnostics = compute_diagnostics(
        build_evaluation_trace(full_snapshots, config)
    )
    suffix_diagnostics = compute_diagnostics(
        build_evaluation_trace(suffix_snapshots, config)
    )

    assert suffix_diagnostics.snapshots == full_diagnostics.snapshots[4:]
    assert suffix_diagnostics.left_censored_zone_count > 0
