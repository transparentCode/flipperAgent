"""Loss-safe multiplexed Binance websocket delivery for ingestion."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.time_alignment import is_aligned
from apps.ingestion_app.observability import IngestionObservability
from apps.ingestion_app.providers.live_sequence import LiveSequenceTracker
from libs.common.exceptions import DataIngestionError

from .websocket_decode import decode_binance_websocket_message
from .websocket_pump import _ClosedCandlePump
from .websocket_session import BinanceWebSocketSessionOwner


def _utc_now() -> datetime:
    """Return the UTC wall-clock sample used by causal live-stream checks."""
    return datetime.now(UTC)


class BinanceWebSocketManager:
    """Own one multiplexed Binance websocket and deliver closed candles."""

    provider_id = "binance_native"

    def __init__(
        self,
        *,
        stream_url: str,
        queue_maxsize: int,
        lifecycle_timeout_seconds: float = 30,
        client_factory: Callable[..., Any] = UMFuturesWebsocketClient,
        observability: IngestionObservability | None = None,
    ) -> None:
        self.stream_url = stream_url
        self.queue_maxsize = queue_maxsize
        self.lifecycle_timeout_seconds = float(lifecycle_timeout_seconds)
        self.client_factory = client_factory
        self.observability = observability or IngestionObservability()
        self._ever_connected = False
        self._session_owner = BinanceWebSocketSessionOwner(
            stream_url=self.stream_url,
            lifecycle_timeout_seconds=self.lifecycle_timeout_seconds,
            client_factory=self.client_factory,
            provider_id=self.provider_id,
        )

    @property
    def lifecycle_quarantined(self) -> bool:
        return self._session_owner.lifecycle_quarantined

    @property
    def lifecycle_quarantine_error(self) -> DataIngestionError | None:
        return self._session_owner.lifecycle_quarantine_error

    @property
    def retained_worker_count(self) -> int:
        return self._session_owner.retained_worker_count

    @staticmethod
    def _validate_subscriptions(
        subscriptions: Mapping[MarketLane, str],
        *,
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
        connection_anchor: datetime,
    ) -> dict[str, tuple[MarketLane, str]]:
        if not subscriptions:
            raise ValueError("subscriptions must not be empty")
        if not is_aligned(connection_anchor, timeframe_duration, alignment_origin):
            raise ValueError("connection_anchor must align to the base grid")

        routes: dict[str, tuple[MarketLane, str]] = {}
        for lane, provider_symbol in subscriptions.items():
            if lane.timeframe != base_timeframe:
                raise ValueError(
                    f"live lane timeframe '{lane.timeframe}' must equal "
                    f"base_timeframe '{base_timeframe}'"
                )
            normalized_symbol = provider_symbol.casefold()
            if normalized_symbol in routes:
                raise ValueError(
                    f"duplicate normalized provider symbol '{provider_symbol}'"
                )
            routes[normalized_symbol] = (lane, provider_symbol)
        return routes

    def stream_closed_candles(
        self,
        subscriptions: Mapping[MarketLane, str],
        *,
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
        connection_anchor: datetime,
    ) -> AsyncIterator[CandleObservation]:
        routes = self._validate_subscriptions(
            subscriptions,
            base_timeframe=base_timeframe,
            timeframe_duration=timeframe_duration,
            alignment_origin=alignment_origin,
            connection_anchor=connection_anchor,
        )
        return self._stream_closed_candles(
            routes=routes,
            base_timeframe=base_timeframe,
            timeframe_duration=timeframe_duration,
            alignment_origin=alignment_origin,
            connection_anchor=connection_anchor,
        )

    def _stream_closed_candles(
        self,
        *,
        routes: Mapping[str, tuple[MarketLane, str]],
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
        connection_anchor: datetime,
    ) -> AsyncIterator[CandleObservation]:
        pump = _ClosedCandlePump(
            routes=routes,
            base_timeframe=base_timeframe,
            timeframe_duration=timeframe_duration,
            alignment_origin=alignment_origin,
            connection_anchor=connection_anchor,
            queue_maxsize=self.queue_maxsize,
            observability=self.observability,
            session_owner=self._session_owner,
            parse_message=self._parse_message,
            on_connection_started=self._on_connection_started,
            tracker_factory=LiveSequenceTracker,
            now_fn=_utc_now,
        )
        return pump.run()

    def _parse_message(
        self,
        raw_message: object,
        *,
        routes: Mapping[str, tuple[MarketLane, str]],
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
    ) -> CandleObservation | None:
        return decode_binance_websocket_message(
            raw_message,
            provider_id=self.provider_id,
            routes=routes,
            base_timeframe=base_timeframe,
            timeframe_duration=timeframe_duration,
            alignment_origin=alignment_origin,
            received_at_fn=_utc_now,
        )

    def _on_connection_started(self) -> None:
        if self._ever_connected:
            self.observability.record_websocket_reconnect()
        self._ever_connected = True
        self.observability.set_websocket_connected(True)


__all__ = ["BinanceWebSocketManager"]
