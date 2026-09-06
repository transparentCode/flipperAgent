"""V1 compatibility facade for the shared dependency-free V4 engine."""

from __future__ import annotations

from collections.abc import Sequence

from .contracts import SideGeometry, TrendlineSnapshot, to_v1_snapshot
from .engine import analyzer, pivots, solver, validity
from .engine import types as _types
from .engine.types import (
    HISTORY_CAPACITY_BARS,
    PIVOT_WINDOW,
    TrendlineBar,
    TrendlineGeometry,
)

Side = _types.Side
PathPoint = _types.PathPoint
_number = _types._number
from .engine.types import (
    _Line as _EngineLine,
)
from .engine.types import (
    _SideState as _EngineSideState,
)
from .engine.types import (
    _utc as _engine_utc,
)


def analyze_trendlines(history: Sequence[TrendlineBar]) -> TrendlineSnapshot:
    """Analyze one ordered closed-bar history at its latest cutoff."""

    return to_v1_snapshot(analyzer.analyze_geometry(history))


# Historical private aliases remain available to research/test callers. The
# implementation is owned by the engine modules, not by this facade.
_pivots = pivots._pivots
_segment_is_valid = validity._segment_is_valid
_crossing_count = validity._crossing_count
_build_line = solver._build_line
_geometry = solver._geometry
_reconstruct_path = solver._reconstruct_path
_solve_side = solver._solve_side
_prepare = analyzer._prepare
_Line = _EngineLine
_SideState = _EngineSideState
_utc = _engine_utc

analyze = analyze_trendlines

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
