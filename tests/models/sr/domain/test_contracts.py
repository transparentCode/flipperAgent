from __future__ import annotations

from dataclasses import MISSING, FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone

import pytest

from libs.models.sr import (
    CandidateLevel,
    ClosedBar,
    ContractValidationError,
    SREvent,
    SREventType,
    SRState,
    SRStateKey,
    SRSnapshot,
    ZoneDefinition,
    ZoneGeometry,
    ZoneRecord,
    ZoneRuntimeState,
    ZoneSide,
    ZoneStatus,
)


def _key() -> SRStateKey:
    return SRStateKey(venue="binance", symbol="BTCUSDT", timeframe="1h")


def _other_key() -> SRStateKey:
    return SRStateKey(venue="binance", symbol="ETHUSDT", timeframe="1h")


def _geometry(center: float = 100.0, half_width: float = 5.0) -> ZoneGeometry:
    return ZoneGeometry(center=center, half_width=half_width)


def _config_hash() -> str:
    return "a" * 64


def _other_config_hash() -> str:
    return "b" * 64


def _definition(
    *,
    center: float = 100.0,
    half_width: float = 5.0,
    config_hash: str | None = None,
    state_key: SRStateKey | None = None,
) -> ZoneDefinition:
    return ZoneDefinition(
        state_key=state_key or _key(),
        side=ZoneSide.SUPPORT,
        geometry=_geometry(center=center, half_width=half_width),
        source="test",
        created_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        available_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        atr_at_creation=1.0,
        config_hash=config_hash or _config_hash(),
    )


def _closed_bar(
    *,
    bar_id: str = "bar-1",
    closed_at: datetime = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
    state_key: SRStateKey | None = None,
    atr_at_close: float = 1.0,
) -> ClosedBar:
    return ClosedBar(
        state_key=state_key or _key(),
        bar_id=bar_id,
        closed_at=closed_at,
        open=100.0,
        high=105.0,
        low=95.0,
        close=102.0,
        atr_at_close=atr_at_close,
    )


def _runtime(definition: ZoneDefinition) -> ZoneRuntimeState:
    return ZoneRuntimeState(
        zone_id=definition.zone_id,
        status=ZoneStatus.ACTIVE,
        touch_count=0,
        fakeout_count=0,
        pending_breach_count=0,
        age_bars=0,
        last_interaction_at=None,
        updated_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
    )


def test_zone_geometry_bounds() -> None:
    g = _geometry()
    assert g.lower_bound == 95.0
    assert g.upper_bound == 105.0
    assert g.center == 100.0


def test_box_geometry_uses_positive_half_width() -> None:
    g = _geometry(half_width=2.5)
    assert g.lower_bound < g.upper_bound


def test_center_must_be_positive() -> None:
    with pytest.raises(ContractValidationError):
        ZoneGeometry(center=0.0, half_width=1.0)
    with pytest.raises(ContractValidationError):
        ZoneGeometry(center=-10.0, half_width=1.0)


def test_line_geometry_uses_zero_half_width() -> None:
    line = ZoneGeometry(center=100.0, half_width=0.0)
    assert line.lower_bound == 100.0
    assert line.upper_bound == 100.0
    with pytest.raises(ContractValidationError):
        ZoneGeometry(center=100.0, half_width=-1.0)


def test_closed_bar_validates_ohlc_and_normalizes_time() -> None:
    local_time = datetime(
        2026, 7, 14, 14, 0, tzinfo=timezone(timedelta(hours=2))
    )
    bar = ClosedBar(
        state_key=_key(),
        bar_id="bar-1",
        closed_at=local_time,
        open=100.0,
        high=105.0,
        low=95.0,
        close=102.0,
        atr_at_close=1.0,
    )
    assert bar.closed_at == datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "field, value",
    [
        ("open", 0.0),
        ("high", float("inf")),
        ("low", float("nan")),
        ("close", -1.0),
    ],
)
def test_closed_bar_ohlc_must_be_positive_finite(field: str, value: float) -> None:
    values = {
        "open": 100.0,
        "high": 105.0,
        "low": 95.0,
        "close": 102.0,
        "atr_at_close": 1.0,
    }
    values[field] = value
    with pytest.raises(ContractValidationError):
        ClosedBar(
            state_key=_key(),
            bar_id="bar-invalid",
            closed_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
            **values,
        )


