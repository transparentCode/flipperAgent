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
from libs.analysis_capabilities.ta.head_shoulders_pattern_geometry import (
    HeadShouldersPatternGeometryRequest,
    compute_head_shoulders_pattern_geometry,
)
from libs.analysis_capabilities.ta.parallel_channel_geometry import ParallelChannelBar
from libs.analysis_capabilities.ta.swing_anchors import SwingAnchor

_START = datetime(2026, 1, 1, tzinfo=UTC)
_TIMES = (0, 1, 2, 5, 6, 9, 10, 14, 18, 19, 20)


def _bars() -> tuple[ParallelChannelBar, ...]:
    return tuple(ParallelChannelBar(_START + timedelta(hours=hour)) for hour in _TIMES)


def _anchor(kind: str, index: int, price: float) -> SwingAnchor:
    formed_at = _START + timedelta(hours=_TIMES[index])
    return SwingAnchor(kind, formed_at, formed_at + timedelta(minutes=5), price)


def _top_request() -> HeadShouldersPatternGeometryRequest:
    bars = _bars()
    return HeadShouldersPatternGeometryRequest(
        bars=bars,
        left_shoulder=_anchor("swing_high", 1, 120.0),
        neck_left=_anchor("swing_low", 2, 100.0),
        head=_anchor("swing_high", 4, 145.0),
        neck_right=_anchor("swing_low", 6, 105.0),
        right_shoulder=_anchor("swing_high", 8, 125.0),
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
            source_revision="head-shoulders-test",
            source_slice_sha256="c" * 64,
            source_available_at=cutoff,
            volume_unit=None,
        ),
        market_as_of=cutoff,
        request_available_at=cutoff + timedelta(minutes=1),
        evaluation_at=cutoff + timedelta(minutes=2),
    )


def test_top_head_shoulders_uses_sloped_bar_ordinal_neckline() -> None:
    snapshot = compute_head_shoulders_pattern_geometry(_top_request())

    assert snapshot.orientation == "top"
    assert snapshot.neckline_slope_per_bar == 1.25
    assert snapshot.neckline_at_left_shoulder == 98.75
    assert snapshot.neckline_at_head == 102.5
    assert snapshot.neckline_at_right_shoulder == 107.5
    assert snapshot.left_shoulder_prominence == 21.25
    assert snapshot.head_prominence == 42.5
    assert snapshot.right_shoulder_prominence == 17.5
    assert snapshot.shoulder_price_difference == 5.0
    assert not hasattr(snapshot, "breakout")
    assert not hasattr(snapshot, "target_price")


def test_inverse_head_shoulders_and_bound_dispatch_parity() -> None:
    bars = _bars()
    request = HeadShouldersPatternGeometryRequest(
        bars=bars,
        left_shoulder=_anchor("swing_low", 1, 100.0),
        neck_left=_anchor("swing_high", 2, 120.0),
        head=_anchor("swing_low", 4, 80.0),
        neck_right=_anchor("swing_high", 6, 115.0),
        right_shoulder=_anchor("swing_low", 8, 105.0),
        market_as_of=bars[-1].closed_at,
    )
    direct = compute_head_shoulders_pattern_geometry(request)
    assert direct.orientation == "bottom"
    assert (
        execute_analysis_capability("ta.head_shoulders_pattern_geometry", request)
        == direct
    )
    bound = execute_bound_analysis_capability(
        "ta.head_shoulders_pattern_geometry", request, _context(request.market_as_of)
    )
    assert bound.result == direct
    assert bound.parameter_identity == ()


def test_head_extremity_is_required_in_request_and_snapshot() -> None:
    with pytest.raises(ValueError, match="head must exceed"):
        replace(
            _top_request(),
            head=_anchor("swing_high", 4, 118.0),
        )
    snapshot = compute_head_shoulders_pattern_geometry(_top_request())
    with pytest.raises(ValueError, match="head must exceed"):
        replace(snapshot, head=_anchor("swing_high", 4, 118.0))


def test_shoulders_need_not_be_equal_but_derived_values_cannot_be_forged() -> None:
    request = replace(
        _top_request(),
        right_shoulder=_anchor("swing_high", 8, 127.0),
    )
    snapshot = compute_head_shoulders_pattern_geometry(request)
    assert snapshot.shoulder_price_difference == 7.0
    with pytest.raises(ValueError):
        replace(snapshot, neckline_at_head=999.0)
    with pytest.raises(ValueError):
        replace(snapshot, head_prominence=999.0)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda request: replace(request, market_as_of=request.bars[-2].closed_at),
        lambda request: replace(request, neck_right=_anchor("swing_high", 6, 105.0)),
        lambda request: replace(request, right_shoulder=_anchor("swing_low", 8, 125.0)),
        lambda request: replace(request, head=_anchor("swing_high", 9, 145.0)),
    ],
)
def test_head_shoulders_topology_and_cutoff_rules_fail_closed(mutator) -> None:
    with pytest.raises((TypeError, ValueError)):
        mutator(_top_request())
