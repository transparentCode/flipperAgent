"""Pure rules of the read API: errors, timestamps, windows, settle, vintage, staleness.

No I/O: every function takes the instants it needs, so the routes stay thin and
the point-in-time rules are testable without a store.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException

CANDIDATE_MODES = ("final", "as_of", "current")
ORDERS = ("desc", "asc")
_MICROSECOND = timedelta(microseconds=1)


class ApiError(HTTPException):
    """``{"detail": {"code", "message", ...}}`` with a status code."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ) -> None:
        super().__init__(
            status_code=status,
            detail={"code": code, "message": message, **extra},
            headers=headers,
        )


def invalid(message: str, code: str = "invalid_request", **extra: Any) -> ApiError:
    return ApiError(422, code, message, **extra)


def parse_timestamp(name: str, value: str) -> datetime:
    """RFC 3339 with an explicit offset; naive values are rejected."""
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        raise invalid(f"{name} is not an RFC 3339 timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise invalid(f"{name} needs an explicit UTC offset (for example Z)")
    try:
        return parsed.astimezone(UTC)
    except OverflowError:
        raise invalid(f"{name} is outside the supported range") from None


def parse_int(
    name: str, value: str | None, *, default: int, low: int, high: int
) -> int:
    if value is None:
        return default
    try:
        number = int(value)
    except ValueError:
        raise invalid(f"{name} must be an integer") from None
    if not low <= number <= high:
        raise invalid(f"{name} must be between {low} and {high}")
    return number


def parse_choice(
    name: str, value: str | None, *, default: str, choices: tuple[str, ...]
) -> str:
    if value is None:
        return default
    if value not in choices:
        raise invalid(f"{name} must be one of {list(choices)}")
    return value


def parse_flag(name: str, value: str | None) -> bool:
    if value is None:
        return False
    if value.lower() in ("true", "1"):
        return True
    if value.lower() in ("false", "0"):
        return False
    raise invalid(f"{name} must be true or false")


def stamp(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


def settled(now: datetime, settle_seconds: int) -> datetime:
    """The latest instant a point-in-time query may name."""
    return now - timedelta(seconds=settle_seconds)


def check_as_of(
    as_of: datetime, *, now: datetime, settle_seconds: int, vintage: datetime | None
) -> None:
    """A named instant must be settled and not older than the retained history."""
    if as_of > settled(now, settle_seconds):
        raise invalid(
            f"as_of is later than now minus the {settle_seconds} s settle interval",
            "as_of_too_recent",
            latest_as_of=stamp(settled(now, settle_seconds)),
        )
    if vintage is None or as_of < vintage:
        raise invalid(
            "as_of is before the oldest retained observation",
            "as_of_before_vintage",
            vintage_available_from=stamp(vintage),
        )


@dataclass(frozen=True, slots=True)
class Reference:
    """The instant a bars request is answered as of (``None`` for ``final``)."""

    mode: str
    as_of: datetime | None
    time: datetime  # reference time for windows, age and staleness


def resolve_bars_reference(
    mode: str,
    as_of: datetime | None,
    *,
    now: datetime,
    settle_seconds: int,
    vintage: datetime | None,
) -> Reference:
    if (mode == "as_of") != (as_of is not None):
        raise invalid("as_of is required for mode=as_of and invalid otherwise")
    if mode == "final":
        return Reference(mode, None, now)
    if mode == "current":
        # Replayable: the response states this instant and mode=as_of reproduces it.
        instant = settled(now, settle_seconds)
        if vintage is None or instant < vintage:
            raise invalid(
                "no observation is available yet",
                "as_of_before_vintage",
                vintage_available_from=stamp(vintage),
            )
        return Reference(mode, instant, instant)
    assert as_of is not None
    check_as_of(as_of, now=now, settle_seconds=settle_seconds, vintage=vintage)
    return Reference(mode, as_of, as_of)


def bars_window(
    start: datetime | None,
    end: datetime | None,
    *,
    reference: datetime,
    interval_seconds: int,
    max_limit: int,
) -> tuple[datetime, datetime]:
    """``start`` inclusive, ``end`` exclusive, on ``bar_open``."""
    widest = timedelta(seconds=interval_seconds * max_limit)
    window_end = reference if end is None else end
    try:
        window_start = window_end - widest if start is None else start
    except OverflowError:
        raise invalid("the window start is outside the supported range") from None
    if window_start >= window_end:
        raise invalid("start must be earlier than end")
    if window_end - window_start > widest:
        raise invalid(
            f"the window spans more than {max_limit} intervals",
            max_span_seconds=int(widest.total_seconds()),
        )
    return window_start, window_end


@dataclass(frozen=True, slots=True)
class Staleness:
    age_seconds: float | None
    stale: bool


def staleness(
    reference: datetime, latest_ok_finished_at: datetime | None, max_age_seconds: int
) -> Staleness:
    """Age of the latest ok read at or before the reference; none counts as stale."""
    if latest_ok_finished_at is None:
        return Staleness(None, True)
    age = (reference - latest_ok_finished_at).total_seconds()
    return Staleness(age, age > max_age_seconds)


def next_after_page(
    *,
    order: str,
    count: int,
    limit: int,
    start: datetime,
    end: datetime,
    first_open: datetime,
    last_open: datetime,
) -> tuple[datetime, datetime] | None:
    """The window to request next, or ``None`` when the walk is complete."""
    if count < limit:
        return None
    if order == "desc":
        # end is exclusive: continue strictly before the oldest bar returned.
        return (start, last_open) if last_open > start else None
    try:
        after = last_open + _MICROSECOND
    except OverflowError:
        return None
    return (after, end) if after < end else None


def format_decimal(value: Any) -> str | None:
    return None if value is None else format(value, "f")


__all__ = [
    "ApiError",
    "Reference",
    "Staleness",
    "bars_window",
    "check_as_of",
    "format_decimal",
    "invalid",
    "next_after_page",
    "parse_choice",
    "parse_flag",
    "parse_int",
    "parse_timestamp",
    "resolve_bars_reference",
    "settled",
    "staleness",
    "stamp",
]
