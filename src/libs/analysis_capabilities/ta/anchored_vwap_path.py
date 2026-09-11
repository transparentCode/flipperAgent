"""Explicit-range cumulative anchored VWAP path geometry."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite

from .vwap_geometry import VWAPBar


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


def _finite(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a real number")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


@dataclass(frozen=True, slots=True)
class AnchoredVWAPPoint:
    """One cumulative anchored VWAP value at a closed bar."""

    closed_at: datetime
    cumulative_volume: float
    vwap_price: float

    def __post_init__(self) -> None:
        closed_at = _utc(self.closed_at, field_name="closed_at")
        cumulative_volume = _finite(
            self.cumulative_volume,
            field_name="cumulative_volume",
        )
        vwap_price = _finite(self.vwap_price, field_name="vwap_price")
        if cumulative_volume <= 0.0:
            raise ValueError("cumulative_volume must be strictly positive")
        if vwap_price <= 0.0:
            raise ValueError("vwap_price must be strictly positive")
        object.__setattr__(self, "closed_at", closed_at)
        object.__setattr__(self, "cumulative_volume", cumulative_volume)
        object.__setattr__(self, "vwap_price", vwap_price)


@dataclass(frozen=True, slots=True)
class AnchoredVWAPPathRequest:
    """Explicit ordered bars and the exact current cutoff."""

    bars: tuple[VWAPBar, ...]
    market_as_of: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.bars, tuple):
            raise TypeError("bars must be a tuple of VWAPBar values")
        if not self.bars:
            raise ValueError("bars must contain at least one VWAPBar")
        previous: datetime | None = None
        has_positive_volume = False
        for index, bar in enumerate(self.bars):
            if not isinstance(bar, VWAPBar):
                raise TypeError(f"bars[{index}] must be VWAPBar")
            if previous is not None and bar.closed_at <= previous:
                raise ValueError("bars.closed_at values must be strictly increasing")
            previous = bar.closed_at
            has_positive_volume = has_positive_volume or bar.volume > 0.0
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        if self.bars[-1].closed_at != market_as_of:
            raise ValueError("final bar must close exactly at market_as_of")
        if not has_positive_volume:
            raise ValueError("at least one bar must have positive volume")
        object.__setattr__(self, "market_as_of", market_as_of)


@dataclass(frozen=True, slots=True)
class AnchoredVWAPPathSnapshot:
    """Immutable cumulative anchored VWAP path at one exact cutoff."""

    market_as_of: datetime
    first_bar_closed_at: datetime
    input_bar_count: int
    points: tuple[AnchoredVWAPPoint, ...]

    def __post_init__(self) -> None:
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        first_bar_closed_at = _utc(
            self.first_bar_closed_at,
            field_name="first_bar_closed_at",
        )
        if first_bar_closed_at > market_as_of:
            raise ValueError("first_bar_closed_at must be <= market_as_of")
        if isinstance(self.input_bar_count, bool) or not isinstance(
            self.input_bar_count, int
        ):
            raise TypeError("input_bar_count must be an integer")
        if self.input_bar_count < 1:
            raise ValueError("input_bar_count must be at least 1")
        if not isinstance(self.points, tuple) or not self.points:
            raise ValueError("points must be a non-empty tuple")
        if len(self.points) > self.input_bar_count:
            raise ValueError("points cannot exceed input_bar_count")
        previous: AnchoredVWAPPoint | None = None
        for index, point in enumerate(self.points):
            if not isinstance(point, AnchoredVWAPPoint):
                raise TypeError(f"points[{index}] must be AnchoredVWAPPoint")
            if point.closed_at < first_bar_closed_at:
                raise ValueError("point precedes first_bar_closed_at")
            if previous is not None:
                if point.closed_at <= previous.closed_at:
                    raise ValueError(
                        "points.closed_at values must be strictly increasing"
                    )
                if point.cumulative_volume < previous.cumulative_volume:
                    raise ValueError("cumulative_volume must not decrease")
            previous = point
        if self.points[-1].closed_at != market_as_of:
            raise ValueError("final point must close exactly at market_as_of")
        object.__setattr__(self, "market_as_of", market_as_of)
        object.__setattr__(self, "first_bar_closed_at", first_bar_closed_at)


def compute_anchored_vwap_path(
    request: AnchoredVWAPPathRequest,
) -> AnchoredVWAPPathSnapshot:
    """Compute one forward cumulative HLC3 VWAP path with no session reset."""

    if not isinstance(request, AnchoredVWAPPathRequest):
        raise TypeError("request must be AnchoredVWAPPathRequest")
    total_volume = 0.0
    weighted_price_sum = 0.0
    points: list[AnchoredVWAPPoint] = []
    for bar in request.bars:
        total_volume += bar.volume
        if not isfinite(total_volume):
            raise ValueError("VWAP accumulation must remain finite")
        if bar.volume > 0.0:
            typical_price = (
                bar.low + (bar.high - bar.low) / 3.0 + (bar.close - bar.low) / 3.0
            )
            weighted_price_sum += typical_price * bar.volume
            if not isfinite(weighted_price_sum):
                raise ValueError("VWAP accumulation must remain finite")
        if total_volume > 0.0:
            vwap_price = weighted_price_sum / total_volume
            if not isfinite(vwap_price):
                raise ValueError("VWAP price must remain finite")
            points.append(
                AnchoredVWAPPoint(
                    closed_at=bar.closed_at,
                    cumulative_volume=total_volume,
                    vwap_price=vwap_price,
                )
            )
    return AnchoredVWAPPathSnapshot(
        market_as_of=request.market_as_of,
        first_bar_closed_at=request.bars[0].closed_at,
        input_bar_count=len(request.bars),
        points=tuple(points),
    )


__all__ = (
    "AnchoredVWAPPathRequest",
    "AnchoredVWAPPathSnapshot",
    "AnchoredVWAPPoint",
    "compute_anchored_vwap_path",
)
