"""Frozen behavior locks for lifecycle-engine cohesion."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256

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
    SRStateKey,
    create_initial_state,
    deterministic_hash,
)
from libs.models.sr.detection import detect_confirmed_pivots
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
_FINAL_STATE_DIGEST = "667cadd0489024dc5e8bfd8401564e05aa25c780536017b29bc98be969895f51"
_PER_BAR_STATE_DIGESTS = (
    "c5fe5895a0ea81074142a496f90375891a0a86531167762d6cfcf011e81197d2",
    "0ca1137377f47177e7711aa2e516dde24d2e169f3f04fb9ff295a96053a3eb98",
    "b388cd0577f6567a6f4853f7748964b1f3eb88de5fe36bbb23d0659defd05104",
    "ff25eeb2e6bae175f8b344f2c542f998c16630f178d9a112f832307c78c5bafe",
    "46868f5c090db96a0f88c9e31586574e5fc19f7689126e393b7aa0d7d90d9e78",
    "81811b95be63b41ebba12d1db362a2b20492ba9b9dfcfe7a1a43f893426ea280",
    "e1d81958971073ae9f244df150cd5ce31eed97a577ff0b448b1bae97bd8b561d",
    "667cadd0489024dc5e8bfd8401564e05aa25c780536017b29bc98be969895f51",
)
_SNAPSHOT_DIGEST = "729be7681495e71ece9c4938879674ed6bb364be1cd0d000d96777c4b2b8857a"
_EVENT_DIGEST = "00c7b43d2f594368a8d1551674ab7563b61da9ce695c5c103101ef74e40d06c5"
_CANDIDATE_DIGEST = "224b6a5a39ee6ff25b4f97f5846d2939594b9b4c7d66909e7503e34134431475"
_CHECKPOINT_STATE_DIGEST = "0d524080b88a83862f60a361b93c7e688b08ff24f02d20d869a6025df7a2284f"
_CHECKPOINT_SNAPSHOT_DIGEST = "5e7b584e1a5f89293319a4af5fae52da8e2c7fb138bced8fbed260cd57812017"
_CHECKPOINT_EVENT_DIGEST = "98e85262245cee0c2f0995c22528f4b64e0931eed06116d06ee9c68b16c69e1a"
_CREATED_ZONE_IDS = (
    "14bdf4070520cf478c76eabb3481d87f4da06dca8727212eda06a359b179459e",
    "f2a3c234d0208facb90df8f876541490c003d70fda8068bb12767c67a6dd1fd3",
    "54423ceb30a12e2c2f03d3839563260f57fbce20836b7feded4b02e36d0f0fea",
    "2fb91c19841ba91d5413608aa6991d57c94b31bcc19b24164c6952354f2fc358",
)
_TERMINAL_STATUSES = (
    (
        "f2a3c234d0208facb90df8f876541490c003d70fda8068bb12767c67a6dd1fd3",
        "BROKEN",
    ),
    (
        "14bdf4070520cf478c76eabb3481d87f4da06dca8727212eda06a359b179459e",
        "EXPIRED",
    ),
)


def _key(*, symbol: str = "BTCUSDT", timeframe: str = "1h") -> SRStateKey:
    return SRStateKey(venue="binance", symbol=symbol, timeframe=timeframe)


def _config(key: SRStateKey, *, pivot_span_bars: int = 1) -> ResolvedSRConfig:
    return ResolvedSRConfig.create(
        version="1",
        asset=key.symbol,
        timeframe=key.timeframe,
        detection=DetectionConfig(
            pivot_span_bars=pivot_span_bars,
            zone_half_width_atr=0.0,
        ),
        association=AssociationConfig(merge_distance_atr=0.5),
        lifecycle=LifecycleConfig(
            touch_tolerance_atr=0.25,
            break_buffer_atr=0.5,
            break_confirm_closes=2,
            max_age_bars=5,
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
) -> ClosedBar:
    return ClosedBar(
        state_key=key,
        bar_id=f"bar-{index}",
        closed_at=_T0 + timedelta(minutes=index),
        open=open_,
        high=high,
        low=low,
        close=close,
        atr_at_close=1.0,
    )


def _bars(key: SRStateKey) -> tuple[ClosedBar, ...]:
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


def _capture_trace() -> tuple[object, ...]:
    key = _key()
    config = _config(key)
    state = create_initial_state(key, config)
    engine = SREngine()
    states = []
    snapshots = []
    events = []
    candidates = []
    for bar in _bars(key):
        detection_bars = state.recent_bars + (bar,)
        candidates.append(
            tuple(
                sorted(
                    detect_confirmed_pivots(detection_bars, config.detection),
                    key=lambda candidate: (
                        candidate.formed_at,
                        candidate.available_at,
                        candidate.candidate_id,
                    ),
                )
            )
        )
        state, snapshot, emitted = engine.step(state, bar, config)
        states.append(state)
        snapshots.append(snapshot)
        events.extend(emitted)
    return state, tuple(states), tuple(snapshots), tuple(events), tuple(candidates)


def test_engine_trace_digests_lock_existing_lifecycle_behavior() -> None:
    final_state, states, snapshots, events, candidates = _capture_trace()

    assert deterministic_hash(final_state) == _FINAL_STATE_DIGEST
    assert tuple(deterministic_hash(state) for state in states) == _PER_BAR_STATE_DIGESTS
    assert deterministic_hash(snapshots) == _SNAPSHOT_DIGEST
    assert deterministic_hash(events) == _EVENT_DIGEST
    assert deterministic_hash(candidates) == _CANDIDATE_DIGEST
    assert tuple(
        event.zone_id for event in events if event.event_type.value == "CREATED"
    ) == _CREATED_ZONE_IDS
    assert tuple(
        (record.definition.zone_id, record.runtime.status.value)
        for record in final_state.zones
        if record.runtime.status.value in {"BROKEN", "EXPIRED"}
    ) == _TERMINAL_STATUSES


@pytest.mark.parametrize("split", range(1, 8))
def test_checkpoint_resume_is_exact_after_every_sensitive_transition(
    split: int,
) -> None:
    key = _key()
    config = _config(key)
    bars = _bars(key)
    initial = create_initial_state(key, config)
    full_state, full_snapshots = replay_bars(initial, bars, config)
    checkpoint_state, _ = replay_bars(initial, bars[:split], config)
    resumed = decode_state(encode_state(checkpoint_state))
    final_state, suffix_snapshots = replay_bars(resumed, bars[split:], config)

    assert final_state == full_state
    assert suffix_snapshots == full_snapshots[split:]


def test_checkpoint_split_digest_locks_codec_and_lifecycle_boundary() -> None:
    key = _key()
    config = _config(key)
    bars = _bars(key)
    initial = create_initial_state(key, config)
    checkpoint_state, _ = replay_bars(initial, bars[:4], config)
    encoded = encode_state(checkpoint_state)
    resumed = decode_state(encoded)
    _, suffix_snapshots = replay_bars(resumed, bars[4:], config)
    suffix_events = tuple(
        event for snapshot in suffix_snapshots for event in snapshot.events
    )

    assert sha256(encoded.encode("utf-8")).hexdigest() == _CHECKPOINT_STATE_DIGEST
    assert deterministic_hash(suffix_snapshots) == _CHECKPOINT_SNAPSHOT_DIGEST
    assert deterministic_hash(suffix_events) == _CHECKPOINT_EVENT_DIGEST


def test_step_keeps_invalid_input_validation_order() -> None:
    engine = SREngine()
    key = _key()
    config = _config(key)
    state = create_initial_state(key, config)
    valid_bar = _bars(key)[0]

    with pytest.raises(ContractValidationError, match="previous_state must be SRState"):
        engine.step(object(), object(), object())
    with pytest.raises(ContractValidationError, match="closed_bar must be ClosedBar"):
        engine.step(state, object(), object())
    with pytest.raises(
        ContractValidationError,
        match="resolved_config must be ResolvedSRConfig",
    ):
        engine.step(state, valid_bar, object())

    other_key = _key(symbol="ETHUSDT")
    mismatched_bar = _bar(
        other_key,
        0,
        open_=97.5,
        high=100.0,
        low=95.0,
        close=97.5,
    )
    with pytest.raises(
        ContractValidationError,
        match="closed_bar.state_key must match previous_state.state_key",
    ):
        engine.step(state, mismatched_bar, _config(other_key))

    incompatible_config = _config(key, pivot_span_bars=2)
    with pytest.raises(
        ContractValidationError,
        match="state.config_hash must match resolved configuration hash",
    ):
        engine.step(state, valid_bar, incompatible_config)
