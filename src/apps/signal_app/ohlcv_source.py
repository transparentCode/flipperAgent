"""Signal-side OHLCV source bindings and ingestion transport adapters."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import quote

from libs.common.db.pool_manager import DBPoolManager
from libs.common.timeframes import timeframe_to_seconds
from libs.contracts.signal import StreamOHLCVPayload

OhlcvSource = Literal["ingestion"]
_EVENT_TYPE = "candle.committed"
_SCHEMA_VERSION = 1


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return normalized


@dataclass(frozen=True, slots=True)
class OhlcvSourceBinding:
    """Immutable source selection for one signal asset."""

    asset: str
    source: OhlcvSource
    venue: str
    instrument_id: str

    def __post_init__(self) -> None:
        asset = _text(self.asset, "asset").upper()
        source = _text(self.source, "source")
        if source != "ingestion":
            raise ValueError("source must be 'ingestion'")
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "venue", _text(self.venue, "venue"))
        object.__setattr__(
            self, "instrument_id", _text(self.instrument_id, "instrument_id")
        )


def parse_ohlcv_source_bindings(raw: object) -> tuple[OhlcvSourceBinding, ...]:
    """Parse explicit ingestion source bindings for every signal asset."""
    if raw is None or not isinstance(raw, Mapping) or not raw:
        raise ValueError("signal.runtime.ohlcv_sources must define explicit bindings")

    bindings: list[OhlcvSourceBinding] = []
    seen_assets: set[str] = set()
    for raw_asset, raw_binding in raw.items():
        asset = _text(raw_asset, "source binding asset").upper()
        if asset in seen_assets:
            raise ValueError(f"duplicate OHLCV source binding for {asset}")
        if not isinstance(raw_binding, Mapping):
            raise TypeError(f"OHLCV source binding for {asset} must be a mapping")
        binding = OhlcvSourceBinding(
            asset=asset,
            source=raw_binding.get("source"),
            venue=raw_binding.get("venue"),
            instrument_id=raw_binding.get("instrument_id"),
        )
        bindings.append(binding)
        seen_assets.add(asset)
    return tuple(bindings)


def stream_key_for_binding(binding: OhlcvSourceBinding, timeframe: str) -> str:
    """Return the canonical ingestion OHLCV stream key for a binding."""
    if not isinstance(binding, OhlcvSourceBinding):
        raise TypeError("binding must be an OhlcvSourceBinding")
    normalized_timeframe = _text(timeframe, "timeframe")
    return ":".join(
        (
            "stream",
            "ohlcv",
            "ingestion",
            quote(binding.venue, safe=""),
            quote(binding.instrument_id, safe=""),
            quote(normalized_timeframe, safe=""),
        )
    )


def _mapping_value(data: Mapping[object, object], key: str) -> object:
    if key in data:
        return data[key]
    encoded = key.encode()
    if encoded in data:
        return data[encoded]
    raise ValueError(f"ingestion event is missing '{key}'")


def _as_text(value: object, field_name: str) -> str:
    if isinstance(value, bytes):
        value = value.decode()
    return _text(value, field_name)


def _parse_utc(value: object, field_name: str) -> datetime:
    text = _as_text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return parsed.astimezone(UTC)


def _decimal(value: object, field_name: str) -> Decimal:
    try:
        if isinstance(value, bytes):
            value = value.decode()
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be a finite decimal")
    return parsed


def decode_ingestion_event(
    data: Mapping[object, object],
    binding: OhlcvSourceBinding,
    timeframe: str,
) -> StreamOHLCVPayload:
    """Decode and validate one ingestion ``candle.committed`` stream entry."""
    if not isinstance(data, Mapping):
        raise TypeError("ingestion event data must be a mapping")
    if binding.source != "ingestion":
        raise ValueError("ingestion event decoding requires an ingestion binding")
    normalized_timeframe = _text(timeframe, "timeframe")

    _as_text(_mapping_value(data, "event_id"), "event_id")
    if _as_text(_mapping_value(data, "event_type"), "event_type") != _EVENT_TYPE:
        raise ValueError("ingestion event_type must be candle.committed")
    schema_version = _mapping_value(data, "schema_version")
    if isinstance(schema_version, bytes):
        schema_version = schema_version.decode()
    if isinstance(schema_version, bool) or str(schema_version) != str(_SCHEMA_VERSION):
        raise ValueError("ingestion schema_version must be 1")
    if _as_text(_mapping_value(data, "producer"), "producer") != "ingestion":
        raise ValueError("ingestion event producer must be ingestion")
    occurred_at = _parse_utc(_mapping_value(data, "occurred_at"), "occurred_at")

    raw_payload = _mapping_value(data, "payload")
    if isinstance(raw_payload, bytes):
        raw_payload = raw_payload.decode()
    if isinstance(raw_payload, str):
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ValueError("ingestion payload must contain valid JSON") from exc
    else:
        payload = raw_payload
    if not isinstance(payload, Mapping):
        raise TypeError("ingestion payload must be a JSON object")

    venue = _as_text(payload.get("venue"), "payload.venue")
    instrument_id = _as_text(payload.get("instrument_id"), "payload.instrument_id")
    payload_timeframe = _as_text(payload.get("timeframe"), "payload.timeframe")
    assert binding.venue is not None
    assert binding.instrument_id is not None
    if venue != binding.venue:
        raise ValueError(
            "ingestion payload venue does not match the configured binding"
        )
    if instrument_id != binding.instrument_id:
        raise ValueError(
            "ingestion payload instrument_id does not match the configured binding"
        )
    if payload_timeframe != normalized_timeframe:
        raise ValueError(
            "ingestion payload timeframe does not match the worker timeframe"
        )

    open_time = _parse_utc(payload.get("open_time"), "payload.open_time")
    close_time = _parse_utc(payload.get("close_time"), "payload.close_time")
    duration = timedelta(seconds=timeframe_to_seconds(normalized_timeframe))
    if close_time != open_time + duration:
        raise ValueError(
            "ingestion payload close_time does not match timeframe duration"
        )
    if occurred_at < close_time:
        raise ValueError("ingestion event occurred_at cannot precede candle close_time")

    values = {
        name: _decimal(payload.get(name), f"payload.{name}")
        for name in ("open", "high", "low", "close", "volume")
    }
    taker_value = payload.get("taker_buy_base")
    if taker_value is None:
        raise ValueError("ingestion payload taker_buy_base is required")
    taker_buy_base = _decimal(taker_value, "payload.taker_buy_base")
    if values["volume"] < 0:
        raise ValueError("ingestion payload volume must be non-negative")
    if taker_buy_base < 0 or taker_buy_base > values["volume"]:
        raise ValueError("ingestion payload taker_buy_base is outside volume bounds")
    if not values["low"] <= values["open"] <= values["high"]:
        raise ValueError("ingestion payload open is outside candle range")
    if not values["low"] <= values["close"] <= values["high"]:
        raise ValueError("ingestion payload close is outside candle range")
    source_provider = payload.get("source_provider")
    source_timeframe = payload.get("source_timeframe")
    provider = (
        _as_text(source_provider, "payload.source_provider")
        if source_provider is not None
        else "ingestion_derived"
    )
    base_timeframe = (
        _as_text(source_timeframe, "payload.source_timeframe")
        if source_timeframe is not None
        else normalized_timeframe
    )

    return StreamOHLCVPayload(
        exchange=venue,
        symbol=binding.asset,
        timeframe=payload_timeframe,
        timestamp=open_time.timestamp(),
        open=float(values["open"]),
        high=float(values["high"]),
        low=float(values["low"]),
        close=float(values["close"]),
        volume=float(values["volume"]),
        taker_buy_base=float(taker_buy_base),
        bar_closed=True,
        ingestion_timestamp=occurred_at.timestamp() * 1000,
        base_timeframe=base_timeframe,
        bar_span_seconds=int(duration.total_seconds()),
        close_timestamp=close_time.timestamp(),
        publication_lag_ms=int((occurred_at - close_time).total_seconds() * 1000),
        provider=provider,
        origin="ingestion",
    )


class IngestionHistoryFetcher:
    """Fetch contiguous canonical ingestion history for a configured signal binding."""

    def __init__(self, binding: OhlcvSourceBinding, pool: Any | None = None) -> None:
        if binding.source != "ingestion":
            raise ValueError("ingestion history fetching requires an ingestion binding")
        self.binding = binding
        self.pool = pool

    async def __call__(
        self,
        asset: str,
        timeframe: str,
        lookback: int,
    ) -> list[tuple[float, ...]]:
        if not isinstance(lookback, int) or isinstance(lookback, bool) or lookback <= 0:
            raise ValueError("lookback must be a positive integer")
        if asset.strip().upper() != self.binding.asset:
            raise ValueError("history asset does not match the configured binding")
        normalized_timeframe = _text(timeframe, "timeframe")
        if timeframe_to_seconds(normalized_timeframe, default=0) <= 0:
            raise ValueError("timeframe must be a supported positive duration")
        pool = self.pool or DBPoolManager.get_reader_pool()
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT open_time, close_time, open, high, low, close,
                       volume, taker_buy_base
                FROM ingestion.candles
                WHERE venue = $1
                  AND instrument_id = $2
                  AND timeframe = $3
                ORDER BY open_time DESC
                LIMIT $4
                """,
                self.binding.venue,
                self.binding.instrument_id,
                normalized_timeframe,
                lookback,
            )

        ascending = list(reversed(rows))
        duration = timedelta(seconds=timeframe_to_seconds(normalized_timeframe))
        result: list[tuple[float, ...]] = []
        previous_open: datetime | None = None
        for row in ascending:
            open_time = _require_utc_datetime(row["open_time"], "open_time")
            close_time = _require_utc_datetime(row["close_time"], "close_time")
            if close_time != open_time + duration:
                raise ValueError("ingestion history contains invalid close geometry")
            if previous_open is not None and open_time != previous_open + duration:
                raise ValueError(
                    "ingestion history contains a gap or duplicate open time"
                )
            values = {
                name: _decimal(row[name], name)
                for name in ("open", "high", "low", "close", "volume")
            }
            taker = row["taker_buy_base"]
            if taker is None:
                raise ValueError("ingestion history contains NULL taker_buy_base")
            taker_buy_base = _decimal(taker, "taker_buy_base")
            if (
                values["volume"] < 0
                or taker_buy_base < 0
                or taker_buy_base > values["volume"]
            ):
                raise ValueError("ingestion history contains invalid volume semantics")
            if not values["low"] <= values["open"] <= values["high"]:
                raise ValueError("ingestion history contains invalid open geometry")
            if not values["low"] <= values["close"] <= values["high"]:
                raise ValueError("ingestion history contains invalid close geometry")
            result.append(
                (
                    float(values["open"]),
                    float(values["high"]),
                    float(values["low"]),
                    float(values["close"]),
                    float(values["volume"]),
                    open_time.timestamp(),
                    float(taker_buy_base),
                )
            )
            previous_open = open_time
        return result


def _require_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"ingestion history {field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"ingestion history {field_name} must be UTC")
    return value.astimezone(UTC)


__all__ = [
    "IngestionHistoryFetcher",
    "OhlcvSourceBinding",
    "decode_ingestion_event",
    "parse_ohlcv_source_bindings",
    "stream_key_for_binding",
]
