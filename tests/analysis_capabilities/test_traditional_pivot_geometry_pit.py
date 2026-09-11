from datetime import UTC, datetime, timedelta

import pytest

from libs.analysis_capabilities.ta.traditional_pivot_geometry import (
    TraditionalPivotGeometryRequest,
    TraditionalPivotGeometrySnapshot,
    TraditionalPivotLevel,
    TraditionalPivotReference,
    compute_traditional_pivot_geometry,
)

OPENED = datetime(2026, 2, 1, tzinfo=UTC)
CLOSED = OPENED + timedelta(hours=4)


def _reference() -> TraditionalPivotReference:
    return TraditionalPivotReference(OPENED, CLOSED, 110.0, 90.0, 100.0)


def test_reference_is_unavailable_before_close_and_available_at_close() -> None:
    reference = _reference()
    with pytest.raises(ValueError):
        TraditionalPivotGeometryRequest(
            reference,
            CLOSED - timedelta(microseconds=1),
        )

    request = TraditionalPivotGeometryRequest(reference, CLOSED)
    snapshot = compute_traditional_pivot_geometry(request)
    assert snapshot.market_as_of == CLOSED
    assert snapshot.reference is reference


def test_later_cutoffs_change_only_snapshot_cutoff() -> None:
    reference = _reference()
    at_close = compute_traditional_pivot_geometry(
        TraditionalPivotGeometryRequest(reference, CLOSED)
    )
    later = compute_traditional_pivot_geometry(
        TraditionalPivotGeometryRequest(reference, CLOSED + timedelta(days=7))
    )

    assert at_close.levels == later.levels
    assert at_close.reference is reference
    assert later.reference is reference
    assert at_close.market_as_of != later.market_as_of


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "opened_at": OPENED,
            "closed_at": OPENED,
            "high": 10,
            "low": 5,
            "close": 7,
        },
        {
            "opened_at": OPENED,
            "closed_at": OPENED - timedelta(hours=1),
            "high": 10,
            "low": 5,
            "close": 7,
        },
        {
            "opened_at": OPENED.replace(tzinfo=None),
            "closed_at": CLOSED,
            "high": 10,
            "low": 5,
            "close": 7,
        },
        {
            "opened_at": OPENED,
            "closed_at": CLOSED,
            "high": 5,
            "low": 10,
            "close": 7,
        },
        {
            "opened_at": OPENED,
            "closed_at": CLOSED,
            "high": 10,
            "low": 5,
            "close": 11,
        },
        {
            "opened_at": OPENED,
            "closed_at": CLOSED,
            "high": True,
            "low": 5,
            "close": 5,
        },
        {
            "opened_at": OPENED,
            "closed_at": CLOSED,
            "high": float("inf"),
            "low": 5,
            "close": 5,
        },
    ],
)
def test_invalid_reference_inputs_fail_closed(kwargs: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        TraditionalPivotReference(**kwargs)  # type: ignore[arg-type]


def test_checked_snapshot_rejects_wrong_level_order() -> None:
    reference = _reference()
    valid = compute_traditional_pivot_geometry(
        TraditionalPivotGeometryRequest(reference, CLOSED)
    )
    with pytest.raises(ValueError):
        TraditionalPivotGeometrySnapshot(
            CLOSED,
            reference,
            tuple(reversed(valid.levels)),
        )


@pytest.mark.parametrize("name,price", [("unknown", 1.0), ("pivot", True)])
def test_level_contract_rejects_invalid_name_or_price(
    name: str,
    price: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        TraditionalPivotLevel(name, price)  # type: ignore[arg-type]
