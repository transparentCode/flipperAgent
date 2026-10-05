"""Structural provider contracts for ingestion."""

from __future__ import annotations

import math
from collections.abc import AsyncIterator, Mapping
from datetime import datetime, timedelta
from typing import Protocol

from libs.common.exceptions import DataIngestionError

from ..domain.candle import CandleObservation
from ..domain.instrument import MarketLane
from ..domain.recovery import RecoveryRequest


class LiveStreamInterrupted(DataIngestionError):
    """A live stream stopped and bounded REST repair is required."""

    def __init__(
        self,
        *,
        reason: str,
        recovery_requests: tuple[RecoveryRequest, ...],
    ) -> None:
        self.reason = reason
        self.recovery_requests = recovery_requests
        super().__init__(f"live stream interrupted: {reason}")


class TransportDeadlineExceeded(DataIngestionError):
    """An SDK operation still owned by its provider at its hard deadline."""

    def __init__(
        self,
        *,
        provider_id: str,
        operation: str,
        timeout_seconds: float,
    ) -> None:
        self.provider_id = provider_id
        self.operation = operation
        self.timeout_seconds = float(timeout_seconds)
        super().__init__(
            f"{provider_id} {operation} exceeded its {timeout_seconds:g}s "
            "deadline while SDK ownership remained unresolved"
        )


class ProviderAvailabilityError(DataIngestionError):
    """A completed provider-availability failure safe for bounded recovery."""


DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 60.0


class ProviderRateLimitedError(ProviderAvailabilityError):
    """A provider asked the caller to stop requests for a finite interval."""

    def __init__(self, *, provider_id: str, retry_after_seconds: float) -> None:
        self.provider_id = provider_id
        self.retry_after_seconds = float(retry_after_seconds)
        super().__init__(
            f"{provider_id} is rate limited; retry after {self.retry_after_seconds:g}s"
        )


def parse_retry_after_seconds(headers: object) -> float:
    """Read a numeric Retry-After value, using the fixed fallback if unusable."""
    if headers is None:
        return DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
    items = getattr(headers, "items", None)
    if not callable(items):
        return DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
    try:
        value = next(
            (
                header_value
                for name, header_value in items()
                if isinstance(name, str) and name.lower() == "retry-after"
            ),
            None,
        )
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
    if isinstance(value, bool) or value is None:
        return DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
    try:
        seconds = float(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
    if not math.isfinite(seconds) or seconds <= 0:
        return DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
    return seconds


class HistoricalCandleProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    async def wait_until_idle(self) -> None: ...

    async def fetch_closed_candles(
        self,
        *,
        lane: MarketLane,
        provider_symbol: str,
        timeframe_duration: timedelta,
        since: datetime,
        until: datetime,
        limit: int,
    ) -> tuple[CandleObservation, ...]: ...


class LiveCandleProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def stream_closed_candles(
        self,
        subscriptions: Mapping[MarketLane, str],
        *,
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
        connection_anchor: datetime,
    ) -> AsyncIterator[CandleObservation]: ...


__all__ = [
    "DEFAULT_RATE_LIMIT_BACKOFF_SECONDS",
    "HistoricalCandleProvider",
    "LiveCandleProvider",
    "LiveStreamInterrupted",
    "ProviderAvailabilityError",
    "ProviderRateLimitedError",
    "TransportDeadlineExceeded",
    "parse_retry_after_seconds",
]
