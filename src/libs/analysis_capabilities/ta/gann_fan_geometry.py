"""Explicit bar-coordinate Gann fan geometry."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import gcd, isfinite
from numbers import Real
from typing import Literal

from .parallel_channel_geometry import ParallelChannelBar
from .swing_anchors import SwingAnchor

GannFanDirection = Literal["up", "down"]


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


def _positive_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value <= 0:
        raise ValueError(f"{field_name} must be strictly positive")
    return value


@dataclass(frozen=True, slots=True)
class GannAngleRatio:
    """One reduced price-units per time-units Gann ratio."""

    price_units: int
    time_units: int

    def __post_init__(self) -> None:
        price_units = _positive_int(self.price_units, field_name="price_units")
        time_units = _positive_int(self.time_units, field_name="time_units")
        if gcd(price_units, time_units) != 1:
            raise ValueError("Gann angle ratio must be in lowest terms")
        object.__setattr__(self, "price_units", price_units)
        object.__setattr__(self, "time_units", time_units)


def _validate_ratios(value: object) -> tuple[GannAngleRatio, ...]:
    if not isinstance(value, tuple):
        raise TypeError("angle_ratios must be a tuple of GannAngleRatio values")
    if not value:
        raise ValueError("angle_ratios must not be empty")
    ratios: list[GannAngleRatio] = []
    previous: GannAngleRatio | None = None
    seen: set[tuple[int, int]] = set()
    for index, ratio in enumerate(value):
        if not isinstance(ratio, GannAngleRatio):
            raise TypeError(f"angle_ratios[{index}] must be GannAngleRatio")
        key = (ratio.price_units, ratio.time_units)
        if key in seen:
            raise ValueError("angle_ratios must not contain duplicate ratios")
        if previous is not None and not (
            previous.price_units * ratio.time_units
            < ratio.price_units * previous.time_units
        ):
            raise ValueError("angle_ratios must be strictly increasing")
        seen.add(key)
        ratios.append(ratio)
        previous = ratio
    return tuple(ratios)


def _validate_bars(
    bars: object, market_as_of: datetime
) -> tuple[ParallelChannelBar, ...]:
    if not isinstance(bars, tuple):
        raise TypeError("bars must be a tuple of ParallelChannelBar values")
    if not bars:
        raise ValueError("bars must contain at least one ParallelChannelBar")
    previous: datetime | None = None
    for index, bar in enumerate(bars):
        if not isinstance(bar, ParallelChannelBar):
            raise TypeError(f"bars[{index}] must be ParallelChannelBar")
        if previous is not None and bar.closed_at <= previous:
            raise ValueError("bars.closed_at values must be strictly increasing")
        previous = bar.closed_at
    if bars[-1].closed_at != market_as_of:
        raise ValueError("final bar must close exactly at market_as_of")
    return bars


@dataclass(frozen=True, slots=True)
class GannFanGeometryRequest:
    """One explicit anchor, scale, ratio set, and closed-bar cutoff."""

    bars: tuple[ParallelChannelBar, ...]
    anchor: SwingAnchor
    price_per_bar: float
    angle_ratios: tuple[GannAngleRatio, ...]
    market_as_of: datetime

    def __post_init__(self) -> None:
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        bars = _validate_bars(self.bars, market_as_of)
        if not isinstance(self.anchor, SwingAnchor):
            raise TypeError("anchor must be SwingAnchor")
        if self.anchor.formed_at not in {bar.closed_at for bar in bars}:
            raise ValueError("anchor.formed_at must occur in bars")
        if self.anchor.available_at > market_as_of:
            raise ValueError("anchor is not available at market_as_of")
        price_per_bar = _finite_real(
            self.price_per_bar,
            field_name="price_per_bar",
        )
        if price_per_bar <= 0.0:
            raise ValueError("price_per_bar must be strictly positive")
        ratios = _validate_ratios(self.angle_ratios)
        object.__setattr__(self, "market_as_of", market_as_of)
        object.__setattr__(self, "price_per_bar", price_per_bar)
        object.__setattr__(self, "angle_ratios", ratios)


@dataclass(frozen=True, slots=True)
class GannFanRay:
    """One explicitly scaled Gann ray at the request cutoff."""

    ratio: GannAngleRatio
    slope_per_bar: float
    price_at_market_as_of: float

    def __post_init__(self) -> None:
        if not isinstance(self.ratio, GannAngleRatio):
            raise TypeError("ratio must be GannAngleRatio")
        object.__setattr__(
            self,
            "slope_per_bar",
            _finite_real(self.slope_per_bar, field_name="slope_per_bar"),
        )
        object.__setattr__(
            self,
            "price_at_market_as_of",
            _finite_real(
                self.price_at_market_as_of,
                field_name="price_at_market_as_of",
            ),
        )


@dataclass(frozen=True, slots=True)
class GannFanGeometrySnapshot:
    """Immutable Gann fan values at one exact closed-bar cutoff."""

    market_as_of: datetime
    anchor: SwingAnchor
    price_per_bar: float
    direction: GannFanDirection
    bar_span: int
    rays: tuple[GannFanRay, ...]

    def __post_init__(self) -> None:
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        if not isinstance(self.anchor, SwingAnchor):
            raise TypeError("anchor must be SwingAnchor")
        if self.anchor.available_at > market_as_of:
            raise ValueError("anchor is not available at market_as_of")
        price_per_bar = _finite_real(
            self.price_per_bar,
            field_name="price_per_bar",
        )
        if price_per_bar <= 0.0:
            raise ValueError("price_per_bar must be strictly positive")
        expected_direction = "up" if self.anchor.kind == "swing_low" else "down"
        if self.direction != expected_direction:
            raise ValueError("direction does not match anchor kind")
        if isinstance(self.bar_span, bool) or not isinstance(self.bar_span, int):
            raise TypeError("bar_span must be an integer")
        if self.bar_span <= 0:
            raise ValueError("bar_span must be strictly positive")
        if not isinstance(self.rays, tuple) or not self.rays:
            raise ValueError("rays must be a non-empty tuple")
        for index, ray in enumerate(self.rays):
            if not isinstance(ray, GannFanRay):
                raise TypeError(f"rays[{index}] must be GannFanRay")
        ratios = tuple(ray.ratio for ray in self.rays)
        _validate_ratios(ratios)
        sign = 1.0 if self.anchor.kind == "swing_low" else -1.0
        expected_slopes: dict[GannAngleRatio, float] = {}
        for ray in self.rays:
            expected_slope = (
                sign * price_per_bar * ray.ratio.price_units / ray.ratio.time_units
            )
            if ray.slope_per_bar != expected_slope:
                raise ValueError("ray slope is inconsistent with anchor and ratio")
            expected_slopes[ray.ratio] = expected_slope
        for ray in self.rays:
            expected_slope = expected_slopes[ray.ratio]
            expected_price = self.anchor.price + expected_slope * self.bar_span
            if ray.price_at_market_as_of != expected_price:
                raise ValueError("ray price is inconsistent with anchor and ratio")
        object.__setattr__(self, "market_as_of", market_as_of)
        object.__setattr__(self, "price_per_bar", price_per_bar)
        object.__setattr__(self, "bar_span", self.bar_span)


def compute_gann_fan_geometry(
    request: GannFanGeometryRequest,
) -> GannFanGeometrySnapshot:
    """Compute explicit Gann rays using only bar ordinals."""

    if not isinstance(request, GannFanGeometryRequest):
        raise TypeError("request must be GannFanGeometryRequest")
    ordinal = {bar.closed_at: index for index, bar in enumerate(request.bars)}
    anchor_index = ordinal[request.anchor.formed_at]
    market_index = ordinal[request.market_as_of]
    sign = 1.0 if request.anchor.kind == "swing_low" else -1.0
    span = market_index - anchor_index
    rays = tuple(
        GannFanRay(
            ratio=ratio,
            slope_per_bar=(
                sign * request.price_per_bar * ratio.price_units / ratio.time_units
            ),
            price_at_market_as_of=request.anchor.price
            + (sign * request.price_per_bar * ratio.price_units / ratio.time_units)
            * span,
        )
        for ratio in request.angle_ratios
    )
    return GannFanGeometrySnapshot(
        market_as_of=request.market_as_of,
        anchor=request.anchor,
        price_per_bar=request.price_per_bar,
        direction="up" if request.anchor.kind == "swing_low" else "down",
        bar_span=span,
        rays=rays,
    )


__all__ = (
    "GannAngleRatio",
    "GannFanDirection",
    "GannFanGeometryRequest",
    "GannFanGeometrySnapshot",
    "GannFanRay",
    "compute_gann_fan_geometry",
)
