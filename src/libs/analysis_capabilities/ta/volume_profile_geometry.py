"""Explicit-range uniform-overlap volume-profile geometry."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import fsum, isfinite, ulp
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
class VolumeProfileBar:
    """One closed OHLCV bar supplied by the caller."""

    closed_at: datetime
    open: float
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
        open_price = _positive_price(self.open, field_name="open")
        high = _positive_price(self.high, field_name="high")
        low = _positive_price(self.low, field_name="low")
        close = _positive_price(self.close, field_name="close")
        if low > high:
            raise ValueError("low must be <= high")
        if not low <= open_price <= high:
            raise ValueError("open must lie within low/high")
        if not low <= close <= high:
            raise ValueError("close must lie within low/high")
        volume = _finite_real(self.volume, field_name="volume")
        if volume < 0.0:
            raise ValueError("volume must be non-negative")
        object.__setattr__(self, "open", open_price)
        object.__setattr__(self, "high", high)
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "close", close)
        object.__setattr__(self, "volume", volume)


@dataclass(frozen=True, slots=True)
class VolumeProfileGeometryRequest:
    """Explicit bars, row count, and value-area fraction."""

    bars: tuple[VolumeProfileBar, ...]
    market_as_of: datetime
    row_count: int
    value_area_fraction: float

    def __post_init__(self) -> None:
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        if not isinstance(self.bars, tuple):
            raise TypeError("bars must be a tuple of VolumeProfileBar values")
        if not self.bars:
            raise ValueError("bars must not be empty")
        previous: datetime | None = None
        for index, bar in enumerate(self.bars):
            if not isinstance(bar, VolumeProfileBar):
                raise TypeError(f"bars[{index}] must be VolumeProfileBar")
            if previous is not None and bar.closed_at <= previous:
                raise ValueError("bars.closed_at values must be strictly increasing")
            previous = bar.closed_at
        if self.bars[-1].closed_at != market_as_of:
            raise ValueError("final bar must close exactly at market_as_of")
        if not any(bar.volume > 0.0 for bar in self.bars):
            raise ValueError("at least one bar must have positive volume")
        if max(bar.high for bar in self.bars) <= min(bar.low for bar in self.bars):
            raise ValueError("profile price range must be positive")
        if isinstance(self.row_count, bool) or not isinstance(self.row_count, int):
            raise TypeError("row_count must be an integer")
        if self.row_count < 1:
            raise ValueError("row_count must be at least 1")
        fraction = _finite_real(
            self.value_area_fraction,
            field_name="value_area_fraction",
        )
        if not 0.0 < fraction <= 1.0:
            raise ValueError("value_area_fraction must be in (0, 1]")
        object.__setattr__(self, "market_as_of", market_as_of)
        object.__setattr__(self, "value_area_fraction", fraction)


@dataclass(frozen=True, slots=True)
class VolumeProfileRow:
    """One ordered volume-profile price row."""

    index: int
    low: float
    high: float
    midpoint: float
    total_volume: float
    up_volume: float
    down_volume: float

    def __post_init__(self) -> None:
        if isinstance(self.index, bool) or not isinstance(self.index, int):
            raise TypeError("index must be an integer")
        if self.index < 0:
            raise ValueError("index must be non-negative")
        low = _positive_price(self.low, field_name="low")
        high = _positive_price(self.high, field_name="high")
        midpoint = _positive_price(self.midpoint, field_name="midpoint")
        if high <= low:
            raise ValueError("row high must be greater than low")
        if midpoint != low + (high - low) / 2:
            raise ValueError("midpoint must be the row midpoint")
        total = _finite_real(self.total_volume, field_name="total_volume")
        up = _finite_real(self.up_volume, field_name="up_volume")
        down = _finite_real(self.down_volume, field_name="down_volume")
        if total < 0.0 or up < 0.0 or down < 0.0:
            raise ValueError("row volumes must be non-negative")
        if total != up + down:
            raise ValueError("row total must equal up plus down volume")
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "high", high)
        object.__setattr__(self, "midpoint", midpoint)
        object.__setattr__(self, "total_volume", total)
        object.__setattr__(self, "up_volume", up)
        object.__setattr__(self, "down_volume", down)


def _validate_fraction(value: object, *, field_name: str) -> float:
    fraction = _finite_real(value, field_name=field_name)
    if not 0.0 < fraction <= 1.0:
        raise ValueError(f"{field_name} must be in (0, 1]")
    return fraction


def _aggregate_operation_budget(input_bar_count: int, row_count: int) -> int:
    """Bound request-side one-ULP errors from profile aggregate operations."""

    return input_bar_count + row_count + 2


def _snapshot_operation_budget(row_count: int) -> int:
    """Bound snapshot-side one-ULP errors from row aggregate operations."""

    return row_count + 2


@dataclass(frozen=True, slots=True)
class VolumeProfileGeometrySnapshot:
    """Immutable histogram, POC, and contiguous value-area summary."""

    market_as_of: datetime
    first_bar_closed_at: datetime
    input_bar_count: int
    row_count: int
    value_area_fraction: float
    profile_low: float
    profile_high: float
    total_volume: float
    total_up_volume: float
    total_down_volume: float
    rows: tuple[VolumeProfileRow, ...]
    poc_row_index: int
    poc_price: float
    value_area_row_indices: tuple[int, ...]
    value_area_low: float
    value_area_high: float

    def __post_init__(self) -> None:
        market_as_of = _utc(self.market_as_of, field_name="market_as_of")
        first_bar_closed_at = _utc(
            self.first_bar_closed_at,
            field_name="first_bar_closed_at",
        )
        if first_bar_closed_at > market_as_of:
            raise ValueError("first_bar_closed_at must not follow market_as_of")
        for field_name, value in (
            ("input_bar_count", self.input_bar_count),
            ("row_count", self.row_count),
            ("poc_row_index", self.poc_row_index),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{field_name} must be an integer")
        if self.input_bar_count < 1 or self.row_count < 1:
            raise ValueError("input_bar_count and row_count must be positive")
        if not 0 <= self.poc_row_index < self.row_count:
            raise ValueError("poc_row_index must identify a row")
        fraction = _validate_fraction(
            self.value_area_fraction,
            field_name="value_area_fraction",
        )
        profile_low = _positive_price(self.profile_low, field_name="profile_low")
        profile_high = _positive_price(self.profile_high, field_name="profile_high")
        if profile_high <= profile_low:
            raise ValueError("profile_high must exceed profile_low")
        total = _finite_real(self.total_volume, field_name="total_volume")
        total_up = _finite_real(self.total_up_volume, field_name="total_up_volume")
        total_down = _finite_real(
            self.total_down_volume,
            field_name="total_down_volume",
        )
        if total < 0.0 or total_up < 0.0 or total_down < 0.0:
            raise ValueError("profile volumes must be non-negative")
        if not isinstance(self.rows, tuple) or len(self.rows) != self.row_count:
            raise ValueError("rows must contain exactly row_count rows")
        width = (profile_high - profile_low) / self.row_count
        for index, row in enumerate(self.rows):
            if not isinstance(row, VolumeProfileRow):
                raise TypeError(f"rows[{index}] must be VolumeProfileRow")
            if row.index != index:
                raise ValueError("rows must be ordered by contiguous index")
            expected_low = profile_low + index * width
            expected_high = profile_low + (index + 1) * width
            expected_midpoint = expected_low + (expected_high - expected_low) / 2
            if row.low != expected_low or row.high != expected_high:
                raise ValueError("rows do not have exact contiguous boundaries")
            if row.midpoint != expected_midpoint:
                raise ValueError("row midpoint is inconsistent with boundaries")
        operation_budget = _snapshot_operation_budget(self.row_count)
        canonical_total = fsum(row.total_volume for row in self.rows)
        canonical_up = fsum(row.up_volume for row in self.rows)
        canonical_down = fsum(row.down_volume for row in self.rows)
        if not (
            _aggregate_equal(canonical_total, total, operation_budget)
            and _aggregate_equal(canonical_up, total_up, operation_budget)
            and _aggregate_equal(canonical_down, total_down, operation_budget)
        ):
            raise ValueError("profile totals do not equal row totals")
        if not _aggregate_equal(
            canonical_total,
            canonical_up + canonical_down,
            operation_budget,
        ):
            raise ValueError("profile total must equal up plus down volume")
        max_volume = max(row.total_volume for row in self.rows)
        expected_poc = next(
            index
            for index, row in enumerate(self.rows)
            if row.total_volume == max_volume
        )
        if self.poc_row_index != expected_poc:
            raise ValueError("poc_row_index is not the lowest-index maximum row")
        if self.poc_price != self.rows[self.poc_row_index].midpoint:
            raise ValueError("poc_price must equal the POC row midpoint")
        if (
            not isinstance(self.value_area_row_indices, tuple)
            or not self.value_area_row_indices
        ):
            raise ValueError("value_area_row_indices must be non-empty")
        if self.value_area_row_indices != tuple(
            range(self.value_area_row_indices[0], self.value_area_row_indices[-1] + 1)
        ):
            raise ValueError("value-area rows must be contiguous and ordered")
        if self.poc_row_index not in self.value_area_row_indices:
            raise ValueError("value area must contain the POC row")
        if any(
            index < 0 or index >= self.row_count
            for index in self.value_area_row_indices
        ):
            raise ValueError("value-area row index is out of range")
        expected_value_area = _value_area(
            self.rows,
            self.poc_row_index,
            fraction,
            canonical_total,
        )
        if self.value_area_row_indices != expected_value_area:
            raise ValueError("value-area rows are inconsistent with profile")
        value_area_low = _positive_price(
            self.value_area_low,
            field_name="value_area_low",
        )
        value_area_high = _positive_price(
            self.value_area_high,
            field_name="value_area_high",
        )
        if value_area_low != self.rows[self.value_area_row_indices[0]].low:
            raise ValueError("value_area_low does not match included rows")
        if value_area_high != self.rows[self.value_area_row_indices[-1]].high:
            raise ValueError("value_area_high does not match included rows")
        object.__setattr__(self, "market_as_of", market_as_of)
        object.__setattr__(self, "first_bar_closed_at", first_bar_closed_at)
        object.__setattr__(self, "value_area_fraction", fraction)
        object.__setattr__(self, "profile_low", profile_low)
        object.__setattr__(self, "profile_high", profile_high)
        object.__setattr__(self, "total_volume", canonical_total)
        object.__setattr__(self, "total_up_volume", canonical_up)
        object.__setattr__(self, "total_down_volume", canonical_down)
        object.__setattr__(self, "value_area_low", value_area_low)
        object.__setattr__(self, "value_area_high", value_area_high)


def _aggregate_equal(left: float, right: float, operation_budget: int) -> bool:
    """Accept only finite, operation-count-scaled floating round-off."""

    if (
        not isfinite(left)
        or not isfinite(right)
        or isinstance(operation_budget, bool)
        or not isinstance(operation_budget, int)
        or operation_budget < 1
    ):
        return False
    return left == right or abs(left - right) <= max(ulp(left), ulp(right)) * (
        operation_budget
    )


def _flat_row_index(
    price: float, profile_low: float, profile_high: float, width: float, row_count: int
) -> int:
    if price == profile_high:
        return row_count - 1
    index = int((price - profile_low) / width)
    return min(max(index, 0), row_count - 1)


def _bar_allocations(
    bar: VolumeProfileBar,
    row_lows: tuple[float, ...],
    row_highs: tuple[float, ...],
) -> tuple[tuple[int, float], ...]:
    if bar.volume == 0.0:
        return ()
    if bar.high == bar.low:
        width = row_highs[0] - row_lows[0]
        index = _flat_row_index(
            bar.high,
            row_lows[0],
            row_highs[-1],
            width,
            len(row_lows),
        )
        return ((index, bar.volume),)
    candidates: list[tuple[int, float]] = []
    for index, (row_low, row_high) in enumerate(zip(row_lows, row_highs)):
        overlap = max(0.0, min(bar.high, row_high) - max(bar.low, row_low))
        if overlap > 0.0:
            candidates.append((index, overlap))
    if not candidates:
        raise ValueError("bar has no overlapping profile row")
    allocations: list[tuple[int, float]] = []
    accumulated = 0.0
    span = bar.high - bar.low
    for position, (index, overlap) in enumerate(candidates):
        if position == len(candidates) - 1:
            amount = bar.volume - accumulated
        else:
            amount = bar.volume * overlap / span
            accumulated += amount
        if not isfinite(amount) or amount < 0.0:
            raise ValueError("bar allocation residual is invalid")
        allocations.append((index, amount))
    return tuple(allocations)


def _value_area(
    rows: tuple[VolumeProfileRow, ...],
    poc_index: int,
    fraction: float,
    total_volume: float,
) -> tuple[int, ...]:
    target = total_volume * fraction
    included = [poc_index]
    included_volume = rows[poc_index].total_volume
    if included_volume >= target:
        return tuple(included)
    lower = poc_index - 1
    upper = poc_index + 1
    while lower >= 0 or upper < len(rows):
        if lower < 0:
            chosen = upper
        elif upper >= len(rows):
            chosen = lower
        elif rows[upper].total_volume > rows[lower].total_volume:
            chosen = upper
        elif rows[lower].total_volume > rows[upper].total_volume:
            chosen = lower
        else:
            upper_distance = upper - poc_index
            lower_distance = poc_index - lower
            chosen = upper if upper_distance <= lower_distance else lower
        candidate_volume = rows[chosen].total_volume
        if candidate_volume > target - included_volume:
            break
        included.append(chosen)
        included_volume += candidate_volume
        if chosen == upper:
            upper += 1
        else:
            lower -= 1
    return tuple(sorted(included))


def compute_volume_profile_geometry(
    request: VolumeProfileGeometryRequest,
) -> VolumeProfileGeometrySnapshot:
    """Compute R4B's explicit uniform-overlap volume profile."""

    if not isinstance(request, VolumeProfileGeometryRequest):
        raise TypeError("request must be VolumeProfileGeometryRequest")
    profile_low = min(bar.low for bar in request.bars)
    profile_high = max(bar.high for bar in request.bars)
    width = (profile_high - profile_low) / request.row_count
    row_lows = tuple(profile_low + index * width for index in range(request.row_count))
    row_highs = tuple(
        profile_low + (index + 1) * width for index in range(request.row_count)
    )
    up_volumes = [0.0] * request.row_count
    down_volumes = [0.0] * request.row_count
    for bar in request.bars:
        for index, amount in _bar_allocations(bar, row_lows, row_highs):
            if bar.close >= bar.open:
                up_volumes[index] += amount
            else:
                down_volumes[index] += amount
    rows = tuple(
        VolumeProfileRow(
            index=index,
            low=row_lows[index],
            high=row_highs[index],
            midpoint=row_lows[index] + (row_highs[index] - row_lows[index]) / 2,
            total_volume=up_volumes[index] + down_volumes[index],
            up_volume=up_volumes[index],
            down_volume=down_volumes[index],
        )
        for index in range(request.row_count)
    )
    poc_row_index = next(
        index
        for index, row in enumerate(rows)
        if row.total_volume == max(candidate.total_volume for candidate in rows)
    )
    total_up = fsum(row.up_volume for row in rows)
    total_down = fsum(row.down_volume for row in rows)
    input_total_volume = fsum(bar.volume for bar in request.bars)
    row_total_volume = fsum(row.total_volume for row in rows)
    operation_budget = _aggregate_operation_budget(
        len(request.bars),
        request.row_count,
    )
    if not _aggregate_equal(
        input_total_volume,
        row_total_volume,
        operation_budget,
    ):
        raise ValueError("input volume does not equal row volume")
    if not _aggregate_equal(
        row_total_volume,
        total_up + total_down,
        operation_budget,
    ):
        raise ValueError("row volume does not equal up plus down volume")
    value_area_row_indices = _value_area(
        rows,
        poc_row_index,
        request.value_area_fraction,
        row_total_volume,
    )
    return VolumeProfileGeometrySnapshot(
        market_as_of=request.market_as_of,
        first_bar_closed_at=request.bars[0].closed_at,
        input_bar_count=len(request.bars),
        row_count=request.row_count,
        value_area_fraction=request.value_area_fraction,
        profile_low=profile_low,
        profile_high=profile_high,
        total_volume=row_total_volume,
        total_up_volume=total_up,
        total_down_volume=total_down,
        rows=rows,
        poc_row_index=poc_row_index,
        poc_price=rows[poc_row_index].midpoint,
        value_area_row_indices=value_area_row_indices,
        value_area_low=rows[value_area_row_indices[0]].low,
        value_area_high=rows[value_area_row_indices[-1]].high,
    )


__all__ = (
    "VolumeProfileBar",
    "VolumeProfileGeometryRequest",
    "VolumeProfileGeometrySnapshot",
    "VolumeProfileRow",
    "compute_volume_profile_geometry",
)
