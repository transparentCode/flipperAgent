"""Independent reproduction of the frozen KineticAlpha pathfinding algorithm.

This module intentionally models the small legacy algorithm only.  It uses raw
prices and integer bar positions, and it does not import the KineticAlpha
repository at runtime.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Side = Literal["support", "resistance"]
PathPoint = tuple[int, float]
GraphEdge = tuple[int, int]


@dataclass(frozen=True, slots=True)
class Bar:
    """The four OHLC values used by the legacy geometry."""

    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class EmittedLine:
    """The final two-anchor projection emitted from a winning path."""

    start_index: int
    end_index: int
    start_price: float
    end_price: float
    slope: float
    intercept: float
    projected_value_at_final_bar: float


@dataclass(frozen=True, slots=True)
class SidePathResult:
    """All compact state needed to audit one legacy support/resistance path."""

    side: Side
    pivots: tuple[PathPoint, ...]
    valid_edges: tuple[GraphEdge, ...]
    dp_scores: tuple[tuple[int, int], ...]
    dp_predecessors: tuple[tuple[int, int], ...]
    winning_path: tuple[PathPoint, ...]
    emitted_line: EmittedLine | None


@dataclass(frozen=True, slots=True)
class LegacyPathfindingResult:
    """Independent result for both sides of one frozen OHLC window."""

    support: SidePathResult
    resistance: SidePathResult


def read_ohlc_window(
    path: str | Path, start_index: int, end_index_exclusive: int
) -> tuple[Bar, ...]:
    """Read exactly one half-open OHLC window from a local CSV source."""

    if start_index < 0 or end_index_exclusive <= start_index:
        raise ValueError("window must be a non-empty half-open interval")

    source_path = Path(path)
    bars: list[Bar] = []
    with source_path.open(newline="") as source:
        reader = csv.DictReader(source)
        required = {"open", "high", "low", "close"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(
                "CSV source must contain open, high, low, and close columns"
            )
        for row_index, row in enumerate(reader):
            if row_index >= end_index_exclusive:
                break
            if row_index >= start_index:
                bars.append(
                    Bar(
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                    )
                )

    expected = end_index_exclusive - start_index
    if len(bars) != expected:
        raise ValueError(
            f"source ended before requested window: expected {expected}, got {len(bars)}"
        )
    return tuple(bars)


def extract_pivots(
    bars: Sequence[Bar], pivot_window: int, side: Side
) -> tuple[PathPoint, ...]:
    """Apply the original inclusive-window equality pivot rule."""

    if pivot_window < 1:
        raise ValueError("pivot_window must be >= 1")
    if side not in ("support", "resistance"):
        raise ValueError(f"unknown side: {side}")

    field = "low" if side == "support" else "high"
    values = [getattr(bar, field) for bar in bars]
    pivots: list[PathPoint] = []
    for index in range(pivot_window, len(values) - pivot_window):
        window = values[index - pivot_window : index + pivot_window + 1]
        value = values[index]
        if value == (min(window) if side == "support" else max(window)):
            pivots.append((index, value))
    return tuple(pivots)


def analyze_side(bars: Sequence[Bar], pivot_window: int, side: Side) -> SidePathResult:
    """Run the frozen pivot, graph, DP, and final-segment steps for one side."""

    pivots = extract_pivots(bars, pivot_window, side)
    return _solve_side(bars, pivots, side)


def analyze_legacy(
    bars: Sequence[Bar], pivot_window: int = 3
) -> LegacyPathfindingResult:
    """Run the independent reproduction with the selected legacy default."""

    resistance = analyze_side(bars, pivot_window, "resistance")
    support = analyze_side(bars, pivot_window, "support")
    return LegacyPathfindingResult(support=support, resistance=resistance)


def result_to_payload(result: LegacyPathfindingResult) -> dict[str, object]:
    """Convert a result to a compact JSON-compatible audit payload."""

    return {
        "support": _side_to_payload(result.support),
        "resistance": _side_to_payload(result.resistance),
    }


def _side_to_payload(result: SidePathResult) -> dict[str, object]:
    return {
        "side": result.side,
        "pivots": [[index, price] for index, price in result.pivots],
        "valid_edges": [
            [previous, current] for previous, current in result.valid_edges
        ],
        "dp_scores": [[index, score] for index, score in result.dp_scores],
        "dp_predecessors": [
            [index, predecessor] for index, predecessor in result.dp_predecessors
        ],
        "winning_path": [[index, price] for index, price in result.winning_path],
        "emitted_line": None
        if result.emitted_line is None
        else _line_to_payload(result.emitted_line),
    }


def _line_to_payload(line: EmittedLine) -> dict[str, object]:
    return {
        "start_index": line.start_index,
        "end_index": line.end_index,
        "start_price": line.start_price,
        "end_price": line.end_price,
        "slope": line.slope,
        "intercept": line.intercept,
        "projected_value_at_final_bar": line.projected_value_at_final_bar,
    }


def _solve_side(
    bars: Sequence[Bar],
    pivots: Sequence[PathPoint],
    side: Side,
) -> SidePathResult:
    valid_edges: list[GraphEdge] = []
    scores = {index: 0 for index, _ in pivots}
    predecessors = {index: -1 for index, _ in pivots}

    for current_position, (current_index, current_price) in enumerate(pivots):
        for previous_position in range(current_position):
            previous_index, previous_price = pivots[previous_position]
            if not _segment_is_valid(
                bars,
                previous_index,
                previous_price,
                current_index,
                current_price,
                side,
            ):
                continue

            valid_edges.append((previous_index, current_index))
            segment_length = current_index - previous_index
            new_score = scores[previous_index] + segment_length
            if new_score > scores[current_index]:
                scores[current_index] = new_score
                predecessors[current_index] = previous_index

    winning_path: list[PathPoint] = []
    if scores:
        best_end = max(scores, key=scores.__getitem__)
        if scores[best_end] != 0:
            prices = dict(pivots)
            cursor = best_end
            while cursor != -1:
                winning_path.append((cursor, prices[cursor]))
                cursor = predecessors[cursor]
            winning_path.reverse()

    winning_path_tuple = tuple(winning_path)
    emitted_line = _build_line(winning_path_tuple, len(bars) - 1)
    return SidePathResult(
        side=side,
        pivots=tuple(pivots),
        valid_edges=tuple(valid_edges),
        dp_scores=tuple(scores.items()),
        dp_predecessors=tuple(predecessors.items()),
        winning_path=winning_path_tuple,
        emitted_line=emitted_line,
    )


def _segment_is_valid(
    bars: Sequence[Bar],
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
        if side == "support":
            if line_value > body_bottom:
                return False
        elif line_value < body_top:
            return False
    return True


def _build_line(path: Sequence[PathPoint], final_bar_index: int) -> EmittedLine | None:
    if len(path) < 2:
        return None

    previous_index, previous_price = path[-2]
    last_index, last_price = path[-1]
    slope = (last_price - previous_price) / (last_index - previous_index)
    intercept = last_price - slope * last_index
    projected = slope * final_bar_index + intercept
    return EmittedLine(
        start_index=previous_index,
        end_index=last_index,
        start_price=previous_price,
        end_price=last_price,
        slope=slope,
        intercept=intercept,
        projected_value_at_final_bar=projected,
    )


__all__ = [
    "Bar",
    "EmittedLine",
    "LegacyPathfindingResult",
    "SidePathResult",
    "analyze_legacy",
    "analyze_side",
    "extract_pivots",
    "read_ohlc_window",
    "result_to_payload",
]
