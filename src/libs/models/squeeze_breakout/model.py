"""SqueezeBreakout model — BB/KC squeeze detection with KAMA + LinReg filters."""

from __future__ import annotations

import collections
from typing import Any

import numpy as np
import pandas as pd

from libs.contracts.schemas import FeatureVector, ModelOutput, ParamDef
from libs.models.base import BaseModel, ModelMeta
from libs.models.feature_extractors import extract_rsi
from libs.models.registry import ModelRegistry


@ModelRegistry.register("SqueezeBreakout")
class SqueezeBreakoutModel(BaseModel):

    meta = ModelMeta(
        name="SqueezeBreakout",
        required_indicators=["KAMA", "BollingerBands", "KeltnerChannel", "LinReg"],
        required_fields=[
            "KAMA",
            "BollingerBands_upper",
            "BollingerBands_lower",
            "KeltnerChannel_upper",
            "KeltnerChannel_lower",
            "LinReg",
        ],
        hyperparameter_schema={
            "kama_period": ParamDef(type="int", default=10, low=5, high=30, step=1),
            "kama_fast": ParamDef(type="int", default=2, low=2, high=5, step=1),
            "kama_slow": ParamDef(type="int", default=30, low=15, high=50, step=1),
            "mom_period": ParamDef(type="int", default=12, low=6, high=24, step=1),
            "squeeze_lookback": ParamDef(type="int", default=1, low=1, high=5, step=1),
            "ss_threshold": ParamDef(type="int", default=3, low=0, high=5, step=1),
        },
        min_history_bars=30,
    )

    # ------------------------------------------------------------------
    # Live single-tick evaluation
    # ------------------------------------------------------------------

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params or {})
        self._squeeze_history: collections.deque = collections.deque(
            maxlen=max(1, self.params["squeeze_lookback"])
        )

    def evaluate(self, features: FeatureVector) -> ModelOutput:
        bb_upper = self._extract_band(features.features, "BollingerBands", "upper")
        bb_lower = self._extract_band(features.features, "BollingerBands", "lower")
        kc_upper = self._extract_band(features.features, "KeltnerChannel", "upper")
        kc_lower = self._extract_band(features.features, "KeltnerChannel", "lower")
        kama = self._extract_scalar(features.features, "KAMA")
        linreg = self._extract_scalar(features.features, "LinReg")
        rsi_value = extract_rsi(features.features)
        close = features.bar_data.get("close", 0.0)

        direction = 0
        conviction = 0.0
        metadata: dict[str, Any] = {
            "kama": kama,
            "linreg": linreg,
            "close": close,
        }

        # Squeeze detection (single-tick can only detect current state)
        if (
            bb_upper is not None
            and bb_lower is not None
            and kc_upper is not None
            and kc_lower is not None
        ):
            squeeze_on = bb_upper < kc_upper and bb_lower > kc_lower
            metadata["squeeze_on"] = squeeze_on

            # Stateful squeeze release detection
            was_squeezed = any(self._squeeze_history)
            squeeze_release = (not squeeze_on) and was_squeezed
            self._squeeze_history.append(squeeze_on)

            if squeeze_release and linreg is not None and kama is not None:
                if linreg > 0 and close > kama:
                    direction = 1
                elif linreg < 0 and close < kama:
                    direction = -1

        # Conviction based on momentum magnitude
        atr = self._extract_scalar(features.features, "ATR")
        if direction != 0 and linreg is not None:
            if atr is not None and atr > 0:
                conviction = min(1.0, abs(linreg) / atr)
            else:
                conviction = 0.5

        # Signal Strength filtering
        if direction != 0:
            ss = self._compute_signal_strength(
                direction, linreg, rsi_value, kama, close,
                bb_upper, bb_lower, kc_upper, kc_lower,
                features.bar_data,
            )
            metadata["signal_strength"] = ss
            if self.params["ss_threshold"] > 0 and ss < self.params["ss_threshold"]:
                direction = 0
                conviction = 0.0

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
        bb_upper = feature_df.get("BollingerBands_upper")
        bb_lower = feature_df.get("BollingerBands_lower")
        kc_upper = feature_df.get("KeltnerChannel_upper")
        kc_lower = feature_df.get("KeltnerChannel_lower")
        kama = feature_df.get("KAMA")
        linreg = feature_df.get("LinReg")
        close = feature_df.get("close")

        directions = pd.Series(0, index=feature_df.index)

        if any(
            s is None
            for s in [bb_upper, bb_lower, kc_upper, kc_lower, kama, linreg, close]
        ):
            return directions

        # Squeeze detection
        squeeze_on = (bb_upper < kc_upper) & (bb_lower > kc_lower)

        # Squeeze release: squeeze was on in any of last squeeze_lookback bars, now off
        lookback = self.params["squeeze_lookback"]
        was_squeezed = squeeze_on.rolling(window=lookback, min_periods=1).max().astype(bool)
        squeeze_off = ~squeeze_on & was_squeezed.shift(1, fill_value=False)

        # Momentum + KAMA filter
        long_mask = squeeze_off & (linreg > 0) & (close > kama)
        short_mask = squeeze_off & (linreg < 0) & (close < kama)

        directions[long_mask] = 1
        directions[short_mask] = -1

        # Signal Strength filtering
        ss_threshold = self.params["ss_threshold"]
        if ss_threshold > 0:
            rsi = feature_df.get("RSI")
            volume = feature_df.get("volume")
            directions = self._batch_signal_strength_filter(
                directions, linreg, rsi, kama, close,
                bb_upper, bb_lower, kc_upper, kc_lower,
                volume, ss_threshold,
            )

        return directions

    # ------------------------------------------------------------------
    # Signal Strength helpers
    # ------------------------------------------------------------------

    def _compute_signal_strength(
        self,
        direction: int,
        linreg: float | None,
        rsi: float | None,
        kama: float | None,
        close: float,
        bb_upper: float | None,
        bb_lower: float | None,
        kc_upper: float | None,
        kc_lower: float | None,
        bar_data: dict[str, float],
    ) -> int:
        """Compute signal strength score (0-5) for single-tick evaluation."""
        ss = 0

        # 1. Momentum confirms direction
        if linreg is not None:
            if (direction == 1 and linreg > 0) or (direction == -1 and linreg < 0):
                ss += 1

        # 2. RSI range check
        if rsi is not None:
            if (direction == 1 and 40 < rsi < 70) or (
                direction == -1 and 30 < rsi < 60
            ):
                ss += 1

        # 3. KAMA slope (need prev_kama from bar_data or features)
        prev_kama = bar_data.get("prev_kama")
        if kama is not None and prev_kama is not None:
            kama_slope = kama - prev_kama
            if (direction == 1 and kama_slope > 0) or (
                direction == -1 and kama_slope < 0
            ):
                ss += 1

        # 4. Squeeze tightness
        if (
            bb_upper is not None
            and bb_lower is not None
            and kc_upper is not None
            and kc_lower is not None
        ):
            bb_width = bb_upper - bb_lower
            kc_width = kc_upper - kc_lower
            if kc_width > 0 and bb_width / kc_width < 0.8:
                ss += 1

        # 5. Volume above average
        volume = bar_data.get("volume")
        avg_volume = bar_data.get("avg_volume")
        if volume is not None and avg_volume is not None and avg_volume > 0:
            if volume > avg_volume:
                ss += 1

        return ss

    def _batch_signal_strength_filter(
        self,
        directions: pd.Series,
        linreg: pd.Series,
        rsi: pd.Series | None,
        kama: pd.Series,
        close: pd.Series,
        bb_upper: pd.Series,
        bb_lower: pd.Series,
        kc_upper: pd.Series,
        kc_lower: pd.Series,
        volume: pd.Series | None,
        ss_threshold: int,
    ) -> pd.Series:
        """Apply signal strength filter to batch directions."""
        ss = pd.Series(0, index=directions.index)

        signal_mask = directions != 0

        # 1. Momentum confirms direction
        mom_confirm = ((directions == 1) & (linreg > 0)) | (
            (directions == -1) & (linreg < 0)
        )
        ss[mom_confirm] += 1

        # 2. RSI range check
        if rsi is not None:
            rsi_long_ok = (directions == 1) & (rsi > 40) & (rsi < 70)
            rsi_short_ok = (directions == -1) & (rsi > 30) & (rsi < 60)
            ss[rsi_long_ok | rsi_short_ok] += 1

        # 3. KAMA slope
        kama_slope = kama - kama.shift(1)
        slope_long = (directions == 1) & (kama_slope > 0)
        slope_short = (directions == -1) & (kama_slope < 0)
        ss[slope_long | slope_short] += 1

        # 4. Squeeze tightness
        bb_width = bb_upper - bb_lower
        kc_width = kc_upper - kc_lower
        tight = (kc_width > 0) & (bb_width / kc_width.replace(0, np.nan) < 0.8)
        ss[tight & signal_mask] += 1

        # 5. Volume above average
        if volume is not None:
            avg_vol = volume.rolling(window=20, min_periods=1).mean()
            vol_ok = volume > avg_vol
            ss[vol_ok & signal_mask] += 1

        # Suppress signals below threshold
        suppress = signal_mask & (ss < ss_threshold)
        directions = directions.copy()
        directions[suppress] = 0

        return directions

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_band(features: dict[str, Any], indicator: str, band: str) -> float | None:
        val = features.get(indicator)
        if isinstance(val, dict):
            return val.get(band)
        return None

    @staticmethod
    def _extract_scalar(features: dict[str, Any], key: str) -> float | None:
        val = features.get(key)
        if isinstance(val, dict):
            return val.get("value")
        if isinstance(val, (int, float)):
            return float(val)
        return None
