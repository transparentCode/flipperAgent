"""TrendFollowingModel — EMA crossover with optional MACD confirmation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from libs.contracts.schemas import FeatureVector, ModelOutput, ParamDef
from libs.models.base import BaseModel, ModelMeta
from libs.models.feature_extractors import extract_macd_field
from libs.models.registry import ModelRegistry


@ModelRegistry.register("TrendFollowing")
class TrendFollowingModel(BaseModel):

    meta = ModelMeta(
        name="TrendFollowing",
        required_indicators=["EMA", "MACD", "ATR"],
        required_fields=[
            "EMA_fast", "EMA_slow",
            "MACD_line", "MACD_signal", "MACD_histogram",
            "ATR",
        ],
        hyperparameter_schema={
            "ema_fast_period": ParamDef(type="int", default=12, low=5, high=20, step=1),
            "ema_slow_period": ParamDef(type="int", default=26, low=15, high=50, step=1),
            "require_macd_confirm": ParamDef(
                type="categorical", default=True, choices=[True, False],
            ),
            "atr_conviction_scale": ParamDef(
                type="float", default=1.0, low=0.5, high=3.0, step=0.1,
            ),
        },
        min_history_bars=50,
    )

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        if self.params["ema_fast_period"] >= self.params["ema_slow_period"]:
            raise ValueError(
                "ema_fast_period must be less than ema_slow_period, got "
                f"{self.params['ema_fast_period']} >= {self.params['ema_slow_period']}"
            )

    # ------------------------------------------------------------------
    # Live single-tick evaluation
    # ------------------------------------------------------------------

    def evaluate(self, features: FeatureVector) -> ModelOutput:
        ema_fast = self._extract_float(features.features, "EMA_fast")
        ema_slow = self._extract_float(features.features, "EMA_slow")
        macd_hist = extract_macd_field(features.features, "histogram")
        atr = self._extract_float(features.features, "ATR")

        direction = 0
        conviction = 0.0
        metadata: dict[str, Any] = {}

        if ema_fast is not None and ema_slow is not None:
            require_macd = self.params["require_macd_confirm"]
            if ema_fast > ema_slow:
                if not require_macd or (macd_hist is not None and macd_hist > 0):
                    direction = 1
            elif ema_fast < ema_slow:
                if not require_macd or (macd_hist is not None and macd_hist < 0):
                    direction = -1

            if direction != 0 and atr is not None and atr > 0:
                scale = self.params["atr_conviction_scale"]
                conviction = min(1.0, abs(ema_fast - ema_slow) / (atr * scale))

        metadata["ema_fast"] = ema_fast
        metadata["ema_slow"] = ema_slow
        metadata["macd_histogram"] = macd_hist

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
        ema_fast = feature_df.get("EMA_fast")
        ema_slow = feature_df.get("EMA_slow")
        macd_hist = feature_df.get("MACD_histogram")
        atr = feature_df.get("ATR")

        directions = pd.Series(0, index=feature_df.index)

        if ema_fast is None or ema_slow is None:
            return directions

        require_macd = self.params["require_macd_confirm"]

        long_mask = ema_fast > ema_slow
        short_mask = ema_fast < ema_slow

        if require_macd and macd_hist is not None:
            long_mask = long_mask & (macd_hist > 0)
            short_mask = short_mask & (macd_hist < 0)

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
