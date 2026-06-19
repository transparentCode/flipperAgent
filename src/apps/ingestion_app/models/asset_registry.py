from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IngestionAssetDesiredState(str, Enum):
    LIVE = "LIVE"
    RESUMING = "RESUMING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    REMOVING = "REMOVING"


class IngestionAssetSource(str, Enum):
    REGISTRY = "registry"
    CONFIG = "config"


class IngestionAssetRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str
    exchange: str = "binance"
    provider: str = "binance_native"
    base_timeframe: str = "1m"
    publish_timeframes: list[str] = Field(default_factory=list)
    historical_backfill_days: int = 2
    retention_days: int | None = None
    enabled: bool = True
    desired_state: IngestionAssetDesiredState = IngestionAssetDesiredState.LIVE
    asset_version: int = 1
    timeframe_version: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source: IngestionAssetSource = IngestionAssetSource.REGISTRY

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return str(value).upper().strip()

    @field_validator("publish_timeframes", mode="before")
    @classmethod
    def normalize_publish_timeframes(cls, value: object) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value]
        return [str(value)]


class IngestionAssetUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    exchange: str = "binance"
    provider: str = "binance_native"
    base_timeframe: str = "1m"
    publish_timeframes: list[str] = Field(default_factory=list)
    historical_backfill_days: int = 2
    retention_days: int | None = None
    enabled: bool = True
    desired_state: IngestionAssetDesiredState = IngestionAssetDesiredState.LIVE
    request_id: str | None = None
    reason: str | None = None
    requested_by: str = "api_app"


class IngestionAssetPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exchange: str | None = None
    provider: str | None = None
    base_timeframe: str | None = None
    publish_timeframes: list[str] | None = None
    historical_backfill_days: int | None = None
    retention_days: int | None = None
    enabled: bool | None = None
    desired_state: IngestionAssetDesiredState | None = None
    request_id: str | None = None
    reason: str | None = None
    requested_by: str = "api_app"


class IngestionAssetActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str | None = None
    reason: str | None = None
    requested_by: str = "api_app"


class IngestionAssetBatchUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[IngestionAssetUpsertRequest] = Field(default_factory=list)


class IngestionAssetBatchActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbols: list[str] = Field(default_factory=list)
    desired_state: IngestionAssetDesiredState
    request_id: str | None = None
    reason: str | None = None
    requested_by: str = "api_app"

    @field_validator("symbols", mode="before")
    @classmethod
    def normalize_symbols(cls, value: object) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(item).upper().strip() for item in value]
        return [str(value).upper().strip()]


class IngestionControlResult(BaseModel):
    asset: IngestionAssetRecord
    command_id: str
    command_type: str
    request_id: str | None = None
    asset_version: int = 1
    timeframe_version: int | None = None
    command_published: bool
    event_published: bool
    lifecycle_published: bool = False
    deduplicated: bool = False
    command_stream_id: str | None = None
    event_stream_id: str | None = None
