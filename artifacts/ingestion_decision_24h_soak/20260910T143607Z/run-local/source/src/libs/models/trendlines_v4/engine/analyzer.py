"""Canonical preparation, analysis, and role conversion for V4."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from . import solver
from .types import (
    HISTORY_CAPACITY_BARS,
    Side,
    SideAnalysis,
    TrendlineAnalysis,
    TrendlineBar,
)


def _prepare(history: Sequence[TrendlineBar]) -> tuple[TrendlineBar, ...]:
    try:
        bars = tuple(history)
    except TypeError as exc:
        raise TypeError("history must be an ordered sequence of TrendlineBar") from exc
    if not bars:
        raise ValueError("history must contain at least one closed bar")
    if any(not isinstance(bar, TrendlineBar) for bar in bars):
        raise TypeError("history must contain only TrendlineBar values")
    if any(
        previous.closed_at >= current.closed_at for previous, current in pairwise(bars)
    ):
        raise ValueError("closed_at values must be strictly increasing")
    return bars[-HISTORY_CAPACITY_BARS:]


def _side_analysis(bars: Sequence[TrendlineBar], side: Side) -> SideAnalysis:
    state = solver._solve_side(bars, side)
    structural = solver._geometry(bars, side, state.structural)
    current = solver._geometry(bars, side, state.current_valid)
    secondary = solver._geometry(bars, side, state.secondary)
    return SideAnalysis(
        structural=structural,
        current_valid=current,
        secondary=secondary,
        same_geometry=structural is not None and structural == current,
    )


def analyze_geometry(history: Sequence[TrendlineBar]) -> TrendlineAnalysis:
    bars = _prepare(history)
    return TrendlineAnalysis(
        history_bar_count=len(bars),
        history_start_at=bars[0].closed_at,
        market_as_of=bars[-1].closed_at,
        support=_side_analysis(bars, "support"),
        resistance=_side_analysis(bars, "resistance"),
    )


__all__ = ["_prepare", "analyze_geometry"]
