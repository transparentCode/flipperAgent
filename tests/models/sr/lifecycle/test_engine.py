from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from libs.models.sr import (
    AssociationConfig,
    CandidateLevel,
    ClosedBar,
    ContractValidationError,
    DetectionConfig,
    LifecycleConfig,
    ResolvedSRConfig,
    RuntimeConfig,
    SREventType,
    SRState,
    SRStateKey,
    SREngine,
    ZoneDefinition,
    ZoneGeometry,
    ZoneRecord,
    ZoneRuntimeState,
    ZoneSide,
    ZoneStatus,
)
from libs.models.sr.detection import detect_confirmed_pivots


_T0 = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _key(*, symbol: str = "BTCUSDT", timeframe: str = "1h") -> SRStateKey:
    return SRStateKey(venue="binance", symbol=symbol, timeframe=timeframe)


def _config(
    key: SRStateKey,
    *,
    pivot_span_bars: int = 5,
    zone_half_width_atr: float = 0.25,
    merge_distance_atr: float = 0.5,
    break_confirm_closes: int = 2,
    max_age_bars: int = 50,
    touch_tolerance_atr: float = 0.25,
    break_buffer_atr: float = 0.5,
    max_active_zones: int = 8,
) -> ResolvedSRConfig:
    return ResolvedSRConfig.create(
        version="1",
        asset=key.symbol,
        timeframe=key.timeframe,
        detection=DetectionConfig(
            pivot_span_bars=pivot_span_bars,
            zone_half_width_atr=zone_half_width_atr,
        ),
        association=AssociationConfig(merge_distance_atr=merge_distance_atr),
        lifecycle=LifecycleConfig(
            touch_tolerance_atr=touch_tolerance_atr,
            break_buffer_atr=break_buffer_atr,
            break_confirm_closes=break_confirm_closes,
            max_age_bars=max_age_bars,
        ),
        runtime=RuntimeConfig(max_active_zones=max_active_zones),
        field_provenance={
            "detection.pivot_span_bars": "defaults",
            "detection.zone_half_width_atr": "defaults",
            "association.merge_distance_atr": "defaults",
            "lifecycle.touch_tolerance_atr": "defaults",
            "lifecycle.break_buffer_atr": "defaults",
            "lifecycle.break_confirm_closes": "defaults",
            "lifecycle.max_age_bars": "defaults",
            "runtime.max_active_zones": "defaults",
        },
    )


def _definition(
    config: ResolvedSRConfig,
    *,
    side: ZoneSide = ZoneSide.SUPPORT,
    center: float = 100.0,
    half_width: float = 5.0,
    available_at: datetime = _T0,
) -> ZoneDefinition:
    return ZoneDefinition(
        state_key=_key(symbol=config.asset, timeframe=config.timeframe),
        side=side,
        geometry=ZoneGeometry(center=center, half_width=half_width),
        source="test",
        created_at=available_at,
        available_at=available_at,
        atr_at_creation=2.0,
        config_hash=config.resolved_config_hash,
    )


