"""MeanReversionModel — first concrete model implementation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from libs.contracts.schemas import FeatureVector, ModelOutput, ParamDef
from libs.models.base import BaseModel, ModelMeta
from libs.models.registry import ModelRegistry


@ModelRegistry.register("MeanReversion")
class MeanReversionModel(BaseModel):

    meta = ModelMeta(
        name="MeanReversion",
        required_indicators=["RSI", "BollingerBands"],
        required_fields=["RSI.value", "BollingerBands.upper", "BollingerBands.lower"],
        hyperparameter_schema={
            "rsi_oversold": ParamDef(type="int", default=30, low=15, high=40, step=1),
            "rsi_overbought": ParamDef(type="int", default=70, low=60, high=85, step=1),
            "bb_entry_std": ParamDef(type="float", default=2.0, low=1.0, high=3.0, step=0.1),
            "holding_period": ParamDef(type="int", default=5, low=1, high=20, step=1),
        },
        min_history_bars=20,
    )

    # ------------------------------------------------------------------
    # Live single-tick evaluation
    # ------------------------------------------------------------------

    def evaluate(self, features: FeatureVector) -> ModelOutput:
        rsi_value = self._extract_rsi(features.features)
        bb_upper = self._extract_bb(features.features, "upper")
        bb_lower = self._extract_bb(features.features, "lower")
        close = features.bar_data.get("close", 0.0)

        direction = 0
        conviction = 0.0
        metadata: dict[str, Any] = {"rsi_value": rsi_value, "close": close}

        if rsi_value is not None:
            if rsi_value <= self.params["rsi_oversold"] and bb_lower is not None and close <= bb_lower:
                direction = 1
                conviction = min(1.0, (self.params["rsi_oversold"] - rsi_value) / self.params["rsi_oversold"])
                metadata["trigger"] = "oversold"
            elif rsi_value >= self.params["rsi_overbought"] and bb_upper is not None and close >= bb_upper:
                direction = -1
                conviction = min(1.0, (rsi_value - self.params["rsi_overbought"]) / (100 - self.params["rsi_overbought"]))
                metadata["trigger"] = "overbought"

        return ModelOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            direction=direction,
            conviction=conviction,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Batch evaluation for optimization / backtest
    # ------------------------------------------------------------------

    def batch_evaluate(self, feature_df: pd.DataFrame) -> pd.Series:
        """Return a Series of directions (-1, 0, 1) aligned with *feature_df* index."""
        rsi = feature_df.get("RSI")
        bb_lower = feature_df.get("BollingerBands_lower")
        bb_upper = feature_df.get("BollingerBands_upper")
        close = feature_df.get("close")

        directions = pd.Series(0, index=feature_df.index)

        if rsi is not None and bb_lower is not None and close is not None:
            long_mask = (rsi <= self.params["rsi_oversold"]) & (close <= bb_lower)
            directions[long_mask] = 1

        if rsi is not None and bb_upper is not None and close is not None:
            short_mask = (rsi >= self.params["rsi_overbought"]) & (close >= bb_upper)
            directions[short_mask] = -1

        return directions

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_rsi(features: dict[str, Any]) -> float | None:
        rsi = features.get("RSI")
        if isinstance(rsi, dict):
            return rsi.get("value")
        if isinstance(rsi, (int, float)):
            return float(rsi)
        return None

    @staticmethod
    def _extract_bb(features: dict[str, Any], band: str) -> float | None:
        bb = features.get("BollingerBands")
        if isinstance(bb, dict):
            return bb.get(band)
        return None
