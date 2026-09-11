"""V2 compatibility facade for the shared V4 engine."""

from __future__ import annotations

from collections.abc import Sequence

from .contracts import (
    GEOMETRY_SCHEMA_VERSION_V2 as GEOMETRY_SCHEMA_VERSION,
)
from .contracts import (
    SideGeometryV2,
    TrendlineSnapshotV2,
    to_v2_snapshot,
)
from .engine import analyzer, solver
from .engine.types import HISTORY_CAPACITY_BARS, PIVOT_WINDOW, TrendlineBar


def analyze_trendlines_v2(
    history: Sequence[TrendlineBar],
) -> TrendlineSnapshotV2:
    """Analyze fixed 3/300 history and expose the exact distinct secondary role."""

    return to_v2_snapshot(analyzer.analyze_geometry(history))


# Private aliases preserve the old diagnostic surface without another solver.
_geometry_key = solver._geometry_key
_solve_side_v2 = solver._solve_side
_prepare = analyzer._prepare
_build_line = solver._build_line
_geometry = solver._geometry
_pivots = solver.pivots._pivots
_reconstruct_path = solver._reconstruct_path
_segment_is_valid = solver.validity._segment_is_valid

analyze = analyze_trendlines_v2

__all__ = [
    "GEOMETRY_SCHEMA_VERSION",
    "HISTORY_CAPACITY_BARS",
    "PIVOT_WINDOW",
    "SideGeometryV2",
    "TrendlineSnapshotV2",
    "analyze",
    "analyze_trendlines_v2",
]
