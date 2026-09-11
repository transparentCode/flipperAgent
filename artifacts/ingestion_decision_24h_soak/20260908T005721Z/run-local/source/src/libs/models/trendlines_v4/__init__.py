"""Dependency-free production namespace for Trendlines V4 geometry."""

from .core import (
    HISTORY_CAPACITY_BARS,
    PIVOT_WINDOW,
    SideGeometry,
    TrendlineBar,
    TrendlineGeometry,
    TrendlineSnapshot,
    analyze,
    analyze_trendlines,
)

__all__ = [
    "HISTORY_CAPACITY_BARS",
    "PIVOT_WINDOW",
    "SideGeometry",
    "TrendlineBar",
    "TrendlineGeometry",
    "TrendlineSnapshot",
    "analyze",
    "analyze_trendlines",
]
