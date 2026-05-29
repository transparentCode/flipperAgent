"""SqueezeBreakoutScorer — continuous edge-scoring wrapper around the proven squeeze-breakout event logic."""

from __future__ import annotations

import collections
from typing import Any

import numpy as np
import pandas as pd

from libs.contracts.signal import ParamDef, ScoringOutput
from libs.contracts.schemas import FeatureVector
from libs.features.indicators.momentum.linreg import _compute_linreg_batch
from libs.models.base import ModelMeta
from libs.models.scoring_base import ScoringModel
from libs.models.registry import ModelRegistry
from libs.models.squeeze_breakout.math_utils import rolling_linreg as _rolling_linreg


@ModelRegistry.register("SqueezeBreakoutScorer")
class SqueezeBreakoutScorer(ScoringModel):

    meta = ModelMeta(
        name="SqueezeBreakoutScorer",
        model_type="scoring",
        required_indicators=[
            "KAMA_fast", "KAMA_slow",
            "BollingerBands", "KeltnerChannel",
            "CCI", "ADX", "ADLine", "MFI", "Momentum", "ATR",
        ],
        required_fields=[
            "KAMA_fast",
            "KAMA_slow",
            "BollingerBands_upper",
            "BollingerBands_lower",
            "KeltnerChannel_upper",
            "KeltnerChannel_lower",
            "CCI",
            "ADX",
            "ADLine",
            "MFI",
            "Momentum",
            "ATR",
        ],
        hyperparameter_schema={
            "kama_fast_period": ParamDef(type="int", default=5, low=3, high=15, step=1),
            "kama_slow_period": ParamDef(type="int", default=30, low=15, high=60, step=1),
            "mom_period": ParamDef(type="int", default=20, low=10, high=40, step=1),
            "squeeze_lookback": ParamDef(type="int", default=1, low=1, high=5, step=1),
            "ss_threshold": ParamDef(type="int", default=3, low=0, high=5, step=1),
            "cci_period": ParamDef(type="int", default=5, low=3, high=20, step=1),
            "adx_period": ParamDef(type="int", default=14, low=7, high=28, step=1),
            "adx_threshold": ParamDef(type="float", default=18.0, low=10.0, high=30.0, step=1.0),
            "ad_sma_period": ParamDef(type="int", default=21, low=10, high=40, step=1),
            "mfi_period": ParamDef(type="int", default=14, low=7, high=28, step=1),
            "mfi_sma_period": ParamDef(type="int", default=9, low=5, high=20, step=1),
            "mom_lr_period": ParamDef(type="int", default=14, low=7, high=28, step=1),
            "mom_lr_mom_period": ParamDef(type="int", default=10, low=5, high=20, step=1),
        },
        min_history_bars=60,
    )

    # ------------------------------------------------------------------
    # Live single-tick evaluation
    # ------------------------------------------------------------------

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params or {})
        self._squeeze_history: collections.deque = collections.deque(
            maxlen=max(1, self.params["squeeze_lookback"])
        )
        # TTM delta internal state
        mom_period = self.params["mom_period"]
        self._close_buf: collections.deque = collections.deque(maxlen=mom_period)
        self._high_buf: collections.deque = collections.deque(maxlen=mom_period)
        self._low_buf: collections.deque = collections.deque(maxlen=mom_period)
        self._delta_buf: collections.deque = collections.deque(maxlen=mom_period)
        # SS voter state
        self._prev_cci: float | None = None
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

    def evaluate(self, features: FeatureVector) -> ScoringOutput:
        bb_upper = self._extract_band(features.features, "BollingerBands", "upper")
        bb_lower = self._extract_band(features.features, "BollingerBands", "lower")
        kc_upper = self._extract_band(features.features, "KeltnerChannel", "upper")
        kc_lower = self._extract_band(features.features, "KeltnerChannel", "lower")
        kama_fast = self._extract_scalar(features.features, "KAMA_fast")
        kama_slow = self._extract_scalar(features.features, "KAMA_slow")
        close = features.bar_data.get("close", 0.0)
        high = features.bar_data.get("high", close)
        low = features.bar_data.get("low", close)

        # Read SS indicator values
        cci_val = self._extract_scalar(features.features, "CCI")
        adx_data = features.features.get("ADX")
        adx_val = adx_data.get("adx") if isinstance(adx_data, dict) else None
        plus_di = adx_data.get("plus_di") if isinstance(adx_data, dict) else None
        minus_di = adx_data.get("minus_di") if isinstance(adx_data, dict) else None
        ad_val = self._extract_scalar(features.features, "ADLine")
        mfi_val = self._extract_scalar(features.features, "MFI")
        mom_val = self._extract_scalar(features.features, "Momentum")
        atr_val = self._extract_scalar(features.features, "ATR")

        direction = 0
        edge_score = 0.0
        conviction = 0.0
        metadata: dict[str, Any] = {
            "kama_fast": kama_fast,
            "kama_slow": kama_slow,
            "close": close,
        }

        # Update TTM delta internal buffers
        self._close_buf.append(close)
        self._high_buf.append(high)
        self._low_buf.append(low)

        lr_mom = None
        mom_period = self.params["mom_period"]
        if len(self._close_buf) >= mom_period:
            hh = max(self._high_buf)
            ll = min(self._low_buf)
            mean_c = sum(self._close_buf) / len(self._close_buf)
            delta = close - ((hh + ll) / 2.0 + mean_c) / 2.0
            self._delta_buf.append(delta)
            if len(self._delta_buf) >= mom_period:
                arr = np.array(list(self._delta_buf), dtype=np.float64)
                lr_vals = _compute_linreg_batch(arr, mom_period)
                lr_mom = lr_vals[-1] if not np.isnan(lr_vals[-1]) else None
        metadata["lr_mom"] = lr_mom

        # Squeeze detection
        if (
            bb_upper is not None
            and bb_lower is not None
            and kc_upper is not None
            and kc_lower is not None
        ):
            squeeze_on = bb_upper < kc_upper and bb_lower > kc_lower
            metadata["squeeze_on"] = squeeze_on

            was_squeezed = any(self._squeeze_history)
            squeeze_release = (not squeeze_on) and was_squeezed
            self._squeeze_history.append(squeeze_on)

            if squeeze_release and lr_mom is not None and kama_fast is not None and kama_slow is not None:
                if kama_fast > kama_slow and lr_mom > 0:
                    direction = 1
                elif kama_fast < kama_slow and lr_mom < 0:
                    direction = -1

        # Compute continuous edge_score and conviction
        if direction != 0 and lr_mom is not None:
            if atr_val is not None and atr_val > 0:
                edge_score = direction * min(abs(lr_mom) / atr_val, 2.0)
            else:
                edge_score = direction * 0.5
            edge_score = max(-2.0, min(edge_score, 2.0))

        # Conviction from signal strength voters
        if direction != 0:
            ss = self._compute_signal_strength(
                direction, cci_val, adx_val, plus_di, minus_di,
                ad_val, mfi_val, mom_val,
            )
            conviction = ss / 5.0
            metadata["signal_strength"] = ss
            if self.params["ss_threshold"] > 0 and ss < self.params["ss_threshold"]:
                edge_score = 0.0
                conviction = 0.0

        # Always update SS voter state (even when direction == 0)
        self._prev_cci = cci_val
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

        return ScoringOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            edge_score=edge_score,
            conviction=conviction,
            metadata=metadata,
        )

    def _compute_signal_strength(
        self,
        direction: int,
        cci_val: float | None,
        adx_val: float | None,
        plus_di: float | None,
        minus_di: float | None,
        ad_val: float | None,
        mfi_val: float | None,
        mom_val: float | None,
    ) -> int:
        """Compute v4 signal-strength score (0-5) for single-tick evaluation."""
        ss = 0

        # 1. CCI rising (long) / falling (short)
        if cci_val is not None and self._prev_cci is not None:
            if direction == 1 and cci_val > self._prev_cci:
                ss += 1
            elif direction == -1 and cci_val < self._prev_cci:
                ss += 1

        # 2. ADX > threshold + DI direction
        adx_threshold = self.params["adx_threshold"]
        if adx_val is not None and adx_val > adx_threshold:
            if plus_di is not None and minus_di is not None:
                if direction == 1 and plus_di > minus_di:
                    ss += 1
                elif direction == -1 and minus_di > plus_di:
                    ss += 1

        # 3. A/D vs SMA(A/D)
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

        # 5. MomentumLR rising/falling
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
        """Return a float Series of edge_scores aligned with *feature_df* index."""
        bb_upper = feature_df.get("BollingerBands_upper")
        bb_lower = feature_df.get("BollingerBands_lower")
        kc_upper = feature_df.get("KeltnerChannel_upper")
        kc_lower = feature_df.get("KeltnerChannel_lower")
        kama_fast = feature_df.get("KAMA_fast")
        kama_slow = feature_df.get("KAMA_slow")
        close = feature_df.get("close")
        high = feature_df.get("high")
        low = feature_df.get("low")
        atr = feature_df.get("ATR")

        edge_scores = pd.Series(0.0, index=feature_df.index)

        if any(
            s is None
            for s in [bb_upper, bb_lower, kc_upper, kc_lower, kama_fast, kama_slow, close]
        ):
            return edge_scores

        # Squeeze detection
        squeeze_on = (bb_upper < kc_upper) & (bb_lower > kc_lower)

        lookback = self.params["squeeze_lookback"]
        was_squeezed = squeeze_on.rolling(window=lookback, min_periods=1).max().astype(bool)
        squeeze_off = ~squeeze_on & was_squeezed.shift(1, fill_value=False)

        # TTM delta-linreg momentum
        mom_period = self.params["mom_period"]
        lr_mom = pd.Series(np.nan, index=feature_df.index)
        if high is not None and low is not None:
            hh = high.rolling(window=mom_period, min_periods=mom_period).max()
            ll = low.rolling(window=mom_period, min_periods=mom_period).min()
            sma_c = close.rolling(window=mom_period, min_periods=mom_period).mean()
            midline = (hh + ll) / 2.0
            delta = close - (midline + sma_c) / 2.0
            lr_arr = _rolling_linreg(delta.values.astype(np.float64), mom_period)
            lr_mom = pd.Series(lr_arr, index=feature_df.index)

        # Dual KAMA crossover + TTM momentum for entry
        long_mask = squeeze_off & (kama_fast > kama_slow) & (lr_mom > 0)
        short_mask = squeeze_off & (kama_fast < kama_slow) & (lr_mom < 0)

        # Compute continuous edge_score = direction * |lr_mom| / ATR
        if atr is not None:
            safe_atr = atr.replace(0, np.nan)
            raw_edge = (lr_mom.abs() / safe_atr).clip(upper=2.0)
        else:
            raw_edge = pd.Series(0.5, index=feature_df.index)

        # Fill NaN ATR fallback
        raw_edge = raw_edge.fillna(0.5)

        edge_scores[long_mask] = raw_edge[long_mask]
        edge_scores[short_mask] = -raw_edge[short_mask]

        # Signal Strength filtering (v4 voters)
        ss_threshold = self.params["ss_threshold"]
        if ss_threshold > 0:
            edge_scores = self._batch_signal_strength_filter(
                edge_scores, feature_df, ss_threshold,
            )

        return edge_scores

    def _batch_signal_strength_filter(
        self,
        edge_scores: pd.Series,
        feature_df: pd.DataFrame,
        ss_threshold: int,
    ) -> pd.Series:
        """Apply v4 signal strength filter — suppress where ss < threshold."""
        ss = pd.Series(0, index=edge_scores.index)
        signal_mask = edge_scores != 0
        directions = np.sign(edge_scores)

        # 1. CCI rising/falling
        cci = feature_df.get("CCI")
        if cci is not None:
            cci_prev = cci.shift(1)
            cci_long = (directions == 1) & (cci > cci_prev)
            cci_short = (directions == -1) & (cci < cci_prev)
            ss[cci_long | cci_short] += 1

        # 2. ADX > threshold + DI direction
        adx = feature_df.get("ADX_adx") if "ADX_adx" in feature_df.columns else None
        pdi = feature_df.get("ADX_plus_di") if "ADX_plus_di" in feature_df.columns else None
        mdi = feature_df.get("ADX_minus_di") if "ADX_minus_di" in feature_df.columns else None
        adx_threshold = self.params["adx_threshold"]
        if adx is not None and pdi is not None and mdi is not None:
            adx_strong = adx > adx_threshold
            adx_long = (directions == 1) & adx_strong & (pdi > mdi)
            adx_short = (directions == -1) & adx_strong & (mdi > pdi)
            ss[adx_long | adx_short] += 1

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

        # 5. MomentumLR rising/falling
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
        edge_scores = edge_scores.copy()
        edge_scores[suppress] = 0.0

        return edge_scores

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
