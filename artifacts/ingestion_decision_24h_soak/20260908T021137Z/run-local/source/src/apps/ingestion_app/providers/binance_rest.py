"""Pure Binance REST row decoders with adapter-specific validation order."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

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


def _native_utc_from_milliseconds(value: object, *, field_name: str) -> datetime:
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


def _native_decimal_value(value: object, *, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DataIngestionError(
            f"Binance {field_name} is not a valid Decimal"
        ) from exc
    if not parsed.is_finite():
        raise DataIngestionError(f"Binance {field_name} must be finite")
    return parsed


def decode_binance_native_klines(
    raw_rows: list[Any] | tuple[Any, ...],
    *,
    lane: MarketLane,
    provider_id: str,
    provider_symbol: str,
    timeframe_duration: timedelta,
    since: datetime,
    until: datetime,
    closed_before: datetime,
    received_at: datetime,
    limit: int,
) -> tuple[CandleObservation, ...]:
    """Decode native Binance rows without moving domain validation ahead of filtering."""
    observations: list[CandleObservation] = []
    for row in raw_rows:
        if not isinstance(row, (list, tuple)) or len(row) <= _TAKER_BUY_BASE_INDEX:
            raise DataIngestionError("Binance returned a malformed kline row")
        try:
            open_time = _native_utc_from_milliseconds(
                row[_OPEN_TIME_INDEX],
                field_name="open timestamp",
            )
            provider_close_time = _native_utc_from_milliseconds(
                row[_CLOSE_TIME_INDEX],
                field_name="close timestamp",
            ) + timedelta(milliseconds=1)
            close_time = open_time + timeframe_duration
            if provider_close_time != close_time:
                raise DataIngestionError(
                    "Binance provider close timestamp disagrees with timeframe_duration"
                )
            open_price = _native_decimal_value(row[_OPEN_INDEX], field_name="open")
            high = _native_decimal_value(row[_HIGH_INDEX], field_name="high")
            low = _native_decimal_value(row[_LOW_INDEX], field_name="low")
            close = _native_decimal_value(row[_CLOSE_INDEX], field_name="close")
            volume = _native_decimal_value(row[_VOLUME_INDEX], field_name="volume")
            taker_buy_base = _native_decimal_value(
                row[_TAKER_BUY_BASE_INDEX],
                field_name="taker_buy_base",
            )
        except DataIngestionError:
            raise
        except (IndexError, OverflowError, TypeError, ValueError) as exc:
            raise DataIngestionError("Binance returned an invalid kline row") from exc

        # Native Binance historically filters the caller's window before the
        # CandleObservation invariant check.  Keep this order: it is an
        # adapter-specific compatibility contract.
        if not (since <= open_time < until and close_time <= closed_before):
            continue
        try:
            observation = CandleObservation(
                lane=lane,
                provider_id=provider_id,
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
            raise DataIngestionError("Binance returned invalid candle values") from exc
        observations.append(observation)

    observations.sort(key=lambda observation: observation.open_time)
    return tuple(observations[:limit])


def _ccxt_utc_from_milliseconds(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise DataIngestionError("CCXT timestamp must be an integer millisecond value")
    try:
        milliseconds = int(value)
        return _EPOCH + timedelta(milliseconds=milliseconds)
    except (OverflowError, TypeError, ValueError) as exc:
        raise DataIngestionError(
            "CCXT timestamp is not a valid millisecond value"
        ) from exc


def _ccxt_decimal_value(value: object, *, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DataIngestionError(f"CCXT {field_name} is not a valid Decimal") from exc
    if not parsed.is_finite():
        raise DataIngestionError(f"CCXT {field_name} must be finite")
    return parsed


def decode_ccxt_ohlcv_rows(
    raw_rows: list[Any] | tuple[Any, ...],
    *,
    lane: MarketLane,
    provider_id: str,
    provider_symbol: str,
    timeframe_duration: timedelta,
    since: datetime,
    until: datetime,
    closed_before: datetime,
    received_at: datetime,
    limit: int,
) -> tuple[CandleObservation, ...]:
    """Decode CCXT rows while preserving its pre-filter volume validation."""
    observations: list[CandleObservation] = []
    for row in raw_rows:
        if not isinstance(row, (list, tuple)) or len(row) <= 9:
            raise DataIngestionError(
                "CCXT Binance USD-M returned a malformed kline row"
            )
        try:
            open_time = _ccxt_utc_from_milliseconds(row[0])
            provider_close_time = _ccxt_utc_from_milliseconds(row[6]) + timedelta(
                milliseconds=1
            )
            close_time = open_time + timeframe_duration
            if provider_close_time != close_time:
                raise DataIngestionError(
                    "CCXT Binance USD-M provider close timestamp disagrees "
                    "with timeframe_duration"
                )
            open_price = _ccxt_decimal_value(row[1], field_name="open")
            high = _ccxt_decimal_value(row[2], field_name="high")
            low = _ccxt_decimal_value(row[3], field_name="low")
            close = _ccxt_decimal_value(row[4], field_name="close")
            volume = _ccxt_decimal_value(row[5], field_name="volume")
            taker_buy_base = _ccxt_decimal_value(row[9], field_name="taker_buy_base")
        except DataIngestionError:
            raise
        except (IndexError, OverflowError, TypeError, ValueError) as exc:
            raise DataIngestionError(
                "CCXT Binance USD-M returned an invalid kline row"
            ) from exc

        # CCXT's adapter-specific volume/taker check intentionally precedes
        # caller-window filtering; out-of-window invalid rows still reject.
        if volume < 0 or not (Decimal(0) <= taker_buy_base <= volume):
            raise DataIngestionError(
                "CCXT Binance USD-M returned invalid volume/taker-buy values"
            )

        if not (since <= open_time < until and close_time <= closed_before):
            continue
        try:
            observation = CandleObservation(
                lane=lane,
                provider_id=provider_id,
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


__all__ = ["decode_binance_native_klines", "decode_ccxt_ohlcv_rows"]
