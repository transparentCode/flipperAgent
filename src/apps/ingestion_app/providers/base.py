"""Structural provider contracts for ingestion."""

from __future__ import annotations

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


class HistoricalCandleProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

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
]
