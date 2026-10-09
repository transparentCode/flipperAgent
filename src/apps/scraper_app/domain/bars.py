"""Bars and the validation gate. Pure functions: no I/O, no clock."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from apps.scraper_app.domain import errors
from apps.scraper_app.domain.datasets import DatasetSpec, Shape
from apps.scraper_app.domain.errors import ScraperError


@dataclass(frozen=True, slots=True)
class RawBar:
    """One bar as received: integer UTC seconds plus ``o, h, l, c[, v]``."""

    time: int
    fields: tuple[Decimal, ...]


@dataclass(frozen=True, slots=True)
class GateResult:
    """Accepted bars plus the number of missing intervals inside their range."""

    bars: list[Bar]
    holes: int


@dataclass(frozen=True, slots=True)
class Bar:
    """A bar that passed the gate."""

    bar_open: datetime
    bar_close: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    content_hash: str


def canonical_decimal(value: Decimal) -> str:
    """Plain, exponent-free text with no trailing zeros (``-0`` becomes ``0``)."""
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def content_hash(
    open_: Decimal,
    high: Decimal,
    low: Decimal,
    close: Decimal,
    volume: Decimal | None,
) -> str:
    """SHA-256 over the canonical decimal strings of the values."""
    parts = [canonical_decimal(v) for v in (open_, high, low, close)]
    parts.append("-" if volume is None else canonical_decimal(volume))
    return hashlib.sha256(",".join(parts).encode("ascii")).hexdigest()


def epoch_to_utc(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, tz=UTC)


def expected_latest_closed_bar_open(
    provider_time: datetime, interval_seconds: int
) -> datetime:
    """Open time of the newest bar that is closed at ``provider_time``."""
    now = int(provider_time.timestamp())
    return epoch_to_utc(now - now % interval_seconds - interval_seconds)


def _check_domain(spec: DatasetSpec, raw: RawBar) -> None:
    values = raw.fields
    if not all(v.is_finite() for v in values):
        raise ScraperError(errors.DOMAIN_VIOLATION, f"non-finite value at {raw.time}")
    open_, high, low, close = values[:4]
    if low > min(open_, close) or high < max(open_, close):
        raise ScraperError(
            errors.DOMAIN_VIOLATION, f"inconsistent high/low at {raw.time}"
        )
    if spec.shape is Shape.OHLCV and values[4] < 0:
        raise ScraperError(errors.DOMAIN_VIOLATION, f"negative volume at {raw.time}")
    if spec.non_negative and any(v < 0 for v in values):
        raise ScraperError(errors.DOMAIN_VIOLATION, f"negative value at {raw.time}")


def validate_bars(
    spec: DatasetSpec,
    *,
    pro_name: str,
    provider_time: int,
    raw_bars: Sequence[RawBar],
) -> GateResult:
    """Run the gate; return closed, ascending, validated bars or raise.

    The newest returned bar is dropped unconditionally: the provider streams the
    still-forming bar as the last element, and a closed-bar test on its time is
    not trusted to tell a forming bar from a final one.
    """
    if pro_name != spec.canonical_symbol:
        raise ScraperError(
            errors.IDENTITY_MISMATCH,
            f"resolved {pro_name!r}, expected {spec.canonical_symbol!r}",
        )

    expected_fields = spec.values_per_bar - 1
    for raw in raw_bars:
        if len(raw.fields) != expected_fields:
            raise ScraperError(
                errors.SHAPE_MISMATCH,
                f"bar {raw.time} has {len(raw.fields) + 1} values, "
                f"expected {spec.values_per_bar}",
            )

    ordered = sorted(raw_bars, key=lambda b: b.time)[:-1]
    if not ordered:
        raise ScraperError(errors.EMPTY, "no closed bars after dropping the newest")

    step = spec.interval_seconds
    for raw in ordered:
        if raw.time + step > provider_time:
            raise ScraperError(
                errors.FUTURE_BAR,
                f"bar {raw.time} closes after provider time {provider_time}",
            )

    # Holes are recorded, not rejected: the provider's own history can have
    # them (daily index data from 2015). Readiness watches for recent ones.
    holes = 0
    if spec.contiguous:
        for previous, current in pairwise(ordered):
            holes += max((current.time - previous.time) // step - 1, 0)

    bars: list[Bar] = []
    for raw in ordered:
        _check_domain(spec, raw)
        open_, high, low, close = raw.fields[:4]
        volume = raw.fields[4] if spec.shape is Shape.OHLCV else None
        bar_open = epoch_to_utc(raw.time)
        bars.append(
            Bar(
                bar_open=bar_open,
                bar_close=bar_open + timedelta(seconds=step),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                content_hash=content_hash(open_, high, low, close, volume),
            )
        )
    return GateResult(bars=bars, holes=holes)


__all__ = [
    "Bar",
    "GateResult",
    "RawBar",
    "canonical_decimal",
    "content_hash",
    "epoch_to_utc",
    "expected_latest_closed_bar_open",
    "validate_bars",
]
