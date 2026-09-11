import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from libs.analysis_capabilities.ta.vwap_geometry import (
    VWAPBar,
    VWAPGeometryRequest,
    VWAPGeometrySnapshot,
    compute_vwap_geometry,
)

START = datetime(2026, 4, 1, 23, 0, tzinfo=UTC)


def _bar(index: int, *, volume: float = 1.0) -> VWAPBar:
    return VWAPBar(
        START + timedelta(hours=index),
        high=12.0 + index,
        low=9.0 + index,
        close=10.0 + index,
        volume=volume,
    )


def test_exact_cutoff_is_required_and_stale_or_future_cutoffs_fail() -> None:
    bars = (_bar(0), _bar(1))
    with pytest.raises(ValueError):
        VWAPGeometryRequest(bars, bars[-1].closed_at - timedelta(microseconds=1))
    with pytest.raises(ValueError):
        VWAPGeometryRequest(bars, bars[-1].closed_at + timedelta(microseconds=1))

    request = VWAPGeometryRequest(bars, bars[-1].closed_at)
    snapshot = compute_vwap_geometry(request)
    assert snapshot.market_as_of == bars[-1].closed_at
    assert snapshot.first_bar_closed_at == bars[0].closed_at


def test_prefixes_are_causal_and_later_suffix_cannot_change_old_prefix() -> None:
    bars = tuple(_bar(index, volume=0.0 if index == 2 else 1.0) for index in range(7))
    prefix_snapshots = []
    for end_index in range(len(bars)):
        prefix = bars[: end_index + 1]
        if not any(bar.volume > 0.0 for bar in prefix):
            continue
        prefix_snapshots.append(
            compute_vwap_geometry(VWAPGeometryRequest(prefix, prefix[-1].closed_at))
        )

    assert [snapshot.bar_count for snapshot in prefix_snapshots] == list(range(1, 8))
    assert all(
        earlier.first_bar_closed_at == bars[0].closed_at for earlier in prefix_snapshots
    )
    historical = prefix_snapshots[3]
    changed_suffix = (
        *bars[:4],
        VWAPBar(bars[4].closed_at, 100, 90, 95, 1000),
        *bars[5:],
    )
    changed_prefix = changed_suffix[:4]
    assert (
        compute_vwap_geometry(
            VWAPGeometryRequest(changed_prefix, changed_prefix[-1].closed_at)
        )
        == historical
    )


def test_every_positive_prefix_matches_independent_decimal_accumulation() -> None:
    bars = tuple(
        VWAPBar(
            START + timedelta(hours=index),
            high=20.0 + index * 1.75,
            low=10.0 + index * 0.5,
            close=15.0 + index,
            volume=0.0 if index in (2, 5) else 0.25 + index * 0.75,
        )
        for index in range(9)
    )
    expected_volume = Decimal(0)
    expected_weighted = Decimal(0)
    for end_index in range(len(bars)):
        bar = bars[end_index]
        expected_volume += Decimal(str(bar.volume))
        if bar.volume > 0.0:
            low = Decimal(str(bar.low))
            high = Decimal(str(bar.high))
            close = Decimal(str(bar.close))
            typical_price = low + (high - low) / Decimal(3) + (close - low) / Decimal(3)
            expected_weighted += typical_price * Decimal(str(bar.volume))
        if expected_volume <= 0:
            continue

        prefix = bars[: end_index + 1]
        snapshot = compute_vwap_geometry(
            VWAPGeometryRequest(prefix, prefix[-1].closed_at)
        )
        expected_vwap = expected_weighted / expected_volume
        assert snapshot.total_volume == float(expected_volume)
        assert math.isclose(
            snapshot.weighted_price_sum,
            float(expected_weighted),
            rel_tol=1e-15,
            abs_tol=1e-15,
        )
        assert math.isclose(
            snapshot.vwap_price,
            float(expected_vwap),
            rel_tol=1e-15,
            abs_tol=1e-15,
        )


def test_zero_volume_final_bar_is_counted_without_changing_vwap() -> None:
    positive = (_bar(0, volume=2.0),)
    with_zero_final = (*positive, _bar(1, volume=0.0))
    first = compute_vwap_geometry(VWAPGeometryRequest(positive, positive[-1].closed_at))
    second = compute_vwap_geometry(
        VWAPGeometryRequest(with_zero_final, with_zero_final[-1].closed_at)
    )

    assert second.bar_count == 2
    assert second.total_volume == first.total_volume
    assert second.weighted_price_sum == first.weighted_price_sum
    assert second.vwap_price == first.vwap_price


def test_utc_midnight_crossing_has_no_hidden_reset() -> None:
    bars = (_bar(0, volume=1.0), _bar(1, volume=3.0))
    snapshot = compute_vwap_geometry(VWAPGeometryRequest(bars, bars[-1].closed_at))
    expected = (((12.0 + 9.0 + 10.0) / 3.0) + (3.0 * (13.0 + 10.0 + 11.0) / 3.0)) / 4.0

    assert bars[0].closed_at.date() != bars[1].closed_at.date()
    assert snapshot.vwap_price == expected


def test_all_zero_volume_and_duplicate_or_nonincreasing_timestamps_fail() -> None:
    zero_bars = (_bar(0, volume=0.0), _bar(1, volume=0.0))
    with pytest.raises(ValueError):
        VWAPGeometryRequest(zero_bars, zero_bars[-1].closed_at)

    duplicate = (_bar(0), VWAPBar(START, 14, 10, 12, 1))
    with pytest.raises(ValueError):
        VWAPGeometryRequest(duplicate, duplicate[-1].closed_at)


def test_overflowed_weighted_sum_fails_closed() -> None:
    bars = (
        VWAPBar(START, 1e308, 1e308, 1e308, 1e308),
        VWAPBar(START + timedelta(hours=1), 1e308, 1e308, 1e308, 1e308),
    )
    request = VWAPGeometryRequest(bars, bars[-1].closed_at)
    with pytest.raises(ValueError):
        compute_vwap_geometry(request)


def test_zero_volume_extreme_bar_is_neutral_and_does_not_overflow() -> None:
    bars = (
        VWAPBar(START, 1e308, 1.0, 1.0, 0.0),
        VWAPBar(START + timedelta(hours=1), 11.0, 9.0, 10.0, 2.0),
    )
    snapshot = compute_vwap_geometry(VWAPGeometryRequest(bars, bars[-1].closed_at))
    assert snapshot.total_volume == 2.0
    assert snapshot.vwap_price == 10.0


def test_snapshot_rejects_forged_vwap_quotient() -> None:
    with pytest.raises(ValueError, match="inconsistent"):
        VWAPGeometrySnapshot(
            market_as_of=START,
            first_bar_closed_at=START,
            bar_count=1,
            total_volume=2.0,
            weighted_price_sum=20.0,
            vwap_price=11.0,
        )


def test_invalid_bar_and_request_shapes_fail_closed() -> None:
    with pytest.raises(TypeError):
        VWAPBar(START, True, 1, 1, 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        VWAPBar(START, 1, 2, 1, 1)
    with pytest.raises(ValueError):
        VWAPBar(START, 2, 1, 1, -1)
    with pytest.raises(TypeError):
        VWAPGeometryRequest([], START)  # type: ignore[arg-type]
