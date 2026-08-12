from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from apps.ingestion_app.publication.outbox import OutboxEvent
from apps.ingestion_app.publication.stream_keys import canonical_lane_stream_key


def _event(payload: object) -> OutboxEvent:
    return OutboxEvent(
        event_id=uuid4(),
        event_type="candle.committed",
        schema_version=1,
        producer="ingestion",
        occurred_at=datetime(2026, 8, 9, tzinfo=UTC),
        payload_json=json.dumps(payload),
    )


def test_canonical_lane_stream_key_trims_identity_without_casefolding() -> None:
    event = _event(
        {
            "venue": " binance ",
            "instrument_id": " BTC-USDT-PERP ",
            "timeframe": " 1m ",
        }
    )

    assert canonical_lane_stream_key(event) == (
        "stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1m"
    )


@pytest.mark.parametrize(
    ("field_name", "left", "right"),
    [
        ("instrument_id", "ABC", "abc"),
        ("venue", "BINANCE", "binance"),
        ("timeframe", "1M", "1m"),
    ],
)
def test_identity_case_is_collision_safe(
    field_name: str,
    left: str,
    right: str,
) -> None:
    base_payload = {
        "venue": "binance",
        "instrument_id": "BTC-USDT-PERP",
        "timeframe": "1m",
    }
    left_payload = {**base_payload, field_name: left}
    right_payload = {**base_payload, field_name: right}

    assert canonical_lane_stream_key(_event(left_payload)) != (
        canonical_lane_stream_key(_event(right_payload))
    )


@pytest.mark.parametrize(
    ("instrument_id", "encoded"),
    [
        ("BTC:USDT:PERP", "BTC%3AUSDT%3APERP"),
        ("BTC/USDT PERP", "BTC%2FUSDT%20PERP"),
        ("BTC%3AUSDT", "BTC%253AUSDT"),
    ],
)
def test_canonical_lane_stream_key_encodes_identity_segments(
    instrument_id: str,
    encoded: str,
) -> None:
    event = _event(
        {
            "venue": " binance ",
            "instrument_id": instrument_id,
            "timeframe": "1m",
        }
    )

    assert canonical_lane_stream_key(event) == (
        f"stream:ohlcv:ingestion:binance:{encoded}:1m"
    )


def test_encoded_identity_segments_are_collision_safe() -> None:
    colon_key = canonical_lane_stream_key(
        _event(
            {
                "venue": "binance",
                "instrument_id": "A:B",
                "timeframe": "1m",
            }
        )
    )
    escaped_key = canonical_lane_stream_key(
        _event(
            {
                "venue": "binance",
                "instrument_id": "A%3AB",
                "timeframe": "1m",
            }
        )
    )

    assert colon_key != escaped_key


@pytest.mark.parametrize(
    "payload",
    [
        "not-an-object",
        {"venue": "binance", "instrument_id": "BTC-USDT-PERP"},
        {"venue": "", "instrument_id": "BTC-USDT-PERP", "timeframe": "1m"},
        {"venue": " ", "instrument_id": "BTC-USDT-PERP", "timeframe": "1m"},
        {"venue": "binance", "instrument_id": " ", "timeframe": "1m"},
        {"venue": "binance", "instrument_id": "BTC-USDT-PERP", "timeframe": " "},
        {"venue": "binance", "instrument_id": 123, "timeframe": "1m"},
    ],
)
def test_canonical_lane_stream_key_rejects_malformed_identity(payload: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        canonical_lane_stream_key(_event(payload))


def test_canonical_lane_stream_key_rejects_invalid_json() -> None:
    event = _event({})
    invalid = OutboxEvent(
        event_id=event.event_id,
        event_type=event.event_type,
        schema_version=event.schema_version,
        producer=event.producer,
        occurred_at=event.occurred_at,
        payload_json="{invalid",
    )

    with pytest.raises(ValueError, match="valid JSON"):
        canonical_lane_stream_key(invalid)