def test_closed_bar_atr_must_be_positive_finite_and_mandatory() -> None:
    assert fields(ClosedBar)[-1].name == "atr_at_close"
    assert fields(ClosedBar)[-1].default is MISSING
    for value in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ContractValidationError):
            _closed_bar(atr_at_close=value)


@pytest.mark.parametrize(
    "values",
    [
        {
            "open": 106.0,
            "high": 105.0,
            "low": 95.0,
            "close": 100.0,
            "atr_at_close": 1.0,
        },
        {
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 106.0,
            "atr_at_close": 1.0,
        },
        {
            "open": 100.0,
            "high": 105.0,
            "low": 101.0,
            "close": 100.0,
            "atr_at_close": 1.0,
        },
    ],
)
def test_closed_bar_ohlc_relationships_are_strict(values: dict[str, float]) -> None:
    with pytest.raises(ContractValidationError):
        ClosedBar(
            state_key=_key(),
            bar_id="bar-invalid",
            closed_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
            **values,
        )


def test_closed_bar_rejects_naive_time_and_invalid_identity() -> None:
    base = {
        "state_key": _key(),
        "bar_id": "bar-1",
        "closed_at": datetime(2026, 7, 14, 12, 0),
        "open": 100.0,
        "high": 105.0,
        "low": 95.0,
        "close": 102.0,
        "atr_at_close": 1.0,
    }
    with pytest.raises(ContractValidationError):
        ClosedBar(**base)
    with pytest.raises(ContractValidationError):
        ClosedBar(**{**base, "closed_at": base["closed_at"].replace(tzinfo=timezone.utc), "bar_id": "   "})
    with pytest.raises(ContractValidationError):
        ClosedBar(**{**base, "closed_at": base["closed_at"].replace(tzinfo=timezone.utc), "state_key": object()})


def test_geometry_lower_bound_must_be_positive() -> None:
    # center must exceed half_width to keep lower_bound > 0.
    with pytest.raises(ContractValidationError):
        ZoneGeometry(center=5.0, half_width=5.0)
    with pytest.raises(ContractValidationError):
        ZoneGeometry(center=5.0, half_width=6.0)
    g = ZoneGeometry(center=5.0, half_width=4.999)
    assert g.lower_bound > 0


def test_geometry_bounds_must_be_finite() -> None:
    with pytest.raises(ContractValidationError):
        ZoneGeometry(center=1e308, half_width=9e307)


def test_atr_at_creation_must_be_positive() -> None:
    with pytest.raises(ContractValidationError):
        CandidateLevel(
            state_key=_key(),
            side=ZoneSide.SUPPORT,
            geometry=_geometry(),
            source="test",
            formed_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
            available_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
            atr_at_creation=0.0,
        )


def test_available_at_must_not_precede_formed_at() -> None:
    t0 = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    t1 = t0 - timedelta(minutes=1)
    with pytest.raises(ContractValidationError):
        CandidateLevel(
            state_key=_key(),
            side=ZoneSide.SUPPORT,
            geometry=_geometry(),
            source="test",
            formed_at=t0,
            available_at=t1,
            atr_at_creation=1.0,
        )


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(ContractValidationError):
        CandidateLevel(
            state_key=_key(),
            side=ZoneSide.SUPPORT,
            geometry=_geometry(),
            source="test",
            formed_at=datetime(2026, 7, 14, 12, 0),
            available_at=datetime(2026, 7, 14, 12, 0),
            atr_at_creation=1.0,
        )


