"""BaseModel ABC and ModelMeta dataclass for declarative model definitions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from libs.contracts.schemas import FeatureVector, ModelOutput, ParamDef


@dataclass(frozen=True)
class ModelMeta:
    """Declarative metadata each model exposes."""

    name: str
    required_indicators: list[str]
    required_fields: list[str]
    hyperparameter_schema: dict[str, ParamDef] = field(default_factory=dict)
    min_history_bars: int = 0


class BaseModel(ABC):
    """Abstract base for all quantitative models."""

    meta: ModelMeta

    def __init__(self, params: dict[str, Any]) -> None:
        self.params = {**self._defaults(), **params}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _defaults(self) -> dict[str, Any]:
        """Return default values from hyperparameter_schema."""
        return {k: v.default for k, v in self.meta.hyperparameter_schema.items()}

    def validate_features(self, available: set[str]) -> list[str]:
        """Return list of missing required indicators."""
        return [ind for ind in self.meta.required_indicators if ind not in available]

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    @abstractmethod
    def evaluate(self, features: FeatureVector) -> ModelOutput:
        """Single-tick evaluation for live inference."""
        ...

    @abstractmethod
    def batch_evaluate(self, feature_df: pd.DataFrame) -> pd.Series:
        """Vectorized evaluation for backtest / optimization."""
        ...
