"""Explicit-range HLC3 volume-weighted average price geometry."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from numbers import Real


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
class VWAPBar:
    """One closed H/L/C/volume bar in a caller-selected range."""

    closed_at: datetime
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "closed_at",
            _utc(self.closed_at, field_name="closed_at"),
        )
        high = _positive_price(self.high, field_name="high")
        low = _positive_price(self.low, field_name="low")
        close = _positive_price(self.close, field_name="close")
        if low > high:
            raise ValueError("low must be <= high")
        if not low <= close <= high:
            raise ValueError("close must be between low and high")
        volume = _finite_real(self.volume, field_name="volume")
        if volume < 0.0:
            raise ValueError("volume must be nonnegative")
        object.__setattr__(self, "high", high)
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "close", close)
        object.__setattr__(self, "volume", volume)


@dataclass(frozen=True, slots=True)
class VWAPGeometryRequest:
    """Explicit ordered completed bars and the exact current cutoff."""

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
class VWAPGeometrySnapshot:
    """Immutable factual VWAP accumulation at one exact cutoff."""

    market_as_of: datetime
    first_bar_closed_at: datetime
    bar_count: int
    total_volume: float
    weighted_price_sum: float
    vwap_price: float

    def __post_init__(self) -> None:
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        first_bar_closed_at = _utc(
            self.first_bar_closed_at,
            field_name="first_bar_closed_at",
        )
        if first_bar_closed_at > market_as_of:
            raise ValueError("first_bar_closed_at must be <= market_as_of")
        if isinstance(self.bar_count, bool) or not isinstance(self.bar_count, int):
            raise TypeError("bar_count must be an integer")
        if self.bar_count < 1:
            raise ValueError("bar_count must be at least 1")
        total_volume = _finite_real(self.total_volume, field_name="total_volume")
        weighted_price_sum = _finite_real(
            self.weighted_price_sum,
            field_name="weighted_price_sum",
        )
        vwap_price = _positive_price(self.vwap_price, field_name="vwap_price")
        if total_volume <= 0.0:
            raise ValueError("total_volume must be strictly positive")
        if weighted_price_sum <= 0.0:
            raise ValueError("weighted_price_sum must be strictly positive")
        expected_vwap = weighted_price_sum / total_volume
        if not isfinite(expected_vwap) or vwap_price != expected_vwap:
            raise ValueError("vwap_price is inconsistent with accumulation")
        object.__setattr__(self, "market_as_of", market_as_of)
        object.__setattr__(self, "first_bar_closed_at", first_bar_closed_at)
        object.__setattr__(self, "total_volume", total_volume)
        object.__setattr__(self, "weighted_price_sum", weighted_price_sum)
        object.__setattr__(self, "vwap_price", vwap_price)


def compute_vwap_geometry(
    request: VWAPGeometryRequest,
) -> VWAPGeometrySnapshot:
    """Compute one explicit-range HLC3 volume-weighted average price."""

    if not isinstance(request, VWAPGeometryRequest):
        raise TypeError("request must be VWAPGeometryRequest")

    total_volume = 0.0
    weighted_price_sum = 0.0
    for bar in request.bars:
        total_volume += bar.volume
        if bar.volume == 0.0:
            continue
        typical_price = (
            bar.low + (bar.high - bar.low) / 3.0 + (bar.close - bar.low) / 3.0
        )
        weighted_price_sum += typical_price * bar.volume

    if not isfinite(total_volume) or not isfinite(weighted_price_sum):
        raise ValueError("VWAP accumulation must remain finite")
    if total_volume <= 0.0:
        raise ValueError("VWAP accumulation must have positive volume")
    vwap_price = weighted_price_sum / total_volume
    if not isfinite(vwap_price):
        raise ValueError("VWAP price must remain finite")

    return VWAPGeometrySnapshot(
        market_as_of=request.market_as_of,
        first_bar_closed_at=request.bars[0].closed_at,
        bar_count=len(request.bars),
        total_volume=total_volume,
        weighted_price_sum=weighted_price_sum,
        vwap_price=vwap_price,
    )


__all__ = (
    "VWAPBar",
    "VWAPGeometryRequest",
    "VWAPGeometrySnapshot",
    "compute_vwap_geometry",
)
