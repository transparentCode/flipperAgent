"""Shared validation and time conversion for bounded historical requests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.validation import require_non_empty_string, require_utc

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def validate_historical_request(
    *,
    lane: MarketLane,
    provider_symbol: str,
    timeframe_duration: timedelta,
    since: datetime,
    until: datetime,
    limit: int,
) -> None:
    if not isinstance(lane, MarketLane):
        raise TypeError("lane must be a MarketLane")
    require_non_empty_string(provider_symbol, field_name="provider_symbol")
    if not isinstance(timeframe_duration, timedelta):
        raise TypeError("timeframe_duration must be a timedelta")
    if timeframe_duration <= timedelta(0):
        raise ValueError("timeframe_duration must be positive")
    require_utc(since, field_name="since")
    require_utc(until, field_name="until")
    if until <= since:
        raise ValueError("until must be after since")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if limit <= 0:
        raise ValueError("limit must be positive")


def epoch_milliseconds(value: datetime) -> int:
    elapsed = value - _EPOCH
    return (
        elapsed.days * 86_400_000
        + elapsed.seconds * 1_000
        + elapsed.microseconds // 1_000
    )


__all__ = ["epoch_milliseconds", "validate_historical_request"]
