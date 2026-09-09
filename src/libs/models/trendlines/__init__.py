"""Canonical public namespace for the Trendlines V2 geometry contract."""

from libs.models.trendlines_v4.contracts import (
    SideGeometryV2 as SideGeometry,
)
from libs.models.trendlines_v4.contracts import (
    TrendlineSnapshotV2 as TrendlineSnapshot,
)
from libs.models.trendlines_v4.core_v2 import (
    HISTORY_CAPACITY_BARS,
    PIVOT_WINDOW,
    analyze_trendlines_v2,
)
from libs.models.trendlines_v4.engine.types import TrendlineBar, TrendlineGeometry

analyze_trendlines = analyze_trendlines_v2
analyze = analyze_trendlines_v2

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
