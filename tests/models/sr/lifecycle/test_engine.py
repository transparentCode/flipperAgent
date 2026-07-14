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


_T0 = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _key(*, symbol: str = "BTCUSDT", timeframe: str = "1h") -> SRStateKey:
    return SRStateKey(venue="binance", symbol=symbol, timeframe=timeframe)


def _config(
    key: SRStateKey,
    *,
    break_confirm_closes: int = 2,
    max_age_bars: int = 50,
    touch_tolerance_atr: float = 0.25,
    break_buffer_atr: float = 0.5,
) -> ResolvedSRConfig:
    return ResolvedSRConfig.create(
        version="1",
        asset=key.symbol,
        timeframe=key.timeframe,
        detection=DetectionConfig(
            pivot_span_bars=5,
            zone_half_width_atr=0.25,
        ),
        association=AssociationConfig(merge_distance_atr=0.5),
        lifecycle=LifecycleConfig(
            touch_tolerance_atr=touch_tolerance_atr,
            break_buffer_atr=break_buffer_atr,
            break_confirm_closes=break_confirm_closes,
            max_age_bars=max_age_bars,
        ),
        runtime=RuntimeConfig(max_active_zones=8),
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
) -> ZoneRecord:
    definition = _definition(
        config,
        side=side,
        center=center,
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
    last_processed_bar: str = "seed",
) -> SRState:
    return SRState(
        schema_version="1.0",
        state_key=state_key
        or _key(symbol=config.asset, timeframe=config.timeframe),
        config_hash=config_hash or config.resolved_config_hash,
        last_processed_bar=last_processed_bar,
        zones=zones,
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
    )


def _event_types(events: tuple) -> tuple[SREventType, ...]:
    return tuple(event.event_type for event in events)


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
