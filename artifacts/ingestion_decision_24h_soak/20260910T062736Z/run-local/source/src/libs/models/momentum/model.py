"""Legacy compatibility adapter for the model-owned Momentum core."""

from __future__ import annotations

from typing import Any

import pandas as pd

from libs.contracts.schemas import FeatureVector, ModelOutput, ParamDef
from libs.models.base import BaseModel, ModelMeta
from libs.models.momentum.config import MomentumConfig
from libs.models.momentum.core import (
    MomentumObservation,
    MomentumResult,
    coerce_numeric_evidence,
    evaluate_momentum,
)
from libs.models.registry import ModelRegistry


def _extract_rsi(features: dict[str, Any]) -> float | None:
    value = features.get("RSI")
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return coerce_numeric_evidence(value, field_name="RSI")
    except (TypeError, ValueError):
        return None


def _extract_macd_field(features: dict[str, Any], field: str) -> float | None:
    macd = features.get("MACD")
    if not isinstance(macd, dict):
        return None
    value = macd.get(field)
    try:
        return coerce_numeric_evidence(value, field_name=f"MACD {field}")
    except (TypeError, ValueError):
        return None


def _batch_float(value: object) -> float:
    try:
        return coerce_numeric_evidence(value, field_name="Momentum feature")
    except (TypeError, ValueError):
        return float("nan")


@ModelRegistry.register("Momentum")
class MomentumModel(BaseModel):
    meta = ModelMeta(
        name="Momentum",
        model_type="direction",
        required_indicators=["RSI", "MACD"],
        required_fields=["RSI", "MACD_histogram", "MACD_line"],
        hyperparameter_schema={
            "rsi_long_threshold": ParamDef(
                type="int", default=55, low=50, high=70, step=1
            ),
            "rsi_short_threshold": ParamDef(
                type="int", default=45, low=30, high=50, step=1
            ),
            "require_macd_positive": ParamDef(
                type="categorical",
                default=False,
                choices=[True, False],
            ),
            "histogram_min_abs": ParamDef(
                type="float",
                default=0.0,
                low=0.0,
                high=1.0,
                step=0.01,
            ),
        },
        min_history_bars=35,
    )

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self.config = MomentumConfig.from_mapping(self.params)

    # ------------------------------------------------------------------
    # Live single-tick evaluation
    # ------------------------------------------------------------------

    def evaluate(self, features: FeatureVector) -> ModelOutput:
        rsi = _extract_rsi(features.features)
        macd_hist = _extract_macd_field(features.features, "histogram")
        macd_line = _extract_macd_field(features.features, "line")
        metadata: dict[str, Any] = {"rsi": rsi, "macd_histogram": macd_hist}

        result = MomentumResult.neutral()
        try:
            observation = MomentumObservation(
                rsi=rsi,
                macd_histogram=macd_hist,
                macd_line=(macd_line if self.config.require_macd_positive else None),
            )
            result = evaluate_momentum(observation, self.config)
        except (TypeError, ValueError):
            # Legacy callers receive a safe neutral result for malformed evidence.
            pass

        return ModelOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            direction=result.direction,
            conviction=result.conviction,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Batch evaluation
    # ------------------------------------------------------------------

    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        rsi_raw = feature_df.get("RSI")
        macd_hist_raw = feature_df.get("MACD_histogram")

        directions = pd.Series(0, index=feature_df.index, dtype="int64")

        if rsi_raw is None or macd_hist_raw is None:
            return directions

        rsi = rsi_raw.map(_batch_float)
        macd_hist = macd_hist_raw.map(_batch_float)
        valid = (
            rsi.notna() & macd_hist.notna() & rsi.between(0.0, 100.0, inclusive="both")
        )

        long_mask = (
            valid
            & (rsi > self.config.rsi_long_threshold)
            & (macd_hist > 0)
            & (macd_hist.abs() >= self.config.histogram_min_abs)
        )
        short_mask = (
            valid
            & (rsi < self.config.rsi_short_threshold)
            & (macd_hist < 0)
            & (macd_hist.abs() >= self.config.histogram_min_abs)
        )

        if self.config.require_macd_positive:
            macd_line_raw = feature_df.get("MACD_line")
            if macd_line_raw is None:
                return directions
            macd_line = macd_line_raw.map(_batch_float)
            long_mask = long_mask & (macd_line > 0)
            short_mask = short_mask & (macd_line < 0)

        directions[long_mask] = 1
        directions[short_mask] = -1

        return directions
