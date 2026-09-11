"""Body-validity and post-anchor crossing facts for V4."""

from __future__ import annotations

from collections.abc import Sequence

from .types import Side, TrendlineBar, _Line


def _segment_is_valid(
    bars: Sequence[TrendlineBar],
    previous_index: int,
    previous_price: float,
    current_index: int,
    current_price: float,
    side: Side,
) -> bool:
    slope = (current_price - previous_price) / (current_index - previous_index)
    intercept = previous_price - slope * previous_index
    for index in range(previous_index + 1, current_index):
        line_value = slope * index + intercept
        body_top = max(bars[index].open, bars[index].close)
        body_bottom = min(bars[index].open, bars[index].close)
        if side == "support" and line_value > body_bottom:
            return False
        if side == "resistance" and line_value < body_top:
            return False
    return True


def _crossing_count(bars: Sequence[TrendlineBar], line: _Line, side: Side) -> int:
    count = 0
    for index in range(line.end_index + 1, len(bars)):
        line_value = line.slope * index + line.intercept
        body_top = max(bars[index].open, bars[index].close)
        body_bottom = min(bars[index].open, bars[index].close)
        if (side == "support" and body_bottom < line_value) or (
            side == "resistance" and body_top > line_value
        ):
            count += 1
    return count


__all__ = ["_crossing_count", "_segment_is_valid"]
