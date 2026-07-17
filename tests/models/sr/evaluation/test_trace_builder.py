from __future__ import annotations

from datetime import timedelta

import pytest

from libs.models.sr import ClosedBar, ContractValidationError, create_initial_state
from libs.models.sr.evaluation import build_evaluation_trace
from libs.models.sr.replay import replay_bars

from .test_contracts import _T0, _config, _key, _record, _snapshot


def _bars(key) -> tuple[ClosedBar, ...]:
    values = (
        (97.5, 100.0, 95.0, 97.5),
        (100.0, 110.0, 90.0, 100.0),
        (97.5, 101.0, 94.0, 97.5),
        (100.0, 111.0, 89.0, 100.0),
        (112.0, 113.0, 99.0, 112.0),
        (100.0, 111.0, 89.0, 100.0),
        (112.0, 113.0, 99.0, 112.0),
        (112.0, 113.0, 99.0, 112.0),
    )
    return tuple(
        ClosedBar(
            state_key=key,
            bar_id=f"bar-{index}",
            closed_at=_T0 + timedelta(minutes=index),
            open=open_,
            high=high,
            low=low,
            close=close,
            atr_at_close=1.0,
        )
        for index, (open_, high, low, close) in enumerate(values)
    )


def _replayed():
    key = _key()
    config = _config(key)
    _, snapshots = replay_bars(
        create_initial_state(key, config),
        _bars(key),
        config,
    )
    return config, snapshots


def test_builder_preserves_authoritative_snapshot_order_and_values() -> None:
    config, snapshots = _replayed()

    trace = build_evaluation_trace(snapshots, config)

    assert [reference.snapshot_id for reference in trace.snapshots] == [
        snapshot.snapshot_id for snapshot in snapshots
    ]
    expected_observations = [
        (snapshot.snapshot_id, zone.definition.zone_id)
        for snapshot in snapshots
        for zone in snapshot.zones
    ]
    assert [
        (observation.snapshot_id, observation.zone_id)
        for observation in trace.zone_observations
    ] == expected_observations
    assert [event.event_id for event in trace.events] == [
        event.event_id
        for snapshot in snapshots
        for event in snapshot.events
    ]
    assert trace.field_provenance == config.field_provenance


def test_builder_rejects_empty_non_tuple_and_wrong_config() -> None:
    key = _key()
    config = _config(key)
    snapshot = _snapshot(config, zones=(_record(config),))

    with pytest.raises(ContractValidationError):
        build_evaluation_trace((), config)
    with pytest.raises(ContractValidationError):
        build_evaluation_trace([snapshot], config)  # type: ignore[arg-type]
    with pytest.raises(ContractValidationError):
        build_evaluation_trace((snapshot,), object())  # type: ignore[arg-type]


def test_builder_rejects_snapshot_config_and_order_mismatches() -> None:
    key = _key()
    config = _config(key)
    snapshot = _snapshot(config, zones=(_record(config),))
    other_config = _config(_key(symbol="ETHUSDT"))
    other_snapshot = _snapshot(
        other_config,
        as_of=_T0 + timedelta(minutes=1),
        zones=(_record(other_config, updated_at=_T0 + timedelta(minutes=1)),),
    )
    later_snapshot = _snapshot(
        config,
        as_of=_T0 + timedelta(minutes=1),
        zones=(_record(config, updated_at=_T0 + timedelta(minutes=1)),),
    )

    with pytest.raises(ContractValidationError, match="state_key"):
        build_evaluation_trace((snapshot, other_snapshot), config)
    with pytest.raises(ContractValidationError, match="strictly increasing"):
        build_evaluation_trace((later_snapshot, snapshot), config)


def test_delayed_pivot_visibility_uses_available_at() -> None:
    key = _key()
    config = _config(key)
    available_at = _T0 + timedelta(minutes=2)
    record = _record(
        config,
        created_at=_T0,
        available_at=available_at,
        updated_at=available_at,
    )
    snapshot = _snapshot(config, as_of=available_at, zones=(record,))

    trace = build_evaluation_trace((snapshot,), config)
    observation = trace.zone_observations[0]

    assert observation.created_at < observation.available_at
    assert observation.visible_from == available_at
    assert observation.visible_from <= observation.as_of


def test_terminal_zones_are_observed_with_frozen_visible_until() -> None:
    config, snapshots = _replayed()
    terminal_observations = {}
    trace = build_evaluation_trace(snapshots, config)

    for observation in trace.zone_observations:
        if observation.visible_until is not None:
            terminal_observations.setdefault(
                observation.zone_id,
                (observation.visible_until, observation.center),
            )
            assert terminal_observations[observation.zone_id] == (
                observation.visible_until,
                observation.center,
            )
    assert terminal_observations


def test_builder_does_not_mutate_snapshot_input() -> None:
    config, snapshots = _replayed()
    before = tuple(snapshots)

    build_evaluation_trace(snapshots, config)

    assert snapshots == before
