import random
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta

import pytest

from libs.analysis_capabilities.execution import execute_analysis_capability
from libs.analysis_capabilities.ta.vwap_geometry import (
    VWAPBar,
    VWAPGeometryRequest,
    VWAPGeometrySnapshot,
    compute_vwap_geometry,
)

START = datetime(2026, 3, 1, tzinfo=UTC)


def _bar(index: int, high: float, low: float, close: float, volume: float) -> VWAPBar:
    return VWAPBar(START + timedelta(hours=index), high, low, close, volume)


def _request(bars: tuple[VWAPBar, ...]) -> VWAPGeometryRequest:
    return VWAPGeometryRequest(bars, bars[-1].closed_at)


def test_one_bar_vwap_equals_hlc3_exactly() -> None:
    bar = _bar(0, 12.0, 9.0, 10.5, 4.0)
    snapshot = compute_vwap_geometry(_request((bar,)))

    assert snapshot.vwap_price == (12.0 + 9.0 + 10.5) / 3.0
    assert snapshot.first_bar_closed_at == bar.closed_at
    assert snapshot.bar_count == 1
    assert snapshot.total_volume == 4.0


def test_hand_calculated_unequal_volume_range_and_zero_volume_bar() -> None:
    bars = (
        _bar(0, 10.0, 8.0, 9.0, 2.0),
        _bar(1, 14.0, 10.0, 13.0, 0.0),
        _bar(2, 20.0, 14.0, 17.0, 3.0),
    )
    snapshot = compute_vwap_geometry(_request(bars))
    expected_weighted = 9.0 * 2.0 + 17.0 * 3.0

    assert snapshot.bar_count == 3
    assert snapshot.total_volume == 5.0
    assert snapshot.weighted_price_sum == expected_weighted
    assert snapshot.vwap_price == expected_weighted / 5.0


def test_randomized_independent_oracle_and_hlc3_bounds() -> None:
    rng = random.Random(20260910)
    bars: list[VWAPBar] = []
    for index in range(80):
        low = rng.uniform(1.0, 500.0)
        high = rng.uniform(low, low + 500.0)
        close = rng.uniform(low, high)
        volume = 0.0 if index % 11 == 0 else rng.uniform(0.01, 1_000.0)
        bars.append(_bar(index, high, low, close, volume))

    bars_tuple = tuple(bars)
    snapshot = compute_vwap_geometry(_request(bars_tuple))
    typical_prices = tuple((bar.high + bar.low + bar.close) / 3.0 for bar in bars_tuple)
    expected_volume = 0.0
    expected_weighted = 0.0
    for typical_price, bar in zip(typical_prices, bars_tuple):
        expected_volume += bar.volume
        expected_weighted += typical_price * bar.volume

    assert snapshot.total_volume == expected_volume
    assert snapshot.weighted_price_sum == expected_weighted
    assert snapshot.vwap_price == expected_weighted / expected_volume
    positive_prices = tuple(
        typical_price
        for typical_price, bar in zip(typical_prices, bars_tuple)
        if bar.volume > 0
    )
    assert min(positive_prices) <= snapshot.vwap_price <= max(positive_prices)


def test_volume_scale_invariance_and_accumulation_scaling() -> None:
    bars = (_bar(0, 10, 8, 9, 2), _bar(1, 20, 14, 17, 3))
    baseline = compute_vwap_geometry(_request(bars))
    scale = 7.5
    scaled = _request(
        tuple(
            VWAPBar(
                bar.closed_at,
                bar.high,
                bar.low,
                bar.close,
                bar.volume * scale,
            )
            for bar in bars
        )
    )
    scaled_snapshot = compute_vwap_geometry(scaled)

    assert scaled_snapshot.vwap_price == baseline.vwap_price
    assert scaled_snapshot.total_volume == baseline.total_volume * scale
    assert scaled_snapshot.weighted_price_sum == baseline.weighted_price_sum * scale


def test_contracts_are_frozen_slotted_and_have_no_defaults() -> None:
    for contract in (VWAPBar, VWAPGeometryRequest, VWAPGeometrySnapshot):
        assert hasattr(contract, "__slots__")
        assert all(field.default is field.default_factory for field in fields(contract))

    snapshot = compute_vwap_geometry(_request((_bar(0, 12, 9, 10, 1),)))
    with pytest.raises(FrozenInstanceError):
        snapshot.vwap_price = 11.0  # type: ignore[misc]


def test_direct_provider_and_dispatcher_have_exact_parity() -> None:
    request = _request((_bar(0, 12, 9, 10, 1),))

    assert compute_vwap_geometry(request) == execute_analysis_capability(
        "ta.vwap_geometry", request
    )
