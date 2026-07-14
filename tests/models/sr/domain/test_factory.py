from __future__ import annotations

from dataclasses import MISSING, fields
from datetime import datetime, timezone

import pytest

from libs.models.sr import (
    AssociationConfig,
    ClosedBar,
    ContractValidationError,
    DetectionConfig,
    LifecycleConfig,
    ResolvedSRConfig,
    RuntimeConfig,
    SREngine,
    SRState,
    SRStateKey,
    ZoneDefinition,
    ZoneGeometry,
    ZoneRecord,
    ZoneRuntimeState,
    ZoneSide,
    ZoneStatus,
    create_initial_state,
)
from libs.models.sr.domain import SR_SCHEMA_VERSION


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


def _config(key: SRStateKey) -> ResolvedSRConfig:
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
            max_age_bars=10,
        ),
        runtime=RuntimeConfig(max_active_zones=8),
        field_provenance={path: "defaults" for path in _PARAMETER_PATHS},
    )


def _bar(key: SRStateKey) -> ClosedBar:
    return ClosedBar(
        state_key=key,
        bar_id="bar-1",
        closed_at=_T0,
        open=100.0,
        high=105.0,
        low=95.0,
        close=102.0,
        atr_at_close=1.0,
    )


def _record(key: SRStateKey, config: ResolvedSRConfig) -> ZoneRecord:
    definition = ZoneDefinition(
        state_key=key,
        side=ZoneSide.SUPPORT,
        geometry=ZoneGeometry(center=100.0, half_width=0.0),
        source="test",
        created_at=_T0,
        available_at=_T0,
        atr_at_creation=1.0,
        config_hash=config.resolved_config_hash,
    )
    return ZoneRecord(
        definition=definition,
        runtime=ZoneRuntimeState(
            zone_id=definition.zone_id,
            status=ZoneStatus.ACTIVE,
            touch_count=0,
            fakeout_count=0,
            pending_breach_count=0,
            age_bars=0,
            last_interaction_at=None,
            updated_at=_T0,
        ),
    )


def test_factory_returns_exact_empty_initial_aggregate() -> None:
    key = _key()
    config = _config(key)

    state = create_initial_state(key, config)

    assert state.schema_version == SR_SCHEMA_VERSION
    assert state.state_key is key
    assert state.config_hash == config.resolved_config_hash
    assert state.last_processed_bar is None
    assert state.zones == ()
    assert state.recent_bars == ()


def test_factory_requires_exact_types_and_matching_owner() -> None:
    key = _key()
    config = _config(key)

    with pytest.raises(ContractValidationError):
        create_initial_state(object(), config)  # type: ignore[arg-type]
    with pytest.raises(ContractValidationError):
        create_initial_state(key, object())  # type: ignore[arg-type]
    with pytest.raises(ContractValidationError, match="symbol"):
        create_initial_state(_key(symbol="ETHUSDT"), config)
    with pytest.raises(ContractValidationError, match="timeframe"):
        create_initial_state(_key(timeframe="4h"), config)


def test_nullable_cursor_invariants_reject_seed_and_partial_empty_states() -> None:
    key = _key()
    config = _config(key)
    record = _record(key, config)
    bar = _bar(key)

    with pytest.raises(ContractValidationError):
        SRState(
            schema_version=SR_SCHEMA_VERSION,
            state_key=key,
            config_hash=config.resolved_config_hash,
            last_processed_bar="seed",
            zones=(),
            recent_bars=(),
        )
    with pytest.raises(ContractValidationError):
        SRState(
            schema_version=SR_SCHEMA_VERSION,
            state_key=key,
            config_hash=config.resolved_config_hash,
            last_processed_bar=None,
            zones=(record,),
            recent_bars=(),
        )
    with pytest.raises(ContractValidationError):
        SRState(
            schema_version=SR_SCHEMA_VERSION,
            state_key=key,
            config_hash=config.resolved_config_hash,
            last_processed_bar=None,
            zones=(),
            recent_bars=(bar,),
        )


def test_only_current_schema_version_is_accepted() -> None:
    key = _key()
    config = _config(key)

    with pytest.raises(ContractValidationError, match="schema version"):
        SRState(
            schema_version="2.0",
            state_key=key,
            config_hash=config.resolved_config_hash,
            last_processed_bar=None,
            zones=(),
            recent_bars=(),
        )


def test_non_null_cursor_requires_buffer_tail_and_buffer_is_mandatory() -> None:
    key = _key()
    config = _config(key)
    bar = _bar(key)

    state = SRState(
        schema_version=SR_SCHEMA_VERSION,
        state_key=key,
        config_hash=config.resolved_config_hash,
        last_processed_bar=bar.bar_id,
        zones=(),
        recent_bars=(bar,),
    )
    assert state.last_processed_bar == bar.bar_id


def test_first_engine_step_from_factory_state_succeeds() -> None:
    key = _key()
    config = _config(key)
    state = create_initial_state(key, config)
    bar = _bar(key)

    next_state, snapshot, events = SREngine().step(state, bar, config)

    assert next_state.last_processed_bar == bar.bar_id
    assert next_state.recent_bars == (bar,)
    assert snapshot.as_of == bar.closed_at
    assert events == snapshot.events


def test_state_field_has_nullable_cursor_without_default() -> None:
    field = next(field for field in fields(SRState) if field.name == "last_processed_bar")
    assert field.default is MISSING
