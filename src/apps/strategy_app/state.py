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
    trigger_timeframe: str | None = None
    base_timeframe: str = "1m"
    trigger_mode: str = "on_bar_close"
    model_names: list[str] = Field(default_factory=list)
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

    @field_validator("trigger_timeframe", mode="before")
    @classmethod
    def normalize_trigger_timeframe(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("base_timeframe", mode="before")
    @classmethod
    def normalize_base_timeframe(cls, value: object) -> str:
        return str(value).strip()

    @field_validator("trigger_mode", mode="before")
    @classmethod
    def normalize_trigger_mode(cls, value: object) -> str:
        return str(value).strip()

    @field_validator("model_names", mode="before")
    @classmethod
    def normalize_model_names(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            items = [value]
        else:
            items = list(value)
        ordered: list[str] = []
        for item in items:
            normalized = str(item).strip()
            if normalized and normalized not in ordered:
                ordered.append(normalized)
        return ordered

    @property
    def decision_timeframe(self) -> str:
        return self.timeframe

    @property
    def key(self) -> str:
        trigger_timeframe = self.trigger_timeframe or self.timeframe
        if trigger_timeframe == self.timeframe:
            return f"{self.asset}:{self.timeframe}"
        return f"{self.asset}:{self.timeframe}@{trigger_timeframe}"


class StrategyRuntimeStatus(BaseModel):
    pair: StrategyPair
    state: StrategyPairState = StrategyPairState.WARMING
    last_feature_ts: float | None = None
    last_signal_ts: float | None = None
    lag_ms: int | None = None
    last_error: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
