"""Immutable publication intent identity for ingestion."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    """One immutable publication intent stored with a canonical insert."""

    event_id: UUID
    event_type: str
    schema_version: int
    producer: str
    occurred_at: datetime
    payload_json: str


__all__ = ["OutboxEvent"]
