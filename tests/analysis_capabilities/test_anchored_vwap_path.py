from datetime import UTC, datetime, timedelta

import pytest

from libs.analysis_capabilities.ta.anchored_vwap_path import (
    AnchoredVWAPPathRequest,
    compute_anchored_vwap_path,
)
from libs.analysis_capabilities.ta.vwap_geometry import (
    VWAPBar,
    VWAPGeometryRequest,
    compute_vwap_geometry,
)

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _request() -> AnchoredVWAPPathRequest:
    bars = (
        VWAPBar(_START, 10.0, 8.0, 9.0, 0.0),
        VWAPBar(_START + timedelta(hours=1), 12.0, 10.0, 11.0, 2.0),
        VWAPBar(_START + timedelta(hours=2), 15.0, 12.0, 14.0, 0.0),
        VWAPBar(_START + timedelta(hours=3), 16.0, 14.0, 15.0, 3.0),
    )
    return AnchoredVWAPPathRequest(bars=bars, market_as_of=bars[-1].closed_at)


def test_path_skips_leading_zero_volume_and_carries_later_zero_volume() -> None:
    result = compute_anchored_vwap_path(_request())

    assert result.first_bar_closed_at == _START
    assert result.input_bar_count == 4
    assert tuple(point.closed_at for point in result.points) == (
        _START + timedelta(hours=1),
        _START + timedelta(hours=2),
        _START + timedelta(hours=3),
    )
    assert result.points[1].cumulative_volume == result.points[0].cumulative_volume
    assert result.points[1].vwap_price == result.points[0].vwap_price


def test_final_point_matches_existing_vwap_kernel_exactly() -> None:
    request = _request()
    path = compute_anchored_vwap_path(request)
    existing = compute_vwap_geometry(
        VWAPGeometryRequest(bars=request.bars, market_as_of=request.market_as_of)
    )
    final = path.points[-1]

    assert final.closed_at == existing.market_as_of
    assert final.cumulative_volume == existing.total_volume
    assert final.vwap_price == existing.vwap_price


def test_all_zero_volume_range_is_rejected() -> None:
    bars = (
        VWAPBar(_START, 10.0, 8.0, 9.0, 0.0),
        VWAPBar(_START + timedelta(hours=1), 11.0, 9.0, 10.0, 0.0),
    )
    with pytest.raises(ValueError, match="positive volume"):
        AnchoredVWAPPathRequest(bars=bars, market_as_of=bars[-1].closed_at)


def test_request_requires_the_final_bar_as_cutoff() -> None:
    request = _request()
    with pytest.raises(ValueError, match="final bar"):
        AnchoredVWAPPathRequest(bars=request.bars, market_as_of=_START)


def test_overflowing_weighted_accumulation_fails_closed() -> None:
    bars = (
        VWAPBar(_START, 1e308, 1e308, 1e308, 1e308),
        VWAPBar(_START + timedelta(hours=1), 1e308, 1e308, 1e308, 1.0),
    )
    request = AnchoredVWAPPathRequest(bars=bars, market_as_of=bars[-1].closed_at)
    with pytest.raises(ValueError, match="finite"):
        compute_anchored_vwap_path(request)
