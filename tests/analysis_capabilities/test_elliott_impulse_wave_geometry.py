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
from libs.analysis_capabilities.ta.elliott_impulse_wave_geometry import (
    ElliottImpulseWaveGeometryRequest,
    compute_elliott_impulse_wave_geometry,
)
from libs.analysis_capabilities.ta.parallel_channel_geometry import ParallelChannelBar
from libs.analysis_capabilities.ta.swing_anchors import SwingAnchor

_START = datetime(2026, 1, 1, tzinfo=UTC)
_OFFSETS = (0, 1, 4, 5, 9, 15, 20)


def _bars() -> tuple[ParallelChannelBar, ...]:
    return tuple(
        ParallelChannelBar(_START + timedelta(hours=offset)) for offset in _OFFSETS
    )


def _anchor(kind: str, offset: int, price: float) -> SwingAnchor:
    formed_at = _START + timedelta(hours=offset)
    return SwingAnchor(kind, formed_at, formed_at + timedelta(minutes=30), price)


def _up_request() -> ElliottImpulseWaveGeometryRequest:
    bars = _bars()
    return ElliottImpulseWaveGeometryRequest(
        bars=bars,
        start=_anchor("swing_low", 0, 100.0),
        wave1=_anchor("swing_high", 1, 150.0),
        wave2=_anchor("swing_low", 4, 149.0),
        wave3=_anchor("swing_high", 5, 150.5),
        wave4=_anchor("swing_low", 9, 150.25),
        wave5=_anchor("swing_high", 15, 152.25),
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
            source_revision="r4d-elliott-impulse",
            source_slice_sha256="e" * 64,
            source_available_at=market_as_of,
            volume_unit=None,
        ),
        market_as_of=market_as_of,
        request_available_at=market_as_of + timedelta(minutes=1),
        evaluation_at=market_as_of + timedelta(minutes=2),
    )


def test_elliott_impulse_up_uses_explicit_factual_wave_geometry() -> None:
    snapshot = compute_elliott_impulse_wave_geometry(_up_request())

    assert snapshot.orientation == "up"
    assert (
        snapshot.wave1_price_magnitude,
        snapshot.wave2_price_magnitude,
        snapshot.wave3_price_magnitude,
        snapshot.wave4_price_magnitude,
        snapshot.wave5_price_magnitude,
    ) == (50.0, 1.0, 1.5, 0.25, 2.0)
    assert (
        snapshot.wave1_bar_span,
        snapshot.wave2_bar_span,
        snapshot.wave3_bar_span,
        snapshot.wave4_bar_span,
        snapshot.wave5_bar_span,
    ) == (1, 1, 1, 1, 1)
    assert snapshot.wave2_over_wave1 == 1.0 / 50.0
    assert snapshot.wave3_over_wave1 == 1.5 / 50.0
    assert snapshot.wave4_over_wave3 == 0.25 / 1.5
    assert snapshot.wave5_over_wave1 == 2.0 / 50.0
    assert snapshot.wave3_time_over_wave1 == 1.0
    assert snapshot.wave5_time_over_wave1 == 1.0
    assert not hasattr(snapshot, "is_valid_impulse")


def test_elliott_impulse_down_and_direct_bound_dispatch_parity() -> None:
    bars = _bars()
    request = ElliottImpulseWaveGeometryRequest(
        bars=bars,
        start=_anchor("swing_high", 0, 200.0),
        wave1=_anchor("swing_low", 1, 150.0),
        wave2=_anchor("swing_high", 4, 151.0),
        wave3=_anchor("swing_low", 5, 149.5),
        wave4=_anchor("swing_high", 9, 149.75),
        wave5=_anchor("swing_low", 15, 147.75),
        market_as_of=bars[-1].closed_at,
    )
    direct = compute_elliott_impulse_wave_geometry(request)
    assert direct.orientation == "down"
    assert (
        execute_analysis_capability("ta.elliott_impulse_wave_geometry", request)
        == direct
    )
    bound = execute_bound_analysis_capability(
        "ta.elliott_impulse_wave_geometry", request, _context(request.market_as_of)
    )
    assert bound.result == direct
    assert bound.parameter_identity == ()


def test_textbook_invalid_but_topologically_valid_impulse_is_measured() -> None:
    snapshot = compute_elliott_impulse_wave_geometry(_up_request())

    assert snapshot.wave3_price_magnitude < snapshot.wave1_price_magnitude
    assert not hasattr(snapshot, "validity")
    assert not hasattr(snapshot, "projection")
    assert not hasattr(snapshot, "next_wave")
    assert not hasattr(snapshot, "degree")
    assert not hasattr(snapshot, "nesting")


def test_elliott_impulse_snapshot_rejects_forged_values_and_common_rules() -> None:
    snapshot = compute_elliott_impulse_wave_geometry(_up_request())
    with pytest.raises(ValueError):
        replace(snapshot, wave3_over_wave1=999.0)
    with pytest.raises(ValueError):
        replace(snapshot, wave4_bar_span=999)
    with pytest.raises((TypeError, ValueError)):
        replace(_up_request(), wave4=_anchor("swing_high", 9, 150.25))
    with pytest.raises((TypeError, ValueError)):
        replace(_up_request(), market_as_of=_bars()[-2].closed_at)
