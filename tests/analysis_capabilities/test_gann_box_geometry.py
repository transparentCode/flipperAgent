from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from libs.analysis_capabilities.execution import execute_analysis_capability
from libs.analysis_capabilities.invocation import (
    AnalysisBindingError,
    AnalysisInvocationContext,
    AnalysisSeriesIdentity,
    AnalysisSourceAttestation,
    execute_bound_analysis_capability,
)
from libs.analysis_capabilities.ta.gann_box_geometry import (
    GannBoxGeometryRequest,
    GannCoordinate,
    compute_gann_box_geometry,
)
from libs.analysis_capabilities.ta.parallel_channel_geometry import ParallelChannelBar

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _bars() -> tuple[ParallelChannelBar, ...]:
    return tuple(
        ParallelChannelBar(_START + timedelta(hours=offset))
        for offset in (0, 1, 2, 8, 9, 20)
    )


def _request(
    *,
    start_price: float = 100.0,
    end_price: float = 160.0,
    price_levels: tuple[float, ...] = (0.0, 0.25, 0.5, 1.0),
    time_levels: tuple[float, ...] = (0.0, 0.5, 1.0),
) -> GannBoxGeometryRequest:
    bars = _bars()
    return GannBoxGeometryRequest(
        bars=bars,
        start=GannCoordinate(bars[1].closed_at, bars[2].closed_at, start_price),
        end=GannCoordinate(bars[3].closed_at, bars[4].closed_at, end_price),
        price_levels=price_levels,
        time_levels=time_levels,
        market_as_of=bars[-1].closed_at,
    )


def _context(cutoff: datetime, *, source_available_at: datetime | None = None):
    series = AnalysisSeriesIdentity(
        asset="BTCUSDT",
        venue="fixture",
        instrument_id="fixture:BTCUSDT",
        timeframe="1h",
    )
    return AnalysisInvocationContext(
        source=AnalysisSourceAttestation(
            series=series,
            source_type="fixture",
            source_provider=None,
            source_timeframe=None,
            source_revision="gann-box-test",
            source_slice_sha256="b" * 64,
            source_available_at=source_available_at or cutoff,
            volume_unit=None,
        ),
        market_as_of=cutoff,
        request_available_at=cutoff + timedelta(minutes=1),
        evaluation_at=cutoff + timedelta(minutes=2),
    )


def test_positive_price_delta_grid_uses_fractional_ordinal_positions() -> None:
    snapshot = compute_gann_box_geometry(_request())

    assert snapshot.start_bar_index == 1
    assert snapshot.end_bar_index == 3
    assert tuple(level.price for level in snapshot.price_levels) == (
        100.0,
        115.0,
        130.0,
        160.0,
    )
    assert tuple(level.bar_position for level in snapshot.time_levels) == (
        1.0,
        2.0,
        3.0,
    )


def test_negative_price_delta_grid_is_supported() -> None:
    snapshot = compute_gann_box_geometry(_request(start_price=200.0, end_price=120.0))

    assert tuple(level.price for level in snapshot.price_levels) == (
        200.0,
        180.0,
        160.0,
        120.0,
    )


def test_irregular_wall_clock_bars_do_not_interpolate_timestamps() -> None:
    snapshot = compute_gann_box_geometry(_request(time_levels=(0.0, 0.25, 0.75, 1.0)))

    assert tuple(level.bar_position for level in snapshot.time_levels) == (
        1.0,
        1.5,
        2.5,
        3.0,
    )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda request: replace(
            request,
            start=GannCoordinate(
                _START + timedelta(hours=99),
                _START + timedelta(hours=99),
                100.0,
            ),
        ),
        lambda request: replace(
            request,
            end=GannCoordinate(
                request.market_as_of,
                request.market_as_of + timedelta(hours=1),
                160.0,
            ),
        ),
        lambda request: replace(
            request,
            start=GannCoordinate(
                request.end.formed_at,
                request.end.available_at,
                100.0,
            ),
        ),
        lambda request: replace(
            request,
            end=GannCoordinate(
                request.end.formed_at,
                request.end.available_at,
                100.0,
            ),
        ),
    ],
)
def test_missing_late_equal_and_unavailable_coordinates_fail(mutator) -> None:
    with pytest.raises((TypeError, ValueError)):
        mutator(_request())


@pytest.mark.parametrize(
    "field_name, levels",
    [
        ("price_levels", ()),
        ("time_levels", (0.0, 0.5)),
        ("price_levels", (-0.1, 0.0, 1.0)),
        ("time_levels", (0.0, 1.1)),
        ("price_levels", (0.0, 0.5, 0.5, 1.0)),
        ("time_levels", (0.5, 0.0, 1.0)),
    ],
)
def test_level_tuples_are_explicit_ordered_and_endpoint_complete(
    field_name, levels
) -> None:
    with pytest.raises(ValueError):
        replace(_request(), **{field_name: levels})


def test_snapshot_rejects_forged_level() -> None:
    snapshot = compute_gann_box_geometry(_request())
    with pytest.raises(ValueError):
        replace(
            snapshot,
            price_levels=(replace(snapshot.price_levels[1], price=999.0),)
            + snapshot.price_levels[1:],
        )


def test_direct_dispatcher_matches_native_kernel() -> None:
    request = _request()
    assert execute_analysis_capability(
        "ta.gann_box_geometry", request
    ) == compute_gann_box_geometry(request)


def test_bound_box_parity_and_parameter_fingerprint() -> None:
    request = _request()
    bound = execute_bound_analysis_capability(
        "ta.gann_box_geometry", request, _context(request.market_as_of)
    )
    changed = execute_bound_analysis_capability(
        "ta.gann_box_geometry",
        replace(request, time_levels=(0.0, 0.25, 1.0)),
        _context(request.market_as_of),
    )
    assert bound.result == compute_gann_box_geometry(request)
    assert bound.parameter_identity == (
        (
            "price_levels",
            "0x0.0p+0,0x1.0000000000000p-2,0x1.0000000000000p-1,0x1.0000000000000p+0",
        ),
        ("time_levels", "0x0.0p+0,0x1.0000000000000p-1,0x1.0000000000000p+0"),
    )
    assert bound.parameter_fingerprint != changed.parameter_fingerprint


def test_bound_box_requires_source_and_request_availability() -> None:
    request = _request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.gann_box_geometry",
            request,
            _context(
                request.market_as_of,
                source_available_at=request.market_as_of - timedelta(seconds=1),
            ),
        )
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.gann_box_geometry",
            request,
            _context(request.market_as_of - timedelta(hours=1)),
        )
