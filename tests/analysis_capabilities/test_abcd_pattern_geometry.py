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
from libs.analysis_capabilities.ta.abcd_pattern_geometry import (
    ABCDPatternGeometryRequest,
    compute_abcd_pattern_geometry,
)
from libs.analysis_capabilities.ta.parallel_channel_geometry import ParallelChannelBar
from libs.analysis_capabilities.ta.swing_anchors import SwingAnchor

_START = datetime(2026, 1, 1, tzinfo=UTC)
_TIMES = (0, 1, 4, 5, 9, 10, 12, 15, 20, 21)


def _bars() -> tuple[ParallelChannelBar, ...]:
    return tuple(ParallelChannelBar(_START + timedelta(hours=hour)) for hour in _TIMES)


def _anchor(kind: str, index: int, price: float) -> SwingAnchor:
    formed_at = _START + timedelta(hours=_TIMES[index])
    return SwingAnchor(kind, formed_at, formed_at + timedelta(minutes=5), price)


def _request() -> ABCDPatternGeometryRequest:
    bars = _bars()
    return ABCDPatternGeometryRequest(
        bars=bars,
        a=_anchor("swing_low", 1, 100.0),
        b=_anchor("swing_high", 3, 140.0),
        c=_anchor("swing_low", 5, 120.0),
        d=_anchor("swing_high", 8, 150.0),
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
            source_revision="abcd-test",
            source_slice_sha256="a" * 64,
            source_available_at=cutoff,
            volume_unit=None,
        ),
        market_as_of=cutoff,
        request_available_at=cutoff + timedelta(minutes=1),
        evaluation_at=cutoff + timedelta(minutes=2),
    )


def test_abcd_uses_explicit_ordinal_geometry_and_factual_ratios() -> None:
    snapshot = compute_abcd_pattern_geometry(_request())

    assert snapshot.sequence_kind == "low_high_low_high"
    assert (
        snapshot.a_bar_index,
        snapshot.b_bar_index,
        snapshot.c_bar_index,
        snapshot.d_bar_index,
    ) == (1, 3, 5, 8)
    assert (
        snapshot.ab_price_magnitude,
        snapshot.bc_price_magnitude,
        snapshot.cd_price_magnitude,
    ) == (40.0, 20.0, 30.0)
    assert (snapshot.ab_bar_span, snapshot.bc_bar_span, snapshot.cd_bar_span) == (
        2,
        2,
        3,
    )
    assert snapshot.bc_over_ab == 0.5
    assert snapshot.cd_over_bc == 1.5
    assert snapshot.cd_over_ab == 0.75
    assert snapshot.cd_time_over_ab == 1.5
    assert not hasattr(snapshot, "pattern_name")


def test_abcd_direct_dispatcher_and_bound_executor_match() -> None:
    request = _request()
    direct = compute_abcd_pattern_geometry(request)
    assert execute_analysis_capability("ta.abcd_pattern_geometry", request) == direct
    bound = execute_bound_analysis_capability(
        "ta.abcd_pattern_geometry", request, _context(request.market_as_of)
    )
    assert bound.result == direct
    assert bound.parameter_identity == ()


def test_abcd_snapshot_rejects_forged_ratio() -> None:
    snapshot = compute_abcd_pattern_geometry(_request())
    with pytest.raises(ValueError):
        replace(snapshot, bc_over_ab=0.75)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda request: replace(request, market_as_of=request.bars[-2].closed_at),
        lambda request: replace(
            request,
            a=_anchor("swing_low", 9, 100.0),
        ),
        lambda request: replace(
            request,
            b=_anchor("swing_low", 3, 140.0),
        ),
        lambda request: replace(
            request,
            b=_anchor("swing_high", 3, 90.0),
        ),
        lambda request: replace(
            request,
            c=_anchor("swing_low", 3, 120.0),
        ),
    ],
)
def test_abcd_common_causal_and_topology_rules_fail_closed(mutator) -> None:
    with pytest.raises((TypeError, ValueError)):
        mutator(_request())
