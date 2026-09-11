"""Explicit-anchor two-point linear Fibonacci geometry."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from numbers import Real
from typing import Literal

from .swing_anchors import SwingAnchor

FibonacciKind = Literal["retracement", "extension"]
FibonacciDirection = Literal["up", "down"]


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


def _finite_ratio(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be a real number")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


def _finite_price(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be a real number")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


def _anchor_direction(
    start_anchor: SwingAnchor,
    end_anchor: SwingAnchor,
) -> FibonacciDirection:
    if not isinstance(start_anchor, SwingAnchor):
        raise TypeError("start_anchor must be SwingAnchor")
    if not isinstance(end_anchor, SwingAnchor):
        raise TypeError("end_anchor must be SwingAnchor")
    if start_anchor.formed_at >= end_anchor.formed_at:
        raise ValueError("start_anchor must be formed before end_anchor")
    if start_anchor.kind == "swing_low" and end_anchor.kind == "swing_high":
        if end_anchor.price <= start_anchor.price:
            raise ValueError("up leg requires end_anchor.price > start_anchor.price")
        return "up"
    if start_anchor.kind == "swing_high" and end_anchor.kind == "swing_low":
        if end_anchor.price >= start_anchor.price:
            raise ValueError("down leg requires end_anchor.price < start_anchor.price")
        return "down"
    raise ValueError("anchors must form a low-to-high or high-to-low leg")


def _validate_ratios(
    values: object,
    *,
    field_name: str,
    kind: FibonacciKind,
) -> tuple[float, ...]:
    if not isinstance(values, tuple):
        raise TypeError(f"{field_name} must be a tuple of ratios")
    normalized: list[float] = []
    previous: float | None = None
    for index, value in enumerate(values):
        ratio = _finite_ratio(value, field_name=f"{field_name}[{index}]")
        if previous is not None and ratio <= previous:
            raise ValueError(f"{field_name} must be strictly increasing")
        if kind == "retracement" and not 0.0 < ratio < 1.0:
            raise ValueError("retracement ratios must satisfy 0 < ratio < 1")
        if kind == "extension" and ratio <= 1.0:
            raise ValueError("extension ratios must satisfy ratio > 1")
        normalized.append(ratio)
        previous = ratio
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class FibonacciLevel:
    """One deterministic retracement or extension level."""

    kind: FibonacciKind
    ratio: float
    price: float

    def __post_init__(self) -> None:
        if self.kind not in ("retracement", "extension"):
            raise ValueError("kind must be 'retracement' or 'extension'")
        ratio = _finite_ratio(self.ratio, field_name="ratio")
        if self.kind == "retracement" and not 0.0 < ratio < 1.0:
            raise ValueError("retracement ratio must satisfy 0 < ratio < 1")
        if self.kind == "extension" and ratio <= 1.0:
            raise ValueError("extension ratio must satisfy ratio > 1")
        object.__setattr__(self, "ratio", ratio)
        object.__setattr__(
            self,
            "price",
            _finite_price(self.price, field_name="price"),
        )


@dataclass(frozen=True, slots=True)
class FibonacciGeometryRequest:
    """Explicit anchors, cutoff, and caller-selected Fibonacci ratios."""

    start_anchor: SwingAnchor
    end_anchor: SwingAnchor
    market_as_of: datetime
    retracement_ratios: tuple[float, ...]
    extension_ratios: tuple[float, ...]

    def __post_init__(self) -> None:
        _anchor_direction(self.start_anchor, self.end_anchor)
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        if self.start_anchor.available_at > market_as_of:
            raise ValueError("start_anchor is not available at market_as_of")
        if self.end_anchor.available_at > market_as_of:
            raise ValueError("end_anchor is not available at market_as_of")
        retracement_ratios = _validate_ratios(
            self.retracement_ratios,
            field_name="retracement_ratios",
            kind="retracement",
        )
        extension_ratios = _validate_ratios(
            self.extension_ratios,
            field_name="extension_ratios",
            kind="extension",
        )
        if not retracement_ratios and not extension_ratios:
            raise ValueError("at least one Fibonacci ratio is required")
        object.__setattr__(self, "market_as_of", market_as_of)
        object.__setattr__(self, "retracement_ratios", retracement_ratios)
        object.__setattr__(self, "extension_ratios", extension_ratios)


@dataclass(frozen=True, slots=True)
class FibonacciGeometrySnapshot:
    """Immutable explicit-anchor Fibonacci geometry at one cutoff."""

    market_as_of: datetime
    direction: FibonacciDirection
    start_anchor: SwingAnchor
    end_anchor: SwingAnchor
    retracements: tuple[FibonacciLevel, ...]
    extensions: tuple[FibonacciLevel, ...]

    def __post_init__(self) -> None:
        if self.direction not in ("up", "down"):
            raise ValueError("direction must be 'up' or 'down'")
        direction = _anchor_direction(self.start_anchor, self.end_anchor)
        if direction != self.direction:
            raise ValueError("direction does not match the anchor leg")
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        if self.start_anchor.available_at > market_as_of:
            raise ValueError("start_anchor is not available at market_as_of")
        if self.end_anchor.available_at > market_as_of:
            raise ValueError("end_anchor is not available at market_as_of")
        retracements = self._validate_levels(
            self.retracements,
            kind="retracement",
            field_name="retracements",
            direction=direction,
            start_price=self.start_anchor.price,
            end_price=self.end_anchor.price,
        )
        extensions = self._validate_levels(
            self.extensions,
            kind="extension",
            field_name="extensions",
            direction=direction,
            start_price=self.start_anchor.price,
            end_price=self.end_anchor.price,
        )
        if not retracements and not extensions:
            raise ValueError("at least one Fibonacci level is required")
        object.__setattr__(self, "market_as_of", market_as_of)
        object.__setattr__(self, "retracements", retracements)
        object.__setattr__(self, "extensions", extensions)

    @staticmethod
    def _validate_levels(
        values: object,
        *,
        kind: FibonacciKind,
        field_name: str,
        direction: FibonacciDirection,
        start_price: float,
        end_price: float,
    ) -> tuple[FibonacciLevel, ...]:
        if not isinstance(values, tuple):
            raise TypeError(f"{field_name} must be a tuple of FibonacciLevel values")
        normalized: list[FibonacciLevel] = []
        previous: float | None = None
        for index, level in enumerate(values):
            if not isinstance(level, FibonacciLevel):
                raise TypeError(f"{field_name}[{index}] must be FibonacciLevel")
            if level.kind != kind:
                raise ValueError(f"{field_name} contains the wrong level kind")
            if previous is not None and level.ratio <= previous:
                raise ValueError(f"{field_name} must be strictly increasing")
            expected_price = _level_price(
                direction,
                kind,
                start_price,
                end_price,
                level.ratio,
            )
            if level.price != expected_price:
                raise ValueError(f"{field_name}[{index}] price is inconsistent")
            _validate_level_representability(
                direction,
                kind,
                start_price,
                end_price,
                expected_price,
            )
            normalized.append(level)
            previous = level.ratio
        return tuple(normalized)


def _level_price(
    direction: FibonacciDirection,
    kind: FibonacciKind,
    start_price: float,
    end_price: float,
    ratio: float,
) -> float:
    if kind == "retracement":
        return _finite_price(
            end_price + ratio * (start_price - end_price),
            field_name="price",
        )
    return _finite_price(
        start_price + ratio * (end_price - start_price),
        field_name="price",
    )


def _validate_level_representability(
    direction: FibonacciDirection,
    kind: FibonacciKind,
    start_price: float,
    end_price: float,
    price: float,
) -> None:
    if direction == "up":
        valid = (
            start_price < price < end_price
            if kind == "retracement"
            else price > end_price
        )
    else:
        valid = (
            end_price < price < start_price
            if kind == "retracement"
            else price < end_price
        )
    if not valid:
        raise ValueError(
            "requested Fibonacci level is not representable at current float precision"
        )


def compute_fibonacci_geometry(
    request: FibonacciGeometryRequest,
) -> FibonacciGeometrySnapshot:
    """Compute explicit-anchor Fibonacci levels without selecting anchors."""

    if not isinstance(request, FibonacciGeometryRequest):
        raise TypeError("request must be FibonacciGeometryRequest")

    start_price = request.start_anchor.price
    end_price = request.end_anchor.price
    direction = _anchor_direction(request.start_anchor, request.end_anchor)
    retracements = tuple(
        FibonacciLevel(
            kind="retracement",
            ratio=ratio,
            price=_level_price(
                direction,
                "retracement",
                start_price,
                end_price,
                ratio,
            ),
        )
        for ratio in request.retracement_ratios
    )
    extensions = tuple(
        FibonacciLevel(
            kind="extension",
            ratio=ratio,
            price=_level_price(
                direction,
                "extension",
                start_price,
                end_price,
                ratio,
            ),
        )
        for ratio in request.extension_ratios
    )
    for level in retracements + extensions:
        _validate_level_representability(
            direction,
            level.kind,
            start_price,
            end_price,
            level.price,
        )
    return FibonacciGeometrySnapshot(
        market_as_of=request.market_as_of,
        direction=direction,
        start_anchor=request.start_anchor,
        end_anchor=request.end_anchor,
        retracements=retracements,
        extensions=extensions,
    )


__all__ = (
    "FibonacciGeometryRequest",
    "FibonacciGeometrySnapshot",
    "FibonacciLevel",
    "compute_fibonacci_geometry",
)
