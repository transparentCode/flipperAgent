"""Canonical strategy-model contracts for the unified model interface."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from libs.contracts.signal import FeatureVector


TriggerMode = Literal["on_bar_close", "every_bar_close", "on_base_bar_close"]
DirectionHint = Literal[-1, 0, 1]
ModelOutputMode = Literal["scoring"]


class ModelTriggerSpec(BaseModel):
    """When and on which cadence a model should evaluate."""

    decision_timeframe: str = Field(..., min_length=1)
    base_timeframe: str = Field(default="1m", min_length=1)
    trigger_mode: TriggerMode = Field(default="on_bar_close")
    trigger_timeframe: str | None = Field(default=None)

    @model_validator(mode="after")
    def _default_trigger_timeframe(self) -> "ModelTriggerSpec":
        if not self.trigger_timeframe:
            self.trigger_timeframe = (
                self.base_timeframe
                if self.trigger_mode == "on_base_bar_close"
                else self.decision_timeframe
            )
        return self


class ModelInputContract(BaseModel):
    """Declarative data requirements for a strategy model."""

    required_indicators: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    required_context_profiles: list[str] = Field(default_factory=list)
    required_bar_fields: list[str] = Field(default_factory=list)
    external_data_sources: list[str] = Field(default_factory=list)
    warmup_bars: int = Field(default=0, ge=0)


class StrategyModelSpec(BaseModel):
    """Canonical model metadata for routing, validation, and tooling."""

    name: str = Field(..., min_length=1)
    version: str = Field(default="v2", min_length=1)
    output_mode: ModelOutputMode = Field(default="scoring")
    stateful: bool = Field(default=False)
    trainable: bool = Field(default=False)
    private_feature_engineering: bool = Field(default=False)
    description: str = Field(default="")
    tags: list[str] = Field(default_factory=list)


class ModelExecutionContext(BaseModel):
    """Runtime payload supplied to a canonical strategy model."""

    feature_vector: FeatureVector
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
    context_views: dict[str, Any] = Field(default_factory=dict)
    bar_views: dict[str, Any] = Field(default_factory=dict)
    state_snapshot: dict[str, Any] | None = Field(default=None)

    @property
    def asset(self) -> str:
        return self.feature_vector.asset

    @property
    def timeframe(self) -> str:
        return self.feature_vector.timeframe

    @property
    def timestamp(self) -> float:
        return float(self.feature_vector.timestamp)


class ModelDecision(BaseModel):
    """Unified model output consumed by strategy selection and publishing."""

    model_name: str
    asset: str
    decision_timeframe: str
    trigger_timeframe: str
    timestamp: float
    score: float
    direction_hint: DirectionHint = Field(default=0)
    conviction: float = Field(default=1.0, ge=0.0, le=1.0)
    explanations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "DirectionHint",
    "ModelDecision",
    "ModelExecutionContext",
    "ModelInputContract",
    "ModelOutputMode",
    "ModelTriggerSpec",
    "StrategyModelSpec",
    "TriggerMode",
]
