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
from libs.analysis_capabilities.ta.elliott_correction_wave_geometry import (
    ElliottCorrectionWaveGeometryRequest,
    compute_elliott_correction_wave_geometry,
)
from libs.analysis_capabilities.ta.parallel_channel_geometry import ParallelChannelBar
from libs.analysis_capabilities.ta.swing_anchors import SwingAnchor

_START = datetime(2026, 1, 1, tzinfo=UTC)
_OFFSETS = (0, 2, 3, 8, 12)


def _bars() -> tuple[ParallelChannelBar, ...]:
    return tuple(
        ParallelChannelBar(_START + timedelta(hours=offset)) for offset in _OFFSETS
    )


def _anchor(kind: str, offset: int, price: float) -> SwingAnchor:
    formed_at = _START + timedelta(hours=offset)
    return SwingAnchor(kind, formed_at, formed_at + timedelta(minutes=30), price)


def _up_request() -> ElliottCorrectionWaveGeometryRequest:
    bars = _bars()
    return ElliottCorrectionWaveGeometryRequest(
        bars=bars,
        start=_anchor("swing_low", 0, 100.0),
        wave_a=_anchor("swing_high", 2, 140.0),
        wave_b=_anchor("swing_low", 3, 130.0),
        wave_c=_anchor("swing_high", 8, 135.0),
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
            source_revision="r4d-elliott-correction",
            source_slice_sha256="f" * 64,
            source_available_at=market_as_of,
            volume_unit=None,
        ),
        market_as_of=market_as_of,
        request_available_at=market_as_of + timedelta(minutes=1),
        evaluation_at=market_as_of + timedelta(minutes=2),
    )


def test_elliott_correction_up_exposes_ordinal_geometry_without_subtype_rules() -> None:
    snapshot = compute_elliott_correction_wave_geometry(_up_request())

    assert snapshot.orientation == "first_leg_up"
    assert (
        snapshot.a_price_magnitude,
        snapshot.b_price_magnitude,
        snapshot.c_price_magnitude,
    ) == (40.0, 10.0, 5.0)
    assert (snapshot.a_bar_span, snapshot.b_bar_span, snapshot.c_bar_span) == (1, 1, 1)
    assert snapshot.b_over_a == 0.25
    assert snapshot.c_over_a == 0.125
    assert snapshot.c_over_b == 0.5
    assert snapshot.b_time_over_a == 1.0
    assert snapshot.c_time_over_a == 1.0
    # C does not pass A, so a textbook zigzag rule would reject this; R4D measures it.
    assert snapshot.wave_c.price < snapshot.wave_a.price
    assert not hasattr(snapshot, "correction_type")
    assert not hasattr(snapshot, "is_valid_correction")


def test_elliott_correction_down_and_direct_bound_dispatch_parity() -> None:
    bars = _bars()
    request = ElliottCorrectionWaveGeometryRequest(
        bars=bars,
        start=_anchor("swing_high", 0, 200.0),
        wave_a=_anchor("swing_low", 2, 150.0),
        wave_b=_anchor("swing_high", 3, 170.0),
        wave_c=_anchor("swing_low", 8, 160.0),
        market_as_of=bars[-1].closed_at,
    )
    direct = compute_elliott_correction_wave_geometry(request)
    assert direct.orientation == "first_leg_down"
    assert (
        execute_analysis_capability("ta.elliott_correction_wave_geometry", request)
        == direct
    )
    bound = execute_bound_analysis_capability(
        "ta.elliott_correction_wave_geometry", request, _context(request.market_as_of)
    )
    assert bound.result == direct
    assert bound.parameter_identity == ()


def test_elliott_correction_snapshot_rejects_forged_values_and_common_rules() -> None:
    snapshot = compute_elliott_correction_wave_geometry(_up_request())
    with pytest.raises(ValueError):
        replace(snapshot, c_over_a=999.0)
    with pytest.raises(ValueError):
        replace(snapshot, c_bar_span=999)
    with pytest.raises((TypeError, ValueError)):
        replace(_up_request(), wave_b=_anchor("swing_high", 3, 130.0))
    with pytest.raises((TypeError, ValueError)):
        replace(_up_request(), market_as_of=_bars()[-2].closed_at)
