from __future__ import annotations

import pytest

from libs.models.trendline_family.contracts import InteractionObservationState
from libs.models.trendline_family.interactions import (
    InteractionAtr,
    build_interaction_zone,
    calculate_interaction_atr,
    evaluate_family_interaction,
)

from .tracker_support import interaction_family, timestamp, tracker_config, tracker_ohlcv


def _state(config, *, candle: tuple[float, float, float, float], atr: float = 2.0):
    return evaluate_family_interaction(
        interaction_family(config, timestamp()),
        timestamp=timestamp(),
        open_price=candle[0],
        high_price=candle[1],
        low_price=candle[2],
        close_price=candle[3],
        interaction_atr=InteractionAtr(value=atr, method="simple_true_range_mean_v1", sample_count=3),
        config=config,
        tick_size=None,
    ).observation.state


def test_tolerance_atr_changes_the_zone_classification() -> None:
    narrow = tracker_config(interaction={"tolerance_atr": 0.10, "approaching_distance_atr": 0.50})
    wide = tracker_config(interaction={"tolerance_atr": 0.50, "approaching_distance_atr": 0.50})
    candle = (101.1, 101.2, 101.0, 101.1)

    assert _state(narrow, candle=candle) is InteractionObservationState.APPROACHING
    assert _state(wide, candle=candle) is InteractionObservationState.IN_ZONE


def test_approaching_distance_atr_changes_only_the_approaching_gate() -> None:
    near = tracker_config(interaction={"tolerance_atr": 0.10, "approaching_distance_atr": 0.20})
    far = tracker_config(interaction={"tolerance_atr": 0.10, "approaching_distance_atr": 0.30})
    candle = (100.8, 101.0, 100.7, 100.8)

    assert _state(near, candle=candle) is InteractionObservationState.FAR
    assert _state(far, candle=candle) is InteractionObservationState.APPROACHING


def test_interaction_atr_window_changes_interaction_owned_normalization() -> None:
    observed = timestamp()
    frame = tracker_ohlcv(observed)
    frame.loc[frame.index[-1], ["high", "low"]] = (110.0, 90.0)

    short = calculate_interaction_atr(frame, window=1)
    long = calculate_interaction_atr(frame, window=3)

    assert short.method == "simple_true_range_mean_v1"
    assert short.value != long.value
    assert short.sample_count == 1
    assert long.sample_count == 3


def test_minimum_zone_ticks_changes_tick_floor_width() -> None:
    one_tick = tracker_config(interaction={"tolerance_atr": 0.10, "minimum_zone_ticks": 1})
    three_ticks = tracker_config(interaction={"tolerance_atr": 0.10, "minimum_zone_ticks": 3})
    atr = InteractionAtr(value=2.0, method="simple_true_range_mean_v1", sample_count=3)

    one = build_interaction_zone(
        interaction_family(one_tick, timestamp()),
        timestamp=timestamp(),
        interaction_atr=atr,
        config=one_tick,
        tick_size=0.5,
    )
    three = build_interaction_zone(
        interaction_family(three_ticks, timestamp()),
        timestamp=timestamp(),
        interaction_atr=atr,
        config=three_ticks,
        tick_size=0.5,
    )

    assert one.zone.upper_price == pytest.approx(100.5)
    assert three.zone.upper_price == pytest.approx(101.5)
