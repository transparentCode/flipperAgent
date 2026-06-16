from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExecutionAssetState(str, Enum):
    WARMING = "WARMING"
    LIVE = "LIVE"
    DEGRADED = "DEGRADED"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class ExecutionAsset(BaseModel):
    model_config = ConfigDict(extra="ignore")

    asset: str

    @field_validator("asset", mode="before")
    @classmethod
    def normalize_asset(cls, value: object) -> str:
        return str(value).upper().strip()

    @property
    def key(self) -> str:
        return self.asset


class ExecutionRuntimeStatus(BaseModel):
    asset: ExecutionAsset
    state: ExecutionAssetState = ExecutionAssetState.WARMING
    mode: str = "paper"
    last_order_ts: float | None = None
    last_fill_ts: float | None = None
    last_failure_ts: float | None = None
    processed_count: int = 0
    failure_count: int = 0
    last_error: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class ExecutionFailureEvent(BaseModel):
    asset: str
    stream: str
    consumer_group: str
    consumer_name: str
    message_id: str
    idempotency_key: str | None = None
    timestamp: float
    error_type: str
    error_message: str
    order_side: str | None = None
    order_size: float | None = None
    requested_price: float | None = None
    order_type: str | None = None
