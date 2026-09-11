"""ScoringModel — thin BaseModel subclass for models that emit continuous edge scores."""

from __future__ import annotations

from abc import abstractmethod

import pandas as pd

from libs.contracts.schemas import FeatureVector
from libs.contracts.signal import ScoringOutput
from libs.models.base import BaseModel


class ScoringModel(BaseModel):
    """Marker subclass for models that emit ScoringOutput.

    Inherits __init__, _defaults, validate_features, validate_required_fields,
    batch_evaluate (template method) from BaseModel.
    Subclasses must implement evaluate() and _batch_evaluate_impl().
    """

    @abstractmethod
    def evaluate(self, features: FeatureVector) -> ScoringOutput:  # type: ignore[override]
        ...

    @abstractmethod
    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        ...
