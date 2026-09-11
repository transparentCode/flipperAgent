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
from libs.analysis_capabilities.ta.three_drives_pattern_geometry import (
    ThreeDrivesPatternGeometryRequest,
    compute_three_drives_pattern_geometry,
)

_START = datetime(2026, 1, 1, tzinfo=UTC)
_OFFSETS = (0, 1, 3, 7, 9, 12, 15)


def _bars() -> tuple[ParallelChannelBar, ...]:
    return tuple(
        ParallelChannelBar(_START + timedelta(hours=offset)) for offset in _OFFSETS
    )


def _anchor(kind: str, offset: int, price: float) -> SwingAnchor:
    formed_at = _START + timedelta(hours=offset)
    return SwingAnchor(kind, formed_at, formed_at + timedelta(minutes=30), price)


def _up_request() -> ThreeDrivesPatternGeometryRequest:
    bars = _bars()
    return ThreeDrivesPatternGeometryRequest(
        bars=bars,
        start=_anchor("swing_low", 0, 100.0),
        drive1=_anchor("swing_high", 1, 160.0),
        retrace_a=_anchor("swing_low", 3, 130.0),
        drive2=_anchor("swing_high", 7, 200.0),
        retrace_c=_anchor("swing_low", 9, 160.0),
        drive3=_anchor("swing_high", 12, 230.0),
        market_as_of=bars[-1].closed_at,
    )


def _context(market_as_of: datetime) -> AnalysisInvocationContext:
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
            source_revision="r4d-three-drives",
            source_slice_sha256="d" * 64,
            source_available_at=market_as_of,
            volume_unit=None,
        ),
        market_as_of=market_as_of,
        request_available_at=market_as_of + timedelta(minutes=1),
        evaluation_at=market_as_of + timedelta(minutes=2),
    )


def test_three_drives_up_exposes_six_anchor_price_and_time_geometry() -> None:
    snapshot = compute_three_drives_pattern_geometry(_up_request())

    assert snapshot.orientation == "drives_up"
    assert (
        snapshot.drive1_mag,
        snapshot.a_retrace_mag,
        snapshot.drive2_mag,
        snapshot.c_retrace_mag,
        snapshot.drive3_mag,
    ) == (60.0, 30.0, 70.0, 40.0, 70.0)
    assert (
        snapshot.drive1_bar_span,
        snapshot.a_retrace_bar_span,
        snapshot.drive2_bar_span,
        snapshot.c_retrace_bar_span,
        snapshot.drive3_bar_span,
    ) == (1, 1, 1, 1, 1)
    assert snapshot.a_retrace_over_drive1 == 0.5
    assert snapshot.drive2_over_a_retrace == 70.0 / 30.0
    assert snapshot.c_retrace_over_drive2 == 40.0 / 70.0
    assert snapshot.drive3_over_c_retrace == 70.0 / 40.0
    assert snapshot.c_retrace_over_a_retrace == 40.0 / 30.0
    assert snapshot.drive3_over_drive2 == 1.0
    assert snapshot.c_retrace_time_over_a_retrace_time == 1.0
    assert snapshot.drive3_time_over_drive2_time == 1.0


def test_three_drives_down_and_direct_bound_dispatch_parity() -> None:
    bars = _bars()
    request = ThreeDrivesPatternGeometryRequest(
        bars=bars,
        start=_anchor("swing_high", 0, 200.0),
        drive1=_anchor("swing_low", 1, 140.0),
        retrace_a=_anchor("swing_high", 3, 170.0),
        drive2=_anchor("swing_low", 7, 100.0),
        retrace_c=_anchor("swing_high", 9, 140.0),
        drive3=_anchor("swing_low", 12, 70.0),
        market_as_of=bars[-1].closed_at,
    )
    direct = compute_three_drives_pattern_geometry(request)
    assert direct.orientation == "drives_down"
    assert (
        execute_analysis_capability("ta.three_drives_pattern_geometry", request)
        == direct
    )
    bound = execute_bound_analysis_capability(
        "ta.three_drives_pattern_geometry", request, _context(request.market_as_of)
    )
    assert bound.result == direct
    assert bound.parameter_identity == ()


def test_three_drives_snapshot_rejects_forgery_and_has_no_predictive_fields() -> None:
    snapshot = compute_three_drives_pattern_geometry(_up_request())
    for field_name, value in (
        ("orientation", "drives_down"),
        ("drive2_mag", 999.0),
        ("drive3_time_over_drive2_time", 999.0),
        ("drive3_bar_span", 999),
    ):
        with pytest.raises((TypeError, ValueError)):
            replace(snapshot, **{field_name: value})
    for field_name in (
        "ratio_target",
        "symmetry_tolerance",
        "reversal",
        "bullish",
        "bearish",
        "target",
        "entry",
        "confidence",
    ):
        assert not hasattr(snapshot, field_name)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda request: replace(request, market_as_of=request.bars[-2].closed_at),
        lambda request: replace(request, drive2=_anchor("swing_high", 7, 125.0)),
        lambda request: replace(request, retrace_a=_anchor("swing_high", 3, 130.0)),
        lambda request: replace(
            request,
            drive3=SwingAnchor(
                "swing_high",
                _START + timedelta(hours=12),
                _START + timedelta(hours=16),
                230.0,
            ),
        ),
    ],
)
def test_three_drives_common_topology_and_causality_rules_fail_closed(mutator) -> None:
    with pytest.raises((TypeError, ValueError)):
        mutator(_up_request())
