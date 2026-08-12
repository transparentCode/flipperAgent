"""Binance USD-M Futures historical REST provider for ingestion."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from binance.um_futures import UMFutures

from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
from libs.common.exceptions import DataIngestionError

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_OPEN_TIME_INDEX = 0
_OPEN_INDEX = 1
_HIGH_INDEX = 2
_LOW_INDEX = 3
_CLOSE_INDEX = 4
_VOLUME_INDEX = 5
_CLOSE_TIME_INDEX = 6
_TAKER_BUY_BASE_INDEX = 9


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


def _utc_from_milliseconds(value: object, *, field_name: str) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise DataIngestionError(
            f"Binance {field_name} must be an integer millisecond value"
        )
    try:
        milliseconds = int(value)
        return _EPOCH + timedelta(milliseconds=milliseconds)
    except (OverflowError, TypeError, ValueError) as exc:
        raise DataIngestionError(
            f"Binance {field_name} is not a valid millisecond timestamp"
        ) from exc


def _decimal_value(value: object, *, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DataIngestionError(
            f"Binance {field_name} is not a valid Decimal"
        ) from exc
    if not parsed.is_finite():
        raise DataIngestionError(f"Binance {field_name} must be finite")
    return parsed


class BinanceNativeHistoricalProvider:
    """Fetch finalized Binance USD-M Futures klines through the native SDK."""

    provider_id = "binance_native"

    def __init__(self, client: Any | None = None) -> None:
        self.client = client if client is not None else UMFutures()

    async def close(self) -> None:
        await asyncio.to_thread(self.client.session.close)

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

        try:
            raw_rows = await asyncio.to_thread(
                self.client.klines,
                provider_symbol,
                lane.timeframe,
                startTime=_epoch_milliseconds(since),
                endTime=_epoch_milliseconds(closed_before),
                limit=limit,
            )
        except Exception as exc:
            raise DataIngestionError(
                f"Binance failed to fetch klines for {provider_symbol}"
            ) from exc

        if not isinstance(raw_rows, (list, tuple)):
            raise DataIngestionError("Binance returned a malformed kline response")

        received_at = datetime.now(UTC)
        observations: list[CandleObservation] = []
        for row in raw_rows:
            if not isinstance(row, (list, tuple)) or len(row) <= _TAKER_BUY_BASE_INDEX:
                raise DataIngestionError("Binance returned a malformed kline row")
            try:
                open_time = _utc_from_milliseconds(
                    row[_OPEN_TIME_INDEX],
                    field_name="open timestamp",
                )
                provider_close_time = _utc_from_milliseconds(
                    row[_CLOSE_TIME_INDEX],
                    field_name="close timestamp",
                ) + timedelta(milliseconds=1)
                close_time = open_time + timeframe_duration
                if provider_close_time != close_time:
                    raise DataIngestionError(
                        "Binance provider close timestamp disagrees with "
                        "timeframe_duration"
                    )
                open_price = _decimal_value(row[_OPEN_INDEX], field_name="open")
                high = _decimal_value(row[_HIGH_INDEX], field_name="high")
                low = _decimal_value(row[_LOW_INDEX], field_name="low")
                close = _decimal_value(row[_CLOSE_INDEX], field_name="close")
                volume = _decimal_value(row[_VOLUME_INDEX], field_name="volume")
                taker_buy_base = _decimal_value(
                    row[_TAKER_BUY_BASE_INDEX],
                    field_name="taker_buy_base",
                )
            except DataIngestionError:
                raise
            except (IndexError, OverflowError, TypeError, ValueError) as exc:
                raise DataIngestionError(
                    "Binance returned an invalid kline row"
                ) from exc

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
                    "Binance returned invalid candle values"
                ) from exc
            observations.append(observation)

        observations.sort(key=lambda observation: observation.open_time)
        return tuple(observations[:limit])


__all__ = ["BinanceNativeHistoricalProvider"]
