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
from libs.analysis_capabilities.ta.gann_fan_geometry import (
    GannAngleRatio,
    GannFanGeometryRequest,
    compute_gann_fan_geometry,
)
from libs.analysis_capabilities.ta.parallel_channel_geometry import ParallelChannelBar
from libs.analysis_capabilities.ta.swing_anchors import SwingAnchor

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _bars() -> tuple[ParallelChannelBar, ...]:
    return tuple(
        ParallelChannelBar(_START + offset)
        for offset in (
            timedelta(hours=0),
            timedelta(hours=1),
            timedelta(hours=7),
            timedelta(days=2),
            timedelta(days=2, hours=1),
            timedelta(days=4),
        )
    )


def _request(
    *,
    kind: str = "swing_low",
    scale: float = 2.0,
    ratios: tuple[GannAngleRatio, ...] = (
        GannAngleRatio(1, 2),
        GannAngleRatio(1, 1),
        GannAngleRatio(2, 1),
    ),
) -> GannFanGeometryRequest:
    bars = _bars()
    anchor = SwingAnchor(
        kind,
        bars[1].closed_at,
        bars[2].closed_at,
        100.0,
    )
    return GannFanGeometryRequest(
        bars=bars,
        anchor=anchor,
        price_per_bar=scale,
        angle_ratios=ratios,
        market_as_of=bars[-1].closed_at,
    )


def _context(cutoff: datetime, *, available_at: datetime | None = None):
    series = AnalysisSeriesIdentity(
        asset="BTCUSDT",
        venue="fixture",
        instrument_id="fixture:BTCUSDT",
        timeframe="1h",
    )
    source = AnalysisSourceAttestation(
        series=series,
        source_type="fixture",
        source_provider=None,
        source_timeframe=None,
        source_revision="gann-fan-test",
        source_slice_sha256="a" * 64,
        source_available_at=available_at or cutoff,
        volume_unit=None,
    )
    return AnalysisInvocationContext(
        source=source,
        market_as_of=cutoff,
        request_available_at=cutoff + timedelta(minutes=1),
        evaluation_at=cutoff + timedelta(minutes=2),
    )


def test_ascending_fan_uses_bar_ordinals_and_exact_one_x_one_arithmetic() -> None:
    request = _request(ratios=(GannAngleRatio(1, 1),))
    snapshot = compute_gann_fan_geometry(request)

    assert snapshot.direction == "up"
    assert snapshot.rays[0].slope_per_bar == 2.0
    assert snapshot.rays[0].price_at_market_as_of == 108.0


def test_descending_fan_uses_negative_one_x_one_slope() -> None:
    request = _request(kind="swing_high", ratios=(GannAngleRatio(1, 1),))
    snapshot = compute_gann_fan_geometry(request)

    assert snapshot.direction == "down"
    assert snapshot.rays[0].slope_per_bar == -2.0
    assert snapshot.rays[0].price_at_market_as_of == 92.0


def test_two_ratios_have_cross_scaled_slopes() -> None:
    request = _request(
        scale=3.0,
        ratios=(GannAngleRatio(1, 2), GannAngleRatio(2, 1)),
    )
    snapshot = compute_gann_fan_geometry(request)

    assert tuple(ray.slope_per_bar for ray in snapshot.rays) == (1.5, 6.0)


def test_irregular_wall_clock_spacing_does_not_change_ordinal_geometry() -> None:
    request = _request(scale=1.0, ratios=(GannAngleRatio(1, 1),))
    snapshot = compute_gann_fan_geometry(request)

    assert snapshot.bar_span == 4
    assert snapshot.rays[0].price_at_market_as_of == 104.0


