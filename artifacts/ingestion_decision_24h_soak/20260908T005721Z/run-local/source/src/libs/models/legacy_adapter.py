"""LegacyScoringAdapter — wraps a BaseModel to emit ScoringOutput.

.. deprecated::
    ``LegacyScoringAdapter`` will be removed once all models migrate to
    native scoring mode.  Prefer implementing ``ScoringModel`` directly.
"""

from __future__ import annotations

import warnings
from typing import Any

import pandas as pd

from libs.contracts.schemas import FeatureVector
from libs.contracts.signal import ScoringOutput
from libs.models.base import BaseModel, ModelMeta
from libs.models.scoring_base import ScoringModel


class LegacyScoringAdapter(ScoringModel):
    """Wraps a BaseModel instance to participate in the scoring pipeline.

    Converts ModelOutput(direction, conviction) → ScoringOutput(edge_score)
    where edge_score = direction * conviction.

    .. deprecated::
        Use native ``ScoringModel`` subclasses instead.
    """

    def __init__(self, wrapped: BaseModel) -> None:
        warnings.warn(
            "LegacyScoringAdapter is deprecated and will be removed in a "
            "future version. Implement ScoringModel directly instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Do NOT call super().__init__() — we delegate everything to wrapped
        self._wrapped = wrapped
        self.params = wrapped.params

    @property
    def meta(self) -> ModelMeta:
        return self._wrapped.meta

    def evaluate(self, features: FeatureVector) -> ScoringOutput:
        """Evaluate wrapped model, convert ModelOutput → ScoringOutput."""
        model_output = self._wrapped.evaluate(features)
        edge_score = float(model_output.direction) * model_output.conviction
        return ScoringOutput(
            model_name=model_output.model_name,
            asset=model_output.asset,
            timeframe=model_output.timeframe,
            timestamp=model_output.timestamp,
            edge_score=edge_score,
            conviction=model_output.conviction,
            metadata={
                **model_output.metadata,
                "_adapted": True,
                "_original_direction": model_output.direction,
            },
        )

    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        """Batch evaluate via wrapped model's batch_evaluate.

        BaseModel.batch_evaluate() returns int directions (-1, 0, 1).
        In adapted mode, these are treated as edge_scores with implicit
        conviction=1.0, preserving ranking order.
        """
        return self._wrapped.batch_evaluate(feature_df).astype(float)
