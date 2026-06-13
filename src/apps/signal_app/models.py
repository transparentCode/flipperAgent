from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SignalPairState(str, Enum):
    WARMING = "WARMING"
    LIVE = "LIVE"
    DEGRADED = "DEGRADED"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class SignalPair(BaseModel):
    model_config = ConfigDict(extra="ignore")

    asset: str
    timeframe: str
    enabled: bool = True
    source: str = "config"

    @field_validator("asset", mode="before")
    @classmethod
    def normalize_asset(cls, value: object) -> str:
        return str(value).upper().strip()

    @field_validator("timeframe", mode="before")
    @classmethod
    def normalize_timeframe(cls, value: object) -> str:
        return str(value).strip()

    @property
    def key(self) -> str:
        return f"{self.asset}:{self.timeframe}"


class SignalRuntimeStatus(BaseModel):
    pair: SignalPair
    state: SignalPairState = SignalPairState.WARMING
    last_input_ts: float | None = None
    last_feature_ts: float | None = None
    lag_ms: int | None = None
    last_error: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)


class SignalFeatureSnapshotRequest(BaseModel):
    asset: str
    timeframe: str
    lookback: int = Field(default=250, ge=1)
    bars: list[dict[str, float]] | None = None

    @field_validator("asset", mode="before")
    @classmethod
    def normalize_asset(cls, value: object) -> str:
        return str(value).upper().strip()

