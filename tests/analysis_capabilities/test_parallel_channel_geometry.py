from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from libs.analysis_capabilities.ta.parallel_channel_geometry import (
    ParallelChannelBar,
    ParallelChannelGeometryRequest,
    compute_parallel_channel_geometry,
)
from libs.analysis_capabilities.ta.swing_anchors import SwingAnchor

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _bars() -> tuple[ParallelChannelBar, ...]:
    return tuple(
        ParallelChannelBar(timestamp)
        for timestamp in (
            _START,
            _START + timedelta(hours=1),
            _START + timedelta(hours=5),
            _START + timedelta(hours=6),
            _START + timedelta(hours=24),
        )
    )


def _support_request() -> ParallelChannelGeometryRequest:
    bars = _bars()
    return ParallelChannelGeometryRequest(
        bars=bars,
        start_anchor=SwingAnchor(
            "swing_low", bars[0].closed_at, bars[1].closed_at, 100.0
        ),
        end_anchor=SwingAnchor(
            "swing_low", bars[2].closed_at, bars[3].closed_at, 104.0
        ),
        offset_anchor=SwingAnchor(
            "swing_high", bars[1].closed_at, bars[2].closed_at, 110.0
        ),
        market_as_of=bars[-1].closed_at,
    )


def test_support_uses_bar_ordinals_not_elapsed_time() -> None:
    result = compute_parallel_channel_geometry(_support_request())

    assert result.baseline_kind == "swing_low"
    assert result.slope_per_bar == 2.0
    assert result.offset_price == 8.0
    assert result.baseline_price_at_market_as_of == 108.0
    assert result.parallel_price_at_market_as_of == 116.0


def test_resistance_channel_uses_opposite_anchor_and_negative_offset() -> None:
    bars = _bars()
    request = ParallelChannelGeometryRequest(
        bars=bars,
        start_anchor=SwingAnchor(
            "swing_high", bars[0].closed_at, bars[1].closed_at, 120.0
        ),
        end_anchor=SwingAnchor(
            "swing_high", bars[2].closed_at, bars[3].closed_at, 110.0
        ),
        offset_anchor=SwingAnchor(
            "swing_low", bars[1].closed_at, bars[2].closed_at, 100.0
        ),
        market_as_of=bars[-1].closed_at,
    )

    result = compute_parallel_channel_geometry(request)

    assert result.baseline_kind == "swing_high"
    assert result.slope_per_bar == -5.0
    assert result.offset_price == -15.0
    assert result.baseline_price_at_market_as_of == 100.0
    assert result.parallel_price_at_market_as_of == 85.0


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("start_anchor", "not-an-anchor"),
        ("end_anchor", "not-an-anchor"),
        ("offset_anchor", "not-an-anchor"),
    ),
)
def test_anchor_types_are_checked_before_geometry(
    field_name: str, value: object
) -> None:
    values = {
        "bars": _bars(),
        "start_anchor": SwingAnchor(
            "swing_low", _bars()[0].closed_at, _bars()[1].closed_at, 100.0
        ),
        "end_anchor": SwingAnchor(
            "swing_low", _bars()[2].closed_at, _bars()[3].closed_at, 104.0
        ),
        "offset_anchor": SwingAnchor(
            "swing_high", _bars()[1].closed_at, _bars()[2].closed_at, 110.0
        ),
        "market_as_of": _bars()[-1].closed_at,
    }
    values[field_name] = value

    with pytest.raises(TypeError):
        ParallelChannelGeometryRequest(**values)


def test_invalid_channel_topology_and_nonpositive_offset_fail_closed() -> None:
    bars = _bars()
    start = SwingAnchor("swing_low", bars[0].closed_at, bars[1].closed_at, 100.0)
    end = SwingAnchor("swing_high", bars[2].closed_at, bars[3].closed_at, 104.0)
    offset = SwingAnchor("swing_high", bars[1].closed_at, bars[2].closed_at, 110.0)

    with pytest.raises(ValueError, match="same kind"):
        ParallelChannelGeometryRequest(
            bars=bars,
            start_anchor=start,
            end_anchor=end,
            offset_anchor=offset,
            market_as_of=bars[-1].closed_at,
        )

    invalid_offset = SwingAnchor(
        "swing_high", bars[1].closed_at, bars[2].closed_at, 101.0
    )
    request = ParallelChannelGeometryRequest(
        bars=bars,
        start_anchor=start,
        end_anchor=SwingAnchor(
            "swing_low", bars[2].closed_at, bars[3].closed_at, 104.0
        ),
        offset_anchor=invalid_offset,
        market_as_of=bars[-1].closed_at,
    )
    with pytest.raises(ValueError, match="offset must be positive"):
        compute_parallel_channel_geometry(request)


def test_cutoff_is_the_final_closed_bar() -> None:
    bars = _bars()
    with pytest.raises(ValueError, match="final bar"):
        ParallelChannelGeometryRequest(
            bars=bars,
            start_anchor=SwingAnchor(
                "swing_low", bars[0].closed_at, bars[1].closed_at, 100.0
            ),
            end_anchor=SwingAnchor(
                "swing_low", bars[2].closed_at, bars[3].closed_at, 104.0
            ),
            offset_anchor=SwingAnchor(
                "swing_high", bars[1].closed_at, bars[2].closed_at, 110.0
            ),
            market_as_of=bars[-2].closed_at,
        )


def test_snapshot_rejects_inconsistent_parallel_value() -> None:
    result = compute_parallel_channel_geometry(_support_request())

    with pytest.raises(ValueError, match="inconsistent"):
        replace(
            result,
            parallel_price_at_market_as_of=result.parallel_price_at_market_as_of + 1.0,
        )
