"""Causal, confirmed swing-high and swing-low anchors."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from numbers import Real
from typing import Literal

SwingKind = Literal["swing_high", "swing_low"]


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


def _positive_finite(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{field_name} must be a real number")
    normalized = float(value)
    if not isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    if normalized <= 0.0:
        raise ValueError(f"{field_name} must be strictly positive")
    return normalized


@dataclass(frozen=True, slots=True)
class SwingAnchorBar:
    """One already-closed OHLC extremum input."""

    closed_at: datetime
    high: float
    low: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "closed_at", _utc(self.closed_at, field_name="closed_at")
        )
        high = _positive_finite(self.high, field_name="high")
        low = _positive_finite(self.low, field_name="low")
        if low > high:
            raise ValueError("low must be <= high")
        object.__setattr__(self, "high", high)
        object.__setattr__(self, "low", low)


@dataclass(frozen=True, slots=True)
class SwingAnchor:
    """One strictly confirmed factual swing extremum."""

    kind: SwingKind
    formed_at: datetime
    available_at: datetime
    price: float

    def __post_init__(self) -> None:
        if self.kind not in ("swing_high", "swing_low"):
            raise ValueError("kind must be 'swing_high' or 'swing_low'")
        formed_at = _utc(self.formed_at, field_name="formed_at")
        available_at = _utc(self.available_at, field_name="available_at")
        if available_at <= formed_at:
            raise ValueError("available_at must be later than formed_at")
        object.__setattr__(self, "formed_at", formed_at)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(
            self, "price", _positive_finite(self.price, field_name="price")
        )


@dataclass(frozen=True, slots=True)
class SwingAnchorRequest:
    """Explicit closed-bar history and caller-selected confirmation span."""

    bars: tuple[SwingAnchorBar, ...]
    span: int

    def __post_init__(self) -> None:
        if not isinstance(self.bars, tuple):
            raise TypeError("bars must be a tuple of SwingAnchorBar values")
        if not self.bars:
            raise ValueError("bars must contain at least one SwingAnchorBar")
        previous: datetime | None = None
        for index, bar in enumerate(self.bars):
            if not isinstance(bar, SwingAnchorBar):
                raise TypeError(f"bars[{index}] must be SwingAnchorBar")
            if previous is not None and bar.closed_at <= previous:
                raise ValueError("bars.closed_at values must be strictly increasing")
            previous = bar.closed_at
        if isinstance(self.span, bool) or not isinstance(self.span, int):
            raise TypeError("span must be an integer")
        if self.span < 1:
            raise ValueError("span must be at least 1")


@dataclass(frozen=True, slots=True)
class SwingAnchorSnapshot:
    """Immutable factual anchor output at one closed-bar cutoff."""

    span: int
    market_as_of: datetime
    anchors: tuple[SwingAnchor, ...]

    def __post_init__(self) -> None:
        if isinstance(self.span, bool) or not isinstance(self.span, int):
            raise TypeError("span must be an integer")
        if self.span < 1:
            raise ValueError("span must be at least 1")
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        object.__setattr__(self, "market_as_of", market_as_of)
        if not isinstance(self.anchors, tuple):
            raise TypeError("anchors must be a tuple of SwingAnchor values")
        for index, anchor in enumerate(self.anchors):
            if not isinstance(anchor, SwingAnchor):
                raise TypeError(f"anchors[{index}] must be SwingAnchor")
            if anchor.available_at > market_as_of:
                raise ValueError("anchor is not available at market_as_of")
        if len(set(self.anchors)) != len(self.anchors):
            raise ValueError("anchors must not contain duplicate values")
        expected_order = tuple(
            sorted(
                self.anchors,
                key=lambda anchor: (
                    anchor.available_at,
                    anchor.formed_at,
                    anchor.kind,
                ),
            )
        )
        if self.anchors != expected_order:
            raise ValueError("anchors must be deterministically ordered")


def compute_swing_anchors(
    request: SwingAnchorRequest,
) -> SwingAnchorSnapshot:
    """Compute strict confirmed extrema without looking ahead of the cutoff."""

    if not isinstance(request, SwingAnchorRequest):
        raise TypeError("request must be SwingAnchorRequest")

    bars = request.bars
    span = request.span
    market_as_of = bars[-1].closed_at
    anchors: list[SwingAnchor] = []

    for center_index in range(span, len(bars) - span):
        center = bars[center_index]
        window = bars[center_index - span : center_index + span + 1]
        confirmation_bar = bars[center_index + span]
        others = window[:span] + window[span + 1 :]

        if all(center.high > other.high for other in others):
            anchors.append(
                SwingAnchor(
                    kind="swing_high",
                    formed_at=center.closed_at,
                    available_at=confirmation_bar.closed_at,
                    price=center.high,
                )
            )
        if all(center.low < other.low for other in others):
            anchors.append(
                SwingAnchor(
                    kind="swing_low",
                    formed_at=center.closed_at,
                    available_at=confirmation_bar.closed_at,
                    price=center.low,
                )
            )

    anchors.sort(
        key=lambda anchor: (anchor.available_at, anchor.formed_at, anchor.kind)
    )
    return SwingAnchorSnapshot(
        span=span,
        market_as_of=market_as_of,
        anchors=tuple(anchors),
    )


__all__ = (
    "SwingAnchor",
    "SwingAnchorBar",
    "SwingAnchorRequest",
    "SwingAnchorSnapshot",
    "compute_swing_anchors",
)
