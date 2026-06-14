from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrategyPairState(str, Enum):
    WARMING = "WARMING"
    LIVE = "LIVE"
    DEGRADED = "DEGRADED"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class StrategyPair(BaseModel):
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


class StrategyRuntimeStatus(BaseModel):
    pair: StrategyPair
    state: StrategyPairState = StrategyPairState.WARMING
    last_feature_ts: float | None = None
    last_signal_ts: float | None = None
    lag_ms: int | None = None
    last_error: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
