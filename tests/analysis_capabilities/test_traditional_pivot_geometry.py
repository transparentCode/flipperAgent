import math
import random
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from itertools import pairwise

import pytest

from libs.analysis_capabilities.execution import execute_analysis_capability
from libs.analysis_capabilities.ta.traditional_pivot_geometry import (
    TraditionalPivotGeometryRequest,
    TraditionalPivotGeometrySnapshot,
    TraditionalPivotLevel,
    TraditionalPivotReference,
    compute_traditional_pivot_geometry,
)

OPENED = datetime(2026, 1, 1, tzinfo=UTC)
CLOSED = OPENED + timedelta(hours=4)


def _reference(
    high: float = 110.0,
    low: float = 90.0,
    close: float = 100.0,
) -> TraditionalPivotReference:
    return TraditionalPivotReference(OPENED, CLOSED, high, low, close)


def _request(
    reference: TraditionalPivotReference | None = None,
) -> TraditionalPivotGeometryRequest:
    return TraditionalPivotGeometryRequest(reference or _reference(), CLOSED)


def test_traditional_vendor_fixture_matches_exact_values() -> None:
    snapshot = compute_traditional_pivot_geometry(_request())

    assert tuple(level.name for level in snapshot.levels) == (
        "s3",
        "s2",
        "s1",
        "pivot",
        "r1",
        "r2",
        "r3",
    )
    assert tuple(level.price for level in snapshot.levels) == (
        70.0,
        80.0,
        90.0,
        100.0,
        110.0,
        120.0,
        130.0,
    )


def test_asymmetric_close_uses_independent_precomputed_constants() -> None:
    snapshot = compute_traditional_pivot_geometry(_request(_reference(120, 90, 99)))

    assert tuple(level.price for level in snapshot.levels) == (
        56.0,
        73.0,
        86.0,
        103.0,
        116.0,
        133.0,
        146.0,
    )


def test_flat_adjacent_decimal_float_remains_exactly_flat() -> None:
    snapshot = compute_traditional_pivot_geometry(_request(_reference(0.1, 0.1, 0.1)))

    assert all(level.price == 0.1 for level in snapshot.levels)
    assert tuple(level.price for level in snapshot.levels) == (0.1,) * 7


def test_randomized_references_match_fraction_oracle_and_ordering() -> None:
    rng = random.Random(20260910)
    for _ in range(200):
        low = rng.uniform(0.01, 1_000.0)
        high = rng.uniform(low, low + 1_000.0)
        close = rng.uniform(low, high)
        snapshot = compute_traditional_pivot_geometry(
            _request(_reference(high, low, close))
        )

        high_exact = Fraction.from_float(high)
        low_exact = Fraction.from_float(low)
        close_exact = Fraction.from_float(close)
        pivot_exact = (
            low_exact + (high_exact - low_exact) / 3 + (close_exact - low_exact) / 3
        )
        expected_exact = (
            low_exact - 2 * (high_exact - pivot_exact),
            pivot_exact - (high_exact - low_exact),
            2 * pivot_exact - high_exact,
            pivot_exact,
            2 * pivot_exact - low_exact,
            pivot_exact + (high_exact - low_exact),
            high_exact + 2 * (pivot_exact - low_exact),
        )
        actual = tuple(level.price for level in snapshot.levels)
        expected = tuple(float(value) for value in expected_exact)
        assert all(
            math.isclose(
                observed,
                target,
                rel_tol=1e-12,
                abs_tol=max(math.ulp(target) * 4, 1e-15),
            )
            for observed, target in zip(actual, expected)
        )
        assert all(left <= right for left, right in pairwise(actual))


def test_direct_provider_and_dispatcher_have_exact_parity() -> None:
    request = _request()

    assert compute_traditional_pivot_geometry(request) == execute_analysis_capability(
        "ta.traditional_pivot_geometry",
        request,
    )


def test_checked_snapshot_rejects_forged_level_prices() -> None:
    reference = _reference()
    forged_levels = tuple(
        TraditionalPivotLevel(name, 999.0)
        for name in ("s3", "s2", "s1", "pivot", "r1", "r2", "r3")
    )

    with pytest.raises(ValueError, match="inconsistent"):
        TraditionalPivotGeometrySnapshot(CLOSED, reference, forged_levels)


def test_contracts_are_frozen_slotted_and_have_no_defaults() -> None:
    for contract in (
        TraditionalPivotReference,
        TraditionalPivotLevel,
        TraditionalPivotGeometryRequest,
        TraditionalPivotGeometrySnapshot,
    ):
        assert hasattr(contract, "__slots__")
        assert all(field.default is field.default_factory for field in fields(contract))

    snapshot = compute_traditional_pivot_geometry(_request())
    with pytest.raises(FrozenInstanceError):
        snapshot.levels = ()  # type: ignore[misc]