def test_non_utc_timestamp_normalized() -> None:
    tz = timezone(timedelta(hours=2))
    t = datetime(2026, 7, 14, 14, 0, tzinfo=tz)
    c = CandidateLevel(
        state_key=_key(),
        side=ZoneSide.SUPPORT,
        geometry=_geometry(),
        source="test",
        formed_at=t,
        available_at=t,
        atr_at_creation=1.0,
    )
    assert c.formed_at.tzinfo is timezone.utc
    assert c.formed_at.hour == 12


def test_candidate_id_is_derived_not_supplied() -> None:
    c = CandidateLevel(
        state_key=_key(),
        side=ZoneSide.SUPPORT,
        geometry=_geometry(),
        source="test",
        formed_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        available_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        atr_at_creation=1.0,
    )
    assert len(c.candidate_id) == 64
    # Creating an equal candidate must yield the same deterministic ID.
    c2 = CandidateLevel(
        state_key=_key(),
        side=ZoneSide.SUPPORT,
        geometry=_geometry(),
        source="test",
        formed_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        available_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        atr_at_creation=1.0,
    )
    assert c2.candidate_id == c.candidate_id


def test_counters_must_be_non_negative() -> None:
    with pytest.raises(ContractValidationError):
        ZoneRuntimeState(
            zone_id="a" * 64,
            status=ZoneStatus.ACTIVE,
            touch_count=-1,
            fakeout_count=0,
            pending_breach_count=0,
            age_bars=0,
            last_interaction_at=None,
            updated_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        )


def test_age_bars_must_be_non_negative() -> None:
    with pytest.raises(ContractValidationError):
        ZoneRuntimeState(
            zone_id="a" * 64,
            status=ZoneStatus.ACTIVE,
            touch_count=0,
            fakeout_count=0,
            pending_breach_count=0,
            age_bars=-1,
            last_interaction_at=None,
            updated_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        )


@pytest.mark.parametrize(
    "status, pending",
    [
        (ZoneStatus.ACTIVE, 1),
        (ZoneStatus.BROKEN, 1),
        (ZoneStatus.EXPIRED, 1),
        (ZoneStatus.BREACH_PENDING, 0),
    ],
)
def test_pending_breach_count_matches_status(
    status: ZoneStatus, pending: int
) -> None:
    with pytest.raises(ContractValidationError):
        ZoneRuntimeState(
            zone_id="a" * 64,
            status=status,
            touch_count=0,
            fakeout_count=0,
            pending_breach_count=pending,
            age_bars=0,
            last_interaction_at=None,
            updated_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        )


def test_event_price_must_be_positive_finite() -> None:
    base = {
        "zone_id": "a" * 64,
        "event_type": SREventType.TOUCHED,
        "timestamp": datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        "bar_id": "bar-1",
    }
    with pytest.raises(ContractValidationError):
        SREvent(price=0.0, **base)
    with pytest.raises(ContractValidationError):
        SREvent(price=float("inf"), **base)


