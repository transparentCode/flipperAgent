"""MeanReversionModel — ADX-gated multi-confirmation mean reversion with signal-strength filtering."""

from __future__ import annotations

import collections
from typing import Any

import numpy as np
import pandas as pd
from numba import njit

from libs.contracts.schemas import FeatureVector, ModelOutput, ParamDef
from libs.features.indicators.momentum.linreg import _compute_linreg_batch
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


def _rolling_linreg(data: np.ndarray, period: int) -> np.ndarray:
    """Rolling linear-regression value, delegates to the njit kernel."""
    return _compute_linreg_batch(data, period)


@ModelRegistry.register("MeanReversion")
class MeanReversionModel(BaseModel):

    meta = ModelMeta(
        name="MeanReversion",
        required_indicators=[
            "RSI", "BollingerBands", "CCI", "ADX", "MFI", "ADLine", "Momentum",
        ],
        required_fields=[
            "RSI",
            "BollingerBands_upper", "BollingerBands_lower",
            "CCI",
            "ADX",
            "MFI",
            "ADLine",
            "Momentum",
        ],
        hyperparameter_schema={
            # Entry thresholds
            "rsi_oversold": ParamDef(type="int", default=30, low=15, high=40, step=1),
            "rsi_overbought": ParamDef(type="int", default=70, low=60, high=85, step=1),
            "bb_entry_std": ParamDef(type="float", default=2.0, low=1.0, high=3.0, step=0.1),
            "cci_oversold": ParamDef(type="int", default=-100, low=-200, high=-50, step=10),
            "cci_overbought": ParamDef(type="int", default=100, low=50, high=200, step=10),
            "mfi_oversold": ParamDef(type="int", default=20, low=10, high=40, step=5),
            "mfi_overbought": ParamDef(type="int", default=80, low=60, high=90, step=5),
            # ADX regime gate
            "adx_regime_threshold": ParamDef(type="float", default=25.0, low=15.0, high=35.0, step=1.0),
            # Signal strength
            "ss_threshold": ParamDef(type="int", default=2, low=0, high=5, step=1),
            # SS voter params
            "ad_sma_period": ParamDef(type="int", default=21, low=10, high=40, step=1),
            "mfi_sma_period": ParamDef(type="int", default=9, low=5, high=20, step=1),
            "mom_lr_period": ParamDef(type="int", default=14, low=7, high=28, step=1),
            # Holding period cooldown
            "holding_period": ParamDef(type="int", default=5, low=1, high=20, step=1),
        },
        min_history_bars=30,
    )

    # ------------------------------------------------------------------
    # Live single-tick evaluation
    # ------------------------------------------------------------------

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params or {})
        # SS voter state
        self._prev_cci: float | None = None
        self._prev_adx: float | None = None
        self._ad_buf: collections.deque = collections.deque(
            maxlen=self.params["ad_sma_period"]
        )
        self._mfi_buf: collections.deque = collections.deque(
            maxlen=self.params["mfi_sma_period"]
        )
        self._mom_lr_buf: collections.deque = collections.deque(
            maxlen=self.params["mom_lr_period"]
        )
        self._prev_mom_lr: float | None = None

    def evaluate(self, features: FeatureVector) -> ModelOutput:
        rsi_value = extract_rsi(features.features)
        bb_upper = self._extract_bb(features.features, "upper")
        bb_lower = self._extract_bb(features.features, "lower")
        close = features.bar_data.get("close", 0.0)

        # Read indicator values
        cci_val = self._extract_scalar(features.features, "CCI")
        adx_data = features.features.get("ADX")
        adx_val = adx_data.get("adx") if isinstance(adx_data, dict) else None
        mfi_val = self._extract_scalar(features.features, "MFI")
        ad_val = self._extract_scalar(features.features, "ADLine")
        mom_val = self._extract_scalar(features.features, "Momentum")

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

        # ADX regime gate — only trade MR when ADX < threshold (ranging market)
        adx_pass = adx_val is not None and adx_val < self.params["adx_regime_threshold"]
        metadata["adx"] = adx_val

        if adx_pass and rsi_value is not None:
            # Multi-confirmation LONG
            rsi_long = rsi_value <= self.params["rsi_oversold"]
            bb_long = model_lower is not None and close <= model_lower
            cci_long = cci_val is not None and cci_val < self.params["cci_oversold"]
            mfi_long = mfi_val is not None and mfi_val < self.params["mfi_oversold"]

            if rsi_long and bb_long and cci_long and mfi_long:
                direction = 1
                conviction = min(1.0, (self.params["rsi_oversold"] - rsi_value) / self.params["rsi_oversold"])
                metadata["trigger"] = "oversold"

            # Multi-confirmation SHORT
            rsi_short = rsi_value >= self.params["rsi_overbought"]
            bb_short = model_upper is not None and close >= model_upper
            cci_short = cci_val is not None and cci_val > self.params["cci_overbought"]
            mfi_short = mfi_val is not None and mfi_val > self.params["mfi_overbought"]

            if rsi_short and bb_short and cci_short and mfi_short:
                direction = -1
                conviction = min(1.0, (rsi_value - self.params["rsi_overbought"]) / (100 - self.params["rsi_overbought"]))
                metadata["trigger"] = "overbought"

        # Signal Strength filtering (5 voters)
        if direction != 0:
            ss = self._compute_signal_strength(
                direction, cci_val, adx_val, ad_val, mfi_val, mom_val,
            )
            metadata["signal_strength"] = ss
            ss_threshold = self.params["ss_threshold"]
            if ss_threshold > 0:
                # Scale conviction by SS ratio when filtering is active
                conviction *= ss / 5.0 if ss > 0 else 0.0
                if ss < ss_threshold:
                    direction = 0
                    conviction = 0.0

        # Always update SS voter state (even when direction == 0)
        self._prev_cci = cci_val
        self._prev_adx = adx_val
        if ad_val is not None:
            self._ad_buf.append(ad_val)
        if mfi_val is not None:
            self._mfi_buf.append(mfi_val)
        if mom_val is not None:
            self._mom_lr_buf.append(mom_val)
            if len(self._mom_lr_buf) >= self.params["mom_lr_period"]:
                arr = np.array(list(self._mom_lr_buf), dtype=np.float64)
                lr_vals = _compute_linreg_batch(arr, self.params["mom_lr_period"])
                cur = lr_vals[-1] if not np.isnan(lr_vals[-1]) else None
                self._prev_mom_lr = cur

        return ModelOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            direction=direction,
            conviction=conviction,
            metadata=metadata,
        )

    def _compute_signal_strength(
        self,
        direction: int,
        cci_val: float | None,
        adx_val: float | None,
        ad_val: float | None,
        mfi_val: float | None,
        mom_val: float | None,
    ) -> int:
        """Compute signal-strength score (0-5) for single-tick evaluation."""
        ss = 0

        # 1. CCI reversal — CCI was falling and now rising (long) or vice versa
        if cci_val is not None and self._prev_cci is not None:
            if direction == 1 and cci_val > self._prev_cci:
                ss += 1
            elif direction == -1 and cci_val < self._prev_cci:
                ss += 1

        # 2. ADX declining — trend weakening (good for MR)
        if adx_val is not None and self._prev_adx is not None:
            if adx_val < self._prev_adx:
                ss += 1

        # 3. A/D Line vs SMA(A/D)
        if ad_val is not None and len(self._ad_buf) >= self.params["ad_sma_period"]:
            ad_sma = sum(self._ad_buf) / len(self._ad_buf)
            if direction == 1 and ad_val > ad_sma:
                ss += 1
            elif direction == -1 and ad_val < ad_sma:
                ss += 1

        # 4. MFI vs SMA(MFI)
        if mfi_val is not None and len(self._mfi_buf) >= self.params["mfi_sma_period"]:
            mfi_sma = sum(self._mfi_buf) / len(self._mfi_buf)
            if direction == 1 and mfi_val > mfi_sma:
                ss += 1
            elif direction == -1 and mfi_val < mfi_sma:
                ss += 1

        # 5. Momentum-LR reversal — MomentumLR was negative and now rising (long)
        #    or was positive and now falling (short)
        if self._prev_mom_lr is not None and mom_val is not None:
            if len(self._mom_lr_buf) >= self.params["mom_lr_period"]:
                arr = np.array(list(self._mom_lr_buf), dtype=np.float64)
                lr_vals = _compute_linreg_batch(arr, self.params["mom_lr_period"])
                cur_lr = lr_vals[-1] if not np.isnan(lr_vals[-1]) else None
                if cur_lr is not None:
                    if direction == 1 and cur_lr > self._prev_mom_lr:
                        ss += 1
                    elif direction == -1 and cur_lr < self._prev_mom_lr:
                        ss += 1

        return ss

    # ------------------------------------------------------------------
    # Batch evaluation for optimization / backtest
    # ------------------------------------------------------------------

    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        """Return a Series of directions (-1, 0, 1) aligned with *feature_df* index."""
        rsi = feature_df.get("RSI")
        bb_lower = feature_df.get("BollingerBands_lower")
        bb_upper = feature_df.get("BollingerBands_upper")
        close = feature_df.get("close")
        cci = feature_df.get("CCI")
        adx = feature_df.get("ADX_adx") if "ADX_adx" in feature_df.columns else None
        mfi = feature_df.get("MFI")

        directions = pd.Series(0, index=feature_df.index)

        # Recompute entry bands using bb_entry_std relative to Bollinger midline
        if bb_lower is not None and bb_upper is not None:
            bb_mid = (bb_upper + bb_lower) / 2.0
            entry_ratio = self.params["bb_entry_std"] / 2.0
            model_lower = bb_mid - entry_ratio * (bb_mid - bb_lower)
            model_upper = bb_mid + entry_ratio * (bb_upper - bb_mid)
        else:
            model_lower = bb_lower
            model_upper = bb_upper

        # ADX regime gate
        adx_pass = adx is not None and (adx < self.params["adx_regime_threshold"])

        if rsi is not None and model_lower is not None and close is not None:
            if cci is not None and mfi is not None and adx is not None:
                long_mask = (
                    adx_pass
                    & (rsi <= self.params["rsi_oversold"])
                    & (close <= model_lower)
                    & (cci < self.params["cci_oversold"])
                    & (mfi < self.params["mfi_oversold"])
                )
                directions[long_mask] = 1

        if rsi is not None and model_upper is not None and close is not None:
            if cci is not None and mfi is not None and adx is not None:
                short_mask = (
                    adx_pass
                    & (rsi >= self.params["rsi_overbought"])
                    & (close >= model_upper)
                    & (cci > self.params["cci_overbought"])
                    & (mfi > self.params["mfi_overbought"])
                )
                directions[short_mask] = -1

        # Signal Strength filtering (5 voters)
        ss_threshold = self.params["ss_threshold"]
        if ss_threshold > 0:
            directions = self._batch_signal_strength_filter(
                directions, feature_df, ss_threshold,
            )

        # Apply holding_period cooldown to suppress whipsaw
        holding_period = self.params["holding_period"]
        if holding_period > 1:
            arr = directions.values.astype(np.float64)
            directions = pd.Series(_apply_cooldown(arr, holding_period), index=directions.index)

        return directions

    def _batch_signal_strength_filter(
        self,
        directions: pd.Series,
        feature_df: pd.DataFrame,
        ss_threshold: int,
    ) -> pd.Series:
        """Apply signal strength filter to batch directions."""
        ss = pd.Series(0, index=directions.index)
        signal_mask = directions != 0

        # 1. CCI reversal — CCI was falling and now rising (long) or vice versa
        cci = feature_df.get("CCI")
        if cci is not None:
            cci_prev = cci.shift(1)
            cci_long = (directions == 1) & (cci > cci_prev)
            cci_short = (directions == -1) & (cci < cci_prev)
            ss[cci_long | cci_short] += 1

        # 2. ADX declining — trend weakening (good for MR)
        adx = feature_df.get("ADX_adx") if "ADX_adx" in feature_df.columns else None
        if adx is not None:
            adx_prev = adx.shift(1)
            adx_declining = adx < adx_prev
            ss[signal_mask & adx_declining] += 1

        # 3. A/D vs SMA(A/D)
        ad = feature_df.get("ADLine")
        if ad is not None:
            ad_sma = ad.rolling(window=self.params["ad_sma_period"], min_periods=1).mean()
            ad_long = (directions == 1) & (ad > ad_sma)
            ad_short = (directions == -1) & (ad < ad_sma)
            ss[ad_long | ad_short] += 1

        # 4. MFI vs SMA(MFI)
        mfi = feature_df.get("MFI")
        if mfi is not None:
            mfi_sma = mfi.rolling(window=self.params["mfi_sma_period"], min_periods=1).mean()
            mfi_long = (directions == 1) & (mfi > mfi_sma)
            mfi_short = (directions == -1) & (mfi < mfi_sma)
            ss[mfi_long | mfi_short] += 1

        # 5. Momentum-LR reversal
        mom = feature_df.get("Momentum")
        if mom is not None:
            lr_mom_arr = _rolling_linreg(mom.values.astype(np.float64), self.params["mom_lr_period"])
            lr_mom = pd.Series(lr_mom_arr, index=feature_df.index)
            lr_mom_prev = lr_mom.shift(1)
            mom_long = (directions == 1) & (lr_mom > lr_mom_prev)
            mom_short = (directions == -1) & (lr_mom < lr_mom_prev)
            ss[mom_long | mom_short] += 1

        # Suppress signals below threshold
        suppress = signal_mask & (ss < ss_threshold)
        directions = directions.copy()
        directions[suppress] = 0

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

    @staticmethod
    def _extract_scalar(features: dict[str, Any], key: str) -> float | None:
        val = features.get(key)
        if isinstance(val, dict):
            return val.get("value")
        if isinstance(val, (int, float)):
            return float(val)
        return None
