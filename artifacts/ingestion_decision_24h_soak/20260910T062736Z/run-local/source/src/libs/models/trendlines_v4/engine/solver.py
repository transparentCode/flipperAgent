"""One exact legacy DP solver used by both public V4 geometry views."""

from __future__ import annotations

from collections.abc import Sequence

from . import pivots, validity
from .types import PathPoint, Side, TrendlineBar, TrendlineGeometry, _Line, _SideState


def _build_line(path: Sequence[PathPoint], final_index: int) -> _Line | None:
    if len(path) < 2:
        return None
    previous_index, previous_price = path[-2]
    end_index, end_price = path[-1]
    slope = (end_price - previous_price) / (end_index - previous_index)
    intercept = end_price - slope * end_index
    return _Line(
        previous_index,
        end_index,
        previous_price,
        end_price,
        slope,
        intercept,
        slope * final_index + intercept,
    )


def _reconstruct_path(
    endpoint: int,
    prices: dict[int, float],
    predecessors: dict[int, int],
    positions: dict[int, int],
) -> tuple[PathPoint, ...]:
    path, seen, cursor = [], set(), endpoint
    while cursor != -1:
        if cursor in seen or cursor not in prices or cursor not in predecessors:
            raise ValueError("invalid predecessor state")
        seen.add(cursor)
        path.append((cursor, prices[cursor]))
        previous = predecessors[cursor]
        if previous != -1 and (
            previous not in positions or positions[previous] >= positions[cursor]
        ):
            raise ValueError("predecessor must be strictly earlier")
        cursor = previous
    path.reverse()
    if not path or path[-1][0] != endpoint:
        raise ValueError("reconstructed path has the wrong endpoint")
    return tuple(path)


def _geometry(
    bars: Sequence[TrendlineBar], side: Side, line: _Line | None
) -> TrendlineGeometry | None:
    if line is None:
        return None
    crossings = validity._crossing_count(bars, line, side)
    return TrendlineGeometry(
        side=side,
        start_anchor_at=bars[line.start_index].closed_at,
        start_anchor_price=line.start_price,
        end_anchor_at=bars[line.end_index].closed_at,
        end_anchor_price=line.end_price,
        slope_per_bar=line.slope,
        projected_price_at_market_as_of=line.projected,
        post_anchor_body_crossed=crossings > 0,
        post_anchor_body_cross_count=crossings,
        projection_positive=line.projected > 0,
    )


def _geometry_key(line: TrendlineGeometry) -> tuple[object, ...]:
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


def _solve_side(bars: Sequence[TrendlineBar], side: Side) -> _SideState:
    """Run the frozen DP once and select all three factual role candidates."""

    pivot_values = pivots._pivots(bars, side)
    scores = {index: 0 for index, _ in pivot_values}
    predecessors = {index: -1 for index, _ in pivot_values}
    for current_position, (current_index, current_price) in enumerate(pivot_values):
        for previous_position in range(current_position):
            previous_index, previous_price = pivot_values[previous_position]
            if not validity._segment_is_valid(
                bars, previous_index, previous_price, current_index, current_price, side
            ):
                continue
            new_score = scores[previous_index] + current_index - previous_index
            if new_score > scores[current_index]:
                scores[current_index] = new_score
                predecessors[current_index] = previous_index

    prices = dict(pivot_values)
    positions = {index: position for position, (index, _) in enumerate(pivot_values)}
    endpoints: list[tuple[int, int, _Line, TrendlineGeometry]] = []
    for endpoint, score in scores.items():
        if score <= 0:
            continue
        path = _reconstruct_path(endpoint, prices, predecessors, positions)
        line = _build_line(path, len(bars) - 1)
        if line is None:
            raise ValueError("positive endpoint did not produce a line")
        geometry = _geometry(bars, side, line)
        if geometry is None:
            raise ValueError("positive endpoint geometry is missing")
        endpoints.append((endpoint, score, line, geometry))

    winning_path = []
    if scores:
        best_end = max(scores, key=scores.__getitem__)
        if scores[best_end] != 0:
            cursor = best_end
            while cursor != -1:
                winning_path.append((cursor, prices[cursor]))
                cursor = predecessors[cursor]
            winning_path.reverse()
    structural = _build_line(winning_path, len(bars) - 1)

    current: tuple[int, _Line] | None = None
    for _endpoint, score, line, geometry in endpoints:
        if geometry.post_anchor_body_cross_count == 0 and (
            current is None or score > current[0]
        ):
            current = (score, line)

    exposed: set[tuple[object, ...]] = set()
    if structural is not None:
        structural_geometry = _geometry(bars, side, structural)
        if structural_geometry is None:
            raise ValueError("structural geometry is missing")
        exposed = {_geometry_key(structural_geometry)}
    if current is not None:
        current_geometry = _geometry(bars, side, current[1])
        if current_geometry is None:
            raise ValueError("current-valid geometry is missing")
        exposed.add(_geometry_key(current_geometry))

    secondary: _Line | None = None
    secondary_score: int | None = None
    for _endpoint, score, line, geometry in endpoints:
        if _geometry_key(geometry) in exposed:
            continue
        if secondary is None or (
            secondary_score is not None and score > secondary_score
        ):
            secondary = line
            secondary_score = score
    return _SideState(structural, None if current is None else current[1], secondary)


__all__ = [
    "_build_line",
    "_geometry",
    "_geometry_key",
    "_reconstruct_path",
    "_solve_side",
]
