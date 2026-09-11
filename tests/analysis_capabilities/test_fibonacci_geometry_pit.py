import math
from datetime import UTC, datetime, timedelta

import pytest

from libs.analysis_capabilities.ta.fibonacci_geometry import (
    FibonacciGeometryRequest,
    FibonacciGeometrySnapshot,
    FibonacciLevel,
    compute_fibonacci_geometry,
)
from libs.analysis_capabilities.ta.swing_anchors import SwingAnchor

T0 = datetime(2026, 2, 1, tzinfo=UTC)


def _up_anchors() -> tuple[SwingAnchor, SwingAnchor]:
    return (
        SwingAnchor("swing_low", T0, T0 + timedelta(hours=2), 100.0),
        SwingAnchor(
            "swing_high", T0 + timedelta(hours=3), T0 + timedelta(hours=5), 200.0
        ),
    )


def _request(cutoff: datetime, *, down: bool = False) -> FibonacciGeometryRequest:
    if down:
        start, end = (
            SwingAnchor("swing_high", T0, T0 + timedelta(hours=2), 200.0),
            SwingAnchor(
                "swing_low", T0 + timedelta(hours=3), T0 + timedelta(hours=5), 100.0
            ),
        )
    else:
        start, end = _up_anchors()
    return FibonacciGeometryRequest(start, end, cutoff, (0.25, 0.5), (1.5,))


def test_cutoff_is_explicit_and_later_cutoffs_do_not_change_geometry() -> None:
    start, end = _up_anchors()
    with pytest.raises(ValueError):
        _request(start.available_at - timedelta(microseconds=1))
    with pytest.raises(ValueError):
        _request(end.available_at - timedelta(microseconds=1))

    at_end = _request(end.available_at)
    later = _request(end.available_at + timedelta(days=1))
    at_snapshot = compute_fibonacci_geometry(at_end)
    later_snapshot = compute_fibonacci_geometry(later)

    assert at_snapshot.market_as_of == end.available_at
    assert later_snapshot.market_as_of == end.available_at + timedelta(days=1)
    assert at_snapshot.start_anchor is at_end.start_anchor
    assert at_snapshot.end_anchor is at_end.end_anchor
    assert at_snapshot.retracements == later_snapshot.retracements
    assert at_snapshot.extensions == later_snapshot.extensions


@pytest.mark.parametrize(
    "start_kind,end_kind,start_price,end_price",
    [
        ("swing_low", "swing_low", 100.0, 120.0),
        ("swing_high", "swing_high", 120.0, 100.0),
        ("swing_high", "swing_low", 100.0, 120.0),
        ("swing_low", "swing_high", 120.0, 100.0),
        ("swing_low", "swing_high", 100.0, 100.0),
    ],
)
def test_invalid_anchor_legs_fail_closed(
    start_kind: str, end_kind: str, start_price: float, end_price: float
) -> None:
    start = SwingAnchor(start_kind, T0, T0 + timedelta(hours=1), start_price)
    end = SwingAnchor(
        end_kind,
        T0 + timedelta(hours=2),
        T0 + timedelta(hours=3),
        end_price,
    )
    with pytest.raises(ValueError):
        FibonacciGeometryRequest(start, end, T0 + timedelta(hours=4), (0.5,), (1.5,))


def test_formation_order_is_not_issuance_order() -> None:
    start, end = _up_anchors()
    reversed_start = SwingAnchor("swing_low", end.formed_at, end.available_at, 100.0)
    with pytest.raises(ValueError):
        FibonacciGeometryRequest(
            reversed_start,
            start,
            end.available_at,
            (0.5,),
            (1.5,),
        )


def test_down_extension_preserves_signed_negative_geometry() -> None:
    start = SwingAnchor("swing_high", T0, T0 + timedelta(hours=1), 100.0)
    end = SwingAnchor(
        "swing_low",
        T0 + timedelta(hours=2),
        T0 + timedelta(hours=3),
        1.0,
    )
    request = FibonacciGeometryRequest(
        start,
        end,
        T0 + timedelta(hours=5),
        (),
        (2.0,),
    )
    snapshot = compute_fibonacci_geometry(request)
    assert snapshot.extensions[0].price == -98.0


def test_snapshot_revalidates_direction_levels_and_cutoff() -> None:
    start, end = _up_anchors()
    retracement = FibonacciLevel("retracement", 0.5, 150.0)
    extension = FibonacciLevel("extension", 1.5, 250.0)
    snapshot = FibonacciGeometrySnapshot(
        end.available_at,
        "up",
        start,
        end,
        (retracement,),
        (extension,),
    )
    assert snapshot.market_as_of == end.available_at
    with pytest.raises(ValueError):
        FibonacciGeometrySnapshot(
            end.available_at,
            "down",
            start,
            end,
            (retracement,),
            (extension,),
        )
    with pytest.raises(ValueError, match="inconsistent"):
        FibonacciGeometrySnapshot(
            end.available_at,
            "up",
            start,
            end,
            (FibonacciLevel("retracement", 0.5, 151.0),),
            (extension,),
        )
    with pytest.raises(ValueError):
        FibonacciGeometrySnapshot(
            end.available_at - timedelta(microseconds=1),
            "up",
            start,
            end,
            (retracement,),
            (extension,),
        )


def test_input_ratio_tuple_and_anchor_values_are_not_mutated() -> None:
    start, end = _up_anchors()
    ratios = (0.25, 0.5)
    request = FibonacciGeometryRequest(start, end, end.available_at, ratios, (1.5,))
    snapshot = compute_fibonacci_geometry(request)
    assert request.retracement_ratios == ratios
    assert snapshot.start_anchor == start
    assert snapshot.end_anchor == end


def test_adjacent_float_level_that_collapses_to_endpoint_is_rejected() -> None:
    start = SwingAnchor("swing_low", T0, T0 + timedelta(hours=1), 1.0)
    end = SwingAnchor(
        "swing_high",
        T0 + timedelta(hours=2),
        T0 + timedelta(hours=3),
        1.0000000000000002,
    )
    request = FibonacciGeometryRequest(
        start,
        end,
        end.available_at,
        (0.5,),
        (),
    )
    with pytest.raises(ValueError, match="not representable"):
        compute_fibonacci_geometry(request)


def test_adjacent_float_extension_that_collapses_to_endpoint_is_rejected() -> None:
    start = SwingAnchor("swing_low", T0, T0 + timedelta(hours=1), 1e16)
    end = SwingAnchor(
        "swing_high",
        T0 + timedelta(hours=2),
        T0 + timedelta(hours=3),
        math.nextafter(1e16, math.inf),
    )
    request = FibonacciGeometryRequest(
        start,
        end,
        end.available_at,
        (),
        (math.nextafter(1.0, math.inf),),
    )
    with pytest.raises(ValueError, match="not representable"):
        compute_fibonacci_geometry(request)
