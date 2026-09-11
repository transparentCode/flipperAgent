"""Private validation helpers for explicit-anchor pattern geometry."""

from datetime import UTC, datetime, timedelta
from math import isfinite
from numbers import Real

from .parallel_channel_geometry import ParallelChannelBar
from .swing_anchors import SwingAnchor


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


def _validate_anchor_sequence(
    anchors: tuple[SwingAnchor, ...], market_as_of: datetime
) -> str:
    previous: SwingAnchor | None = None
    for index, anchor in enumerate(anchors):
        if not isinstance(anchor, SwingAnchor):
            raise TypeError(f"anchor[{index}] must be SwingAnchor")
        if anchor.available_at > market_as_of:
            raise ValueError(f"anchor[{index}] is not available at market_as_of")
        if previous is not None:
            if anchor.formed_at <= previous.formed_at:
                raise ValueError("anchors must be strictly increasing by formed_at")
            if anchor.kind == previous.kind:
                raise ValueError("adjacent anchors must alternate swing kind")
            if previous.kind == "swing_low" and anchor.price <= previous.price:
                raise ValueError("low-to-high price movement must be strictly rising")
            if previous.kind == "swing_high" and anchor.price >= previous.price:
                raise ValueError("high-to-low price movement must be strictly falling")
        previous = anchor
    return "_".join(anchor.kind.removeprefix("swing_") for anchor in anchors)


def _validate_pattern_inputs(
    bars: object,
    anchors: tuple[SwingAnchor, ...],
    market_as_of: object,
) -> tuple[tuple[ParallelChannelBar, ...], datetime, tuple[int, ...], str]:
    market = _utc(market_as_of, field_name="market_as_of")
    normalized_bars = _validate_bars(bars, market)
    sequence_kind = _validate_anchor_sequence(anchors, market)
    ordinal = {bar.closed_at: index for index, bar in enumerate(normalized_bars)}
    indices: list[int] = []
    for index, anchor in enumerate(anchors):
        try:
            indices.append(ordinal[anchor.formed_at])
        except KeyError as exc:
            raise ValueError(f"anchor[{index}] timestamp is absent from bars") from exc
    return normalized_bars, market, tuple(indices), sequence_kind


def _validate_bar_indices(
    indices: tuple[object, ...], *, field_name: str = "bar_indices"
) -> tuple[int, ...]:
    normalized: list[int] = []
    previous: int | None = None
    for index, value in enumerate(indices):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{field_name}[{index}] must be an integer")
        if value < 0:
            raise ValueError(f"{field_name}[{index}] must be non-negative")
        if previous is not None and value <= previous:
            raise ValueError(f"{field_name} must be strictly increasing")
        normalized.append(value)
        previous = value
    return tuple(normalized)


__all__ = ()
