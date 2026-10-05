"""Binance USD-M Futures historical REST provider for ingestion."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any

from binance.error import ClientError, ServerError
from binance.um_futures import UMFutures
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import SSLError
from requests.exceptions import Timeout as RequestsTimeout

from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.base import (
    ProviderAvailabilityError,
    ProviderRateLimitedError,
    TransportDeadlineExceeded,
)
from apps.ingestion_app.providers.owned_historical import OwnedHistoricalProvider
from apps.ingestion_app.providers.request import epoch_milliseconds
from apps.ingestion_app.transport.ownership import OwnedBlockingCall
from libs.common.exceptions import DataIngestionError

from .rest_decode import decode_binance_native_klines


def _is_provider_availability_error(error: BaseException) -> bool:
    return isinstance(
        error,
        (ServerError, RequestsConnectionError, RequestsTimeout, TimeoutError),
    ) and not isinstance(error, SSLError)


class BinanceNativeHistoricalProvider(OwnedHistoricalProvider[OwnedBlockingCall]):
    """Fetch finalized Binance USD-M Futures klines through the native SDK."""

    provider_id = "binance_native"
    _provider_label = "Binance"
    _close_operation = "session close"
    _close_failure_message = "Binance failed to close HTTP session"

    def __init__(
        self,
        client: Any | None = None,
        *,
        attempt_timeout_seconds: float = 30,
        max_concurrency: int = 1,
        monotonic_fn: Callable[[], float] = monotonic,
    ) -> None:
        self.client = (
            client
            if client is not None
            else UMFutures(timeout=float(attempt_timeout_seconds))
        )
        super().__init__(
            attempt_timeout_seconds=attempt_timeout_seconds,
            max_concurrency=max_concurrency,
            monotonic_fn=monotonic_fn,
        )

    def _admit(
        self,
        operation: str,
        *,
        call: OwnedBlockingCall,
        exclusive: bool = False,
        allow_closing: bool = False,
    ) -> None:
        self._check_available(operation, allow_closing=allow_closing)
        if exclusive and self.retained_worker_count:
            raise DataIngestionError(
                f"Binance provider has active work; cannot start {operation}"
            )
        if not self._ownership.admit(call, exclusive=exclusive):
            if self._ownership.quarantined:
                self._check_available(operation, allow_closing=allow_closing)
            raise DataIngestionError(
                f"Binance provider {operation} admission is saturated"
            )

    def _new_close_call(self, loop: asyncio.AbstractEventLoop) -> OwnedBlockingCall:
        def close_session() -> None:
            self.client.session.close()

        return OwnedBlockingCall(
            loop=loop,
            operation=close_session,
            name="binance-native-session-close",
            finished_callback=self._finish_close_call,
        )

    def _record_rate_limit(self, headers: object) -> ProviderRateLimitedError:
        return self._note_rate_limit(headers)

    async def fetch_closed_candles(
        self,
        *,
        lane: MarketLane,
        provider_symbol: str,
        timeframe_duration: timedelta,
        since: datetime,
        until: datetime,
        limit: int,
    ) -> tuple[CandleObservation, ...]:
        self._check_available("REST klines")
        request_started_at = datetime.now(UTC)
        self._raise_if_rate_limited()
        closed_before = min(until, request_started_at)
        if closed_before <= since:
            return ()
        loop = asyncio.get_running_loop()
        call = OwnedBlockingCall(
            loop=loop,
            operation=lambda: self.client.klines(
                provider_symbol,
                lane.timeframe,
                startTime=epoch_milliseconds(since),
                endTime=epoch_milliseconds(closed_before),
                limit=limit,
            ),
            name="binance-native-klines",
            finished_callback=self._ownership.release,
        )
        self._admit("REST klines", call=call)
        try:
            call.start()
            raw_rows = await self._wait_owned_call(
                call,
                operation=f"REST klines for {provider_symbol}",
            )
        except TransportDeadlineExceeded:
            raise
        except Exception as exc:
            if isinstance(exc, ClientError) and exc.status_code in (418, 429):
                raise self._record_rate_limit(exc.header) from exc
            if _is_provider_availability_error(exc):
                raise ProviderAvailabilityError(
                    f"Binance provider unavailable while fetching klines for "
                    f"{provider_symbol}"
                ) from exc
            raise DataIngestionError(
                f"Binance failed to fetch klines for {provider_symbol}"
            ) from exc

        if not isinstance(raw_rows, (list, tuple)):
            raise DataIngestionError("Binance returned a malformed kline response")

        return decode_binance_native_klines(
            raw_rows,
            lane=lane,
            provider_id=self.provider_id,
            provider_symbol=provider_symbol,
            timeframe_duration=timeframe_duration,
            since=since,
            until=until,
            closed_before=closed_before,
            received_at=datetime.now(UTC),
            limit=limit,
        )


__all__ = ["BinanceNativeHistoricalProvider"]
