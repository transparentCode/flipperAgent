"""CCXT historical REST provider for ingestion."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import ccxt.async_support as ccxt

from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
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


def _utc_from_milliseconds(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise DataIngestionError("CCXT timestamp must be an integer millisecond value")
    try:
        milliseconds = int(value)
        return _EPOCH + timedelta(milliseconds=milliseconds)
    except (OverflowError, TypeError, ValueError) as exc:
        raise DataIngestionError(
            "CCXT timestamp is not a valid millisecond value"
        ) from exc


def _decimal_value(value: object, *, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DataIngestionError(f"CCXT {field_name} is not a valid Decimal") from exc
    if not parsed.is_finite():
        raise DataIngestionError(f"CCXT {field_name} must be finite")
    return parsed


class CCXTHistoricalProvider:
    """Fetch bounded finalized Binance USD-M klines through async CCXT."""

    def __init__(
        self,
        *,
        provider_id: str,
        exchange_id: str,
        exchange: Any | None = None,
    ) -> None:
        _require_non_empty_string(provider_id, field_name="provider_id")
        _require_non_empty_string(exchange_id, field_name="exchange_id")
        self.provider_id = provider_id
        if exchange is not None:
            self.exchange = exchange
            return
        try:
            exchange_class = getattr(ccxt, exchange_id)
        except AttributeError as exc:
            raise ValueError(f"Unknown CCXT exchange: {exchange_id}") from exc
        self.exchange = exchange_class()

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

        native_symbol = await self._resolve_native_symbol(provider_symbol)
        raw_klines = getattr(self.exchange, "fapiPublicGetKlines", None)
        if not callable(raw_klines):
            raise DataIngestionError(
                "CCXT Binance USD-M client lacks fapiPublicGetKlines; "
                "taker-buy-complete klines are required"
            )

        try:
            raw_rows = await raw_klines(
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

        if not isinstance(raw_rows, (list, tuple)):
            raise DataIngestionError("CCXT returned a malformed OHLCV response")

        received_at = datetime.now(UTC)
        observations: list[CandleObservation] = []
        for row in raw_rows:
            if not isinstance(row, (list, tuple)) or len(row) <= 9:
                raise DataIngestionError(
                    "CCXT Binance USD-M returned a malformed kline row"
                )
            try:
                open_time = _utc_from_milliseconds(row[0])
                provider_close_time = _utc_from_milliseconds(row[6]) + timedelta(
                    milliseconds=1
                )
                close_time = open_time + timeframe_duration
                if provider_close_time != close_time:
                    raise DataIngestionError(
                        "CCXT Binance USD-M provider close timestamp disagrees "
                        "with timeframe_duration"
                    )
                open_price = _decimal_value(row[1], field_name="open")
                high = _decimal_value(row[2], field_name="high")
                low = _decimal_value(row[3], field_name="low")
                close = _decimal_value(row[4], field_name="close")
                volume = _decimal_value(row[5], field_name="volume")
                taker_buy_base = _decimal_value(row[9], field_name="taker_buy_base")
            except DataIngestionError:
                raise
            except (IndexError, OverflowError, TypeError, ValueError) as exc:
                raise DataIngestionError(
                    "CCXT Binance USD-M returned an invalid kline row"
                ) from exc

            if volume < 0 or not (Decimal(0) <= taker_buy_base <= volume):
                raise DataIngestionError(
                    "CCXT Binance USD-M returned invalid volume/taker-buy values"
                )

            if not (since <= open_time < until and close_time <= closed_before):
                continue
            try:
                observation = CandleObservation(
                    lane=lane,
                    provider_id=self.provider_id,
                    provider_symbol=provider_symbol,
                    transport="rest",
                    open_time=open_time,
                    close_time=close_time,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    taker_buy_base=taker_buy_base,
                    received_at=received_at,
                    provider_close_time=provider_close_time,
                    provider_event_id=None,
                )
            except (TypeError, ValueError) as exc:
                raise DataIngestionError(
                    "CCXT Binance USD-M returned invalid candle values"
                ) from exc
            observations.append(observation)

        observations.sort(key=lambda observation: observation.open_time)
        return tuple(observations[:limit])

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
        await self.exchange.close()


__all__ = ["CCXTHistoricalProvider"]
