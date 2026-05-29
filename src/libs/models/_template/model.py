"""Minimal BaseModel subclass template.

Copy this file into your new model directory and customise.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from libs.contracts.schemas import FeatureVector, ModelOutput, ParamDef
from libs.models.base import BaseModel, ModelMeta
from libs.models.registry import ModelRegistry


# Uncomment and rename when ready to register:
# @ModelRegistry.register("MyNewModel")
class _TemplateModel(BaseModel):
    """Replace with a one-line description of the model."""

    meta = ModelMeta(
        name="_TemplateModel",
        model_type="direction",  # or "scoring"
        required_indicators=[
            # e.g. "RSI", "BollingerBands"
        ],
        required_fields=[
            # e.g. "RSI", "BollingerBands_upper", "BollingerBands_lower"
        ],
        hyperparameter_schema={
            # "param_name": ParamDef(type="float", default=1.0, low=0.1, high=5.0, step=0.1),
        },
        min_history_bars=20,
    )

    def evaluate(self, features: FeatureVector) -> ModelOutput:
        """Return a ModelOutput (or ScoringOutput for scoring models)."""
        return ModelOutput(
            model_name=self.meta.name,
            direction=0,
            conviction=0.0,
            metadata={},
        )

    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        """Return a float Series of model scores aligned with *feature_df* index."""
        return pd.Series(0.0, index=feature_df.index)