def test_zone_record_requires_matching_zone_id() -> None:
    definition = _definition()
    runtime = ZoneRuntimeState(
        zone_id="b" * 64,
        status=ZoneStatus.ACTIVE,
        touch_count=0,
        fakeout_count=0,
        pending_breach_count=0,
        age_bars=0,
        last_interaction_at=None,
        updated_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(ContractValidationError):
        ZoneRecord(definition=definition, runtime=runtime)


def test_runtime_rejects_last_interaction_after_updated_at() -> None:
    with pytest.raises(ContractValidationError):
        ZoneRuntimeState(
            zone_id="a" * 64,
            status=ZoneStatus.ACTIVE,
            touch_count=0,
            fakeout_count=0,
            pending_breach_count=0,
            age_bars=0,
            last_interaction_at=datetime(2026, 7, 14, 12, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        )


def test_zone_record_rejects_runtime_before_definition_available() -> None:
    definition = _definition()
    runtime = ZoneRuntimeState(
        zone_id=definition.zone_id,
        status=ZoneStatus.ACTIVE,
        touch_count=0,
        fakeout_count=0,
        pending_breach_count=0,
        age_bars=0,
        last_interaction_at=None,
        updated_at=datetime(2026, 7, 14, 11, 59, tzinfo=timezone.utc),
    )
    with pytest.raises(ContractValidationError):
        ZoneRecord(definition=definition, runtime=runtime)


def test_zone_record_rejects_interaction_before_definition_available() -> None:
    definition = _definition()
    runtime = ZoneRuntimeState(
        zone_id=definition.zone_id,
        status=ZoneStatus.ACTIVE,
        touch_count=0,
        fakeout_count=0,
        pending_breach_count=0,
        age_bars=0,
        last_interaction_at=datetime(2026, 7, 14, 11, 59, tzinfo=timezone.utc),
        updated_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(ContractValidationError):
        ZoneRecord(definition=definition, runtime=runtime)


def test_zone_definition_requires_config_hash() -> None:
    with pytest.raises(ContractValidationError):
        ZoneDefinition(
            state_key=_key(),
            side=ZoneSide.SUPPORT,
            geometry=_geometry(),
            source="test",
            created_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
            available_at=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
            atr_at_creation=1.0,
            config_hash="",
        )


def test_zone_definition_id_is_derived_not_supplied() -> None:
    d = _definition()
    assert len(d.zone_id) == 64
    d2 = _definition()
    assert d2.zone_id == d.zone_id


def test_collections_are_stored_as_tuples() -> None:
    definition = _definition()
    record = ZoneRecord(definition=definition, runtime=_runtime(definition))
    state = SRState(
        schema_version="1.0",
        state_key=_key(),
        config_hash=_config_hash(),
        last_processed_bar="bar-1",
        zones=[record],
        recent_bars=(_closed_bar(bar_id="bar-1"),),
    )
    assert isinstance(state.zones, tuple)
    assert isinstance(state.recent_bars, tuple)

    snapshot = SRSnapshot(
        schema_version="1.0",
        state_key=_key(),
        config_hash=_config_hash(),
        as_of=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        zones=[record],
        events=[],
    )
    assert isinstance(snapshot.zones, tuple)
    assert isinstance(snapshot.events, tuple)


def test_dataclasses_are_frozen() -> None:
    g = _geometry()
    with pytest.raises(FrozenInstanceError):
        g.center = 50.0


def test_state_rejects_mismatched_zone_state_key() -> None:
    definition = _definition(state_key=_other_key())
    record = ZoneRecord(definition=definition, runtime=_runtime(definition))
    with pytest.raises(ContractValidationError):
        SRState(
            schema_version="1.0",
            state_key=_key(),
            config_hash=_config_hash(),
            last_processed_bar="bar-1",
            zones=[record],
            recent_bars=(),
        )


def test_state_rejects_mismatched_zone_config_hash() -> None:
    definition = _definition(config_hash=_other_config_hash())
    record = ZoneRecord(definition=definition, runtime=_runtime(definition))
    with pytest.raises(ContractValidationError):
        SRState(
            schema_version="1.0",
            state_key=_key(),
            config_hash=_config_hash(),
            last_processed_bar="bar-1",
            zones=[record],
            recent_bars=(),
        )


def test_state_rejects_duplicate_zone_id() -> None:
    definition = _definition()
    record = ZoneRecord(definition=definition, runtime=_runtime(definition))
    with pytest.raises(ContractValidationError):
        SRState(
            schema_version="1.0",
            state_key=_key(),
            config_hash=_config_hash(),
            last_processed_bar="bar-1",
            zones=[record, record],
            recent_bars=(),
        )


def test_recent_bars_are_immutable_and_canonical() -> None:
    first = _closed_bar()
    second = _closed_bar(
        bar_id="bar-2",
        closed_at=datetime(2026, 7, 14, 12, 1, tzinfo=timezone.utc),
    )
    definition = _definition()
    record = ZoneRecord(definition=definition, runtime=_runtime(definition))
    state = SRState(
        schema_version="1.0",
        state_key=_key(),
        config_hash=_config_hash(),
        last_processed_bar="bar-2",
        zones=[record],
        recent_bars=[first, second],
    )

    assert isinstance(state.recent_bars, tuple)
    assert state.recent_bars == (first, second)


@pytest.mark.parametrize(
    "recent_bars, last_processed_bar, expected",
    [
        (
            (
                _closed_bar(),
                _closed_bar(
                    bar_id="bar-2",
                    closed_at=datetime(
                        2026, 7, 14, 12, 1, tzinfo=timezone.utc
                    ),
                    state_key=_other_key(),
                ),
            ),
            "bar-2",
            "state_key",
        ),
        (
            (_closed_bar(), _closed_bar()),
            "bar-1",
            "duplicate bar_id",
        ),
        (
            (
                _closed_bar(),
                _closed_bar(
                    bar_id="bar-2",
                    closed_at=datetime(
                        2026, 7, 14, 12, 0, tzinfo=timezone.utc
                    ),
                ),
            ),
            "bar-2",
            "strictly increasing",
        ),
        ((_closed_bar(),), "different", "final bar_id"),
        ((object(),), "object", "exactly ClosedBar"),
    ],
)
def test_recent_bars_validation(
    recent_bars: tuple[object, ...],
    last_processed_bar: str,
    expected: str,
) -> None:
    with pytest.raises(ContractValidationError, match=expected):
        SRState(
            schema_version="1.0",
            state_key=_key(),
            config_hash=_config_hash(),
            last_processed_bar=last_processed_bar,
            zones=(),
            recent_bars=recent_bars,
        )


def test_state_orders_zones_canonically() -> None:
    low = _definition(center=90.0, half_width=5.0)
    high = _definition(center=110.0, half_width=5.0)
    record_low = ZoneRecord(definition=low, runtime=_runtime(low))
    record_high = ZoneRecord(definition=high, runtime=_runtime(high))
    state = SRState(
        schema_version="1.0",
        state_key=_key(),
        config_hash=_config_hash(),
        last_processed_bar="bar-1",
        zones=[record_high, record_low],
        recent_bars=(_closed_bar(bar_id="bar-1"),),
    )
    assert state.zones[0] == record_high
    assert state.zones[1] == record_low


def test_snapshot_orders_events_and_zones_canonically() -> None:
    low = _definition(center=90.0, half_width=5.0)
    high = _definition(center=110.0, half_width=5.0)
    record_low = ZoneRecord(definition=low, runtime=_runtime(low))
    record_high = ZoneRecord(definition=high, runtime=_runtime(high))
    event_later = SREvent(
        zone_id=low.zone_id,
        event_type=SREventType.TOUCHED,
        timestamp=datetime(2026, 7, 14, 12, 5, tzinfo=timezone.utc),
        price=90.0,
        bar_id="bar-2",
    )
    event_earlier = SREvent(
        zone_id=low.zone_id,
        event_type=SREventType.CREATED,
        timestamp=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        price=90.0,
        bar_id="bar-1",
    )
    snapshot = SRSnapshot(
        schema_version="1.0",
        state_key=_key(),
        config_hash=_config_hash(),
        as_of=datetime(2026, 7, 14, 12, 5, tzinfo=timezone.utc),
        zones=[record_low, record_high],
        events=[event_later, event_earlier],
    )
    assert snapshot.zones[0] == record_high
    assert snapshot.zones[1] == record_low
    assert snapshot.events[0] == event_earlier
    assert snapshot.events[1] == event_later


def test_snapshot_identity_independent_of_input_order() -> None:
    low = _definition(center=90.0, half_width=5.0)
    high = _definition(center=110.0, half_width=5.0)
    record_low = ZoneRecord(definition=low, runtime=_runtime(low))
    record_high = ZoneRecord(definition=high, runtime=_runtime(high))
    event_later = SREvent(
        zone_id=low.zone_id,
        event_type=SREventType.TOUCHED,
        timestamp=datetime(2026, 7, 14, 12, 5, tzinfo=timezone.utc),
        price=90.0,
        bar_id="bar-2",
    )
    event_earlier = SREvent(
        zone_id=low.zone_id,
        event_type=SREventType.CREATED,
        timestamp=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        price=90.0,
        bar_id="bar-1",
    )
    s1 = SRSnapshot(
        schema_version="1.0",
        state_key=_key(),
        config_hash=_config_hash(),
        as_of=datetime(2026, 7, 14, 12, 5, tzinfo=timezone.utc),
        zones=[record_low, record_high],
        events=[event_later, event_earlier],
    )
    s2 = SRSnapshot(
        schema_version="1.0",
        state_key=_key(),
        config_hash=_config_hash(),
        as_of=datetime(2026, 7, 14, 12, 5, tzinfo=timezone.utc),
        zones=[record_high, record_low],
        events=[event_earlier, event_later],
    )
    assert s1.snapshot_id == s2.snapshot_id


def test_snapshot_rejects_future_runtime_update() -> None:
    definition = _definition()
    runtime = ZoneRuntimeState(
        zone_id=definition.zone_id,
        status=ZoneStatus.ACTIVE,
        touch_count=0,
        fakeout_count=0,
        pending_breach_count=0,
        age_bars=0,
        last_interaction_at=None,
        updated_at=datetime(2026, 7, 14, 12, 1, tzinfo=timezone.utc),
    )
    record = ZoneRecord(definition=definition, runtime=runtime)
    with pytest.raises(ContractValidationError):
        SRSnapshot(
            schema_version="1.0",
            state_key=_key(),
            config_hash=_config_hash(),
            as_of=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
            zones=[record],
            events=[],
        )


def test_snapshot_rejects_future_event() -> None:
    definition = _definition()
    record = ZoneRecord(definition=definition, runtime=_runtime(definition))
    event = SREvent(
        zone_id=definition.zone_id,
        event_type=SREventType.TOUCHED,
        timestamp=datetime(2026, 7, 14, 12, 1, tzinfo=timezone.utc),
        price=100.0,
        bar_id="bar-future",
    )
    with pytest.raises(ContractValidationError):
        SRSnapshot(
            schema_version="1.0",
            state_key=_key(),
            config_hash=_config_hash(),
            as_of=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
            zones=[record],
            events=[event],
        )


def test_snapshot_rejects_event_before_zone_availability() -> None:
    definition = _definition()
    record = ZoneRecord(definition=definition, runtime=_runtime(definition))
    event = SREvent(
        zone_id=definition.zone_id,
        event_type=SREventType.CREATED,
        timestamp=datetime(2026, 7, 14, 11, 59, tzinfo=timezone.utc),
        price=100.0,
        bar_id="bar-before-availability",
    )
    with pytest.raises(ContractValidationError):
        SRSnapshot(
            schema_version="1.0",
            state_key=_key(),
            config_hash=_config_hash(),
            as_of=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
            zones=[record],
            events=[event],
        )


def test_snapshot_rejects_duplicate_event_ids() -> None:
    definition = _definition()
    record = ZoneRecord(definition=definition, runtime=_runtime(definition))
    event = SREvent(
        zone_id=definition.zone_id,
        event_type=SREventType.TOUCHED,
        timestamp=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        price=100.0,
        bar_id="bar-duplicate",
    )
    with pytest.raises(ContractValidationError):
        SRSnapshot(
            schema_version="1.0",
            state_key=_key(),
            config_hash=_config_hash(),
            as_of=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
            zones=[record],
            events=[event, event],
        )


def test_snapshot_rejects_event_for_unknown_zone() -> None:
    definition = _definition()
    record = ZoneRecord(definition=definition, runtime=_runtime(definition))
    event = SREvent(
        zone_id="b" * 64,
        event_type=SREventType.TOUCHED,
        timestamp=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
        price=100.0,
        bar_id="bar-orphan",
    )
    with pytest.raises(ContractValidationError):
        SRSnapshot(
            schema_version="1.0",
            state_key=_key(),
            config_hash=_config_hash(),
            as_of=datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc),
            zones=[record],
            events=[event],
        )
