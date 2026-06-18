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
    trigger_timeframe: str | None = None
    trigger_mode: str = "on_bar_close"
    base_timeframe: str = "1m"
    required_context_profiles: list[str] = Field(default_factory=list)
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

    @field_validator("trigger_mode", mode="before")
    @classmethod
    def normalize_trigger_mode(cls, value: object) -> str:
        return str(value).strip()

    @field_validator("base_timeframe", mode="before")
    @classmethod
    def normalize_base_timeframe(cls, value: object) -> str:
        return str(value).strip()

    @field_validator("required_context_profiles", mode="before")
    @classmethod
    def normalize_required_context_profiles(cls, value: object) -> list[str]:
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
    def key(self) -> str:
        trigger_timeframe = self.trigger_timeframe or self.timeframe
        if trigger_timeframe == self.timeframe:
            return f"{self.asset}:{self.timeframe}"
        return f"{self.asset}:{self.timeframe}@{trigger_timeframe}"


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
