"""Domain values shared by the versioned Trendlines V4 views."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
    secondary: _Line | None = None


@dataclass(frozen=True, slots=True)
class SideAnalysis:
    structural: TrendlineGeometry | None
    current_valid: TrendlineGeometry | None
    secondary: TrendlineGeometry | None
    same_geometry: bool


@dataclass(frozen=True, slots=True)
class TrendlineAnalysis:
    history_bar_count: int
    history_start_at: datetime
    market_as_of: datetime
    support: SideAnalysis
    resistance: SideAnalysis


__all__ = [
    "HISTORY_CAPACITY_BARS",
    "PIVOT_WINDOW",
    "PathPoint",
    "Side",
    "SideAnalysis",
    "TrendlineAnalysis",
    "TrendlineBar",
    "TrendlineGeometry",
    "_Line",
    "_SideState",
    "_number",
    "_utc",
]
