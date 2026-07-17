from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from libs.models.sr import (
    AssociationConfig,
    ClosedBar,
    ContractValidationError,
    DetectionConfig,
    LifecycleConfig,
    ResolvedSRConfig,
    RuntimeConfig,
    SREventType,
    SREngine,
    SRStateKey,
    ZoneSide,
    create_initial_state,
)
from libs.models.sr.replay import replay_bars
from libs.models.sr.serialization import decode_state, encode_state


_T0 = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
_PARAMETER_PATHS = (
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


def _config(
    key: SRStateKey,
    *,
    max_age_bars: int = 5,
) -> ResolvedSRConfig:
    return ResolvedSRConfig.create(
        version="1",
        asset=key.symbol,
        timeframe=key.timeframe,
        detection=DetectionConfig(pivot_span_bars=1, zone_half_width_atr=0.0),
        association=AssociationConfig(merge_distance_atr=0.5),
        lifecycle=LifecycleConfig(
            touch_tolerance_atr=0.25,
            break_buffer_atr=0.5,
            break_confirm_closes=2,
            max_age_bars=max_age_bars,
        ),
        runtime=RuntimeConfig(max_active_zones=8),
        field_provenance={path: "defaults" for path in _PARAMETER_PATHS},
    )


def _bar(
    key: SRStateKey,
    index: int,
    *,
    open_: float,
    high: float,
    low: float,
    close: float,
    when: datetime | None = None,
) -> ClosedBar:
    return ClosedBar(
        state_key=key,
        bar_id=f"bar-{index}",
        closed_at=when or _T0 + timedelta(minutes=index),
        open=open_,
        high=high,
        low=low,
        close=close,
        atr_at_close=1.0,
    )


def _parity_sequence(key: SRStateKey) -> tuple[ClosedBar, ...]:
    return (
        _bar(key, 0, open_=97.5, high=100.0, low=95.0, close=97.5),
        _bar(key, 1, open_=100.0, high=110.0, low=90.0, close=100.0),
        _bar(key, 2, open_=97.5, high=101.0, low=94.0, close=97.5),
        _bar(key, 3, open_=100.0, high=111.0, low=89.0, close=100.0),
        _bar(key, 4, open_=112.0, high=113.0, low=99.0, close=112.0),
        _bar(key, 5, open_=100.0, high=111.0, low=89.0, close=100.0),
        _bar(key, 6, open_=112.0, high=113.0, low=99.0, close=112.0),
        _bar(key, 7, open_=112.0, high=113.0, low=99.0, close=112.0),
    )


def test_empty_replay_returns_unchanged_state() -> None:
    key = _key()
    config = _config(key)
    initial = create_initial_state(key, config)

    state, snapshots = replay_bars(initial, (), config)

    assert state is initial
    assert snapshots == ()


def test_one_bar_replay_matches_direct_engine_step() -> None:
    key = _key()
    config = _config(key)
    initial = create_initial_state(key, config)
    bar = _parity_sequence(key)[0]

    direct_state, direct_snapshot, _ = SREngine().step(initial, bar, config)
    replayed_state, snapshots = replay_bars(initial, (bar,), config)

    assert replayed_state == direct_state
    assert snapshots == (direct_snapshot,)


def test_multi_bar_replay_is_deterministic_and_preserves_order() -> None:
    key = _key()
    config = _config(key)
    initial = create_initial_state(key, config)
    bars = _parity_sequence(key)

    first = replay_bars(initial, bars, config)
    second = replay_bars(initial, bars, config)

    assert first == second
    assert [snapshot.as_of for snapshot in first[1]] == [bar.closed_at for bar in bars]
    assert [state_bar.bar_id for state_bar in first[0].recent_bars] == [
        bar.bar_id for bar in bars[-2:]
    ]
    assert first[0].last_processed_bar == bars[-1].bar_id


def test_checkpoint_resume_matches_uninterrupted_suffix_exactly() -> None:
    key = _key()
    config = _config(key)
    initial = create_initial_state(key, config)
    bars = _parity_sequence(key)

    full_state, full_snapshots = replay_bars(initial, bars, config)
    checkpoint_state, _ = replay_bars(initial, bars[:4], config)
    resumed_state = decode_state(encode_state(checkpoint_state))
    final_state, suffix_snapshots = replay_bars(
        resumed_state,
        bars[4:],
        config,
    )

    assert final_state == full_state
    assert suffix_snapshots == full_snapshots[4:]
    assert [snapshot.snapshot_id for snapshot in suffix_snapshots] == [
        snapshot.snapshot_id for snapshot in full_snapshots[4:]
    ]
    assert [snapshot.events for snapshot in suffix_snapshots] == [
        snapshot.events for snapshot in full_snapshots[4:]
    ]


def test_parity_sequence_exercises_detection_lifecycle_and_buffer_rollover() -> None:
    key = _key()
    config = _config(key)
    initial = create_initial_state(key, config)
    bars = _parity_sequence(key)
    final_state, snapshots = replay_bars(initial, bars, config)
    event_types = {
        event.event_type
        for snapshot in snapshots
        for event in snapshot.events
    }

    assert {ZoneSide.SUPPORT, ZoneSide.RESISTANCE} == {
        zone.definition.side for zone in snapshots[2].zones
    }
    assert {
        SREventType.CREATED,
        SREventType.TOUCHED,
        SREventType.BREACH_STARTED,
        SREventType.FALSE_BREAKOUT,
        SREventType.BREAK_CONFIRMED,
        SREventType.EXPIRED,
    } <= event_types
    assert len(snapshots) == len(bars)
    assert len(final_state.recent_bars) == 2


def test_snapshot_events_remain_authoritative_and_owned() -> None:
    key = _key()
    config = _config(key)
    state, snapshots = replay_bars(
        create_initial_state(key, config),
        _parity_sequence(key),
        config,
    )

    assert state.zones
    for snapshot in snapshots:
        zone_ids = {zone.definition.zone_id for zone in snapshot.zones}
        for event in snapshot.events:
            assert event.zone_id in zone_ids
            assert event.timestamp <= snapshot.as_of


def test_duplicate_id_within_batch_rejected_before_processing() -> None:
    key = _key()
    config = _config(key)
    initial = create_initial_state(key, config)
    bar = _parity_sequence(key)[0]

    with pytest.raises(ContractValidationError, match="duplicate bar_id"):
        replay_bars(initial, (bar, bar), config)


def test_duplicate_id_against_retained_buffer_rejected() -> None:
    key = _key()
    config = _config(key)
    initial = create_initial_state(key, config)
    bar = _parity_sequence(key)[0]
    checkpoint, _ = replay_bars(initial, (bar,), config)

    with pytest.raises(ContractValidationError, match="retained recent"):
        replay_bars(checkpoint, (bar,), config)


@pytest.mark.parametrize("mode", ["equal", "decreasing"])
def test_equal_or_decreasing_timestamps_rejected(mode: str) -> None:
    key = _key()
    config = _config(key)
    initial = create_initial_state(key, config)
    first = _parity_sequence(key)[0]
    second_time = first.closed_at if mode == "equal" else first.closed_at - timedelta(minutes=1)
    second = _bar(
        key,
        99,
        open_=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        when=second_time,
    )

    with pytest.raises(ContractValidationError, match="strictly increasing"):
        replay_bars(initial, (first, second), config)


def test_out_of_order_batch_rejected_without_sorting() -> None:
    key = _key()
    config = _config(key)
    initial = create_initial_state(key, config)
    bars = _parity_sequence(key)

    with pytest.raises(ContractValidationError, match="strictly increasing"):
        replay_bars(initial, (bars[1], bars[0]), config)


def test_mixed_state_key_rejected() -> None:
    key = _key()
    config = _config(key)
    initial = create_initial_state(key, config)
    other_key = _key(symbol="ETHUSDT")
    mixed = _bar(
        other_key,
        1,
        open_=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
    )

    with pytest.raises(ContractValidationError, match="state_key"):
        replay_bars(initial, (mixed,), config)


def test_state_config_mismatch_rejected() -> None:
    key = _key()
    initial_config = _config(key)
    other_config = _config(key, max_age_bars=6)
    initial = create_initial_state(key, initial_config)

    with pytest.raises(ContractValidationError, match="config_hash"):
        replay_bars(initial, (_parity_sequence(key)[0],), other_config)


def test_exact_config_type_required() -> None:
    key = _key()
    config = _config(key)
    initial = create_initial_state(key, config)

    with pytest.raises(ContractValidationError, match="ResolvedSRConfig"):
        replay_bars(initial, (), object())  # type: ignore[arg-type]


def test_positive_timestamp_gap_is_accepted_without_fill() -> None:
    key = _key()
    config = _config(key)
    initial = create_initial_state(key, config)
    first = _parity_sequence(key)[0]
    second = _bar(
        key,
        2,
        open_=100.0,
        high=101.0,
        low=99.0,
        close=100.0,
        when=first.closed_at + timedelta(days=3),
    )

    state, snapshots = replay_bars(initial, (first, second), config)

    assert len(snapshots) == 2
    assert state.last_processed_bar == second.bar_id
    assert [bar.bar_id for bar in state.recent_bars] == [first.bar_id, second.bar_id]


def test_invalid_batch_returns_no_partial_result_and_inputs_remain_unchanged() -> None:
    key = _key()
    config = _config(key)
    initial = create_initial_state(key, config)
    bars = _parity_sequence(key)
    invalid_batch = bars[:2] + (bars[1],)
    before = encode_state(initial)

    with pytest.raises(ContractValidationError):
        replay_bars(initial, invalid_batch, config)

    assert encode_state(initial) == before
    assert invalid_batch == bars[:2] + (bars[1],)


@pytest.mark.parametrize("bad_input", [object(), [], [None]])
def test_exact_input_types_required(bad_input: object) -> None:
    key = _key()
    config = _config(key)
    initial = create_initial_state(key, config)
    bar = _parity_sequence(key)[0]

    with pytest.raises(ContractValidationError):
        if isinstance(bad_input, list):
            replay_bars(initial, bad_input, config)  # type: ignore[arg-type]
        else:
            replay_bars(bad_input, (bar,), config)  # type: ignore[arg-type]
