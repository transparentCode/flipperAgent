"""Small deterministic, dependency-free production core for Trendlines V4."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from math import isfinite
from numbers import Real
from typing import Literal

Side = Literal["support", "resistance"]
PathPoint = tuple[int, float]
PIVOT_WINDOW = 3
HISTORY_CAPACITY_BARS = 300


def _utc(value: datetime, name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TypeError(f"{name} must be a timezone-aware UTC datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC")
    return value.astimezone(UTC)


def _number(value: object, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{name} must be finite")
    if positive and result <= 0:
        raise ValueError(f"{name} must be positive")
    return result


@dataclass(frozen=True, slots=True)
class TrendlineBar:
    """One closed, UTC-timestamped OHLC bar accepted by the core."""

    closed_at: datetime
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "closed_at", _utc(self.closed_at, "closed_at"))
        values = {
            "open": _number(self.open, "open", positive=True),
            "high": _number(self.high, "high", positive=True),
            "low": _number(self.low, "low", positive=True),
            "close": _number(self.close, "close", positive=True),
        }
        if values["low"] > values["high"]:
            raise ValueError("low must be <= high")
        if not values["low"] <= values["open"] <= values["high"]:
            raise ValueError("open must lie within [low, high]")
        if not values["low"] <= values["close"] <= values["high"]:
            raise ValueError("close must lie within [low, high]")
        for name, value in values.items():
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class TrendlineGeometry:
    """One emitted raw-price line plus factual validity metadata."""

    side: Side
    start_anchor_at: datetime
    start_anchor_price: float
    end_anchor_at: datetime
    end_anchor_price: float
    slope_per_bar: float
    projected_price_at_market_as_of: float
    post_anchor_body_crossed: bool
    post_anchor_body_cross_count: int
    projection_positive: bool

    def __post_init__(self) -> None:
        if self.side not in ("support", "resistance"):
            raise ValueError("side must be support or resistance")
        object.__setattr__(
            self, "start_anchor_at", _utc(self.start_anchor_at, "start_anchor_at")
        )
        object.__setattr__(
            self, "end_anchor_at", _utc(self.end_anchor_at, "end_anchor_at")
        )
        if self.end_anchor_at <= self.start_anchor_at:
            raise ValueError("end_anchor_at must be later than start_anchor_at")
        object.__setattr__(
            self,
            "start_anchor_price",
            _number(self.start_anchor_price, "start_anchor_price", positive=True),
        )
        object.__setattr__(
            self,
            "end_anchor_price",
            _number(self.end_anchor_price, "end_anchor_price", positive=True),
        )
        object.__setattr__(
            self, "slope_per_bar", _number(self.slope_per_bar, "slope_per_bar")
        )
        projected = _number(
            self.projected_price_at_market_as_of, "projected_price_at_market_as_of"
        )
        object.__setattr__(self, "projected_price_at_market_as_of", projected)
        if not isinstance(self.projection_positive, bool):
            raise TypeError("projection_positive must be bool")
        if isinstance(self.post_anchor_body_crossed, bool) is False:
            raise TypeError("post_anchor_body_crossed must be bool")
        if isinstance(self.post_anchor_body_cross_count, bool) or not isinstance(
            self.post_anchor_body_cross_count, int
        ):
            raise TypeError("post_anchor_body_cross_count must be an integer")
        if self.post_anchor_body_cross_count < 0:
            raise ValueError("post_anchor_body_cross_count must be non-negative")
        if self.post_anchor_body_crossed != (self.post_anchor_body_cross_count > 0):
            raise ValueError("crossing flag and count disagree")
        if self.projection_positive != (projected > 0):
            raise ValueError("projection_positive disagrees with projection")


@dataclass(frozen=True, slots=True)
class SideGeometry:
    """Structural and current-valid roles for one side."""

    structural: TrendlineGeometry | None
    current_valid: TrendlineGeometry | None
    same_geometry: bool

    def __post_init__(self) -> None:
        if self.structural is not None and not isinstance(
            self.structural, TrendlineGeometry
        ):
            raise TypeError("structural must be TrendlineGeometry or None")
        if self.current_valid is not None and not isinstance(
            self.current_valid, TrendlineGeometry
        ):
            raise TypeError("current_valid must be TrendlineGeometry or None")
        if not isinstance(self.same_geometry, bool):
            raise TypeError("same_geometry must be bool")
        expected = self.structural is not None and self.structural == self.current_valid
        if self.same_geometry != expected:
            raise ValueError("same_geometry disagrees with the two roles")


@dataclass(frozen=True, slots=True)
class TrendlineSnapshot:
    """One bounded analytical geometry snapshot at a closed-bar cutoff."""

    schema_version: Literal["trendlines.geometry.v1"]
    history_bar_count: int
    history_capacity_bars: int
    pivot_window: int
    history_start_at: datetime
    market_as_of: datetime
    support: SideGeometry
    resistance: SideGeometry

    def __post_init__(self) -> None:
        if self.schema_version != "trendlines.geometry.v1":
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
        if not isinstance(self.support, SideGeometry) or not isinstance(
            self.resistance, SideGeometry
        ):
            raise TypeError("support and resistance must be SideGeometry")


@dataclass(frozen=True, slots=True)
class _Line:
    start_index: int
    end_index: int
    start_price: float
    end_price: float
    slope: float
    intercept: float
    projected: float


@dataclass(frozen=True, slots=True)
class _SideState:
    structural: _Line | None
    current_valid: _Line | None


def _pivots(bars: Sequence[TrendlineBar], side: Side) -> tuple[PathPoint, ...]:
    values = [bar.low if side == "support" else bar.high for bar in bars]
    result = []
    for index in range(PIVOT_WINDOW, len(values) - PIVOT_WINDOW):
        window = values[index - PIVOT_WINDOW : index + PIVOT_WINDOW + 1]
        value = values[index]
        if value == (min(window) if side == "support" else max(window)):
            result.append((index, value))
    return tuple(result)


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


def _solve_side(bars: Sequence[TrendlineBar], side: Side) -> _SideState:
    pivots = _pivots(bars, side)
    scores = {index: 0 for index, _ in pivots}
    predecessors = {index: -1 for index, _ in pivots}
    for current_position, (current_index, current_price) in enumerate(pivots):
        for previous_position in range(current_position):
            previous_index, previous_price = pivots[previous_position]
            if not _segment_is_valid(
                bars, previous_index, previous_price, current_index, current_price, side
            ):
                continue
            new_score = scores[previous_index] + current_index - previous_index
            if new_score > scores[current_index]:
                scores[current_index] = new_score
                predecessors[current_index] = previous_index
    winning_path = []
    if scores:
        best_end = max(scores, key=scores.__getitem__)
        if scores[best_end] != 0:
            prices = dict(pivots)
            cursor = best_end
            while cursor != -1:
                winning_path.append((cursor, prices[cursor]))
                cursor = predecessors[cursor]
            winning_path.reverse()
    structural = _build_line(winning_path, len(bars) - 1)
    prices = dict(pivots)
    positions = {index: position for position, (index, _) in enumerate(pivots)}
    current = None
    for endpoint, score in scores.items():
        if score <= 0:
            continue
        path = _reconstruct_path(endpoint, prices, predecessors, positions)
        line = _build_line(path, len(bars) - 1)
        if line is None:
            raise ValueError("positive endpoint did not produce a line")
        if _crossing_count(bars, line, side) == 0 and (
            current is None or score > current[0]
        ):
            current = (score, line)
    return _SideState(structural, None if current is None else current[1])


def _geometry(
    bars: Sequence[TrendlineBar], side: Side, line: _Line | None
) -> TrendlineGeometry | None:
    if line is None:
        return None
    crossings = _crossing_count(bars, line, side)
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


def _side_geometry(
    bars: Sequence[TrendlineBar], side: Side, state: _SideState
) -> SideGeometry:
    structural = _geometry(bars, side, state.structural)
    current = _geometry(bars, side, state.current_valid)
    return SideGeometry(
        structural, current, structural is not None and structural == current
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


def analyze_trendlines(history: Sequence[TrendlineBar]) -> TrendlineSnapshot:
    """Analyze one ordered closed-bar history at its latest cutoff."""

    bars = _prepare(history)
    support = _solve_side(bars, "support")
    resistance = _solve_side(bars, "resistance")
    support_geometry = _side_geometry(bars, "support", support)
    resistance_geometry = _side_geometry(bars, "resistance", resistance)
    return TrendlineSnapshot(
        schema_version="trendlines.geometry.v1",
        history_bar_count=len(bars),
        history_capacity_bars=HISTORY_CAPACITY_BARS,
        pivot_window=PIVOT_WINDOW,
        history_start_at=bars[0].closed_at,
        market_as_of=bars[-1].closed_at,
        support=support_geometry,
        resistance=resistance_geometry,
    )


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
