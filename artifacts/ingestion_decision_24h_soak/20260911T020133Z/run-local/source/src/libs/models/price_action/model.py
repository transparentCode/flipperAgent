"""PriceActionModel — 6-kernel price-geometry ensemble scoring model."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from libs.contracts.schemas import FeatureVector, ParamDef
from libs.contracts.signal import ScoringOutput
from libs.models.base import ModelMeta
from libs.models.price_action.batch import _batch_price_action
from libs.models.price_action.kernels.bos import bos_score
from libs.models.price_action.kernels.engulfing import engulfing_score
from libs.models.price_action.kernels.fvg import fvg_score
from libs.models.price_action.kernels.inside_bar import inside_bar_score
from libs.models.price_action.kernels.pin_bar import pin_bar_score
from libs.models.price_action.kernels.sweep import sweep_score
from libs.models.registry import ModelRegistry
from libs.models.scoring_base import ScoringModel


@ModelRegistry.register("PriceAction")
class PriceActionModel(ScoringModel):
    """Pure OHLCV price-geometry ensemble.

    Combines 6 kernels (FVG, Sweep, Pin Bar, Engulfing, BOS, Inside Bar)
    via weighted sum + confluence bonus, with pattern decay and context
    multipliers.  All kernels are Numba-accelerated.
    """

    meta = ModelMeta(
        name="PriceAction",
        model_type="scoring",
        required_indicators=["ATR"],
        required_fields=["ATR"],
        hyperparameter_schema={
            # Swing detection
            "swing_lookback": ParamDef(type="int", default=5, low=3, high=10, step=1),
            # K1: FVG
            "fvg_atr_scale": ParamDef(type="float", default=1.0, low=0.3, high=3.0, step=0.1),
            "w_fvg": ParamDef(type="float", default=0.20, low=0.0, high=0.5, step=0.05),
            # K2: Sweep
            "sweep_wick_scale": ParamDef(type="float", default=1.5, low=0.5, high=3.0, step=0.1),
            "w_sweep": ParamDef(type="float", default=0.25, low=0.0, high=0.5, step=0.05),
            # K3: Pin Bar
            "pin_wick_body_ratio": ParamDef(type="float", default=2.0, low=1.5, high=4.0, step=0.5),
            "pin_wick_dominance": ParamDef(type="float", default=1.5, low=1.0, high=3.0, step=0.5),
            "pin_min_range_atr": ParamDef(type="float", default=0.3, low=0.1, high=0.8, step=0.1),
            "pin_strength_scale": ParamDef(type="float", default=1.5, low=0.5, high=3.0, step=0.1),
            "w_pin": ParamDef(type="float", default=0.15, low=0.0, high=0.5, step=0.05),
            # K4: Engulfing
            "engulf_min_body_atr": ParamDef(type="float", default=0.5, low=0.2, high=1.5, step=0.1),
            "engulf_ratio_scale": ParamDef(type="float", default=0.5, low=0.2, high=1.0, step=0.1),
            "w_engulf": ParamDef(type="float", default=0.15, low=0.0, high=0.5, step=0.05),
            # K5: BOS
            "bos_displacement_scale": ParamDef(type="float", default=1.0, low=0.3, high=3.0, step=0.1),
            "w_bos": ParamDef(type="float", default=0.15, low=0.0, high=0.5, step=0.05),
            # K6: Inside Bar
            "ib_breakout_scale": ParamDef(type="float", default=0.5, low=0.2, high=1.5, step=0.1),
            "w_inside": ParamDef(type="float", default=0.10, low=0.0, high=0.3, step=0.05),
            # Ensemble
            "confluence_scale": ParamDef(type="float", default=0.15, low=0.0, high=0.5, step=0.05),
            "confluence_min": ParamDef(type="int", default=2, low=1, high=4, step=1),
            "conviction_scale": ParamDef(type="float", default=1.0, low=0.5, high=2.0, step=0.1),
            # Context
            "context_proximity_boost": ParamDef(type="float", default=0.3, low=0.0, high=1.0, step=0.1),
            "context_alignment_boost": ParamDef(type="float", default=0.25, low=0.0, high=1.0, step=0.05),
            # Decay
            "pattern_decay_rate": ParamDef(type="float", default=0.3, low=0.0, high=0.8, step=0.05),
        },
        min_history_bars=20,
    )

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params or {})
        # Live state — ring buffer for swing tracking + decay accumulators
        self._bar_buffer: list[tuple[float, float, float, float, float]] = []  # (O,H,L,C,ATR)
        self._last_swing_high: float = float("nan")
        self._last_swing_low: float = float("nan")
        self._bar_count: int = 0
        # Decay accumulators for live mode
        self._dk_prev = [0.0] * 6  # one per kernel

    # ------------------------------------------------------------------
    # Live single-tick evaluation
    # ------------------------------------------------------------------

    def evaluate(self, features: FeatureVector) -> ScoringOutput:
        close = features.bar_data.get("close")
        open_ = features.bar_data.get("open")
        high = features.bar_data.get("high")
        low = features.bar_data.get("low")
        atr_val = self._extract_scalar(features.features, "ATR")

        if close is None or open_ is None or high is None or low is None:
            return self._empty_output(features, "missing_ohlc")

        if atr_val is None or atr_val <= 0.0:
            return self._empty_output(features, "missing_atr")

        # Append to ring buffer
        self._bar_buffer.append((open_, high, low, close, atr_val))
        self._bar_count += 1
        buf_len = len(self._bar_buffer)
        max_buf = self.meta.min_history_bars + 1
        if buf_len > max_buf:
            self._bar_buffer = self._bar_buffer[-max_buf:]
            buf_len = max_buf

        # Update swing points
        sl = int(self.params["swing_lookback"])
        self._update_swings(sl)

        # Not enough history
        if buf_len < 3:
            return self._empty_output(features, "warmup")

        idx = buf_len - 1  # current bar index within buffer
        # Build numpy arrays from buffer
        buf_open = np.array([b[0] for b in self._bar_buffer])
        buf_high = np.array([b[1] for b in self._bar_buffer])
        buf_low = np.array([b[2] for b in self._bar_buffer])
        buf_close = np.array([b[3] for b in self._bar_buffer])
        buf_atr = np.array([b[4] for b in self._bar_buffer])

        # Kernel scores
        k1 = float(fvg_score(buf_high, buf_low, buf_close, buf_atr, idx, self.params["fvg_atr_scale"]))
        k2 = float(sweep_score(buf_high, buf_low, buf_close, idx,
                                self._last_swing_high, self._last_swing_low,
                                self.params["sweep_wick_scale"]))
        k3 = float(pin_bar_score(buf_open, buf_high, buf_low, buf_close, buf_atr, idx,
                                  self.params["pin_wick_body_ratio"],
                                  self.params["pin_wick_dominance"],
                                  self.params["pin_min_range_atr"],
                                  self.params["pin_strength_scale"]))
        k4 = float(engulfing_score(buf_open, buf_high, buf_low, buf_close, buf_atr, idx,
                                    self.params["engulf_min_body_atr"],
                                    self.params["engulf_ratio_scale"]))
        k5 = float(bos_score(buf_close, buf_atr, idx,
                              self._last_swing_high, self._last_swing_low,
                              self.params["bos_displacement_scale"]))
        k6 = float(inside_bar_score(buf_high, buf_low, buf_close, buf_atr, idx,
                                     self.params["ib_breakout_scale"]))

        # Pattern decay
        kernels_raw = [k1, k2, k3, k4, k5, k6]
        decay = self.params["pattern_decay_rate"]
        dk = [0.0] * 6
        for j in range(6):
            dk[j] = kernels_raw[j] + decay * self._dk_prev[j]
            self._dk_prev[j] = dk[j]

        # Context multipliers
        dk = self._apply_context(dk, close, atr_val)

        # Weighted sum
        weights = [
            self.params["w_fvg"], self.params["w_sweep"], self.params["w_pin"],
            self.params["w_engulf"], self.params["w_bos"], self.params["w_inside"],
        ]
        raw = sum(w * d for w, d in zip(weights, dk))

        # Confluence bonus
        sign_raw = 1.0 if raw > 0 else (-1.0 if raw < 0 else 0.0)
        n_agree = sum(1 for d in dk if d * sign_raw > 0)
        bonus_count = max(0, n_agree - int(self.params["confluence_min"]))
        bonus = 1.0 + self.params["confluence_scale"] * bonus_count

        edge_score = raw * bonus
        conviction = min(1.0, abs(edge_score) * self.params["conviction_scale"])

        return ScoringOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            edge_score=edge_score,
            conviction=conviction,
            metadata={
                "k_fvg": dk[0], "k_sweep": dk[1], "k_pin": dk[2],
                "k_engulf": dk[3], "k_bos": dk[4], "k_inside": dk[5],
                "n_agree": n_agree, "confluence_bonus": bonus,
            },
        )

    # ------------------------------------------------------------------
    # Batch evaluation
    # ------------------------------------------------------------------

    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        n = len(feature_df)
        zero_arr = np.zeros(n, dtype=np.float64)

        open_ = feature_df["open"].values.astype(np.float64) if "open" in feature_df.columns else zero_arr.copy()
        high = feature_df["high"].values.astype(np.float64) if "high" in feature_df.columns else zero_arr.copy()
        low = feature_df["low"].values.astype(np.float64) if "low" in feature_df.columns else zero_arr.copy()
        close = feature_df["close"].values.astype(np.float64) if "close" in feature_df.columns else zero_arr.copy()
        atr = feature_df["ATR"].values.astype(np.float64) if "ATR" in feature_df.columns else zero_arr.copy()

        edge_arr = _batch_price_action(
            open_, high, low, close, atr,
            int(self.params["swing_lookback"]),
            float(self.params["fvg_atr_scale"]),
            float(self.params["sweep_wick_scale"]),
            float(self.params["pin_wick_body_ratio"]),
            float(self.params["pin_wick_dominance"]),
            float(self.params["pin_min_range_atr"]),
            float(self.params["pin_strength_scale"]),
            float(self.params["engulf_min_body_atr"]),
            float(self.params["engulf_ratio_scale"]),
            float(self.params["bos_displacement_scale"]),
            float(self.params["ib_breakout_scale"]),
            float(self.params["w_fvg"]),
            float(self.params["w_sweep"]),
            float(self.params["w_pin"]),
            float(self.params["w_engulf"]),
            float(self.params["w_bos"]),
            float(self.params["w_inside"]),
            float(self.params["confluence_scale"]),
            int(self.params["confluence_min"]),
            float(self.params["context_proximity_boost"]),
            float(self.params["context_alignment_boost"]),
            float(self.params["pattern_decay_rate"]),
        )

        return pd.Series(edge_arr, index=feature_df.index)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_swings(self, swing_lookback: int) -> None:
        """Update confirmed swing high/low from the ring buffer."""
        buf = self._bar_buffer
        n = len(buf)
        if n < 2 * swing_lookback + 1:
            return
        check_idx = n - 1 - swing_lookback
        if check_idx < swing_lookback:
            return
        check_high = buf[check_idx][1]
        check_low = buf[check_idx][2]
        is_sh = True
        is_sl = True
        for j in range(check_idx - swing_lookback, check_idx + swing_lookback + 1):
            if j != check_idx and 0 <= j < n:
                if buf[j][1] >= check_high:
                    is_sh = False
                if buf[j][2] <= check_low:
                    is_sl = False
        if is_sh:
            self._last_swing_high = check_high
        if is_sl:
            self._last_swing_low = check_low

    def _apply_context(self, dk: list[float], close: float, atr_val: float) -> list[float]:
        """Apply context multipliers to decayed kernel scores."""
        prox_boost = self.params["context_proximity_boost"]
        align_boost = self.params["context_alignment_boost"]

        # Proximity boost for reversal kernels near swing levels
        if atr_val > 0.0:
            dist_sh = abs(close - self._last_swing_high) / (atr_val + 1e-10) if not math.isnan(self._last_swing_high) else 999.0
            dist_sl = abs(close - self._last_swing_low) / (atr_val + 1e-10) if not math.isnan(self._last_swing_low) else 999.0
            min_dist = min(dist_sh, dist_sl)
            if min_dist < 1.5:
                prox = 1.0 + prox_boost * (1.0 - min_dist / 1.5)
                dk[1] *= prox  # sweep
                dk[2] *= prox  # pin bar
                dk[3] *= prox  # engulfing

        # Alignment boost: FVG + BOS
        if dk[0] != 0.0 and dk[4] != 0.0:
            dk[0] *= (1.0 + align_boost)

        # Alignment boost: sweep/pin aligns with FVG direction
        if dk[0] != 0.0:
            if dk[1] != 0.0 and (dk[1] > 0) == (dk[0] > 0):
                dk[1] *= (1.0 + align_boost * 0.5)
            if dk[2] != 0.0 and (dk[2] > 0) == (dk[0] > 0):
                dk[2] *= (1.0 + align_boost * 0.5)

        return dk

    def _empty_output(self, features: FeatureVector, trigger: str) -> ScoringOutput:
        return ScoringOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            edge_score=0.0,
            conviction=0.0,
            metadata={"trigger": trigger},
        )

    @staticmethod
    def _extract_scalar(features: dict[str, Any], key: str) -> float | None:
        val = features.get(key)
        if val is None:
            return None
        if isinstance(val, dict):
            return val.get("value")
        return float(val)
