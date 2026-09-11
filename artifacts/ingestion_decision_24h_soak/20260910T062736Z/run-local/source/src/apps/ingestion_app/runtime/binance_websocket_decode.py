"""Pure Binance websocket payload decoding for finalized kline observations."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from apps.ingestion_app.domain.candle import CandleObservation
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.services.time_alignment import aligned_bucket_start
from libs.common.exceptions import DataIngestionError

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _utc_from_milliseconds(value: object, *, field_name: str) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise DataIngestionError(
            f"Binance websocket {field_name} must be integer milliseconds"
        )
    try:
        milliseconds = int(value)
        return _EPOCH + timedelta(milliseconds=milliseconds)
    except (OverflowError, TypeError, ValueError) as exc:
        raise DataIngestionError(
            f"Binance websocket {field_name} is not a valid timestamp"
        ) from exc


def _decimal_value(value: object, *, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise DataIngestionError(
            f"Binance websocket {field_name} is not a valid Decimal"
        ) from exc
    if not parsed.is_finite():
        raise DataIngestionError(f"Binance websocket {field_name} must be finite")
    return parsed


def decode_binance_websocket_message(
    raw_message: object,
    *,
    provider_id: str,
    routes: Mapping[str, tuple[MarketLane, str]],
    base_timeframe: str,
    timeframe_duration: timedelta,
    alignment_origin: datetime,
    received_at_fn: Callable[[], datetime],
) -> CandleObservation | None:
    """Decode one payload, sampling receive time only at observation construction."""
    if isinstance(raw_message, (str, bytes, bytearray)):
        try:
            payload = json.loads(raw_message)
        except (TypeError, ValueError) as exc:
            raise DataIngestionError("Binance websocket returned invalid JSON") from exc
    else:
        payload = raw_message

    if not isinstance(payload, Mapping):
        raise DataIngestionError("Binance websocket payload must be a mapping")

    if "data" not in payload:
        if "result" in payload and "id" in payload:
            return None
        raise DataIngestionError("Binance websocket payload is missing data")

    stream_name = payload.get("stream")
    data = payload.get("data")
    if not isinstance(stream_name, str) or not stream_name.strip():
        raise DataIngestionError("Binance websocket stream name is malformed")
    if not isinstance(data, Mapping):
        raise DataIngestionError("Binance websocket data is malformed")
    if data.get("e") != "kline":
        raise DataIngestionError("Binance websocket event is not a kline")

    kline = data.get("k")
    if not isinstance(kline, Mapping):
        raise DataIngestionError("Binance websocket kline is malformed")

    raw_symbol = kline.get("s")
    if not isinstance(raw_symbol, str) or not raw_symbol.strip():
        raise DataIngestionError("Binance websocket kline symbol is malformed")
    route = routes.get(raw_symbol.casefold())
    if route is None:
        raise DataIngestionError(
            f"Binance websocket returned unknown symbol '{raw_symbol}'"
        )
    lane, provider_symbol = route
    expected_stream = f"{provider_symbol.lower()}@kline_{base_timeframe}".casefold()
    if stream_name.casefold() != expected_stream:
        raise DataIngestionError(
            f"Binance websocket stream '{stream_name}' does not match "
            f"configured symbol '{provider_symbol}'"
        )

    if kline.get("i") != base_timeframe:
        raise DataIngestionError(
            "Binance websocket interval does not match base timeframe"
        )
    closed = kline.get("x")
    if not isinstance(closed, bool):
        raise DataIngestionError("Binance websocket kline close flag must be a boolean")
    if not closed:
        return None

    open_time = _utc_from_milliseconds(
        kline.get("t"),
        field_name="open timestamp",
    )
    provider_close_time = _utc_from_milliseconds(
        kline.get("T"),
        field_name="close timestamp",
    ) + timedelta(milliseconds=1)
    close_time = open_time + timeframe_duration
    if provider_close_time != close_time:
        raise DataIngestionError(
            "Binance websocket provider close timestamp disagrees with "
            "timeframe_duration"
        )
    if (
        aligned_bucket_start(open_time, timeframe_duration, alignment_origin)
        != open_time
    ):
        raise DataIngestionError(
            "Binance websocket open timestamp is not base-grid aligned"
        )

    try:
        open_price = _decimal_value(kline.get("o"), field_name="open")
        high = _decimal_value(kline.get("h"), field_name="high")
        low = _decimal_value(kline.get("l"), field_name="low")
        close = _decimal_value(kline.get("c"), field_name="close")
        volume = _decimal_value(kline.get("v"), field_name="volume")
        taker_buy_base = _decimal_value(
            kline.get("V"),
            field_name="taker_buy_base",
        )
        # Keep the receive-time sample at the same point as the prior inline
        # sample: after payload/value validation and immediately before the
        # domain observation is constructed.
        received_at = received_at_fn()
        observation = CandleObservation(
            lane=lane,
            provider_id=provider_id,
            provider_symbol=provider_symbol,
            transport="websocket",
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
            "Binance websocket returned invalid candle values"
        ) from exc
    return observation


__all__ = ["decode_binance_websocket_message"]
