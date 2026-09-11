"""VPINKyleModel — VPIN toxicity + Kyle Lambda direction model."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from libs.contracts.schemas import FeatureVector, ModelOutput, ParamDef
from libs.models.base import BaseModel, ModelMeta
from libs.models.registry import ModelRegistry


@ModelRegistry.register("VPINKyle")
class VPINKyleModel(BaseModel):

    meta = ModelMeta(
        name="VPINKyle",
        model_type="direction",
        required_indicators=["VPIN", "KyleLambda", "ATR", "RSI"],
        required_fields=[
            "vpin_z",
            "net_taker_buy_ratio",
            "kyle_z",
            "kyle_regime",
            "ATR",
            "RSI",
        ],
        hyperparameter_schema={
            "vpin_z_threshold": ParamDef(
                type="float", default=1.25, low=0.75, high=2.0, step=0.25,
            ),
            "kyle_z_threshold": ParamDef(
                type="float", default=1.0, low=0.5, high=1.5, step=0.25,
            ),
            "buy_ratio_long": ParamDef(
                type="float", default=0.58, low=0.52, high=0.62, step=0.02,
            ),
            "buy_ratio_short": ParamDef(
                type="float", default=0.42, low=0.38, high=0.48, step=0.02,
            ),
            "atr_tp_mult": ParamDef(
                type="float", default=2.0, low=1.5, high=4.0, step=0.5,
            ),
            "atr_sl_mult": ParamDef(
                type="float", default=1.5, low=1.0, high=2.5, step=0.5,
            ),
        },
        min_history_bars=300,
    )

    # ------------------------------------------------------------------
    # Live single-tick evaluation
    # ------------------------------------------------------------------

    def evaluate(self, features: FeatureVector) -> ModelOutput:
        vpin_z = self._extract_float(features.features, "vpin_z")
        buy_ratio = self._extract_float(features.features, "net_taker_buy_ratio")
        kyle_z = self._extract_float(features.features, "kyle_z")
        kyle_regime = features.features.get("kyle_regime")
        atr = self._extract_float(features.features, "ATR")
        rsi = self._extract_float(features.features, "RSI")
        close = features.bar_data.get("close", 0.0)

        direction = 0
        conviction = 0.0
        metadata: dict[str, Any] = {}

        if (
            kyle_regime == "informed"
            and vpin_z is not None
            and buy_ratio is not None
            and rsi is not None
        ):
            if vpin_z > self.params["vpin_z_threshold"]:
                if buy_ratio > self.params["buy_ratio_long"] and rsi < 70:
                    direction = 1
                elif buy_ratio < self.params["buy_ratio_short"] and rsi > 30:
                    direction = -1

            if direction != 0:
                ratio_dev = abs(buy_ratio - 0.5) * 2.0
                conviction = float(np.clip(vpin_z / 3.0 * ratio_dev, 0.0, 1.0))

        # ATR-based TP/SL
        if atr is not None and direction != 0:
            metadata["atr_tp"] = close + direction * atr * self.params["atr_tp_mult"]
            metadata["atr_sl"] = close - direction * atr * self.params["atr_sl_mult"]

        metadata["vpin_z"] = vpin_z
        metadata["kyle_z"] = kyle_z
        metadata["buy_ratio"] = buy_ratio

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
        vpin_z = feature_df.get("vpin_z")
        buy_ratio = feature_df.get("net_taker_buy_ratio")
        kyle_regime = feature_df.get("kyle_regime")
        rsi = feature_df.get("RSI")

        directions = pd.Series(0, index=feature_df.index)

        if vpin_z is None or buy_ratio is None or kyle_regime is None or rsi is None:
            return directions

        informed_mask = kyle_regime == "informed"
        high_vpin = vpin_z > self.params["vpin_z_threshold"]

        long_mask = (
            informed_mask
            & high_vpin
            & (buy_ratio > self.params["buy_ratio_long"])
            & (rsi < 70)
        )
        short_mask = (
            informed_mask
            & high_vpin
            & (buy_ratio < self.params["buy_ratio_short"])
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
