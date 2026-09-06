"""Additive V2 Trendlines core with the research-backed secondary role."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .core import (
    HISTORY_CAPACITY_BARS,
    PIVOT_WINDOW,
    TrendlineBar,
    TrendlineGeometry,
    _build_line,
    _geometry,
    _pivots,
    _prepare,
    _reconstruct_path,
    _segment_is_valid,
    _utc,
)

Side = Literal["support", "resistance"]
GEOMETRY_SCHEMA_VERSION = "trendlines.geometry.v2"


@dataclass(frozen=True, slots=True)
class SideGeometryV2:
    """Three factual role slots for one side of a V2 snapshot."""

    structural: TrendlineGeometry | None
    current_valid: TrendlineGeometry | None
    secondary: TrendlineGeometry | None
    same_geometry: bool

    def __post_init__(self) -> None:
        roles = (self.structural, self.current_valid, self.secondary)
        if any(
            line is not None and not isinstance(line, TrendlineGeometry)
            for line in roles
        ):
            raise TypeError("side roles must be TrendlineGeometry or None")
        if not isinstance(self.same_geometry, bool):
            raise TypeError("same_geometry must be bool")
        expected = self.structural is not None and self.structural == self.current_valid
        if self.same_geometry != expected:
            raise ValueError("same_geometry disagrees with structural/current_valid")
        side = next((line.side for line in roles if line is not None), None)
        if side is not None and any(
            line is not None and line.side != side for line in roles
        ):
            raise ValueError("side roles must use one side")


@dataclass(frozen=True, slots=True)
class TrendlineSnapshotV2:
    """One bounded V2 analytical geometry snapshot at a closed-bar cutoff."""

    schema_version: Literal["trendlines.geometry.v2"]
    history_bar_count: int
    history_capacity_bars: int
    pivot_window: int
    history_start_at: datetime
    market_as_of: datetime
    support: SideGeometryV2
    resistance: SideGeometryV2

    def __post_init__(self) -> None:
        if self.schema_version != GEOMETRY_SCHEMA_VERSION:
            raise ValueError("unsupported geometry schema_version")
        if (
            isinstance(self.history_bar_count, bool)
            or not isinstance(self.history_bar_count, int)
            or self.history_bar_count < 1
        ):
            raise ValueError("history_bar_count must be positive")
        if self.history_capacity_bars != HISTORY_CAPACITY_BARS:
            raise ValueError("history_capacity_bars must be 300")
        if self.pivot_window != PIVOT_WINDOW:
            raise ValueError("pivot_window must be 3")
        start = _utc(self.history_start_at, "history_start_at")
        market = _utc(self.market_as_of, "market_as_of")
        if market < start:
            raise ValueError("market_as_of must not precede history_start_at")
        object.__setattr__(self, "history_start_at", start)
        object.__setattr__(self, "market_as_of", market)
        if not isinstance(self.support, SideGeometryV2) or not isinstance(
            self.resistance, SideGeometryV2
        ):
            raise TypeError("support and resistance must be SideGeometryV2")


@dataclass(frozen=True, slots=True)
class _SideStateV2:
    structural: TrendlineGeometry | None
    current_valid: TrendlineGeometry | None
    secondary: TrendlineGeometry | None


def _geometry_key(line: TrendlineGeometry) -> tuple[object, ...]:
    """Return an exact role-independent key for one cutoff's geometry."""

    return (
        line.side,
        line.start_anchor_at,
        line.start_anchor_price,
        line.end_anchor_at,
        line.end_anchor_price,
        line.slope_per_bar,
        line.projected_price_at_market_as_of,
        line.post_anchor_body_crossed,
        line.post_anchor_body_cross_count,
        line.projection_positive,
    )


def _solve_side_v2(history: Sequence[TrendlineBar], side: Side) -> _SideStateV2:
    """Reproduce the V1 DP, then select one distinct endpoint by legacy score."""

    pivots = tuple(_pivots(history, side))
    scores = {index: 0 for index, _ in pivots}
    predecessors = {index: -1 for index, _ in pivots}
    for current_position, (current_index, current_price) in enumerate(pivots):
        for previous_position in range(current_position):
            previous_index, previous_price = pivots[previous_position]
            if not _segment_is_valid(
                history,
                previous_index,
                previous_price,
                current_index,
                current_price,
                side,
            ):
                continue
            new_score = scores[previous_index] + current_index - previous_index
            if new_score > scores[current_index]:
                scores[current_index] = new_score
                predecessors[current_index] = previous_index

    positions = {index: position for position, (index, _) in enumerate(pivots)}
    prices = dict(pivots)
    endpoints: list[tuple[int, int, TrendlineGeometry]] = []
    for endpoint_index, score in scores.items():
        if score <= 0:
            continue
        path = _reconstruct_path(endpoint_index, prices, predecessors, positions)
        line = _build_line(path, len(history) - 1)
        if line is None:
            raise ValueError("positive endpoint did not produce a line")
        geometry = _geometry(history, side, line)
        if geometry is None:
            raise ValueError("positive endpoint geometry is missing")
        endpoints.append((endpoint_index, score, geometry))

    by_endpoint = {
        endpoint: (score, geometry) for endpoint, score, geometry in endpoints
    }
    structural: TrendlineGeometry | None = None
    if scores:
        best_endpoint = max(scores, key=scores.__getitem__)
        if scores[best_endpoint] > 0:
            structural = by_endpoint[best_endpoint][1]

    current_valid: TrendlineGeometry | None = None
    current_score: int | None = None
    for _endpoint, score, geometry in endpoints:
        if geometry.post_anchor_body_cross_count != 0:
            continue
        if current_valid is None or (
            current_score is not None and score > current_score
        ):
            current_valid = geometry
            current_score = score

    exposed = {
        _geometry_key(line) for line in (structural, current_valid) if line is not None
    }
    secondary: TrendlineGeometry | None = None
    secondary_score: int | None = None
    for _endpoint, score, geometry in endpoints:
        if _geometry_key(geometry) in exposed:
            continue
        if secondary is None or (
            secondary_score is not None and score > secondary_score
        ):
            secondary = geometry
            secondary_score = score
    return _SideStateV2(structural, current_valid, secondary)


def _side_geometry_v2(state: _SideStateV2) -> SideGeometryV2:
    return SideGeometryV2(
        structural=state.structural,
        current_valid=state.current_valid,
        secondary=state.secondary,
        same_geometry=(
            state.structural is not None and state.structural == state.current_valid
        ),
    )


def analyze_trendlines_v2(
    history: Sequence[TrendlineBar],
) -> TrendlineSnapshotV2:
    """Analyze fixed 3/300 history and add the exact distinct secondary role."""

    bars = _prepare(history)
    support = _solve_side_v2(bars, "support")
    resistance = _solve_side_v2(bars, "resistance")
    return TrendlineSnapshotV2(
        schema_version=GEOMETRY_SCHEMA_VERSION,
        history_bar_count=len(bars),
        history_capacity_bars=HISTORY_CAPACITY_BARS,
        pivot_window=PIVOT_WINDOW,
        history_start_at=bars[0].closed_at,
        market_as_of=bars[-1].closed_at,
        support=_side_geometry_v2(support),
        resistance=_side_geometry_v2(resistance),
    )


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