@pytest.mark.parametrize(
    "bad_request",
    [
        lambda: replace(
            _request(),
            anchor=SwingAnchor(
                "swing_low",
                _START + timedelta(hours=2),
                _START + timedelta(hours=3),
                100.0,
            ),
        ),
        lambda: replace(
            _request(),
            anchor=SwingAnchor(
                "swing_low",
                _bars()[1].closed_at,
                _bars()[-1].closed_at + timedelta(hours=1),
                100.0,
            ),
        ),
        lambda: replace(_request(), price_per_bar=0.0),
        lambda: replace(_request(), price_per_bar=float("inf")),
        lambda: replace(_request(), angle_ratios=()),
    ],
)
def test_invalid_anchor_scale_and_ratio_inputs_fail_closed(bad_request) -> None:
    with pytest.raises((TypeError, ValueError)):
        bad_request()


@pytest.mark.parametrize(
    "args",
    [(True, 1), (0, 1), (-1, 1), (2, 2)],
)
def test_ratio_units_must_be_positive_reduced_integers(args) -> None:
    with pytest.raises((TypeError, ValueError)):
        GannAngleRatio(*args)


def test_duplicate_and_unsorted_ratios_fail_without_float_sorting() -> None:
    with pytest.raises(ValueError):
        _request(ratios=(GannAngleRatio(1, 1), GannAngleRatio(1, 1)))
    with pytest.raises(ValueError):
        _request(ratios=(GannAngleRatio(2, 1), GannAngleRatio(1, 1)))


def test_snapshot_rejects_forged_slope_or_price() -> None:
    request = _request()
    snapshot = compute_gann_fan_geometry(request)
    with pytest.raises(ValueError):
        replace(snapshot, rays=(replace(snapshot.rays[0], slope_per_bar=9.0),))
    with pytest.raises(ValueError):
        replace(
            snapshot,
            rays=(replace(snapshot.rays[0], price_at_market_as_of=999.0),)
            + snapshot.rays[1:],
        )


def test_snapshot_uses_request_span_instead_of_inferring_it_from_ray_prices() -> None:
    snapshot = compute_gann_fan_geometry(_request())
    wrong_span = 9
    forged_rays = tuple(
        replace(
            ray,
            price_at_market_as_of=(
                snapshot.anchor.price + ray.slope_per_bar * wrong_span
            ),
        )
        for ray in snapshot.rays
    )

    with pytest.raises(ValueError):
        replace(snapshot, rays=forged_rays)
    with pytest.raises(ValueError):
        replace(snapshot, bar_span=wrong_span)


@pytest.mark.parametrize("bar_span", [True, 0, -1, "4"])
def test_snapshot_bar_span_is_a_positive_integer(bar_span) -> None:
    snapshot = compute_gann_fan_geometry(_request())
    with pytest.raises((TypeError, ValueError)):
        replace(snapshot, bar_span=bar_span)


def test_direct_dispatcher_matches_native_kernel() -> None:
    request = _request()
    assert execute_analysis_capability(
        "ta.gann_fan_geometry", request
    ) == compute_gann_fan_geometry(request)


def test_bound_result_matches_direct_and_parameter_identity_is_stable() -> None:
    request = _request()
    direct = compute_gann_fan_geometry(request)
    bound = execute_bound_analysis_capability(
        "ta.gann_fan_geometry",
        request,
        _context(request.market_as_of),
    )
    changed_scale = execute_bound_analysis_capability(
        "ta.gann_fan_geometry",
        replace(request, price_per_bar=3.0),
        _context(request.market_as_of),
    )
    assert bound.result == direct
    assert bound.parameter_identity == (
        ("angle_ratios", "1x2,1x1,2x1"),
        ("price_per_bar", "0x1.0000000000000p+1"),
    )
    assert bound.parameter_fingerprint != changed_scale.parameter_fingerprint


def test_bound_fan_requires_cutoff_and_source_availability() -> None:
    request = _request()
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.gann_fan_geometry",
            request,
            _context(request.market_as_of - timedelta(hours=1)),
        )
    with pytest.raises(AnalysisBindingError):
        execute_bound_analysis_capability(
            "ta.gann_fan_geometry",
            request,
            _context(
                request.market_as_of,
                available_at=request.market_as_of - timedelta(seconds=1),
            ),
        )
