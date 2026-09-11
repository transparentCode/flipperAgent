from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from libs.analysis_capabilities.execution import execute_analysis_capability
from libs.analysis_capabilities.invocation import (
    AnalysisInvocationContext,
    AnalysisSeriesIdentity,
    AnalysisSourceAttestation,
    execute_bound_analysis_capability,
)
from libs.analysis_capabilities.ta.parallel_channel_geometry import ParallelChannelBar
from libs.analysis_capabilities.ta.swing_anchors import SwingAnchor
from libs.analysis_capabilities.ta.triangle_pattern_geometry import (
    TrianglePatternGeometryRequest,
    compute_triangle_pattern_geometry,
)

_START = datetime(2026, 1, 1, tzinfo=UTC)
_TIMES = (0, 1, 2, 5, 6, 9, 10, 14, 18, 19, 20)


def _bars() -> tuple[ParallelChannelBar, ...]:
    return tuple(ParallelChannelBar(_START + timedelta(hours=hour)) for hour in _TIMES)


def _anchor(kind: str, index: int, price: float) -> SwingAnchor:
    formed_at = _START + timedelta(hours=_TIMES[index])
    return SwingAnchor(kind, formed_at, formed_at + timedelta(minutes=5), price)


def _high_first_request() -> TrianglePatternGeometryRequest:
    bars = _bars()
    return TrianglePatternGeometryRequest(
        bars=bars,
        a=_anchor("swing_high", 1, 130.0),
        b=_anchor("swing_low", 2, 100.0),
        c=_anchor("swing_high", 5, 120.0),
        d=_anchor("swing_low", 7, 110.0),
        market_as_of=bars[-1].closed_at,
    )


def _low_first_request() -> TrianglePatternGeometryRequest:
    bars = _bars()
    return TrianglePatternGeometryRequest(
        bars=bars,
        a=_anchor("swing_low", 1, 100.0),
        b=_anchor("swing_high", 2, 130.0),
        c=_anchor("swing_low", 5, 110.0),
        d=_anchor("swing_high", 7, 120.0),
        market_as_of=bars[-1].closed_at,
    )


def _context(cutoff: datetime) -> AnalysisInvocationContext:
    return AnalysisInvocationContext(
        source=AnalysisSourceAttestation(
            series=AnalysisSeriesIdentity(
                asset="BTCUSDT",
                venue="fixture",
                instrument_id="fixture:BTCUSDT",
                timeframe="1h",
            ),
            source_type="fixture",
            source_provider=None,
            source_timeframe=None,
            source_revision="triangle-test",
            source_slice_sha256="d" * 64,
            source_available_at=cutoff,
            volume_unit=None,
        ),
        market_as_of=cutoff,
        request_available_at=cutoff + timedelta(minutes=1),
        evaluation_at=cutoff + timedelta(minutes=2),
    )


def test_triangle_high_first_assigns_upper_and_lower_and_solves_future_apex() -> None:
    snapshot = compute_triangle_pattern_geometry(_high_first_request())

    assert snapshot.upper_first_anchor.kind == "swing_high"
    assert snapshot.lower_first_anchor.kind == "swing_low"
    assert snapshot.upper_slope_per_bar == -2.5
    assert snapshot.lower_slope_per_bar == 2.0
    assert snapshot.upper_price_at_d == 115.0
    assert snapshot.lower_price_at_d == 110.0
    assert snapshot.boundary_gap_at_d == 5.0
    assert snapshot.apex_relation == "future"
    assert snapshot.apex_bar_position == pytest.approx(8.11111111111111)
    assert snapshot.apex_price == pytest.approx(112.22222222222223)
    assert not hasattr(snapshot, "triangle_subtype")


def test_triangle_low_first_has_same_ordinal_geometry_and_dispatch_bound_parity() -> (
    None
):
    request = _low_first_request()
    direct = compute_triangle_pattern_geometry(request)
    assert direct.upper_first_anchor == request.b
    assert direct.lower_first_anchor == request.a
    assert direct.upper_slope_per_bar == -2.0
    assert direct.lower_slope_per_bar == 2.5
    assert direct.boundary_gap_at_d == 5.0
    assert (
        execute_analysis_capability("ta.triangle_pattern_geometry", request) == direct
    )
    bound = execute_bound_analysis_capability(
        "ta.triangle_pattern_geometry", request, _context(request.market_as_of)
    )
    assert bound.result == direct
    assert bound.parameter_identity == ()


def test_triangle_parallel_boundaries_have_no_apex() -> None:
    bars = _bars()
    request = TrianglePatternGeometryRequest(
        bars=bars,
        a=_anchor("swing_high", 1, 130.0),
        b=_anchor("swing_low", 2, 100.0),
        c=_anchor("swing_high", 5, 138.0),
        d=_anchor("swing_low", 7, 110.0),
        market_as_of=bars[-1].closed_at,
    )
    snapshot = compute_triangle_pattern_geometry(request)
    assert snapshot.upper_slope_per_bar == snapshot.lower_slope_per_bar == 2.0
    assert snapshot.apex_bar_position is None
    assert snapshot.apex_price is None
    assert snapshot.apex_relation == "parallel"


def test_triangle_past_apex_is_retained_as_descriptive_geometry() -> None:
    bars = _bars()
    request = TrianglePatternGeometryRequest(
        bars=bars,
        a=_anchor("swing_high", 1, 130.0),
        b=_anchor("swing_low", 2, 100.0),
        c=_anchor("swing_high", 5, 150.0),
        d=_anchor("swing_low", 7, 100.0),
        market_as_of=bars[-1].closed_at,
    )
    snapshot = compute_triangle_pattern_geometry(request)
    assert snapshot.apex_relation == "at_or_before_latest"
    assert snapshot.apex_bar_position < snapshot.d_bar_index


def test_triangle_snapshot_rejects_forged_boundary_or_apex_facts() -> None:
    snapshot = compute_triangle_pattern_geometry(_high_first_request())
    with pytest.raises(ValueError):
        replace(snapshot, boundary_gap_at_d=99.0)
    with pytest.raises(ValueError):
        replace(snapshot, apex_price=99.0)


def test_triangle_crossed_by_final_anchor_fails_closed() -> None:
    bars = _bars()
    with pytest.raises(ValueError, match="ordered at d"):
        compute_triangle_pattern_geometry(
            TrianglePatternGeometryRequest(
                bars=bars,
                a=_anchor("swing_high", 1, 130.0),
                b=_anchor("swing_low", 2, 100.0),
                c=_anchor("swing_high", 5, 105.0),
                d=_anchor("swing_low", 7, 100.0),
                market_as_of=bars[-1].closed_at,
            )
        )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda request: replace(request, market_as_of=request.bars[-2].closed_at),
        lambda request: replace(request, c=_anchor("swing_low", 5, 120.0)),
        lambda request: replace(request, d=_anchor("swing_low", 4, 110.0)),
        lambda request: replace(request, a=_anchor("swing_high", 10, 130.0)),
    ],
)
def test_triangle_common_causal_and_topology_rules_fail_closed(mutator) -> None:
    with pytest.raises((TypeError, ValueError)):
        mutator(_high_first_request())
