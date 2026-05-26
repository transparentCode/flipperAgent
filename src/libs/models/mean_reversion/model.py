"""MeanReversionModel — first concrete model implementation."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from numba import njit

from libs.contracts.schemas import FeatureVector, ModelOutput, ParamDef
from libs.models.base import BaseModel, ModelMeta
from libs.models.feature_extractors import extract_rsi
from libs.models.registry import ModelRegistry


@njit(cache=True)
def _apply_cooldown(directions_arr: np.ndarray, holding_period: int) -> np.ndarray:
    cooldown = 0
    last_dir = 0
    for i in range(len(directions_arr)):
        if cooldown > 0:
            directions_arr[i] = last_dir
            cooldown -= 1
        elif directions_arr[i] != 0:
            if last_dir != 0 and directions_arr[i] != last_dir:
                last_dir = directions_arr[i]
                cooldown = holding_period - 1
            else:
                last_dir = directions_arr[i]
    return directions_arr


@ModelRegistry.register("MeanReversion")
class MeanReversionModel(BaseModel):

    meta = ModelMeta(
        name="MeanReversion",
        required_indicators=["RSI", "BollingerBands"],
        required_fields=["RSI", "BollingerBands_upper", "BollingerBands_lower"],
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
        rsi_value = extract_rsi(features.features)
        bb_upper = self._extract_bb(features.features, "upper")
        bb_lower = self._extract_bb(features.features, "lower")
        close = features.bar_data.get("close", 0.0)

        direction = 0
        conviction = 0.0
        metadata: dict[str, Any] = {
            "rsi_value": rsi_value,
            "close": close,
            "holding_period": self.params["holding_period"],
        }

        # Recompute entry bands using bb_entry_std relative to Bollinger midline
        if bb_upper is not None and bb_lower is not None:
            bb_mid = (bb_upper + bb_lower) / 2.0
            entry_ratio = self.params["bb_entry_std"] / 2.0  # 2.0 = assumed indicator num_std
            model_lower = bb_mid - entry_ratio * (bb_mid - bb_lower)
            model_upper = bb_mid + entry_ratio * (bb_upper - bb_mid)
        else:
            model_lower = bb_lower
            model_upper = bb_upper

        if rsi_value is not None:
            if rsi_value <= self.params["rsi_oversold"] and model_lower is not None and close <= model_lower:
                direction = 1
                conviction = min(1.0, (self.params["rsi_oversold"] - rsi_value) / self.params["rsi_oversold"])
                metadata["trigger"] = "oversold"
            elif rsi_value >= self.params["rsi_overbought"] and model_upper is not None and close >= model_upper:
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

    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        """Return a Series of directions (-1, 0, 1) aligned with *feature_df* index."""
        rsi = feature_df.get("RSI")
        bb_lower = feature_df.get("BollingerBands_lower")
        bb_upper = feature_df.get("BollingerBands_upper")
        close = feature_df.get("close")

        directions = pd.Series(0, index=feature_df.index)

        # Recompute entry bands using bb_entry_std relative to Bollinger midline
        if bb_lower is not None and bb_upper is not None:
            bb_mid = (bb_upper + bb_lower) / 2.0
            entry_ratio = self.params["bb_entry_std"] / 2.0  # 2.0 = assumed indicator num_std
            model_lower = bb_mid - entry_ratio * (bb_mid - bb_lower)
            model_upper = bb_mid + entry_ratio * (bb_upper - bb_mid)
        else:
            model_lower = bb_lower
            model_upper = bb_upper

        if rsi is not None and model_lower is not None and close is not None:
            long_mask = (rsi <= self.params["rsi_oversold"]) & (close <= model_lower)
            directions[long_mask] = 1

        if rsi is not None and model_upper is not None and close is not None:
            short_mask = (rsi >= self.params["rsi_overbought"]) & (close >= model_upper)
            directions[short_mask] = -1

        # Apply holding_period cooldown to suppress whipsaw
        holding_period = self.params["holding_period"]
        if holding_period > 1:
            arr = directions.values.astype(np.float64)
            directions = pd.Series(_apply_cooldown(arr, holding_period), index=directions.index)

        return directions

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_bb(features: dict[str, Any], band: str) -> float | None:
        bb = features.get("BollingerBands")
        if isinstance(bb, dict):
            return bb.get(band)
        return None
