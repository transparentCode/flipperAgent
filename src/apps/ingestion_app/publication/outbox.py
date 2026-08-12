"""The single canonical-candle outbox event contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from apps.ingestion_app.domain.candle import CanonicalCandle

CANDLE_COMMITTED_EVENT_TYPE = "candle.committed"
CANDLE_COMMITTED_SCHEMA_VERSION = 1
CANDLE_COMMITTED_PRODUCER = "ingestion"


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    """One immutable publication intent stored with a canonical insert."""

    event_id: UUID
    event_type: str
    schema_version: int
    producer: str
    occurred_at: datetime
    payload_json: str


def _utc_isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_candle_committed_event(candle: CanonicalCandle) -> OutboxEvent:
    """Build the stable JSON payload for a newly committed canonical candle."""
    payload = {
        "venue": candle.lane.venue,
        "instrument_id": candle.lane.instrument_id,
        "timeframe": candle.lane.timeframe,
        "open_time": _utc_isoformat(candle.open_time),
        "close_time": _utc_isoformat(candle.close_time),
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "volume": str(candle.volume),
        "taker_buy_base": (
            None if candle.taker_buy_base is None else str(candle.taker_buy_base)
        ),
        "source_type": candle.source_type,
        "source_provider": candle.source_provider,
        "source_timeframe": candle.source_timeframe,
    }
    return OutboxEvent(
        event_id=uuid4(),
        event_type=CANDLE_COMMITTED_EVENT_TYPE,
        schema_version=CANDLE_COMMITTED_SCHEMA_VERSION,
        producer=CANDLE_COMMITTED_PRODUCER,
        occurred_at=datetime.now(UTC),
        payload_json=json.dumps(payload, separators=(",", ":"), sort_keys=True),
    )


__all__ = [
    "CANDLE_COMMITTED_EVENT_TYPE",
    "CANDLE_COMMITTED_PRODUCER",
    "CANDLE_COMMITTED_SCHEMA_VERSION",
    "OutboxEvent",
    "build_candle_committed_event",
]
