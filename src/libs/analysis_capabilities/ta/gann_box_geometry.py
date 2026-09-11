"""Explicit bar-coordinate Gann box price/time grid geometry."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import isfinite
from numbers import Real

from .parallel_channel_geometry import ParallelChannelBar


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


def _validate_levels(value: object, *, field_name: str) -> tuple[float, ...]:
    if not isinstance(value, tuple):
        raise TypeError(f"{field_name} must be a tuple of fractions")
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    levels: list[float] = []
    previous: float | None = None
    for index, level in enumerate(value):
        normalized = _finite_real(level, field_name=f"{field_name}[{index}]")
        if not 0.0 <= normalized <= 1.0:
            raise ValueError(f"{field_name} values must be in [0, 1]")
        if previous is not None and normalized <= previous:
            raise ValueError(f"{field_name} must be strictly increasing")
        levels.append(normalized)
        previous = normalized
    if levels[0] != 0.0 or levels[-1] != 1.0:
        raise ValueError(f"{field_name} must include exact 0 and 1 endpoints")
    return tuple(levels)


@dataclass(frozen=True, slots=True)
class GannCoordinate:
    """One explicit price/time coordinate with causal availability."""

    formed_at: datetime
    available_at: datetime
    price: float

    def __post_init__(self) -> None:
        formed_at = _utc(self.formed_at, field_name="formed_at")
        available_at = _utc(self.available_at, field_name="available_at")
        if available_at < formed_at:
            raise ValueError("available_at must be at or after formed_at")
        object.__setattr__(self, "formed_at", formed_at)
        object.__setattr__(self, "available_at", available_at)
        object.__setattr__(
            self,
            "price",
            _positive_price(self.price, field_name="price"),
        )


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
class GannBoxGeometryRequest:
    """Two explicit coordinates and caller-selected partition fractions."""

    bars: tuple[ParallelChannelBar, ...]
    start: GannCoordinate
    end: GannCoordinate
    price_levels: tuple[float, ...]
    time_levels: tuple[float, ...]
    market_as_of: datetime

    def __post_init__(self) -> None:
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        bars = _validate_bars(self.bars, market_as_of)
        if not isinstance(self.start, GannCoordinate):
            raise TypeError("start must be GannCoordinate")
        if not isinstance(self.end, GannCoordinate):
            raise TypeError("end must be GannCoordinate")
        timestamps = {bar.closed_at for bar in bars}
        if self.start.formed_at not in timestamps:
            raise ValueError("start.formed_at must occur in bars")
        if self.end.formed_at not in timestamps:
            raise ValueError("end.formed_at must occur in bars")
        if self.start.formed_at >= self.end.formed_at:
            raise ValueError("start must be formed before end")
        if (
            self.start.available_at > market_as_of
            or self.end.available_at > market_as_of
        ):
            raise ValueError("coordinates must be available at market_as_of")
        if self.start.price == self.end.price:
            raise ValueError("start and end prices must differ")
        price_levels = _validate_levels(self.price_levels, field_name="price_levels")
        time_levels = _validate_levels(self.time_levels, field_name="time_levels")
        object.__setattr__(self, "market_as_of", market_as_of)
        object.__setattr__(self, "price_levels", price_levels)
        object.__setattr__(self, "time_levels", time_levels)


@dataclass(frozen=True, slots=True)
class GannBoxPriceLevel:
    """One price partition at an explicit fraction."""

    fraction: float
    price: float

    def __post_init__(self) -> None:
        fraction = _finite_real(self.fraction, field_name="fraction")
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("fraction must be in [0, 1]")
        object.__setattr__(self, "fraction", fraction)
        object.__setattr__(
            self, "price", _positive_price(self.price, field_name="price")
        )


@dataclass(frozen=True, slots=True)
class GannBoxTimeLevel:
    """One time partition in bar-ordinal coordinates."""

    fraction: float
    bar_position: float
    bar_offset_from_start: float

    def __post_init__(self) -> None:
        fraction = _finite_real(self.fraction, field_name="fraction")
        if not 0.0 <= fraction <= 1.0:
            raise ValueError("fraction must be in [0, 1]")
        object.__setattr__(self, "fraction", fraction)
        object.__setattr__(
            self,
            "bar_position",
            _finite_real(self.bar_position, field_name="bar_position"),
        )
        object.__setattr__(
            self,
            "bar_offset_from_start",
            _finite_real(
                self.bar_offset_from_start,
                field_name="bar_offset_from_start",
            ),
        )


@dataclass(frozen=True, slots=True)
class GannBoxGeometrySnapshot:
    """Immutable Gann box price/time grid at one closed-bar cutoff."""

    market_as_of: datetime
    start: GannCoordinate
    end: GannCoordinate
    start_bar_index: int
    end_bar_index: int
    price_levels: tuple[GannBoxPriceLevel, ...]
    time_levels: tuple[GannBoxTimeLevel, ...]

    def __post_init__(self) -> None:
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        if not isinstance(self.start, GannCoordinate):
            raise TypeError("start must be GannCoordinate")
        if not isinstance(self.end, GannCoordinate):
            raise TypeError("end must be GannCoordinate")
        if self.start.formed_at >= self.end.formed_at:
            raise ValueError("start must be formed before end")
        if (
            self.start.available_at > market_as_of
            or self.end.available_at > market_as_of
        ):
            raise ValueError("coordinates must be available at market_as_of")
        for field_name, value in (
            ("start_bar_index", self.start_bar_index),
            ("end_bar_index", self.end_bar_index),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.start_bar_index >= self.end_bar_index:
            raise ValueError("start_bar_index must be before end_bar_index")
        if self.start.price == self.end.price:
            raise ValueError("start and end prices must differ")
        if not isinstance(self.price_levels, tuple) or not self.price_levels:
            raise ValueError("price_levels must be non-empty")
        if not isinstance(self.time_levels, tuple) or not self.time_levels:
            raise ValueError("time_levels must be non-empty")
        if any(not isinstance(level, GannBoxPriceLevel) for level in self.price_levels):
            raise TypeError("price_levels must contain GannBoxPriceLevel values")
        if any(not isinstance(level, GannBoxTimeLevel) for level in self.time_levels):
            raise TypeError("time_levels must contain GannBoxTimeLevel values")
        price_fractions = tuple(level.fraction for level in self.price_levels)
        time_fractions = tuple(level.fraction for level in self.time_levels)
        _validate_levels(price_fractions, field_name="price_levels")
        _validate_levels(time_fractions, field_name="time_levels")
        price_delta = self.end.price - self.start.price
        bar_span = self.end_bar_index - self.start_bar_index
        for level in self.price_levels:
            expected = self.start.price + price_delta * level.fraction
            if level.price != expected:
                raise ValueError("price level is inconsistent with box coordinates")
        for level in self.time_levels:
            expected_offset = bar_span * level.fraction
            expected_position = self.start_bar_index + expected_offset
            if level.bar_offset_from_start != expected_offset:
                raise ValueError("time level offset is inconsistent with box span")
            if level.bar_position != expected_position:
                raise ValueError("time level position is inconsistent with box span")
        object.__setattr__(self, "market_as_of", market_as_of)


def compute_gann_box_geometry(
    request: GannBoxGeometryRequest,
) -> GannBoxGeometrySnapshot:
    """Compute explicit price fractions and ordinal time fractions."""

    if not isinstance(request, GannBoxGeometryRequest):
        raise TypeError("request must be GannBoxGeometryRequest")
    ordinal = {bar.closed_at: index for index, bar in enumerate(request.bars)}
    start_index = ordinal[request.start.formed_at]
    end_index = ordinal[request.end.formed_at]
    price_delta = request.end.price - request.start.price
    span = end_index - start_index
    price_levels = tuple(
        GannBoxPriceLevel(
            fraction=fraction,
            price=request.start.price + price_delta * fraction,
        )
        for fraction in request.price_levels
    )
    time_levels = tuple(
        GannBoxTimeLevel(
            fraction=fraction,
            bar_position=start_index + span * fraction,
            bar_offset_from_start=span * fraction,
        )
        for fraction in request.time_levels
    )
    return GannBoxGeometrySnapshot(
        market_as_of=request.market_as_of,
        start=request.start,
        end=request.end,
        start_bar_index=start_index,
        end_bar_index=end_index,
        price_levels=price_levels,
        time_levels=time_levels,
    )


__all__ = (
    "GannBoxGeometryRequest",
    "GannBoxGeometrySnapshot",
    "GannBoxPriceLevel",
    "GannBoxTimeLevel",
    "GannCoordinate",
    "compute_gann_box_geometry",
)
