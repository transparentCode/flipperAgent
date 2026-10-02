"""CCXT historical REST provider for ingestion."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any

import ccxt.async_support as ccxt

from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.validation import require_non_empty_string
from apps.ingestion_app.providers.base import (
    ProviderAvailabilityError,
    ProviderRateLimitedError,
    TransportDeadlineExceeded,
    parse_retry_after_seconds,
)
from apps.ingestion_app.providers.request import (
    epoch_milliseconds,
    validate_historical_request,
)
from apps.ingestion_app.transport.ownership import (
    OwnedAsyncCall,
    OwnedOperationTracker,
    wait_for_owned_call,
)
from libs.common.exceptions import DataIngestionError

from .rest_decode import decode_ccxt_ohlcv_rows


def _is_provider_availability_error(error: BaseException) -> bool:
    return isinstance(error, (ccxt.NetworkError, TimeoutError)) and not isinstance(
        error,
        ccxt.InvalidNonce,
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
        monotonic_fn: Callable[[], float] = monotonic,
    ) -> None:
        require_non_empty_string(provider_id, field_name="provider_id")
        require_non_empty_string(exchange_id, field_name="exchange_id")
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
        self._monotonic = monotonic_fn
        self._rate_limited_until = 0.0
        self._ownership = OwnedOperationTracker(max_concurrency)
        self._closed = False
        self._closing = False
        self._close_call: OwnedAsyncCall | None = None
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
        return self._ownership.retained_count

    @property
    def quarantined(self) -> bool:
        return self._ownership.quarantined

    async def _wait_for_owned_calls_idle(self, *, operation: str) -> None:
        await self._ownership.wait_until_idle(
            timeout_seconds=self.attempt_timeout_seconds,
            timeout_error=lambda: TransportDeadlineExceeded(
                provider_id=self.provider_id,
                operation=operation,
                timeout_seconds=self.attempt_timeout_seconds,
            ),
        )

    async def wait_until_idle(self) -> None:
        """Wait for all provider-owned SDK work and admission to be released."""
        self._check_available("historical provider quiescence")
        await self._wait_for_owned_calls_idle(
            operation="historical provider quiescence"
        )

    def _finish_close_call(self, call: OwnedAsyncCall) -> None:
        self._ownership.release(call)
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
        self._ownership.quarantine()

    def _check_available(self, operation: str, *, allow_closing: bool = False) -> None:
        if self._ownership.quarantined:
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
        call: OwnedAsyncCall,
        exclusive: bool = False,
        allow_closing: bool = False,
    ) -> None:
        self._check_available(operation, allow_closing=allow_closing)
        if not self._ownership.admit(call, exclusive=exclusive):
            if self._ownership.quarantined:
                self._check_available(operation, allow_closing=allow_closing)
            if exclusive and self._ownership.active_count:
                raise DataIngestionError(
                    f"CCXT provider has active work; cannot start {operation}"
                )
            raise DataIngestionError(
                f"CCXT provider {operation} admission is saturated"
            )

    def _owned_call_deadline_error(self, operation: str) -> BaseException:
        self._quarantine()
        return TransportDeadlineExceeded(
            provider_id=self.provider_id,
            operation=operation,
            timeout_seconds=self.attempt_timeout_seconds,
        )

    async def _wait_owned_call(
        self,
        call: OwnedAsyncCall,
        *,
        operation: str,
    ) -> Any:
        return await wait_for_owned_call(
            call,
            timeout_seconds=self.attempt_timeout_seconds,
            timeout_error=lambda _exc: self._owned_call_deadline_error(operation),
        )

    async def _drain_owned_calls(self) -> None:
        await self._wait_for_owned_calls_idle(operation="exchange close drain")

    def _raise_if_rate_limited(self) -> None:
        remaining = self._rate_limited_until - self._monotonic()
        if remaining > 0:
            raise ProviderRateLimitedError(
                provider_id=self.provider_id,
                retry_after_seconds=remaining,
            )

    def _record_rate_limit(self) -> ProviderRateLimitedError:
        retry_after = parse_retry_after_seconds(
            getattr(self.exchange, "last_response_headers", None)
        )
        now = self._monotonic()
        self._rate_limited_until = max(
            self._rate_limited_until,
            now + retry_after,
        )
        return ProviderRateLimitedError(
            provider_id=self.provider_id,
            retry_after_seconds=self._rate_limited_until - now,
        )

    @staticmethod
    def _is_rate_limit_error(error: BaseException) -> bool:
        return isinstance(error, (ccxt.RateLimitExceeded, ccxt.DDoSProtection))

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
                    "startTime": epoch_milliseconds(since),
                    "endTime": epoch_milliseconds(closed_before),
                    "limit": limit,
                }
            )
        except ccxt.BaseError as exc:
            if self._is_rate_limit_error(exc):
                raise self._record_rate_limit() from exc
            if _is_provider_availability_error(exc):
                raise ProviderAvailabilityError(
                    f"CCXT provider unavailable while fetching Binance USD-M "
                    f"klines for {provider_symbol}"
                ) from exc
            raise DataIngestionError(
                f"CCXT failed to fetch Binance USD-M klines for {provider_symbol}"
            ) from exc
        except TimeoutError as exc:
            raise ProviderAvailabilityError(
                f"CCXT provider unavailable while fetching Binance USD-M klines "
                f"for {provider_symbol}"
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
        validate_historical_request(
            lane=lane,
            provider_symbol=provider_symbol,
            timeframe_duration=timeframe_duration,
            since=since,
            until=until,
            limit=limit,
        )
        self._raise_if_rate_limited()
        closed_before = min(until, request_started_at)
        if closed_before <= since:
            return ()

        loop = asyncio.get_running_loop()
        call = OwnedAsyncCall(
            loop=loop,
            operation=lambda: self._fetch_raw_rows(
                provider_symbol=provider_symbol,
                lane=lane,
                since=since,
                closed_before=closed_before,
                limit=limit,
            ),
            name="ccxt-historical-attempt",
            finished_callback=self._ownership.release,
        )
        self._admit("historical attempt", call=call)
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
            if self._is_rate_limit_error(exc):
                raise self._record_rate_limit() from exc
            if _is_provider_availability_error(exc):
                raise ProviderAvailabilityError(
                    f"CCXT provider unavailable while resolving Binance USD-M "
                    f"market {provider_symbol}"
                ) from exc
            raise DataIngestionError(
                f"CCXT could not resolve Binance USD-M market {provider_symbol}"
            ) from exc
        except TimeoutError as exc:
            raise ProviderAvailabilityError(
                f"CCXT provider unavailable while resolving Binance USD-M market "
                f"{provider_symbol}"
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
        call: OwnedAsyncCall | None = None
        loop = asyncio.get_running_loop()
        try:
            await self._drain_owned_calls()
            call = OwnedAsyncCall(
                loop=loop,
                operation=self.exchange.close,
                name="ccxt-exchange-close",
                finished_callback=self._finish_close_call,
            )
            self._admit(
                "exchange close",
                call=call,
                exclusive=True,
                allow_closing=True,
            )
            self._close_call = call
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
                if call.failed or self._ownership.quarantined:
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
