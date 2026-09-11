"""Binance USD-M Futures historical REST provider for ingestion."""

from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, datetime, timedelta
from threading import BoundedSemaphore, Lock
from typing import Any

from binance.error import ServerError
from binance.um_futures import UMFutures
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import SSLError
from requests.exceptions import Timeout as RequestsTimeout

from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.base import (
    ProviderAvailabilityError,
    TransportDeadlineExceeded,
)
from apps.ingestion_app.providers.binance_rest import decode_binance_native_klines
from apps.ingestion_app.runtime.blocking import (
    _OwnedBlockingCall,
    _OwnedCallTimeout,
)
from libs.common.exceptions import DataIngestionError

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _require_non_empty_string(value: object, *, field_name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


def _require_utc(value: object, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")


def _validate_request(
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
    _require_non_empty_string(provider_symbol, field_name="provider_symbol")
    if not isinstance(timeframe_duration, timedelta):
        raise TypeError("timeframe_duration must be a timedelta")
    if timeframe_duration <= timedelta(0):
        raise ValueError("timeframe_duration must be positive")
    _require_utc(since, field_name="since")
    _require_utc(until, field_name="until")
    if until <= since:
        raise ValueError("until must be after since")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if limit <= 0:
        raise ValueError("limit must be positive")


def _epoch_milliseconds(value: datetime) -> int:
    elapsed = value - _EPOCH
    return (
        elapsed.days * 86_400_000
        + elapsed.seconds * 1_000
        + elapsed.microseconds // 1_000
    )


def _is_provider_availability_error(error: BaseException) -> bool:
    return isinstance(
        error,
        (ServerError, RequestsConnectionError, RequestsTimeout, TimeoutError),
    ) and not isinstance(error, SSLError)


class BinanceNativeHistoricalProvider:
    """Fetch finalized Binance USD-M Futures klines through the native SDK."""

    provider_id = "binance_native"

    def __init__(
        self,
        client: Any | None = None,
        *,
        attempt_timeout_seconds: float = 30,
        max_concurrency: int = 1,
    ) -> None:
        if isinstance(attempt_timeout_seconds, bool) or not isinstance(
            attempt_timeout_seconds,
            (int, float),
        ):
            raise TypeError("attempt_timeout_seconds must be a number")
        if (
            not math.isfinite(float(attempt_timeout_seconds))
            or attempt_timeout_seconds <= 0
        ):
            raise ValueError("attempt_timeout_seconds must be positive")
        if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
            raise TypeError("max_concurrency must be an integer")
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        self.client = (
            client
            if client is not None
            else UMFutures(timeout=float(attempt_timeout_seconds))
        )
        self.attempt_timeout_seconds = float(attempt_timeout_seconds)
        self.max_concurrency = max_concurrency
        self._owned_calls: set[_OwnedBlockingCall] = set()
        self._owned_calls_lock = Lock()
        self._admission = BoundedSemaphore(max_concurrency)
        self._quarantined = False
        self._closed = False
        self._closing = False
        self._close_call: _OwnedBlockingCall | None = None
        self._close_cancelled = False
        self._close_operation_succeeded = False

    @property
    def retained_worker_count(self) -> int:
        with self._owned_calls_lock:
            return sum(not call.finished for call in self._owned_calls)

    @property
    def quarantined(self) -> bool:
        return self._quarantined

    def _track_call(self, call: _OwnedBlockingCall) -> None:
        with self._owned_calls_lock:
            self._owned_calls.add(call)

    def _forget_call(self, call: _OwnedBlockingCall) -> None:
        with self._owned_calls_lock:
            self._owned_calls.discard(call)
        self._admission.release()

    def _finish_close_call(self, call: _OwnedBlockingCall) -> None:
        self._forget_call(call)
        if self._close_call is not call:
            return
        self._close_call = None
        if call.failed:
            self._quarantine()
            return
        self._close_operation_succeeded = True
        if self._close_cancelled:
            self._closed = True
            self._closing = False
            self._close_cancelled = False

    def _quarantine(self) -> None:
        self._quarantined = True

    def _check_available(self, operation: str, *, allow_closing: bool = False) -> None:
        if self._quarantined:
            raise TransportDeadlineExceeded(
                provider_id=self.provider_id,
                operation=f"quarantined {operation}",
                timeout_seconds=self.attempt_timeout_seconds,
            )
        if self._closed:
            raise DataIngestionError("Binance historical provider is closed")
        if self._closing and not allow_closing:
            raise DataIngestionError("Binance historical provider is closing")

    def _admit(
        self,
        operation: str,
        *,
        exclusive: bool = False,
        allow_closing: bool = False,
    ) -> None:
        self._check_available(operation, allow_closing=allow_closing)
        if exclusive and self.retained_worker_count:
            raise DataIngestionError(
                f"Binance provider has active work; cannot start {operation}"
            )
        if not self._admission.acquire(blocking=False):
            raise DataIngestionError(
                f"Binance provider {operation} admission is saturated"
            )

    async def _wait_owned_call(
        self,
        call: _OwnedBlockingCall,
        *,
        operation: str,
    ) -> Any:
        try:
            result = await call.wait(self.attempt_timeout_seconds)
        except _OwnedCallTimeout as exc:
            if (
                call.operation_finished
                and call.operation_finished_at is not None
                and call.operation_finished_at <= exc.deadline
            ):
                try:
                    result = call.result_or_raise()
                except BaseException:
                    call.adopt()
                    raise
                if not call.adopt():
                    raise asyncio.CancelledError
                return result
            call.abandon()
            self._quarantine()
            raise TransportDeadlineExceeded(
                provider_id=self.provider_id,
                operation=operation,
                timeout_seconds=self.attempt_timeout_seconds,
            ) from exc
        except asyncio.CancelledError:
            if call.operation_finished:
                call.adopt()
            else:
                call.abandon()
            raise
        except BaseException:
            call.adopt()
            raise
        if not call.adopt():
            raise asyncio.CancelledError
        return result

    async def _drain_owned_calls(self) -> None:
        deadline = time.monotonic() + self.attempt_timeout_seconds
        while True:
            with self._owned_calls_lock:
                retained = bool(self._owned_calls)
            if not retained:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._quarantine()
                raise TransportDeadlineExceeded(
                    provider_id=self.provider_id,
                    operation="session close drain",
                    timeout_seconds=self.attempt_timeout_seconds,
                )
            await asyncio.sleep(min(0.01, remaining))

    async def close(self) -> None:
        if self._closed:
            return
        self._check_available("session close")
        if self._closing:
            raise DataIngestionError("Binance historical provider is closing")
        self._closing = True
        self._close_cancelled = False
        self._close_operation_succeeded = False
        call: _OwnedBlockingCall | None = None
        loop = asyncio.get_running_loop()

        def close_session() -> None:
            self.client.session.close()

        try:
            await self._drain_owned_calls()
            self._admit("session close", exclusive=True, allow_closing=True)
            call = _OwnedBlockingCall(
                loop=loop,
                operation=close_session,
                name="binance-native-session-close",
                finished_callback=self._finish_close_call,
            )
            self._close_call = call
            self._track_call(call)
            call.start()
            await self._wait_owned_call(call, operation="session close")
            await self._drain_owned_calls()
        except asyncio.CancelledError:
            self._close_cancelled = True
            if call is None:
                self._closing = False
                self._close_cancelled = False
                self._close_operation_succeeded = False
            elif call.finished or self._close_operation_succeeded:
                if call.failed or self._quarantined:
                    self._quarantine()
                else:
                    self._closed = True
                    self._closing = False
                    self._close_cancelled = False
            raise
        except DataIngestionError:
            self._quarantine()
            raise
        except Exception as exc:
            self._quarantine()
            raise DataIngestionError("Binance failed to close HTTP session") from exc
        else:
            self._closed = True
            self._close_cancelled = False

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
        _validate_request(
            lane=lane,
            provider_symbol=provider_symbol,
            timeframe_duration=timeframe_duration,
            since=since,
            until=until,
            limit=limit,
        )
        closed_before = min(until, request_started_at)
        if closed_before <= since:
            return ()
        self._admit("REST klines")
        loop = asyncio.get_running_loop()
        call = _OwnedBlockingCall(
            loop=loop,
            operation=lambda: self.client.klines(
                provider_symbol,
                lane.timeframe,
                startTime=_epoch_milliseconds(since),
                endTime=_epoch_milliseconds(closed_before),
                limit=limit,
            ),
            name="binance-native-klines",
            finished_callback=self._forget_call,
        )
        self._track_call(call)
        try:
            call.start()
            raw_rows = await self._wait_owned_call(
                call,
                operation=f"REST klines for {provider_symbol}",
            )
        except TransportDeadlineExceeded:
            raise
        except Exception as exc:
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
