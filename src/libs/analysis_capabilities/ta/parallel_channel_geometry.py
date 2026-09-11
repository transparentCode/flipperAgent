"""Explicit three-anchor, bar-index parallel channel geometry."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from numbers import Real
from typing import Literal

from .swing_anchors import SwingAnchor

ChannelBaselineKind = Literal["swing_low", "swing_high"]


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


@dataclass(frozen=True, slots=True)
class ParallelChannelBar:
    """One closed-bar timestamp used to resolve bar ordinals."""

    closed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "closed_at", _utc(self.closed_at, field_name="closed_at")
        )


def _validate_anchor_topology(
    start_anchor: SwingAnchor,
    end_anchor: SwingAnchor,
    offset_anchor: SwingAnchor,
    market_as_of: datetime,
) -> None:
    for field_name, anchor in (
        ("start_anchor", start_anchor),
        ("end_anchor", end_anchor),
        ("offset_anchor", offset_anchor),
    ):
        if not isinstance(anchor, SwingAnchor):
            raise TypeError(f"{field_name} must be SwingAnchor")
        if anchor.available_at > market_as_of:
            raise ValueError(f"{field_name} is not available at market_as_of")
    if start_anchor.formed_at >= end_anchor.formed_at:
        raise ValueError("start_anchor must be formed before end_anchor")
    if start_anchor.kind != end_anchor.kind:
        raise ValueError("start_anchor and end_anchor must have the same kind")
    if offset_anchor.kind == start_anchor.kind:
        raise ValueError("offset_anchor must have the opposite kind")


@dataclass(frozen=True, slots=True)
class ParallelChannelGeometryRequest:
    """Three explicit causal anchors over an ordered closed-bar timeline."""

    bars: tuple[ParallelChannelBar, ...]
    start_anchor: SwingAnchor
    end_anchor: SwingAnchor
    offset_anchor: SwingAnchor
    market_as_of: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.bars, tuple):
            raise TypeError("bars must be a tuple of ParallelChannelBar values")
        if not self.bars:
            raise ValueError("bars must contain at least one ParallelChannelBar")
        previous: datetime | None = None
        timestamps: set[datetime] = set()
        for index, bar in enumerate(self.bars):
            if not isinstance(bar, ParallelChannelBar):
                raise TypeError(f"bars[{index}] must be ParallelChannelBar")
            if previous is not None and bar.closed_at <= previous:
                raise ValueError("bars.closed_at values must be strictly increasing")
            timestamps.add(bar.closed_at)
            previous = bar.closed_at
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        if self.bars[-1].closed_at != market_as_of:
            raise ValueError("final bar must close exactly at market_as_of")
        _validate_anchor_topology(
            self.start_anchor,
            self.end_anchor,
            self.offset_anchor,
            market_as_of,
        )
        for field_name, anchor in (
            ("start_anchor", self.start_anchor),
            ("end_anchor", self.end_anchor),
            ("offset_anchor", self.offset_anchor),
        ):
            if anchor.formed_at not in timestamps:
                raise ValueError(f"{field_name} timestamp is absent from bars")
        object.__setattr__(self, "market_as_of", market_as_of)


@dataclass(frozen=True, slots=True)
class ParallelChannelGeometrySnapshot:
    """Immutable three-anchor channel values at one exact cutoff."""

    market_as_of: datetime
    baseline_kind: ChannelBaselineKind
    start_anchor: SwingAnchor
    end_anchor: SwingAnchor
    offset_anchor: SwingAnchor
    slope_per_bar: float
    offset_price: float
    baseline_price_at_market_as_of: float
    parallel_price_at_market_as_of: float

    def __post_init__(self) -> None:
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        if self.baseline_kind not in ("swing_low", "swing_high"):
            raise ValueError("baseline_kind must be swing_low or swing_high")
        _validate_anchor_topology(
            self.start_anchor,
            self.end_anchor,
            self.offset_anchor,
            market_as_of,
        )
        if self.baseline_kind != self.start_anchor.kind:
            raise ValueError("baseline_kind must match the start anchor kind")
        slope = _finite_real(self.slope_per_bar, field_name="slope_per_bar")
        offset = _finite_real(self.offset_price, field_name="offset_price")
        baseline = _finite_real(
            self.baseline_price_at_market_as_of,
            field_name="baseline_price_at_market_as_of",
        )
        parallel = _finite_real(
            self.parallel_price_at_market_as_of,
            field_name="parallel_price_at_market_as_of",
        )
        if self.baseline_kind == "swing_low" and offset <= 0.0:
            raise ValueError("support channel offset must be positive")
        if self.baseline_kind == "swing_high" and offset >= 0.0:
            raise ValueError("resistance channel offset must be negative")
        if parallel != baseline + offset:
            raise ValueError("parallel price is inconsistent with baseline and offset")
        object.__setattr__(self, "market_as_of", market_as_of)
        object.__setattr__(self, "slope_per_bar", slope)
        object.__setattr__(self, "offset_price", offset)
        object.__setattr__(self, "baseline_price_at_market_as_of", baseline)
        object.__setattr__(self, "parallel_price_at_market_as_of", parallel)


def compute_parallel_channel_geometry(
    request: ParallelChannelGeometryRequest,
) -> ParallelChannelGeometrySnapshot:
    """Compute a parallel channel using only explicit bar-index geometry."""

    if not isinstance(request, ParallelChannelGeometryRequest):
        raise TypeError("request must be ParallelChannelGeometryRequest")
    ordinal = {bar.closed_at: index for index, bar in enumerate(request.bars)}
    start_index = ordinal[request.start_anchor.formed_at]
    end_index = ordinal[request.end_anchor.formed_at]
    offset_index = ordinal[request.offset_anchor.formed_at]
    market_index = ordinal[request.market_as_of]
    slope = (request.end_anchor.price - request.start_anchor.price) / (
        end_index - start_index
    )
    baseline_at_offset = request.start_anchor.price + slope * (
        offset_index - start_index
    )
    offset = request.offset_anchor.price - baseline_at_offset
    if request.start_anchor.kind == "swing_low" and offset <= 0.0:
        raise ValueError("support channel offset must be positive")
    if request.start_anchor.kind == "swing_high" and offset >= 0.0:
        raise ValueError("resistance channel offset must be negative")
    baseline_at_market = request.start_anchor.price + slope * (
        market_index - start_index
    )
    return ParallelChannelGeometrySnapshot(
        market_as_of=request.market_as_of,
        baseline_kind=request.start_anchor.kind,
        start_anchor=request.start_anchor,
        end_anchor=request.end_anchor,
        offset_anchor=request.offset_anchor,
        slope_per_bar=slope,
        offset_price=offset,
        baseline_price_at_market_as_of=baseline_at_market,
        parallel_price_at_market_as_of=baseline_at_market + offset,
    )


__all__ = (
    "ParallelChannelBar",
    "ParallelChannelGeometryRequest",
    "ParallelChannelGeometrySnapshot",
    "compute_parallel_channel_geometry",
)
