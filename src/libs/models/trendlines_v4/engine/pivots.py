"""Pivot extraction for the canonical V4 geometry engine."""

from __future__ import annotations

from collections.abc import Sequence

from .types import PIVOT_WINDOW, PathPoint, Side, TrendlineBar


def _pivots(bars: Sequence[TrendlineBar], side: Side) -> tuple[PathPoint, ...]:
    values = [bar.low if side == "support" else bar.high for bar in bars]
    result = []
    for index in range(PIVOT_WINDOW, len(values) - PIVOT_WINDOW):
        window = values[index - PIVOT_WINDOW : index + PIVOT_WINDOW + 1]
        value = values[index]
        if value == (min(window) if side == "support" else max(window)):
            result.append((index, value))
    return tuple(result)


__all__ = ["_pivots"]
