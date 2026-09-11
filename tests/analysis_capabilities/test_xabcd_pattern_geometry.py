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
from libs.analysis_capabilities.ta.xabcd_pattern_geometry import (
    XABCDPatternGeometryRequest,
    compute_xabcd_pattern_geometry,
)

_START = datetime(2026, 1, 1, tzinfo=UTC)
_TIMES = (0, 1, 2, 5, 6, 9, 10, 14, 18, 19, 20)


def _bars() -> tuple[ParallelChannelBar, ...]:
    return tuple(ParallelChannelBar(_START + timedelta(hours=hour)) for hour in _TIMES)


def _anchor(kind: str, index: int, price: float) -> SwingAnchor:
    formed_at = _START + timedelta(hours=_TIMES[index])
    return SwingAnchor(kind, formed_at, formed_at + timedelta(minutes=5), price)


def _request() -> XABCDPatternGeometryRequest:
    bars = _bars()
    return XABCDPatternGeometryRequest(
        bars=bars,
        x=_anchor("swing_low", 1, 100.0),
        a=_anchor("swing_high", 2, 160.0),
        b=_anchor("swing_low", 4, 130.0),
        c=_anchor("swing_high", 6, 150.0),
        d=_anchor("swing_low", 8, 110.0),
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
            source_revision="xabcd-test",
            source_slice_sha256="b" * 64,
            source_available_at=cutoff,
            volume_unit=None,
        ),
        market_as_of=cutoff,
        request_available_at=cutoff + timedelta(minutes=1),
        evaluation_at=cutoff + timedelta(minutes=2),
    )


def test_xabcd_exposes_explicit_magnitudes_spans_and_ratios() -> None:
    snapshot = compute_xabcd_pattern_geometry(_request())

    assert snapshot.sequence_kind == "low_high_low_high_low"
    assert (
        snapshot.x_bar_index,
        snapshot.a_bar_index,
        snapshot.b_bar_index,
        snapshot.c_bar_index,
        snapshot.d_bar_index,
    ) == (1, 2, 4, 6, 8)
    assert (
        snapshot.xa_price_magnitude,
        snapshot.ab_price_magnitude,
        snapshot.bc_price_magnitude,
        snapshot.cd_price_magnitude,
        snapshot.ad_price_magnitude,
    ) == (60.0, 30.0, 20.0, 40.0, 50.0)
    assert (
        snapshot.xa_bar_span,
        snapshot.ab_bar_span,
        snapshot.bc_bar_span,
        snapshot.cd_bar_span,
    ) == (1, 2, 2, 2)
    assert snapshot.ab_over_xa == 0.5
    assert snapshot.bc_over_ab == 2.0 / 3.0
    assert snapshot.cd_over_bc == 2.0
    assert snapshot.ad_over_xa == 5.0 / 6.0
    assert snapshot.bcd_time_over_xab_time == 4.0 / 3.0
    assert not hasattr(snapshot, "harmonic_name")


def test_xabcd_downward_orientation_and_dispatch_bound_parity() -> None:
    bars = _bars()
    request = XABCDPatternGeometryRequest(
        bars=bars,
        x=_anchor("swing_high", 1, 200.0),
        a=_anchor("swing_low", 2, 140.0),
        b=_anchor("swing_high", 4, 170.0),
        c=_anchor("swing_low", 6, 150.0),
        d=_anchor("swing_high", 8, 190.0),
        market_as_of=bars[-1].closed_at,
    )
    direct = compute_xabcd_pattern_geometry(request)
    assert direct.sequence_kind == "high_low_high_low_high"
    assert execute_analysis_capability("ta.xabcd_pattern_geometry", request) == direct
    bound = execute_bound_analysis_capability(
        "ta.xabcd_pattern_geometry", request, _context(request.market_as_of)
    )
    assert bound.result == direct
    assert bound.parameter_identity == ()


def test_xabcd_snapshot_rejects_forged_ratio_or_index() -> None:
    snapshot = compute_xabcd_pattern_geometry(_request())
    with pytest.raises(ValueError):
        replace(snapshot, ad_over_xa=0.25)
    with pytest.raises(ValueError):
        replace(snapshot, c_bar_index=7)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda request: replace(request, market_as_of=request.bars[-2].closed_at),
        lambda request: replace(request, d=_anchor("swing_low", 10, 110.0)),
        lambda request: replace(request, c=_anchor("swing_low", 6, 150.0)),
        lambda request: replace(request, b=_anchor("swing_low", 4, 175.0)),
        lambda request: replace(request, a=_anchor("swing_high", 4, 160.0)),
    ],
)
def test_xabcd_common_causal_and_topology_rules_fail_closed(mutator) -> None:
    with pytest.raises((TypeError, ValueError)):
        mutator(_request())
