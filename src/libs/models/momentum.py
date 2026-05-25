"""MomentumModel — RSI directional bias with MACD histogram confirmation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from libs.contracts.schemas import FeatureVector, ModelOutput, ParamDef
from libs.models.base import BaseModel, ModelMeta
from libs.models.registry import ModelRegistry


@ModelRegistry.register("Momentum")
class MomentumModel(BaseModel):

    meta = ModelMeta(
        name="Momentum",
        required_indicators=["RSI", "MACD"],
        required_fields=["RSI.value", "MACD.histogram", "MACD.line"],
        hyperparameter_schema={
            "rsi_long_threshold": ParamDef(type="int", default=55, low=50, high=70, step=1),
            "rsi_short_threshold": ParamDef(type="int", default=45, low=30, high=50, step=1),
            "require_macd_positive": ParamDef(
                type="categorical", default=False, choices=[True, False],
            ),
            "histogram_min_abs": ParamDef(
                type="float", default=0.0, low=0.0, high=1.0, step=0.01,
            ),
        },
        min_history_bars=35,
    )

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        if self.params["rsi_short_threshold"] >= self.params["rsi_long_threshold"]:
            raise ValueError(
                "rsi_short_threshold must be less than rsi_long_threshold, got "
                f"{self.params['rsi_short_threshold']} >= {self.params['rsi_long_threshold']}"
            )

    # ------------------------------------------------------------------
    # Live single-tick evaluation
    # ------------------------------------------------------------------

    def evaluate(self, features: FeatureVector) -> ModelOutput:
        rsi = self._extract_rsi(features.features)
        macd_hist = self._extract_macd_field(features.features, "histogram")
        macd_line = self._extract_macd_field(features.features, "line")

        direction = 0
        conviction = 0.0
        metadata: dict[str, Any] = {"rsi": rsi, "macd_histogram": macd_hist}

        hist_min = self.params["histogram_min_abs"]
        require_macd_pos = self.params["require_macd_positive"]

        if rsi is not None and macd_hist is not None:
            if (
                rsi > self.params["rsi_long_threshold"]
                and macd_hist > 0
                and abs(macd_hist) >= hist_min
                and (not require_macd_pos or (macd_line is not None and macd_line > 0))
            ):
                direction = 1
                conviction = min(1.0, (rsi - 50) / 50)
            elif (
                rsi < self.params["rsi_short_threshold"]
                and macd_hist < 0
                and abs(macd_hist) >= hist_min
                and (not require_macd_pos or (macd_line is not None and macd_line < 0))
            ):
                direction = -1
                conviction = min(1.0, (50 - rsi) / 50)

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
        rsi = feature_df.get("RSI")
        macd_hist = feature_df.get("MACD_histogram")
        macd_line = feature_df.get("MACD_line")

        directions = pd.Series(0, index=feature_df.index)

        if rsi is None or macd_hist is None:
            return directions

        hist_min = self.params["histogram_min_abs"]
        require_macd_pos = self.params["require_macd_positive"]

        long_mask = (
            (rsi > self.params["rsi_long_threshold"])
            & (macd_hist > 0)
            & (macd_hist.abs() >= hist_min)
        )
        short_mask = (
            (rsi < self.params["rsi_short_threshold"])
            & (macd_hist < 0)
            & (macd_hist.abs() >= hist_min)
        )

        if require_macd_pos and macd_line is not None:
            long_mask = long_mask & (macd_line > 0)
            short_mask = short_mask & (macd_line < 0)

        directions[long_mask] = 1
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
    def _extract_macd_field(features: dict[str, Any], field: str) -> float | None:
        macd = features.get("MACD")
        if isinstance(macd, dict):
            val = macd.get(field)
            if isinstance(val, (int, float)):
                return float(val)
        return None
