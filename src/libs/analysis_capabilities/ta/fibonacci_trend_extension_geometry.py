"""Explicit three-point trend-based Fibonacci extension geometry."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from numbers import Real
from typing import Literal

from .swing_anchors import SwingAnchor

FibonacciTrendExtensionDirection = Literal["up", "down"]


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


def _validate_anchors(
    start_anchor: SwingAnchor,
    impulse_end_anchor: SwingAnchor,
    retracement_anchor: SwingAnchor,
    market_as_of: datetime,
) -> None:
    for field_name, anchor in (
        ("start_anchor", start_anchor),
        ("impulse_end_anchor", impulse_end_anchor),
        ("retracement_anchor", retracement_anchor),
    ):
        if not isinstance(anchor, SwingAnchor):
            raise TypeError(f"{field_name} must be SwingAnchor")
        if anchor.available_at > market_as_of:
            raise ValueError(f"{field_name} is not available at market_as_of")
    if not (
        start_anchor.formed_at
        < impulse_end_anchor.formed_at
        < retracement_anchor.formed_at
    ):
        raise ValueError("three anchors must be strictly ordered in time")
    if start_anchor.kind == impulse_end_anchor.kind:
        raise ValueError("start and impulse-end anchors must have opposite kinds")
    if impulse_end_anchor.kind == retracement_anchor.kind:
        raise ValueError("impulse-end and retracement anchors must have opposite kinds")
    if start_anchor.kind != retracement_anchor.kind:
        raise ValueError("start and retracement anchors must have the same kind")
    if (
        start_anchor.kind == "swing_low"
        and impulse_end_anchor.price <= start_anchor.price
    ):
        raise ValueError(
            "up impulse requires impulse_end_anchor.price > start_anchor.price"
        )
    if (
        start_anchor.kind == "swing_high"
        and impulse_end_anchor.price >= start_anchor.price
    ):
        raise ValueError(
            "down impulse requires impulse_end_anchor.price < start_anchor.price"
        )


def _validate_ratios(ratios: tuple[float, ...]) -> tuple[float, ...]:
    if not isinstance(ratios, tuple):
        raise TypeError("extension_ratios must be a tuple of ratios")
    normalized: list[float] = []
    previous: float | None = None
    for index, ratio in enumerate(ratios):
        value = _finite_real(ratio, field_name=f"extension_ratios[{index}]")
        if value <= 0.0:
            raise ValueError("extension ratios must be strictly positive")
        if previous is not None and value <= previous:
            raise ValueError("extension ratios must be strictly increasing")
        normalized.append(value)
        previous = value
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class FibonacciTrendExtensionLevel:
    """One explicit three-point extension level."""

    ratio: float
    price: float

    def __post_init__(self) -> None:
        ratio = _finite_real(self.ratio, field_name="ratio")
        if ratio <= 0.0:
            raise ValueError("ratio must be strictly positive")
        price = _finite_real(self.price, field_name="price")
        object.__setattr__(self, "ratio", ratio)
        object.__setattr__(self, "price", price)


@dataclass(frozen=True, slots=True)
class FibonacciTrendExtensionRequest:
    """Explicit A/B/C anchors and caller-selected extension ratios."""

    start_anchor: SwingAnchor
    impulse_end_anchor: SwingAnchor
    retracement_anchor: SwingAnchor
    market_as_of: datetime
    extension_ratios: tuple[float, ...]

    def __post_init__(self) -> None:
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        _validate_anchors(
            self.start_anchor,
            self.impulse_end_anchor,
            self.retracement_anchor,
            market_as_of,
        )
        ratios = _validate_ratios(self.extension_ratios)
        object.__setattr__(self, "market_as_of", market_as_of)
        object.__setattr__(self, "extension_ratios", ratios)


@dataclass(frozen=True, slots=True)
class FibonacciTrendExtensionSnapshot:
    """Immutable three-point extension geometry at one exact cutoff."""

    market_as_of: datetime
    start_anchor: SwingAnchor
    impulse_end_anchor: SwingAnchor
    retracement_anchor: SwingAnchor
    direction: FibonacciTrendExtensionDirection
    levels: tuple[FibonacciTrendExtensionLevel, ...]

    def __post_init__(self) -> None:
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        _validate_anchors(
            self.start_anchor,
            self.impulse_end_anchor,
            self.retracement_anchor,
            market_as_of,
        )
        expected_direction = "up" if self.start_anchor.kind == "swing_low" else "down"
        if self.direction != expected_direction:
            raise ValueError("direction does not match anchor topology")
        if not isinstance(self.levels, tuple):
            raise TypeError("levels must be a tuple of FibonacciTrendExtensionLevel")
        previous: float | None = None
        impulse = self.impulse_end_anchor.price - self.start_anchor.price
        for index, level in enumerate(self.levels):
            if not isinstance(level, FibonacciTrendExtensionLevel):
                raise TypeError(f"levels[{index}] must be FibonacciTrendExtensionLevel")
            if previous is not None and level.ratio <= previous:
                raise ValueError("levels must be strictly ordered by ratio")
            expected_price = self.retracement_anchor.price + impulse * level.ratio
            if level.price != expected_price:
                raise ValueError(f"levels[{index}] price is inconsistent with anchors")
            previous = level.ratio
        object.__setattr__(self, "market_as_of", market_as_of)

    @property
    def extension_levels(self) -> tuple[FibonacciTrendExtensionLevel, ...]:
        """Compatibility name for the explicit output levels."""

        return self.levels


def compute_fibonacci_trend_extension(
    request: FibonacciTrendExtensionRequest,
) -> FibonacciTrendExtensionSnapshot:
    """Compute C + (B - A) * ratio for every explicit ratio."""

    if not isinstance(request, FibonacciTrendExtensionRequest):
        raise TypeError("request must be FibonacciTrendExtensionRequest")
    impulse = request.impulse_end_anchor.price - request.start_anchor.price
    levels = tuple(
        FibonacciTrendExtensionLevel(
            ratio=ratio,
            price=request.retracement_anchor.price + impulse * ratio,
        )
        for ratio in request.extension_ratios
    )
    return FibonacciTrendExtensionSnapshot(
        market_as_of=request.market_as_of,
        start_anchor=request.start_anchor,
        impulse_end_anchor=request.impulse_end_anchor,
        retracement_anchor=request.retracement_anchor,
        direction=("up" if request.start_anchor.kind == "swing_low" else "down"),
        levels=levels,
    )


__all__ = (
    "FibonacciTrendExtensionLevel",
    "FibonacciTrendExtensionRequest",
    "FibonacciTrendExtensionSnapshot",
    "compute_fibonacci_trend_extension",
)