def _runtime(
    definition: ZoneDefinition,
    *,
    status: ZoneStatus = ZoneStatus.ACTIVE,
    age_bars: int = 0,
    pending_breach_count: int = 0,
    touch_count: int = 0,
    fakeout_count: int = 0,
    last_interaction_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> ZoneRuntimeState:
    return ZoneRuntimeState(
        zone_id=definition.zone_id,
        status=status,
        touch_count=touch_count,
        fakeout_count=fakeout_count,
        pending_breach_count=pending_breach_count,
        age_bars=age_bars,
        last_interaction_at=last_interaction_at,
        updated_at=updated_at or definition.available_at,
    )


def _record(
    config: ResolvedSRConfig,
    *,
    side: ZoneSide = ZoneSide.SUPPORT,
    center: float = 100.0,
    status: ZoneStatus = ZoneStatus.ACTIVE,
    age_bars: int = 0,
    pending_breach_count: int = 0,
    touch_count: int = 0,
    fakeout_count: int = 0,
    last_interaction_at: datetime | None = None,
    updated_at: datetime | None = None,
    available_at: datetime = _T0,
    half_width: float = 5.0,
) -> ZoneRecord:
    definition = _definition(
        config,
        side=side,
        center=center,
        half_width=half_width,
        available_at=available_at,
    )
    return ZoneRecord(
        definition=definition,
        runtime=_runtime(
            definition,
            status=status,
            age_bars=age_bars,
            pending_breach_count=pending_breach_count,
            touch_count=touch_count,
            fakeout_count=fakeout_count,
            last_interaction_at=last_interaction_at,
            updated_at=updated_at,
        ),
    )


def _state(
    config: ResolvedSRConfig,
    *,
    zones: tuple[ZoneRecord, ...] = (),
    state_key: SRStateKey | None = None,
    config_hash: str | None = None,
    last_processed_bar: str | None = None,
    recent_bars: tuple[ClosedBar, ...] = (),
) -> SRState:
    state_key = state_key or _key(
        symbol=config.asset,
        timeframe=config.timeframe,
    )
    if not recent_bars and (zones or last_processed_bar is not None):
        last_processed_bar = last_processed_bar or "preexisting-bar"
        recent_bars = (
            _bar(
                state_key,
                bar_id=last_processed_bar,
                when=_T0 - timedelta(minutes=1),
            ),
        )
    return SRState(
        schema_version="1.0",
        state_key=state_key,
        config_hash=config_hash or config.resolved_config_hash,
        last_processed_bar=last_processed_bar,
        zones=zones,
        recent_bars=recent_bars,
    )


def _bar(
    key: SRStateKey,
    *,
    bar_id: str,
    when: datetime,
    close: float = 100.0,
    open: float = 100.0,
    high: float | None = None,
    low: float | None = None,
    atr_at_close: float = 1.0,
) -> ClosedBar:
    high = high if high is not None else max(open, close, 101.0)
    low = low if low is not None else min(open, close, 99.0)
    return ClosedBar(
        state_key=key,
        bar_id=bar_id,
        closed_at=when,
        open=open,
        high=high,
        low=low,
        close=close,
        atr_at_close=atr_at_close,
    )


def _event_types(events: tuple) -> tuple[SREventType, ...]:
    return tuple(event.event_type for event in events)


def _pivot_bar(
    key: SRStateKey,
    index: int,
    *,
    high: float,
    low: float,
    atr_at_close: float = 1.0,
) -> ClosedBar:
    price = (high + low) / 2
    return _bar(
        key,
        bar_id=f"pivot-{index}",
        when=_T0 + timedelta(minutes=index),
        open=price,
        high=high,
        low=low,
        close=price,
        atr_at_close=atr_at_close,
    )


def _both_side_pivot_bars(
    key: SRStateKey,
    *,
    confirmation_atr: float = 2.0,
) -> tuple[ClosedBar, ...]:
    return (
        _pivot_bar(key, 0, high=100.0, low=95.0),
        _pivot_bar(key, 1, high=110.0, low=90.0),
        _pivot_bar(
            key,
            2,
            high=101.0,
            low=94.0,
            atr_at_close=confirmation_atr,
        ),
    )


def test_availability_bar_is_not_eligible() -> None:
    key = _key()
    config = _config(key)
    record = _record(config)
    state = _state(config, zones=(record,))
    bar = _bar(key, bar_id="availability", when=_T0, close=93.0)

    next_state, snapshot, events = SREngine().step(state, bar, config)

    assert next_state.zones[0] == record
    assert next_state.last_processed_bar == "availability"
    assert snapshot.as_of == _T0
    assert events == snapshot.events == ()


def test_first_eligible_bar_advances_age_and_runtime_time() -> None:
    key = _key()
    config = _config(key)
    state = _state(config, zones=(_record(config),))
    when = _T0 + timedelta(minutes=1)

    next_state, _, events = SREngine().step(
        state,
        _bar(
            key,
            bar_id="eligible",
            when=when,
            open=120.0,
            high=121.0,
            low=119.0,
            close=120.0,
        ),
        config,
    )

    runtime = next_state.zones[0].runtime
    assert runtime.age_bars == 1
    assert runtime.updated_at == when
    assert events == ()


def test_active_touch_records_only_touch_event() -> None:
    key = _key()
    config = _config(key)
    state = _state(config, zones=(_record(config),))
    when = _T0 + timedelta(minutes=1)
    bar = _bar(key, bar_id="touch", when=when, high=101.0, low=94.0)

    next_state, snapshot, events = SREngine().step(state, bar, config)

    runtime = next_state.zones[0].runtime
    assert runtime.status is ZoneStatus.ACTIVE
    assert runtime.touch_count == 1
    assert runtime.fakeout_count == 0
    assert runtime.last_interaction_at == when
    assert _event_types(events) == (SREventType.TOUCHED,)
    assert events == snapshot.events
    assert events[0].price == bar.close
    assert events[0].bar_id == bar.bar_id


def test_active_breach_starts_pending_and_suppresses_touch() -> None:
    key = _key()
    config = _config(key, break_confirm_closes=3)
    state = _state(config, zones=(_record(config),))
    when = _T0 + timedelta(minutes=1)
    bar = _bar(key, bar_id="breach-start", when=when, close=93.0)

    next_state, _, events = SREngine().step(state, bar, config)

    runtime = next_state.zones[0].runtime
    assert runtime.status is ZoneStatus.BREACH_PENDING
    assert runtime.pending_breach_count == 1
    assert runtime.touch_count == 0
    assert runtime.last_interaction_at == when
    assert _event_types(events) == (SREventType.BREACH_STARTED,)


def test_pending_breach_confirms_after_required_consecutive_closes() -> None:
    key = _key()
    config = _config(key, break_confirm_closes=3)
    record = _record(config)
    state = _state(config, zones=(record,))
    engine = SREngine()

    first, _, first_events = engine.step(
        state,
        _bar(key, bar_id="break-1", when=_T0 + timedelta(minutes=1), close=93.0),
        config,
    )
    second, _, second_events = engine.step(
        first,
        _bar(key, bar_id="break-2", when=_T0 + timedelta(minutes=2), close=93.0),
        config,
    )
    third, snapshot, third_events = engine.step(
        second,
        _bar(key, bar_id="break-3", when=_T0 + timedelta(minutes=3), close=93.0),
        config,
    )

    assert _event_types(first_events) == (SREventType.BREACH_STARTED,)
    assert second.zones[0].runtime.status is ZoneStatus.BREACH_PENDING
    assert second.zones[0].runtime.pending_breach_count == 2
    assert second_events == ()
    assert third.zones[0].runtime.status is ZoneStatus.BROKEN
    assert third.zones[0].runtime.pending_breach_count == 0
    assert _event_types(third_events) == (SREventType.BREAK_CONFIRMED,)
    assert third_events == snapshot.events


def test_direct_break_with_one_confirmation_emits_start_then_confirm() -> None:
    key = _key()
    config = _config(key, break_confirm_closes=1)
    state = _state(config, zones=(_record(config),))
    when = _T0 + timedelta(minutes=1)

    next_state, _, events = SREngine().step(
        state, _bar(key, bar_id="direct-break", when=when, close=93.0), config
    )

    assert next_state.zones[0].runtime.status is ZoneStatus.BROKEN
    assert _event_types(events) == (
        SREventType.BREACH_STARTED,
        SREventType.BREAK_CONFIRMED,
    )


def test_pending_breach_resolves_as_fakeout_without_touch() -> None:
    key = _key()
    config = _config(key, break_confirm_closes=3)
    state = _state(config, zones=(_record(config),))
    engine = SREngine()
    pending, _, _ = engine.step(
        state,
        _bar(key, bar_id="break", when=_T0 + timedelta(minutes=1), close=93.0),
        config,
    )

    next_state, _, events = engine.step(
        pending,
        _bar(
            key,
            bar_id="fakeout",
            when=_T0 + timedelta(minutes=2),
            close=100.0,
            high=101.0,
            low=94.0,
        ),
        config,
    )

    runtime = next_state.zones[0].runtime
    assert runtime.status is ZoneStatus.ACTIVE
    assert runtime.pending_breach_count == 0
    assert runtime.fakeout_count == 1
    assert runtime.touch_count == 0
    assert _event_types(events) == (SREventType.FALSE_BREAKOUT,)


def test_fakeout_episode_can_start_again_later() -> None:
    key = _key()
    config = _config(key, break_confirm_closes=3)
    state = _state(config, zones=(_record(config),))
    engine = SREngine()
    pending, _, _ = engine.step(
        state,
        _bar(key, bar_id="break-1", when=_T0 + timedelta(minutes=1), close=93.0),
        config,
    )
    active, _, fakeout_events = engine.step(
        pending,
        _bar(key, bar_id="fakeout", when=_T0 + timedelta(minutes=2)),
        config,
    )
    next_state, _, breach_events = engine.step(
        active,
        _bar(key, bar_id="break-2", when=_T0 + timedelta(minutes=3), close=93.0),
        config,
    )

    assert _event_types(fakeout_events) == (SREventType.FALSE_BREAKOUT,)
    assert _event_types(breach_events) == (SREventType.BREACH_STARTED,)
    assert next_state.zones[0].runtime.pending_breach_count == 1
    assert next_state.zones[0].runtime.fakeout_count == 1


def test_touch_then_expiry_emits_both_events_and_expires() -> None:
    key = _key()
    config = _config(key, max_age_bars=1)
    state = _state(config, zones=(_record(config),))
    when = _T0 + timedelta(minutes=1)

    next_state, _, events = SREngine().step(
        state,
        _bar(key, bar_id="touch-expire", when=when, high=101.0, low=94.0),
        config,
    )

    runtime = next_state.zones[0].runtime
    assert runtime.status is ZoneStatus.EXPIRED
    assert runtime.touch_count == 1
    assert set(_event_types(events)) == {
        SREventType.TOUCHED,
        SREventType.EXPIRED,
    }


def test_unconfirmed_breach_then_expiry_clears_pending() -> None:
    key = _key()
    config = _config(key, break_confirm_closes=2, max_age_bars=1)
    state = _state(config, zones=(_record(config),))
    when = _T0 + timedelta(minutes=1)

    next_state, _, events = SREngine().step(
        state, _bar(key, bar_id="breach-expire", when=when, close=93.0), config
    )

    runtime = next_state.zones[0].runtime
    assert runtime.status is ZoneStatus.EXPIRED
    assert runtime.pending_breach_count == 0
    assert _event_types(events) == (
        SREventType.BREACH_STARTED,
        SREventType.EXPIRED,
    )


def test_confirmed_break_wins_over_same_bar_expiry() -> None:
    key = _key()
    config = _config(key, break_confirm_closes=1, max_age_bars=1)
    state = _state(config, zones=(_record(config),))
    when = _T0 + timedelta(minutes=1)

    next_state, _, events = SREngine().step(
        state, _bar(key, bar_id="break-expire", when=when, close=93.0), config
    )

    assert next_state.zones[0].runtime.status is ZoneStatus.BROKEN
    assert SREventType.EXPIRED not in _event_types(events)


def test_pending_fakeout_can_expire_after_interaction() -> None:
    key = _key()
    config = _config(key, break_confirm_closes=3, max_age_bars=2)
    state = _state(config, zones=(_record(config),))
    engine = SREngine()
    pending, _, _ = engine.step(
        state,
        _bar(key, bar_id="break", when=_T0 + timedelta(minutes=1), close=93.0),
        config,
    )

    next_state, _, events = engine.step(
        pending,
        _bar(key, bar_id="fakeout-expire", when=_T0 + timedelta(minutes=2)),
        config,
    )

    assert next_state.zones[0].runtime.status is ZoneStatus.EXPIRED
    assert set(_event_types(events)) == {
        SREventType.FALSE_BREAKOUT,
        SREventType.EXPIRED,
    }


@pytest.mark.parametrize("status", [ZoneStatus.BROKEN, ZoneStatus.EXPIRED])
def test_terminal_zones_are_inert_and_do_not_age(status: ZoneStatus) -> None:
    key = _key()
    config = _config(key)
    record = _record(config, status=status, age_bars=7)
    state = _state(config, zones=(record,))
    bar = _bar(key, bar_id="terminal", when=_T0 + timedelta(minutes=1), close=93.0)

    next_state, _, events = SREngine().step(state, bar, config)

    assert next_state.zones[0] is record
    assert next_state.zones[0].runtime.age_bars == 7
    assert next_state.last_processed_bar == "terminal"
    assert events == ()


def test_empty_state_advances_without_events() -> None:
    key = _key()
    config = _config(key)
    state = _state(config)
    bar = _bar(key, bar_id="empty", when=_T0 + timedelta(minutes=1))

    next_state, snapshot, events = SREngine().step(state, bar, config)

    assert next_state.zones == ()
    assert snapshot.zones == ()
    assert events == ()
    assert next_state.last_processed_bar == "empty"


def test_definitions_and_geometry_are_reused_unchanged() -> None:
    key = _key()
    config = _config(key)
    record = _record(config)
    state = _state(config, zones=(record,))
    bar = _bar(key, bar_id="next", when=_T0 + timedelta(minutes=1))

    next_state, _, _ = SREngine().step(state, bar, config)

    assert state.zones == (record,)
    assert next_state.zones[0].definition is record.definition
    assert next_state.zones[0].definition.geometry is record.definition.geometry
    assert next_state.zones[0].definition.zone_id == record.definition.zone_id


def test_support_and_resistance_zones_transition_independently() -> None:
    key = _key()
    config = _config(key, break_confirm_closes=3)
    support = _record(config, side=ZoneSide.SUPPORT, center=100.0)
    resistance = _record(config, side=ZoneSide.RESISTANCE, center=110.0)
    state = _state(config, zones=(support, resistance))
    bar = _bar(
        key,
        bar_id="support-only-break",
        when=_T0 + timedelta(minutes=1),
        close=93.0,
    )

    next_state, _, events = SREngine().step(state, bar, config)

    by_side = {
        record.definition.side: record.runtime for record in next_state.zones
    }
    assert by_side[ZoneSide.SUPPORT].status is ZoneStatus.BREACH_PENDING
    assert by_side[ZoneSide.RESISTANCE].status is ZoneStatus.ACTIVE
    assert by_side[ZoneSide.RESISTANCE].age_bars == 1
    assert len(events) == 1
    assert events[0].zone_id == support.definition.zone_id


def test_multiple_zones_have_stable_state_and_event_order() -> None:
    key = _key()
    config = _config(key)
    support = _record(config, side=ZoneSide.SUPPORT, center=100.0)
    resistance = _record(config, side=ZoneSide.RESISTANCE, center=110.0)
    state = _state(config, zones=(support, resistance))
    bar = _bar(
        key,
        bar_id="both-touch",
        when=_T0 + timedelta(minutes=1),
        high=112.0,
        low=88.0,
    )
    engine = SREngine()

    first = engine.step(state, bar, config)
    second = engine.step(state, bar, config)

    assert first == second
    assert first[2] == first[1].events
    assert [event.zone_id for event in first[2]] == sorted(
        event.zone_id for event in first[2]
    )


@pytest.mark.parametrize(
    "bad_input, expected",
    [
        ("state", "previous_state must be SRState"),
        ("bar", "closed_bar must be ClosedBar"),
        ("config", "resolved_config must be ResolvedSRConfig"),
    ],
)
def test_step_rejects_wrong_input_types(bad_input: str, expected: str) -> None:
    key = _key()
    config = _config(key)
    state = _state(config)
    bar = _bar(key, bar_id="bar", when=_T0 + timedelta(minutes=1))
    args: list[object] = [state, bar, config]
    args[{"state": 0, "bar": 1, "config": 2}[bad_input]] = object()

    with pytest.raises(ContractValidationError, match=expected):
        SREngine().step(*args)  # type: ignore[arg-type]


def test_step_rejects_state_key_mismatch() -> None:
    key = _key()
    config = _config(key)
    state = _state(config)
    bar = _bar(
        _key(symbol="ETHUSDT"),
        bar_id="wrong-key",
        when=_T0 + timedelta(minutes=1),
    )

    with pytest.raises(ContractValidationError, match="state_key"):
        SREngine().step(state, bar, config)


def test_step_rejects_state_config_identity_mismatch() -> None:
    key = _key()
    config = _config(key)
    state = _state(config, config_hash="b" * 64)
    bar = _bar(key, bar_id="wrong-hash", when=_T0 + timedelta(minutes=1))

    with pytest.raises(ContractValidationError, match="config_hash"):
        SREngine().step(state, bar, config)


def test_step_rejects_state_symbol_or_timeframe_mismatch() -> None:
    key = _key()
    config = _config(key)
    wrong_key = _key(symbol="ETHUSDT")
    wrong_state = _state(config, state_key=wrong_key)
    bar = _bar(wrong_key, bar_id="wrong-owner", when=_T0 + timedelta(minutes=1))

    with pytest.raises(ContractValidationError, match="symbol/timeframe"):
        SREngine().step(wrong_state, bar, config)


def test_step_rejects_duplicate_last_processed_bar() -> None:
    key = _key()
    config = _config(key)
    state = _state(config, last_processed_bar="duplicate")
    bar = _bar(key, bar_id="duplicate", when=_T0 + timedelta(minutes=1))

    with pytest.raises(ContractValidationError, match="duplicates"):
        SREngine().step(state, bar, config)


def test_step_rejects_bar_older_than_runtime_update() -> None:
    key = _key()
    config = _config(key)
    updated_at = _T0 + timedelta(minutes=2)
    record = _record(config, updated_at=updated_at)
    state = _state(config, zones=(record,))
    bar = _bar(key, bar_id="older", when=_T0 + timedelta(minutes=1))

    with pytest.raises(ContractValidationError, match="runtime.updated_at"):
        SREngine().step(state, bar, config)


@pytest.mark.parametrize(
    "status, age_bars, pending_breach_count, close, expected_message",
    [
        (
            ZoneStatus.ACTIVE,
            50,
            0,
            93.0,
            "age_bars",
        ),
        (
            ZoneStatus.ACTIVE,
            50,
            0,
            100.0,
            "age_bars",
        ),
        (
            ZoneStatus.BREACH_PENDING,
            0,
            2,
            93.0,
            "pending_breach_count",
        ),
        (
            ZoneStatus.BREACH_PENDING,
            0,
            2,
            100.0,
            "pending_breach_count",
        ),
    ],
)
def test_step_rejects_config_inconsistent_non_terminal_state(
    status: ZoneStatus,
    age_bars: int,
    pending_breach_count: int,
    close: float,
    expected_message: str,
) -> None:
    key = _key()
    config = _config(key, break_confirm_closes=2, max_age_bars=50)
    record = _record(
        config,
        status=status,
        age_bars=age_bars,
        pending_breach_count=pending_breach_count,
    )
    state = _state(config, zones=(record,))
    bar = _bar(
        key,
        bar_id=f"invalid-{status.value}-{close}",
        when=_T0 + timedelta(minutes=1),
        close=close,
    )

    with pytest.raises(ContractValidationError, match=expected_message):
        SREngine().step(state, bar, config)


def test_engine_warmup_then_creates_confirmed_pivots() -> None:
    key = _key()
    config = _config(
        key,
        pivot_span_bars=1,
        zone_half_width_atr=0.25,
    )
    state = _state(config)
    engine = SREngine()
    bars = _both_side_pivot_bars(key, confirmation_atr=2.0)

    for bar in bars[:2]:
        state, snapshot, events = engine.step(state, bar, config)
        assert events == snapshot.events == ()
        assert state.zones == ()

    state, snapshot, events = engine.step(state, bars[2], config)

    assert len(state.zones) == 2
    assert len(state.recent_bars) == 2
    assert state.recent_bars == bars[1:]
    assert len(events) == 2
    assert all(event.event_type is SREventType.CREATED for event in events)
    assert all(event.bar_id == bars[2].bar_id for event in events)
    assert snapshot.zones == state.zones
    assert not hasattr(snapshot, "recent_bars")
    for record in state.zones:
        assert record.runtime.status is ZoneStatus.ACTIVE
        assert record.runtime.age_bars == 0
        assert record.runtime.touch_count == 0
        assert record.runtime.fakeout_count == 0
        assert record.runtime.pending_breach_count == 0
        assert record.runtime.last_interaction_at is None
        assert record.runtime.updated_at == bars[2].closed_at
        assert record.definition.source == "pivot_v1"
        assert record.definition.created_at == bars[1].closed_at
        assert record.definition.available_at == bars[2].closed_at
        assert record.definition.atr_at_creation == 2.0
        assert record.definition.geometry.half_width == 0.5
        assert record.definition.config_hash == config.resolved_config_hash
        created = next(
            event
            for event in events
            if event.zone_id == record.definition.zone_id
        )
        assert created.timestamp == bars[2].closed_at
        assert created.price == record.definition.geometry.center


def test_matched_candidate_is_suppressed_without_mutating_existing_zone() -> None:
    key = _key()
    config = _config(key, pivot_span_bars=1, zone_half_width_atr=0.25)
    bars = (
        _pivot_bar(key, 0, high=100.0, low=90.0),
        _pivot_bar(key, 1, high=110.0, low=95.0),
        _pivot_bar(
            key,
            2,
            high=101.0,
            low=94.0,
            atr_at_close=2.0,
        ),
    )
    record = _record(
        config,
        side=ZoneSide.RESISTANCE,
        center=110.0,
        half_width=0.0,
        available_at=bars[2].closed_at,
    )
    state = _state(
        config,
        zones=(record,),
        last_processed_bar=bars[1].bar_id,
        recent_bars=bars[:2],
    )

    next_state, snapshot, events = SREngine().step(state, bars[2], config)

    assert next_state.zones == (record,)
    assert next_state.zones[0] is record
    assert snapshot.zones == (record,)
    assert events == snapshot.events == ()


def test_created_batch_zone_suppresses_later_same_side_candidate() -> None:
    key = _key()
    config = _config(
        key,
        pivot_span_bars=1,
        zone_half_width_atr=0.0,
        merge_distance_atr=0.5,
    )
    when = _T0 + timedelta(minutes=1)
    first_candidate = CandidateLevel(
        state_key=key,
        side=ZoneSide.SUPPORT,
        geometry=ZoneGeometry(center=100.0, half_width=0.0),
        source="controlled_batch",
        formed_at=when,
        available_at=when,
        atr_at_creation=1.0,
    )
    later_candidate = CandidateLevel(
        state_key=key,
        side=ZoneSide.SUPPORT,
        geometry=ZoneGeometry(center=100.5, half_width=0.0),
        source="controlled_batch",
        formed_at=when,
        available_at=when,
        atr_at_creation=1.0,
    )
    state = _state(config)
    bar = _bar(key, bar_id="controlled-batch", when=when)

    with patch(
        "libs.models.sr.lifecycle.engine.detect_confirmed_pivots",
        return_value=(first_candidate, later_candidate),
    ) as detector:
        next_state, snapshot, events = SREngine().step(state, bar, config)

    detector.assert_called_once()
    assert len(next_state.zones) == 1
    assert next_state.zones[0].definition.side is ZoneSide.SUPPORT
    assert next_state.zones[0].definition.geometry.center in {100.0, 100.5}
    assert _event_types(events) == (SREventType.CREATED,)
    assert events == snapshot.events


def test_current_bar_terminal_zone_suppresses_same_bar_recreation() -> None:
    key = _key()
    config = _config(
        key,
        pivot_span_bars=1,
        zone_half_width_atr=0.0,
        merge_distance_atr=0.5,
        break_confirm_closes=1,
    )
    first = _pivot_bar(key, 0, high=100.0, low=95.0)
    center = _pivot_bar(key, 1, high=100.0, low=90.0)
    confirmation = _bar(
        key,
        bar_id="pivot-2",
        when=_T0 + timedelta(minutes=2),
        open=91.0,
        high=95.0,
        low=90.5,
        close=91.0,
        atr_at_close=10.0,
    )
    record = _record(
        config,
        side=ZoneSide.SUPPORT,
        center=93.0,
        half_width=0.0,
        available_at=_T0,
    )
    state = _state(
        config,
        zones=(record,),
        last_processed_bar=center.bar_id,
        recent_bars=(first, center),
    )

    next_state, _, events = SREngine().step(state, confirmation, config)

    assert next_state.zones[0].runtime.status is ZoneStatus.BROKEN
    assert _event_types(events) == (
        SREventType.BREACH_STARTED,
        SREventType.BREAK_CONFIRMED,
    )
    assert all(event.event_type is not SREventType.CREATED for event in events)


def test_later_bar_can_create_after_retained_terminal_zone() -> None:
    key = _key()
    config = _config(
        key,
        pivot_span_bars=1,
        zone_half_width_atr=0.0,
        merge_distance_atr=0.5,
        break_confirm_closes=1,
    )
    first = _pivot_bar(key, 0, high=100.0, low=95.0)
    center = _pivot_bar(key, 1, high=100.0, low=90.0)
    confirmation = _bar(
        key,
        bar_id="pivot-2",
        when=_T0 + timedelta(minutes=2),
        open=91.0,
        high=95.0,
        low=90.5,
        close=91.0,
        atr_at_close=10.0,
    )
    record = _record(
        config,
        side=ZoneSide.SUPPORT,
        center=93.0,
        half_width=0.0,
        available_at=_T0,
    )
    state = _state(
        config,
        zones=(record,),
        last_processed_bar=center.bar_id,
        recent_bars=(first, center),
    )
    terminal, _, _ = SREngine().step(state, confirmation, config)

    next_bar = _bar(
        key,
        bar_id="pivot-3",
        when=_T0 + timedelta(minutes=3),
        open=92.5,
        high=100.0,
        low=85.0,
        close=92.5,
        atr_at_close=1.0,
    )
    final_bar = _bar(
        key,
        bar_id="pivot-4",
        when=_T0 + timedelta(minutes=4),
        open=86.0,
        high=101.0,
        low=85.5,
        close=86.0,
        atr_at_close=1.0,
    )
    after_warmup, _, warmup_events = SREngine().step(
        terminal,
        next_bar,
        config,
    )
    next_state, _, events = SREngine().step(
        after_warmup,
        final_bar,
        config,
    )

    assert warmup_events == ()
    assert next_state.zones[0].runtime.status is ZoneStatus.BROKEN
    assert len(next_state.zones) == 2
    assert _event_types(events) == (SREventType.CREATED,)
    created = next(
        zone
        for zone in next_state.zones
        if zone.definition.zone_id != record.definition.zone_id
    )
    assert created.definition.geometry.center == 85.0


def test_capacity_uses_candidate_identity_order_without_eviction() -> None:
    key = _key()
    config = _config(
        key,
        pivot_span_bars=1,
        zone_half_width_atr=0.0,
        max_active_zones=1,
    )
    bars = _both_side_pivot_bars(key)
    state = _state(config)
    engine = SREngine()
    for bar in bars:
        state, _, events = engine.step(state, bar, config)

    candidates = detect_confirmed_pivots(bars, config.detection)
    assert len(state.zones) == 1
    assert state.zones[0].definition.side is candidates[0].side
    assert _event_types(events) == (SREventType.CREATED,)


def test_terminal_zones_do_not_consume_capacity() -> None:
    key = _key()
    config = _config(
        key,
        pivot_span_bars=1,
        zone_half_width_atr=0.0,
        max_active_zones=1,
    )
    bars = _both_side_pivot_bars(key)
    terminal = _record(config, status=ZoneStatus.BROKEN, center=130.0)
    state = _state(config, zones=(terminal,))
    engine = SREngine()
    for bar in bars:
        state, _, events = engine.step(state, bar, config)

    assert len(state.zones) == 2
    assert terminal in state.zones
    assert any(
        record.runtime.status is ZoneStatus.ACTIVE
        for record in state.zones
        if record is not terminal
    )
    assert _event_types(events) == (SREventType.CREATED,)


def test_capacity_does_not_evict_existing_active_zone() -> None:
    key = _key()
    config = _config(
        key,
        pivot_span_bars=1,
        zone_half_width_atr=0.0,
        max_active_zones=1,
    )
    bars = _both_side_pivot_bars(key)
    existing = _record(
        config,
        side=ZoneSide.SUPPORT,
        center=100.0,
        half_width=0.0,
        available_at=bars[0].closed_at,
    )
    state = _state(
        config,
        zones=(existing,),
        last_processed_bar=bars[1].bar_id,
        recent_bars=bars[:2],
    )

    next_state, _, events = SREngine().step(state, bars[2], config)

    assert next_state.zones[0].definition.zone_id == existing.definition.zone_id
    assert len(next_state.zones) == 1
    assert SREventType.CREATED not in _event_types(events)


def test_over_capacity_previous_state_fails_before_processing_events() -> None:
    key = _key()
    config = _config(key, max_active_zones=1)
    first = _record(config, center=100.0)
    second = _record(config, center=120.0)
    state = _state(config, zones=(first, second))
    bar = _bar(
        key,
        bar_id="over-capacity",
        when=_T0 + timedelta(minutes=1),
        close=80.0,
        open=80.0,
        high=81.0,
        low=79.0,
    )

    with pytest.raises(ContractValidationError, match="exceeds max_active_zones"):
        SREngine().step(state, bar, config)


@pytest.mark.parametrize("mode", ["duplicate", "equal_timestamp"])
def test_step_rejects_duplicate_or_non_increasing_buffer_bar(mode: str) -> None:
    key = _key()
    config = _config(key, pivot_span_bars=1)
    bars = _both_side_pivot_bars(key)
    state = _state(
        config,
        last_processed_bar=bars[1].bar_id,
        recent_bars=bars[:2],
    )
    if mode == "duplicate":
        bar = _bar(
            key,
            bar_id=bars[0].bar_id,
            when=bars[2].closed_at,
        )
        expected = "duplicates a recent bar"
    else:
        bar = _bar(
            key,
            bar_id="same-time",
            when=bars[1].closed_at,
        )
        expected = "later than recent bars"

    with pytest.raises(ContractValidationError, match=expected):
        SREngine().step(state, bar, config)


def test_step_rejects_buffer_longer_than_configured_window() -> None:
    key = _key()
    config = _config(key, pivot_span_bars=1)
    bars = (
        _pivot_bar(key, 0, high=100.0, low=95.0),
        _pivot_bar(key, 1, high=101.0, low=94.0),
        _pivot_bar(key, 2, high=102.0, low=93.0),
    )
    state = _state(
        config,
        last_processed_bar=bars[-1].bar_id,
        recent_bars=bars,
    )

    with pytest.raises(ContractValidationError, match="detection buffer"):
        SREngine().step(
            state,
            _pivot_bar(key, 3, high=103.0, low=92.0),
            config,
        )


def test_step_rejects_buffer_not_ending_at_last_processed_bar() -> None:
    key = _key()
    config = _config(key, pivot_span_bars=1)
    bars = _both_side_pivot_bars(key)
    state = _state(
        config,
        last_processed_bar=bars[1].bar_id,
        recent_bars=bars[:2],
    )
    object.__setattr__(state, "last_processed_bar", "not-the-final-buffer-bar")

    with pytest.raises(ContractValidationError, match="final bar_id"):
        SREngine().step(state, bars[2], config)
