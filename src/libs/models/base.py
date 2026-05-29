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
    model_type: str = "direction"
    external_data_sources: list[str] = field(default_factory=list)
    sub_models: list[str] = field(default_factory=list)
    artifacts_path: str | None = None
    trainable: bool = False


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

    def validate_required_fields(self, available: set[str]) -> list[str]:
        """Return required fields whose indicator prefix is not in *available*."""
        missing: list[str] = []
        for f in self.meta.required_fields:
            prefix = f.split(".")[0] if "." in f else f
            if prefix not in available:
                missing.append(f)
        return missing

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    @abstractmethod
    def evaluate(self, features: FeatureVector) -> ModelOutput:
        """Single-tick evaluation for live inference."""
        ...

    # ------------------------------------------------------------------
    # Batch evaluation — Template Method with temporal guard
    # ------------------------------------------------------------------

    def batch_evaluate(self, feature_df: pd.DataFrame) -> pd.Series:
        """Validate temporal ordering, delegate to subclass, validate result."""
        self._validate_temporal_ordering(feature_df)
        result = self._batch_evaluate_impl(feature_df)
        self._validate_result_alignment(feature_df, result)
        return result

    @abstractmethod
    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        """Subclass implementation of batch evaluation."""
        ...

    def _validate_temporal_ordering(self, df: pd.DataFrame) -> None:
        """Raise if DataFrame index is not monotonically non-decreasing."""
        if hasattr(df.index, "is_monotonic_increasing"):
            if not df.index.is_monotonic_increasing:
                raise ValueError(
                    f"{self.meta.name}: batch_evaluate input index is not "
                    "monotonically increasing — possible temporal ordering violation."
                )

    def _validate_result_alignment(self, df: pd.DataFrame, result: pd.Series) -> None:
        """Raise if result length doesn't match input."""
        if len(result) != len(df):
            raise ValueError(
                f"{self.meta.name}: batch_evaluate result length ({len(result)}) "
                f"does not match input length ({len(df)})."
            )
