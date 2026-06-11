"""Ingestion control-plane contracts."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class IngestionCommandType(str, Enum):
    UPSERT_ASSET = "UPSERT_ASSET"
    UPDATE_ASSET = "UPDATE_ASSET"
    PAUSE_ASSET = "PAUSE_ASSET"
    RESUME_ASSET = "RESUME_ASSET"
    REMOVE_ASSET = "REMOVE_ASSET"


class IngestionEventType(str, Enum):
    COMMAND_ACCEPTED = "COMMAND_ACCEPTED"


class IngestionControlCommand(BaseModel):
    command_id: str
    command_type: IngestionCommandType
    symbol: str
    exchange: str = "binance"
    provider: str = "binance_native"
    base_timeframe: str = "1m"
    publish_timeframes: list[str] = Field(default_factory=list)
    historical_backfill_days: int = 2
    retention_days: int | None = None
    enabled: bool = True
    desired_state: str = "LIVE"
    requested_by: str = "api_app"
    reason: str | None = None
    requested_at: float


class IngestionControlEvent(BaseModel):
    event_id: str
    event_type: IngestionEventType
    command_id: str
    command_type: IngestionCommandType
    symbol: str
    status: Literal["accepted"] = "accepted"
    requested_by: str = "api_app"
    detail: dict[str, Any] = Field(default_factory=dict)
    emitted_at: float


__all__ = [
    "IngestionCommandType",
    "IngestionControlCommand",
    "IngestionControlEvent",
    "IngestionEventType",
]
