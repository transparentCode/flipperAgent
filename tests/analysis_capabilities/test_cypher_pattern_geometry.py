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
from libs.analysis_capabilities.ta.cypher_pattern_geometry import (
    CypherPatternGeometryRequest,
    compute_cypher_pattern_geometry,
)
from libs.analysis_capabilities.ta.parallel_channel_geometry import ParallelChannelBar
from libs.analysis_capabilities.ta.swing_anchors import SwingAnchor

_START = datetime(2026, 1, 1, tzinfo=UTC)
_OFFSETS = (0, 1, 3, 7, 9, 12)


def _bars() -> tuple[ParallelChannelBar, ...]:
    return tuple(
        ParallelChannelBar(_START + timedelta(hours=offset)) for offset in _OFFSETS
    )


def _anchor(kind: str, offset: int, price: float) -> SwingAnchor:
    formed_at = _START + timedelta(hours=offset)
    return SwingAnchor(kind, formed_at, formed_at + timedelta(minutes=30), price)


def _request() -> CypherPatternGeometryRequest:
    bars = _bars()
    return CypherPatternGeometryRequest(
        bars=bars,
        x=_anchor("swing_low", 0, 100.0),
        a=_anchor("swing_high", 1, 160.0),
        b=_anchor("swing_low", 3, 130.0),
        c=_anchor("swing_high", 7, 190.0),
        d=_anchor("swing_low", 9, 145.0),
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
            source_revision="r4d-cypher",
            source_slice_sha256="c" * 64,
            source_available_at=market_as_of,
            volume_unit=None,
        ),
        market_as_of=market_as_of,
        request_available_at=market_as_of + timedelta(minutes=1),
        evaluation_at=market_as_of + timedelta(minutes=2),
    )


def test_cypher_low_high_geometry_uses_ordinal_spans_and_factual_ratios() -> None:
    snapshot = compute_cypher_pattern_geometry(_request())

    assert snapshot.sequence_kind == "low_high_low_high_low"
    assert snapshot.xa_price_magnitude == 60.0
    assert snapshot.ab_price_magnitude == 30.0
    assert snapshot.bc_price_magnitude == 60.0
    assert snapshot.cd_price_magnitude == 45.0
    assert snapshot.xc_price_magnitude == 90.0
    assert (
        snapshot.xa_bar_span,
        snapshot.ab_bar_span,
        snapshot.bc_bar_span,
        snapshot.cd_bar_span,
    ) == (1, 1, 1, 1)
    assert snapshot.ab_over_xa == 0.5
    assert snapshot.xc_over_xa == 1.5
    assert snapshot.cd_over_xc == 0.5


def test_cypher_inverse_and_direct_bound_parity() -> None:
    bars = _bars()
    request = CypherPatternGeometryRequest(
        bars=bars,
        x=_anchor("swing_high", 0, 200.0),
        a=_anchor("swing_low", 1, 100.0),
        b=_anchor("swing_high", 3, 150.0),
        c=_anchor("swing_low", 7, 80.0),
        d=_anchor("swing_high", 9, 140.0),
        market_as_of=bars[-1].closed_at,
    )
    direct = compute_cypher_pattern_geometry(request)
    assert direct.sequence_kind == "high_low_high_low_high"
    assert execute_analysis_capability("ta.cypher_pattern_geometry", request) == direct
    bound = execute_bound_analysis_capability(
        "ta.cypher_pattern_geometry", request, _context(request.market_as_of)
    )
    assert bound.result == direct
    assert bound.parameter_identity == ()


def test_cypher_snapshot_rejects_forged_derived_values_and_has_no_classifier_fields() -> (
    None
):
    snapshot = compute_cypher_pattern_geometry(_request())
    with pytest.raises(ValueError):
        replace(snapshot, xc_over_xa=999.0)
    with pytest.raises(ValueError):
        replace(snapshot, cd_bar_span=999)
    for field_name in (
        "is_valid_cypher",
        "ratio_tolerance",
        "potential_reversal_zone",
        "entry",
        "target",
        "directional_recommendation",
    ):
        assert not hasattr(snapshot, field_name)


def test_cypher_rejects_undefined_xc_ratio() -> None:
    request = replace(
        _request(),
        x=_anchor("swing_low", 0, 150.0),
        c=_anchor("swing_high", 7, 150.0),
    )
    with pytest.raises(ValueError, match="X and C prices must differ"):
        compute_cypher_pattern_geometry(request)

    snapshot = compute_cypher_pattern_geometry(_request())
    with pytest.raises(ValueError, match="X and C prices must differ"):
        replace(
            snapshot,
            x=_anchor("swing_low", 0, 150.0),
            c=_anchor("swing_high", 7, 150.0),
        )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda request: replace(request, market_as_of=request.bars[-2].closed_at),
        lambda request: replace(request, b=_anchor("swing_high", 3, 130.0)),
        lambda request: replace(request, c=_anchor("swing_high", 7, 120.0)),
        lambda request: replace(
            request,
            d=SwingAnchor(
                "swing_low",
                _START + timedelta(hours=9),
                _START + timedelta(hours=13),
                145.0,
            ),
        ),
    ],
)
def test_cypher_common_causal_and_topology_rules_fail_closed(mutator) -> None:
    with pytest.raises((TypeError, ValueError)):
        mutator(_request())
