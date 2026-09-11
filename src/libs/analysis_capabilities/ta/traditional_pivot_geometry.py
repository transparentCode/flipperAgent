"""Traditional floor-trader pivot geometry from one completed range."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from numbers import Real
from typing import Literal

TraditionalPivotName = Literal["s3", "s2", "s1", "pivot", "r1", "r2", "r3"]
_LEVEL_NAMES = ("s3", "s2", "s1", "pivot", "r1", "r2", "r3")


def _utc(value: object, *, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TypeError(f"{field_name} must be a timezone-aware UTC datetime")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
    return value.astimezone(UTC)


def _finite_real(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be a real number")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


def _positive_price(value: object, *, field_name: str) -> float:
    normalized = _finite_real(value, field_name=field_name)
    if normalized <= 0.0:
        raise ValueError(f"{field_name} must be strictly positive")
    return normalized


@dataclass(frozen=True, slots=True)
class TraditionalPivotReference:
    """One explicitly completed high/low/close reference range."""

    opened_at: datetime
    closed_at: datetime
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        opened_at = _utc(self.opened_at, field_name="opened_at")
        closed_at = _utc(self.closed_at, field_name="closed_at")
        if closed_at <= opened_at:
            raise ValueError("closed_at must be later than opened_at")
        high = _positive_price(self.high, field_name="high")
        low = _positive_price(self.low, field_name="low")
        close = _positive_price(self.close, field_name="close")
        if low > high:
            raise ValueError("low must be <= high")
        if not low <= close <= high:
            raise ValueError("close must be between low and high")
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "closed_at", closed_at)
        object.__setattr__(self, "high", high)
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "close", close)


@dataclass(frozen=True, slots=True)
class TraditionalPivotLevel:
    """One named Traditional seven-level pivot value."""

    name: TraditionalPivotName
    price: float

    def __post_init__(self) -> None:
        if self.name not in _LEVEL_NAMES:
            raise ValueError("name is not a Traditional pivot level")
        object.__setattr__(
            self,
            "price",
            _finite_real(self.price, field_name="price"),
        )


@dataclass(frozen=True, slots=True)
class TraditionalPivotGeometryRequest:
    """One explicit completed reference and its point-in-time cutoff."""

    reference: TraditionalPivotReference
    market_as_of: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.reference, TraditionalPivotReference):
            raise TypeError("reference must be TraditionalPivotReference")
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        if self.reference.closed_at > market_as_of:
            raise ValueError("reference is not complete at market_as_of")
        object.__setattr__(self, "market_as_of", market_as_of)


@dataclass(frozen=True, slots=True)
class TraditionalPivotGeometrySnapshot:
    """Immutable checked Traditional seven-level geometry at one cutoff."""

    market_as_of: datetime
    reference: TraditionalPivotReference
    levels: tuple[TraditionalPivotLevel, ...]

    def __post_init__(self) -> None:
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        if not isinstance(self.reference, TraditionalPivotReference):
            raise TypeError("reference must be TraditionalPivotReference")
        if self.reference.closed_at > market_as_of:
            raise ValueError("reference is not complete at market_as_of")
        if not isinstance(self.levels, tuple):
            raise TypeError("levels must be a tuple of TraditionalPivotLevel values")
        if len(self.levels) != len(_LEVEL_NAMES):
            raise ValueError("levels must contain exactly seven values")
        expected_prices = _traditional_prices(self.reference)
        for index, level in enumerate(self.levels):
            if not isinstance(level, TraditionalPivotLevel):
                raise TypeError(f"levels[{index}] must be TraditionalPivotLevel")
            if level.name != _LEVEL_NAMES[index]:
                raise ValueError("levels must use the fixed semantic order")
            if level.price != expected_prices[index]:
                raise ValueError("levels are inconsistent with the reference")
        object.__setattr__(self, "market_as_of", market_as_of)


def _traditional_prices(
    reference: TraditionalPivotReference,
) -> tuple[float, ...]:
    high = reference.high
    low = reference.low
    close = reference.close
    if high == low:
        return (low,) * len(_LEVEL_NAMES)

    range_size = high - low
    close_offset = close - low
    pivot = low + range_size / 3.0 + close_offset / 3.0
    return (
        low - 2.0 * (high - pivot),
        pivot - range_size,
        2.0 * pivot - high,
        pivot,
        2.0 * pivot - low,
        pivot + range_size,
        high + 2.0 * (pivot - low),
    )


def compute_traditional_pivot_geometry(
    request: TraditionalPivotGeometryRequest,
) -> TraditionalPivotGeometrySnapshot:
    """Compute the fixed Traditional/floor-trader pivot formulas."""

    if not isinstance(request, TraditionalPivotGeometryRequest):
        raise TypeError("request must be TraditionalPivotGeometryRequest")

    levels = tuple(
        TraditionalPivotLevel(name, price)
        for name, price in zip(_LEVEL_NAMES, _traditional_prices(request.reference))
    )
    return TraditionalPivotGeometrySnapshot(
        market_as_of=request.market_as_of,
        reference=request.reference,
        levels=levels,
    )


__all__ = (
    "TraditionalPivotGeometryRequest",
    "TraditionalPivotGeometrySnapshot",
    "TraditionalPivotLevel",
    "TraditionalPivotReference",
    "compute_traditional_pivot_geometry",
)
