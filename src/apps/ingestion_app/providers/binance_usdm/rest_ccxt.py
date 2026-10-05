"""CCXT historical REST provider for ingestion."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any

import ccxt.async_support as ccxt

from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.base import (
    ProviderAvailabilityError,
    ProviderRateLimitedError,
    TransportDeadlineExceeded,
)
from apps.ingestion_app.providers.owned_historical import OwnedHistoricalProvider
from apps.ingestion_app.providers.request import epoch_milliseconds
from apps.ingestion_app.transport.ownership import OwnedAsyncCall
from libs.common.exceptions import DataIngestionError

from .rest_decode import decode_ccxt_ohlcv_rows


def _is_provider_availability_error(error: BaseException) -> bool:
    return isinstance(error, (ccxt.NetworkError, TimeoutError)) and not isinstance(
        error,
        ccxt.InvalidNonce,
    )


class CCXTHistoricalProvider(OwnedHistoricalProvider[OwnedAsyncCall]):
    """Fetch bounded finalized Binance USD-M klines through async CCXT."""

    _provider_label = "CCXT"
    _close_operation = "exchange close"
    _close_failure_message = "CCXT exchange close failed"

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
        self.provider_id = provider_id
        super().__init__(
            attempt_timeout_seconds=attempt_timeout_seconds,
            max_concurrency=max_concurrency,
            monotonic_fn=monotonic_fn,
        )
        if exchange is not None:
            self.exchange = exchange
            return
        try:
            exchange_class = getattr(ccxt, exchange_id)
        except AttributeError as exc:
            raise ValueError(f"Unknown CCXT exchange: {exchange_id}") from exc
        self.exchange = exchange_class()

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

    def _new_close_call(self, loop: asyncio.AbstractEventLoop) -> OwnedAsyncCall:
        return OwnedAsyncCall(
            loop=loop,
            operation=self.exchange.close,
            name="ccxt-exchange-close",
            finished_callback=self._finish_close_call,
        )

    def _record_rate_limit(self) -> ProviderRateLimitedError:
        return self._note_rate_limit(
            getattr(self.exchange, "last_response_headers", None)
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


__all__ = ["CCXTHistoricalProvider"]
