"""ScoringModel ABC — base class for models that emit continuous edge scores."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from libs.contracts.signal import ScoringOutput
from libs.models.base import ModelMeta


class ScoringModel(ABC):
    """Base class for models that emit continuous edge scores."""

    meta: ModelMeta

    def __init__(self, params: dict[str, Any]) -> None:
        self.params = {**self._defaults(), **params}

    def _defaults(self) -> dict[str, Any]:
        return {k: v.default for k, v in self.meta.hyperparameter_schema.items()}

    def validate_features(self, available: set[str]) -> list[str]:
        return [ind for ind in self.meta.required_indicators if ind not in available]

    def validate_required_fields(self, available: set[str]) -> list[str]:
        missing: list[str] = []
        for f in self.meta.required_fields:
            prefix = f.split(".")[0] if "." in f else f
            if prefix not in available:
                missing.append(f)
        return missing

    @abstractmethod
    def evaluate(self, features) -> ScoringOutput:
        """Return a continuous edge score for the current bar."""
        ...

    @abstractmethod
    def batch_evaluate(self, feature_df: pd.DataFrame) -> pd.Series:
        """Batch edge scores for backtesting. Returns float Series."""
        ...
