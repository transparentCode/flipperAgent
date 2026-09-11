from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from libs.analysis_capabilities.execution import execute_analysis_capability
from libs.analysis_capabilities.execution.sr import (
    SRExecutionRequest,
    SRExecutionResult,
    execute_sr,
)
from libs.models.sr import (
    AssociationConfig,
    ClosedBar,
    DetectionConfig,
    LifecycleConfig,
    ResolvedSRConfig,
    RuntimeConfig,
    SREngine,
    SRStateKey,
    create_initial_state,
)

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _config(key: SRStateKey) -> ResolvedSRConfig:
    return ResolvedSRConfig.create(
        version="1",
        asset=key.symbol,
        timeframe=key.timeframe,
        detection=DetectionConfig(pivot_span_bars=1, zone_half_width_atr=0.25),
        association=AssociationConfig(merge_distance_atr=0.5),
        lifecycle=LifecycleConfig(
            touch_tolerance_atr=0.25,
            break_buffer_atr=0.5,
            break_confirm_closes=2,
            max_age_bars=50,
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


def _bar(key: SRStateKey, index: int) -> ClosedBar:
    close = 100.0 + index
    return ClosedBar(
        state_key=key,
        bar_id=f"bar-{index}",
        closed_at=_START + timedelta(hours=index),
        open=close - 0.25,
        high=close + 0.75,
        low=close - 0.75,
        close=close,
        atr_at_close=1.0,
    )


def test_sr_direct_adapter_and_dispatcher_are_exactly_equal() -> None:
    key = SRStateKey(venue="binance", symbol="BTCUSDT", timeframe="1h")
    config = _config(key)
    state = create_initial_state(key, config)
    request = SRExecutionRequest(state, _bar(key, 0), config)

    direct = SREngine().step(state, request.closed_bar, config)
    adapted = execute_sr(request)
    dispatched = execute_analysis_capability("model.sr", request)

    assert isinstance(adapted, SRExecutionResult)
    assert (adapted.next_state, adapted.snapshot, adapted.events) == direct
    assert dispatched == adapted
    assert state == create_initial_state(key, config)


def test_sr_state_is_explicitly_threaded_across_two_causal_steps() -> None:
    key = SRStateKey(venue="binance", symbol="BTCUSDT", timeframe="1h")
    config = _config(key)
    initial = create_initial_state(key, config)
    first = execute_sr(SRExecutionRequest(initial, _bar(key, 0), config))
    second = execute_sr(SRExecutionRequest(first.next_state, _bar(key, 1), config))

    direct_second = SREngine().step(first.next_state, _bar(key, 1), config)
    assert (second.next_state, second.snapshot, second.events) == direct_second
    assert first.next_state.last_processed_bar == "bar-0"
    assert second.next_state.last_processed_bar == "bar-1"


def test_sr_result_and_request_are_frozen() -> None:
    key = SRStateKey(venue="binance", symbol="BTCUSDT", timeframe="1h")
    config = _config(key)
    state = create_initial_state(key, config)
    request = SRExecutionRequest(state, _bar(key, 0), config)
    result = execute_sr(request)

    with pytest.raises(FrozenInstanceError):
        request.closed_bar = _bar(key, 1)
    with pytest.raises(FrozenInstanceError):
        result.events = ()


def test_sr_native_identity_errors_are_not_repaired() -> None:
    key = SRStateKey(venue="binance", symbol="BTCUSDT", timeframe="1h")
    config = _config(key)
    state = create_initial_state(key, config)
    first = execute_sr(SRExecutionRequest(state, _bar(key, 0), config))
    repeated = SRExecutionRequest(first.next_state, _bar(key, 0), config)

    with pytest.raises(Exception) as direct_error:
        SREngine().step(first.next_state, repeated.closed_bar, config)
    with pytest.raises(type(direct_error.value)) as adapter_error:
        execute_sr(repeated)
    assert str(adapter_error.value) == str(direct_error.value)
