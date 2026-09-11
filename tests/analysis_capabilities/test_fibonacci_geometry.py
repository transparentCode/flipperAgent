from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta

import pytest

from libs.analysis_capabilities.execution import execute_analysis_capability
from libs.analysis_capabilities.ta.fibonacci_geometry import (
    FibonacciGeometryRequest,
    FibonacciGeometrySnapshot,
    FibonacciLevel,
    compute_fibonacci_geometry,
)
from libs.analysis_capabilities.ta.swing_anchors import SwingAnchor

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _anchors(*, down: bool = False) -> tuple[SwingAnchor, SwingAnchor]:
    if down:
        return (
            SwingAnchor("swing_high", T0, T0 + timedelta(hours=1), 160.0),
            SwingAnchor(
                "swing_low", T0 + timedelta(hours=2), T0 + timedelta(hours=3), 100.0
            ),
        )
    return (
        SwingAnchor("swing_low", T0, T0 + timedelta(hours=1), 100.0),
        SwingAnchor(
            "swing_high", T0 + timedelta(hours=2), T0 + timedelta(hours=3), 160.0
        ),
    )


def _request(*, down: bool = False) -> FibonacciGeometryRequest:
    start, end = _anchors(down=down)
    return FibonacciGeometryRequest(
        start_anchor=start,
        end_anchor=end,
        market_as_of=T0 + timedelta(hours=4),
        retracement_ratios=(0.25, 0.5),
        extension_ratios=(1.25, 1.5),
    )


def test_up_geometry_uses_exact_explicit_anchors_and_formulas() -> None:
    request = _request()
    snapshot = compute_fibonacci_geometry(request)

    assert snapshot.direction == "up"
    assert snapshot.start_anchor is request.start_anchor
    assert snapshot.end_anchor is request.end_anchor
    assert [level.price for level in snapshot.retracements] == [145.0, 130.0]
    assert [level.price for level in snapshot.extensions] == [175.0, 190.0]
    assert [level.ratio for level in snapshot.retracements] == [0.25, 0.5]
    assert [level.ratio for level in snapshot.extensions] == [1.25, 1.5]


def test_down_geometry_and_single_kind_ratio_sets() -> None:
    request = _request(down=True)
    snapshot = compute_fibonacci_geometry(request)

    assert snapshot.direction == "down"
    assert [level.price for level in snapshot.retracements] == [115.0, 130.0]
    assert [level.price for level in snapshot.extensions] == [85.0, 70.0]

    start, end = _anchors()
    retracement_only = FibonacciGeometryRequest(
        start, end, T0 + timedelta(hours=4), (0.5,), ()
    )
    extension_only = FibonacciGeometryRequest(
        start, end, T0 + timedelta(hours=4), (), (1.5,)
    )
    assert len(compute_fibonacci_geometry(retracement_only).extensions) == 0
    assert len(compute_fibonacci_geometry(extension_only).retracements) == 0


def test_direct_provider_and_dispatcher_have_exact_parity() -> None:
    request = _request()

    assert compute_fibonacci_geometry(request) == execute_analysis_capability(
        "ta.fibonacci_geometry", request
    )


def test_contracts_are_frozen_slotted_and_have_no_defaults() -> None:
    for contract in (
        FibonacciLevel,
        FibonacciGeometryRequest,
        FibonacciGeometrySnapshot,
    ):
        assert hasattr(contract, "__slots__")
        assert all(field.default is field.default_factory for field in fields(contract))

    snapshot = compute_fibonacci_geometry(_request())
    with pytest.raises(FrozenInstanceError):
        snapshot.direction = "down"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snapshot.retracements = ()  # type: ignore[misc]


@pytest.mark.parametrize(
    ("retracements", "extensions"),
    [
        ((), ()),
        ((0.5, 0.4), ()),
        ((0.5, 0.5), ()),
        ((0.0,), ()),
        ((1.0,), ()),
        ((), (1.0,)),
        ((), (0.5,)),
    ],
)
def test_ratio_collections_are_explicit_ordered_and_domain_checked(
    retracements: tuple[float, ...], extensions: tuple[float, ...]
) -> None:
    start, end = _anchors()
    with pytest.raises((TypeError, ValueError)):
        FibonacciGeometryRequest(
            start,
            end,
            T0 + timedelta(hours=4),
            retracements,
            extensions,
        )
