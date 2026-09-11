"""CCXT historical REST provider for ingestion."""

from __future__ import annotations

import asyncio
import math
import time
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

import ccxt.async_support as ccxt

from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.base import TransportDeadlineExceeded
from apps.ingestion_app.providers.binance_rest import decode_ccxt_ohlcv_rows
from apps.ingestion_app.runtime.blocking import _OwnedAsyncCall, _OwnedCallTimeout
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


class CCXTHistoricalProvider:
    """Fetch bounded finalized Binance USD-M klines through async CCXT."""

    def __init__(
        self,
        *,
        provider_id: str,
        exchange_id: str,
        exchange: Any | None = None,
        attempt_timeout_seconds: float = 30,
        max_concurrency: int = 1,
    ) -> None:
        _require_non_empty_string(provider_id, field_name="provider_id")
        _require_non_empty_string(exchange_id, field_name="exchange_id")
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
        self.provider_id = provider_id
        self.attempt_timeout_seconds = float(attempt_timeout_seconds)
        self.max_concurrency = max_concurrency
        self._owned_calls: set[_OwnedAsyncCall] = set()
        self._owned_calls_lock = Lock()
        self._active_count = 0
        self._quarantined = False
        self._closed = False
        self._closing = False
        self._close_call: _OwnedAsyncCall | None = None
        self._close_cancelled = False
        self._close_operation_succeeded = False
        if exchange is not None:
            self.exchange = exchange
            return
        try:
            exchange_class = getattr(ccxt, exchange_id)
        except AttributeError as exc:
            raise ValueError(f"Unknown CCXT exchange: {exchange_id}") from exc
        self.exchange = exchange_class()

    @property
    def retained_worker_count(self) -> int:
        with self._owned_calls_lock:
            return sum(not call.finished for call in self._owned_calls)

    @property
    def quarantined(self) -> bool:
        return self._quarantined

    def _track_call(self, call: _OwnedAsyncCall) -> None:
        with self._owned_calls_lock:
            self._owned_calls.add(call)

    def _forget_call(self, call: _OwnedAsyncCall) -> None:
        with self._owned_calls_lock:
            self._owned_calls.discard(call)
            self._active_count -= 1

    def _finish_close_call(self, call: _OwnedAsyncCall) -> None:
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
            raise DataIngestionError("CCXT historical provider is closed")
        if self._closing and not allow_closing:
            raise DataIngestionError("CCXT historical provider is closing")

    def _admit(
        self,
        operation: str,
        *,
        exclusive: bool = False,
        allow_closing: bool = False,
    ) -> None:
        self._check_available(operation, allow_closing=allow_closing)
        with self._owned_calls_lock:
            if exclusive and self._active_count:
                raise DataIngestionError(
                    f"CCXT provider has active work; cannot start {operation}"
                )
            if self._active_count >= self.max_concurrency:
                raise DataIngestionError(
                    f"CCXT provider {operation} admission is saturated"
                )
            self._active_count += 1

    async def _wait_owned_call(
        self,
        call: _OwnedAsyncCall,
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
                    operation="exchange close drain",
                    timeout_seconds=self.attempt_timeout_seconds,
                )
            await asyncio.sleep(min(0.01, remaining))

    async def _fetch_raw_rows(
        self,
        *,
        provider_symbol: str,
        lane: MarketLane,
        since: datetime,
        closed_before: datetime,
        limit: int,
    ) -> object:
        """Keep market loading and the raw request in one owned attempt."""
        native_symbol = await self._resolve_native_symbol(provider_symbol)
        raw_klines = getattr(self.exchange, "fapiPublicGetKlines", None)
        if not callable(raw_klines):
            raise DataIngestionError(
                "CCXT Binance USD-M client lacks fapiPublicGetKlines; "
                "taker-buy-complete klines are required"
            )

        try:
            return await raw_klines(
                {
                    "symbol": native_symbol,
                    "interval": lane.timeframe,
                    "startTime": _epoch_milliseconds(since),
                    "endTime": _epoch_milliseconds(closed_before),
                    "limit": limit,
                }
            )
        except ccxt.BaseError as exc:
            raise DataIngestionError(
                f"CCXT failed to fetch Binance USD-M klines for {provider_symbol}"
            ) from exc

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
        self._check_available("historical attempt")
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

        self._admit("historical attempt")
        loop = asyncio.get_running_loop()
        call = _OwnedAsyncCall(
            loop=loop,
            operation=lambda: self._fetch_raw_rows(
                provider_symbol=provider_symbol,
                lane=lane,
                since=since,
                closed_before=closed_before,
                limit=limit,
            ),
            name="ccxt-historical-attempt",
            finished_callback=self._forget_call,
        )
        self._track_call(call)
        try:
            call.start()
            raw_rows = await self._wait_owned_call(
                call,
                operation=f"historical attempt for {provider_symbol}",
            )
        except TransportDeadlineExceeded:
            raise
        except DataIngestionError:
            raise
        except Exception as exc:
            raise DataIngestionError(
                f"CCXT failed to fetch Binance USD-M klines for {provider_symbol}"
            ) from exc

        if not isinstance(raw_rows, (list, tuple)):
            raise DataIngestionError("CCXT returned a malformed OHLCV response")

        return decode_ccxt_ohlcv_rows(
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

    async def _resolve_native_symbol(self, provider_symbol: str) -> str:
        try:
            await self.exchange.load_markets()
            market = self.exchange.market(provider_symbol)
        except ccxt.BaseError as exc:
            raise DataIngestionError(
                f"CCXT could not resolve Binance USD-M market {provider_symbol}"
            ) from exc
        except Exception as exc:
            raise DataIngestionError(
                f"CCXT could not resolve Binance USD-M market {provider_symbol}"
            ) from exc

        if not isinstance(market, dict):
            raise DataIngestionError(
                f"CCXT returned malformed market metadata for {provider_symbol}"
            )
        native_symbol = market.get("id")
        if not isinstance(native_symbol, str) or not native_symbol.strip():
            raise DataIngestionError(
                f"CCXT market metadata has no native Binance symbol for "
                f"{provider_symbol}"
            )
        return native_symbol.strip()

    async def close(self) -> None:
        if self._closed:
            return
        self._check_available("exchange close")
        if self._closing:
            raise DataIngestionError("CCXT historical provider is closing")
        self._closing = True
        self._close_cancelled = False
        self._close_operation_succeeded = False
        call: _OwnedAsyncCall | None = None
        loop = asyncio.get_running_loop()
        try:
            await self._drain_owned_calls()
            self._admit("exchange close", exclusive=True, allow_closing=True)
            call = _OwnedAsyncCall(
                loop=loop,
                operation=self.exchange.close,
                name="ccxt-exchange-close",
                finished_callback=self._finish_close_call,
            )
            self._close_call = call
            self._track_call(call)
            call.start()
            await self._wait_owned_call(call, operation="exchange close")
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
            raise DataIngestionError("CCXT exchange close failed") from exc
        else:
            self._closed = True
            self._close_cancelled = False


__all__ = ["CCXTHistoricalProvider"]
