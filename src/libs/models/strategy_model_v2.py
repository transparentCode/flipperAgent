"""Canonical strategy-model base for future unified model integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from libs.contracts.strategy_model import (
    ModelDecision,
    ModelExecutionContext,
    ModelInputContract,
    ModelTriggerSpec,
    StrategyModelSpec,
)


class StrategyModelV2(ABC):
    """Single canonical interface for future strategy models."""

    spec: StrategyModelSpec
    trigger: ModelTriggerSpec
    inputs: ModelInputContract
    param_schema: dict[str, Any] = {}

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = {**self._defaults(), **(params or {})}

    def _defaults(self) -> dict[str, Any]:
        defaults: dict[str, Any] = {}
        for key, definition in self.param_schema.items():
            default = getattr(definition, "default", None)
            defaults[key] = default
        return defaults

    def validate_feature_coverage(self, available_features: set[str]) -> list[str]:
        return [
            indicator
            for indicator in self.inputs.required_indicators
            if indicator not in available_features
        ]

    def validate_required_fields(self, available_features: set[str]) -> list[str]:
        missing: list[str] = []
        for field_name in self.inputs.required_fields:
            prefix = field_name.split(".")[0] if "." in field_name else field_name
            if prefix not in available_features:
                missing.append(field_name)
        return missing

    def validate_context_profiles(self, available_profiles: set[str]) -> list[str]:
        return [
            profile
            for profile in self.inputs.required_context_profiles
            if profile not in available_profiles
        ]

    @abstractmethod
    def evaluate(self, context: ModelExecutionContext) -> ModelDecision:
        """Evaluate a single canonical execution context."""

    def batch_evaluate(self, contexts: list[ModelExecutionContext]) -> list[ModelDecision]:
        return [self.evaluate(context) for context in contexts]


__all__ = ["StrategyModelV2"]
