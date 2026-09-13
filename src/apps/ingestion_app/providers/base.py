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
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("reason must be a non-empty string")
        if not isinstance(recovery_requests, tuple):
            raise TypeError("recovery_requests must be a tuple")
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
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("provider_id must be a non-empty string")
        if not isinstance(operation, str) or not operation.strip():
            raise ValueError("operation must be a non-empty string")
        if isinstance(timeout_seconds, bool) or not isinstance(
            timeout_seconds,
            (int, float),
        ):
            raise TypeError("timeout_seconds must be a number")
        if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.provider_id = provider_id
        self.operation = operation
        self.timeout_seconds = float(timeout_seconds)
        super().__init__(
            f"{provider_id} {operation} exceeded its {timeout_seconds:g}s "
            "deadline while SDK ownership remained unresolved"
        )


class ProviderAvailabilityError(DataIngestionError):
    """A completed provider-availability failure safe for bounded recovery."""


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
    "HistoricalCandleProvider",
    "LiveCandleProvider",
    "LiveStreamInterrupted",
    "ProviderAvailabilityError",
    "TransportDeadlineExceeded",
]
