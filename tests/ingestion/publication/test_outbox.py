from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.ingestion_app.domain.candle import CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.publication.outbox import (
    CANDLE_COMMITTED_EVENT_TYPE,
    CANDLE_COMMITTED_PRODUCER,
    CANDLE_COMMITTED_SCHEMA_VERSION,
    build_candle_committed_event,
)


def _candle(
    *,
    source_type: str = "provider",
    source_provider: str | None = "binance_native",
    source_timeframe: str | None = None,
    taker_buy_base: Decimal | None = Decimal("4.0000"),
) -> CanonicalCandle:
    open_time = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    return CanonicalCandle(
        lane=MarketLane("binance", "BTC-TEST-PERP", "1m"),
        open_time=open_time,
        close_time=datetime(2026, 8, 9, 9, 1, tzinfo=UTC),
        open=Decimal("123.4500"),
        high=Decimal("124.0000"),
        low=Decimal("123.0000"),
        close=Decimal("123.7500"),
        volume=Decimal("10.5000"),
        taker_buy_base=taker_buy_base,
        source_type=source_type,
        source_provider=source_provider,
        source_timeframe=source_timeframe,
    )


@pytest.mark.parametrize(
    ("source_type", "source_provider", "source_timeframe", "taker_buy_base"),
    [
        ("provider", "binance_native", None, Decimal("4.0000")),
        ("derived", None, "1m", None),
    ],
)
def test_candle_event_payload_preserves_canonical_values(
    source_type: str,
    source_provider: str | None,
    source_timeframe: str | None,
    taker_buy_base: Decimal | None,
) -> None:
    event = build_candle_committed_event(
        _candle(
            source_type=source_type,
            source_provider=source_provider,
            source_timeframe=source_timeframe,
            taker_buy_base=taker_buy_base,
        )
    )
    payload = json.loads(event.payload_json)

    assert event.event_id.version == 4
    assert event.event_type == CANDLE_COMMITTED_EVENT_TYPE
    assert event.schema_version == CANDLE_COMMITTED_SCHEMA_VERSION
    assert event.producer == CANDLE_COMMITTED_PRODUCER
    assert event.occurred_at.tzinfo is not None
    assert event.occurred_at.utcoffset() == UTC.utcoffset(event.occurred_at)
    assert payload == {
        "close": "123.7500",
        "close_time": "2026-08-09T09:01:00Z",
        "high": "124.0000",
        "instrument_id": "BTC-TEST-PERP",
        "low": "123.0000",
        "open": "123.4500",
        "open_time": "2026-08-09T09:00:00Z",
        "source_provider": source_provider,
        "source_timeframe": source_timeframe,
        "source_type": source_type,
        "taker_buy_base": (None if taker_buy_base is None else str(taker_buy_base)),
        "timeframe": "1m",
        "venue": "binance",
        "volume": "10.5000",
    }
    assert all(
        isinstance(value, (str, type(None)))
        for key, value in payload.items()
        if key
        in {
            "open",
            "high",
            "low",
            "close",
            "volume",
            "taker_buy_base",
        }
    )


def test_payload_is_deterministic_for_same_candle() -> None:
    candle = _candle()

    first = build_candle_committed_event(candle)
    second = build_candle_committed_event(candle)

    assert first.payload_json == second.payload_json


def test_outbox_event_is_immutable() -> None:
    event = build_candle_committed_event(_candle())

    with pytest.raises(FrozenInstanceError):
        event.event_type = "changed"  # type: ignore[misc]
