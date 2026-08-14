"""Decision-owned parser for the canonical ingestion candle stream.

This is an adapter for an external protocol.  It deliberately does not import
the ingestion application's domain or storage packages.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from apps.decision_app.market_state import (
    MarketSeriesKey,
    TimeframeGrid,
    validate_canonical_bar_geometry,
)
from libs.contracts.decision import CausalBarView, require_utc

INGESTION_STREAM_PREFIX = "stream:ohlcv:ingestion:"
INGESTION_EVENT_TYPE = "candle.committed"
INGESTION_SCHEMA_VERSION = 1
INGESTION_PRODUCER = "ingestion"


class CanonicalIngestionEventError(ValueError):
    """Raised when a transport event violates the canonical contract."""


def _text(value: object, field_name: str) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str) or not value.strip():
        raise CanonicalIngestionEventError(f"{field_name} must be non-empty text")
    return value.strip()


def _field(fields: Mapping[object, object], name: str) -> object:
    if name in fields:
        return fields[name]
    encoded = name.encode("utf-8")
    if encoded in fields:
        return fields[encoded]
    raise CanonicalIngestionEventError(f"missing stream field: {name}")


def _parse_utc(value: object, field_name: str) -> datetime:
    text = _text(value, field_name)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CanonicalIngestionEventError(
            f"{field_name} must be an ISO-8601 datetime"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise CanonicalIngestionEventError(f"{field_name} must be aware UTC")
    return parsed.astimezone(UTC)


def _decimal(value: object, field_name: str) -> Decimal:
    text = _text(value, field_name)
    try:
        result = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise CanonicalIngestionEventError(
            f"{field_name} must be Decimal text"
        ) from exc
    if not result.is_finite():
        raise CanonicalIngestionEventError(f"{field_name} must be finite")
    return result


def _encoded_identity(value: str) -> str:
    return quote(value, safe="")


def canonical_ingestion_stream_key(series_key: MarketSeriesKey) -> str:
    """Return the exact external stream identity for a canonical series."""

    if not isinstance(series_key, MarketSeriesKey):
        raise TypeError("series_key must be MarketSeriesKey")
    return (
        f"{INGESTION_STREAM_PREFIX}{_encoded_identity(series_key.venue)}:"
        f"{_encoded_identity(series_key.instrument_id)}:"
        f"{_encoded_identity(series_key.timeframe)}"
    )


def _parse_payload(value: object) -> Mapping[object, object]:
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if not isinstance(value, str):
        raise CanonicalIngestionEventError("payload must be JSON text")
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CanonicalIngestionEventError("payload must be valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise CanonicalIngestionEventError("payload must be a JSON object")
    return payload


def _payload_value(payload: Mapping[object, object], name: str) -> object:
    if name not in payload:
        raise CanonicalIngestionEventError(f"missing payload field: {name}")
    return payload[name]


def validate_canonical_provenance(
    source_type: object,
    source_provider: object,
    source_timeframe: object,
) -> tuple[str, str | None, str | None]:
    """Validate the canonical provider/derived provenance contract.

    ``source_timeframe`` identifies the source series for a derived candle; it
    is not the target candle timeframe.  The target geometry is validated
    separately against the requested canonical series.
    """

    normalized_type = _text(source_type, "source_type")
    provider = (
        None if source_provider is None else _text(source_provider, "source_provider")
    )
    source = (
        None
        if source_timeframe is None
        else _text(source_timeframe, "source_timeframe")
    )
    if normalized_type == "provider":
        if provider is None or source is not None:
            raise CanonicalIngestionEventError(
                "provider source metadata is inconsistent"
            )
    elif normalized_type == "derived":
        if provider is not None or source is None:
            raise CanonicalIngestionEventError(
                "derived source metadata is inconsistent"
            )
    else:
        raise CanonicalIngestionEventError("source_type must be provider or derived")
    return normalized_type, provider, source


@dataclass(frozen=True, slots=True, kw_only=True)
class CanonicalMarketEvent:
    """Validated one-event view shared by startup capture and history tests."""

    stream_key: str
    stream_id: str
    event_id: str
    occurred_at: datetime
    series_key: MarketSeriesKey
    bar: CausalBarView
    source_type: str
    source_provider: str | None
    source_timeframe: str | None

    def __post_init__(self) -> None:
        if not self.stream_key.startswith(INGESTION_STREAM_PREFIX):
            raise CanonicalIngestionEventError("stream key is not canonical ingestion")
        _text(self.stream_id, "stream_id")
        _text(self.event_id, "event_id")
        require_utc(self.occurred_at, field_name="occurred_at")
        if not isinstance(self.series_key, MarketSeriesKey):
            raise TypeError("series_key must be MarketSeriesKey")
        if self.stream_key != canonical_ingestion_stream_key(self.series_key):
            raise CanonicalIngestionEventError("stream key does not match series")
        if not isinstance(self.bar, CausalBarView) or not self.bar.closed:
            raise CanonicalIngestionEventError(
                "event bar must be a closed CausalBarView"
            )
        validate_canonical_provenance(
            self.source_type,
            self.source_provider,
            self.source_timeframe,
        )


def parse_canonical_ingestion_event(
    *,
    stream_key: object,
    stream_id: object,
    fields: Mapping[object, object],
    expected_series: MarketSeriesKey | None = None,
    timeframe_grid: TimeframeGrid | None = None,
) -> CanonicalMarketEvent:
    """Parse one Valkey stream record without inferring any timestamp units."""

    if not isinstance(fields, Mapping):
        raise TypeError("stream fields must be a mapping")
    normalized_stream_key = _text(stream_key, "stream_key")
    normalized_stream_id = _text(stream_id, "stream_id")
    event_type = _text(_field(fields, "event_type"), "event_type")
    if event_type != INGESTION_EVENT_TYPE:
        raise CanonicalIngestionEventError("unsupported ingestion event_type")
    schema_value = _field(fields, "schema_version")
    try:
        schema_version = int(_text(schema_value, "schema_version"))
    except ValueError as exc:
        raise CanonicalIngestionEventError(
            "schema_version must be integer text"
        ) from exc
    if schema_version != INGESTION_SCHEMA_VERSION:
        raise CanonicalIngestionEventError("unsupported ingestion schema_version")
    if _text(_field(fields, "producer"), "producer") != INGESTION_PRODUCER:
        raise CanonicalIngestionEventError("unsupported ingestion producer")
    event_id = _text(_field(fields, "event_id"), "event_id")
    occurred_at = _parse_utc(_field(fields, "occurred_at"), "occurred_at")
    payload = _parse_payload(_field(fields, "payload"))

    venue = _text(_payload_value(payload, "venue"), "payload.venue")
    instrument_id = _text(
        _payload_value(payload, "instrument_id"), "payload.instrument_id"
    )
    timeframe = _text(_payload_value(payload, "timeframe"), "payload.timeframe")
    if normalized_stream_key != canonical_ingestion_stream_key(
        MarketSeriesKey(
            asset=(expected_series.asset if expected_series is not None else "_"),
            venue=venue,
            instrument_id=instrument_id,
            timeframe=timeframe,
        )
    ):
        raise CanonicalIngestionEventError("stream key does not match payload identity")

    if expected_series is not None and (
        expected_series.venue != venue
        or expected_series.instrument_id != instrument_id
        or expected_series.timeframe != timeframe
    ):
        raise CanonicalIngestionEventError(
            "event series does not match expected series"
        )
    series_key = expected_series or MarketSeriesKey(
        asset=instrument_id,
        venue=venue,
        instrument_id=instrument_id,
        timeframe=timeframe,
    )
    open_time = _parse_utc(_payload_value(payload, "open_time"), "payload.open_time")
    close_time = _parse_utc(_payload_value(payload, "close_time"), "payload.close_time")
    if close_time <= open_time:
        raise CanonicalIngestionEventError("close_time must be after open_time")
    volume = _decimal(_payload_value(payload, "volume"), "payload.volume")
    taker_value = _payload_value(payload, "taker_buy_base")
    taker_buy_base = (
        None if taker_value is None else _decimal(taker_value, "payload.taker_buy_base")
    )
    if volume < 0:
        raise CanonicalIngestionEventError("volume must be non-negative")
    if taker_buy_base is not None and not 0 <= taker_buy_base <= volume:
        raise CanonicalIngestionEventError("taker_buy_base must be within volume")
    bar = CausalBarView(
        timeframe=timeframe,
        bar_open_at=open_time,
        bar_close_at=close_time,
        market_as_of=close_time,
        open=_decimal(_payload_value(payload, "open"), "payload.open"),
        high=_decimal(_payload_value(payload, "high"), "payload.high"),
        low=_decimal(_payload_value(payload, "low"), "payload.low"),
        close=_decimal(_payload_value(payload, "close"), "payload.close"),
        volume=volume,
        taker_buy_base=taker_buy_base,
        closed=True,
    )
    if timeframe_grid is not None:
        validate_canonical_bar_geometry(series_key, bar, timeframe_grid)
    source_type, source_provider, source_timeframe = validate_canonical_provenance(
        _payload_value(payload, "source_type"),
        _payload_value(payload, "source_provider"),
        _payload_value(payload, "source_timeframe"),
    )
    return CanonicalMarketEvent(
        stream_key=normalized_stream_key,
        stream_id=normalized_stream_id,
        event_id=event_id,
        occurred_at=occurred_at,
        series_key=series_key,
        bar=bar,
        source_type=source_type,
        source_provider=source_provider,
        source_timeframe=source_timeframe,
    )


__all__ = [
    "INGESTION_EVENT_TYPE",
    "INGESTION_PRODUCER",
    "INGESTION_SCHEMA_VERSION",
    "INGESTION_STREAM_PREFIX",
    "CanonicalIngestionEventError",
    "CanonicalMarketEvent",
    "canonical_ingestion_stream_key",
    "parse_canonical_ingestion_event",
    "validate_canonical_provenance",
]
