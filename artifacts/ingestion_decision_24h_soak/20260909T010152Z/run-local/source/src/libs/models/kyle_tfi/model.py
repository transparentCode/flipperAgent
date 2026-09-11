"""KyleTFIModel — Informed-flow direction model using Kyle Lambda + TFI."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from libs.contracts.schemas import FeatureVector, ModelOutput, ParamDef
from libs.models.base import BaseModel, ModelMeta
from libs.models.registry import ModelRegistry


@ModelRegistry.register("KyleTFI")
class KyleTFIModel(BaseModel):

    meta = ModelMeta(
        name="KyleTFI",
        model_type="direction",
        required_indicators=["KyleLambda", "TFI", "ATR", "RSI"],
        required_fields=[
            "kyle_z",
            "kyle_regime",
            "tfi_zscore",
            "ATR",
            "RSI",
        ],
        hyperparameter_schema={
            "kyle_smooth": ParamDef(type="int", default=24, low=8, high=48, step=4),
            "kyle_lookback": ParamDef(type="int", default=200, low=50, high=300, step=50),
            "informed_z_threshold": ParamDef(
                type="float", default=1.5, low=0.5, high=2.0, step=0.25,
            ),
            "tfi_z_long": ParamDef(
                type="float", default=1.5, low=0.5, high=2.0, step=0.25,
            ),
            "tfi_z_short": ParamDef(
                type="float", default=-1.5, low=-2.0, high=-0.5, step=0.25,
            ),
            "atr_tp_mult": ParamDef(
                type="float", default=2.0, low=1.5, high=4.0, step=0.5,
            ),
            "atr_sl_mult": ParamDef(
                type="float", default=1.5, low=1.0, high=2.5, step=0.5,
            ),
        },
        min_history_bars=250,
    )

    # ------------------------------------------------------------------
    # Live single-tick evaluation
    # ------------------------------------------------------------------

    def evaluate(self, features: FeatureVector) -> ModelOutput:
        kyle_z = self._extract_float(features.features, "kyle_z")
        kyle_regime = features.features.get("kyle_regime")
        tfi_zscore = self._extract_float(features.features, "tfi_zscore")
        atr = self._extract_float(features.features, "ATR")
        rsi = self._extract_float(features.features, "RSI")
        close = features.bar_data.get("close", 0.0)

        direction = 0
        conviction = 0.0
        metadata: dict[str, Any] = {}

        if kyle_regime == "informed" and tfi_zscore is not None and rsi is not None:
            if tfi_zscore > self.params["tfi_z_long"] and rsi < 70:
                direction = 1
            elif tfi_zscore < self.params["tfi_z_short"] and rsi > 30:
                direction = -1

            if direction != 0 and kyle_z is not None:
                conviction = float(
                    np.clip(abs(tfi_zscore) / 3.0 * (kyle_z / 2.0), 0.0, 1.0)
                )

        # ATR-based TP/SL
        if atr is not None and direction != 0:
            metadata["atr_tp"] = close + direction * atr * self.params["atr_tp_mult"]
            metadata["atr_sl"] = close - direction * atr * self.params["atr_sl_mult"]

        metadata["kyle_z"] = kyle_z
        metadata["tfi_zscore"] = tfi_zscore
        metadata["kyle_regime"] = kyle_regime

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
    # Batch evaluation
    # ------------------------------------------------------------------

    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        kyle_z = feature_df.get("kyle_z")
        kyle_regime = feature_df.get("kyle_regime")
        tfi_zscore = feature_df.get("tfi_zscore")
        rsi = feature_df.get("RSI")

        directions = pd.Series(0, index=feature_df.index)

        if kyle_regime is None or tfi_zscore is None or rsi is None:
            return directions

        informed_mask = kyle_regime == "informed"
        long_mask = (
            informed_mask
            & (tfi_zscore > self.params["tfi_z_long"])
            & (rsi < 70)
        )
        short_mask = (
            informed_mask
            & (tfi_zscore < self.params["tfi_z_short"])
            & (rsi > 30)
        )

        directions[long_mask] = 1
        directions[short_mask] = -1

        return directions

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_float(features: dict[str, Any], key: str) -> float | None:
        val = features.get(key)
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, dict):
            return val.get("value")
        return None
