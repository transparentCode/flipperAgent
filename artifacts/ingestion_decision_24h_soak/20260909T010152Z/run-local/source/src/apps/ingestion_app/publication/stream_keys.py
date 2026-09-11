"""Canonical ingestion publication stream-key derivation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from urllib.parse import quote

from apps.ingestion_app.publication.outbox import OutboxEvent


def _normalize_identity_part(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be non-empty")
    return quote(normalized, safe="")


def canonical_lane_stream_key(event: OutboxEvent) -> str:
    """Derive the deterministic stream for an outbox candle event."""
    if not isinstance(event, OutboxEvent):
        raise TypeError("event must be an OutboxEvent")
    try:
        payload = json.loads(event.payload_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("outbox payload must be valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise TypeError("outbox payload must be a JSON object")

    venue = _normalize_identity_part(payload.get("venue"), field_name="venue")
    instrument_id = _normalize_identity_part(
        payload.get("instrument_id"),
        field_name="instrument_id",
    )
    timeframe = _normalize_identity_part(
        payload.get("timeframe"),
        field_name="timeframe",
    )
    return f"stream:ohlcv:ingestion:{venue}:{instrument_id}:{timeframe}"


__all__ = ["canonical_lane_stream_key"]
