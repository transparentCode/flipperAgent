"""DivergenceEdgeScorer — price-indicator divergence magnitude as edge."""

from __future__ import annotations

import collections
from typing import Any

import numpy as np
import pandas as pd

from libs.contracts.signal import ParamDef, ScoringOutput
from libs.contracts.schemas import FeatureVector
from libs.models.base import ModelMeta
from libs.models.scoring_base import ScoringModel
from libs.models.scoring_registry import ScoringModelRegistry


def _ols_slope(values: collections.deque) -> float | None:
    """Compute OLS slope over a deque of float values."""
    n = len(values)
    if n < 2:
        return None
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    if abs(den) < 1e-12:
        return 0.0
    return num / den


def _np_rolling_slope(arr: np.ndarray, window: int) -> np.ndarray:
    """Vectorized rolling OLS slope for batch evaluation."""
    n = len(arr)
    result = np.full(n, np.nan)
    if n < window or window < 2:
        return result
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()
    if abs(x_var) < 1e-12:
        return result
    for i in range(window - 1, n):
        y = arr[i - window + 1 : i + 1]
        if np.any(np.isnan(y)):
            continue
        y_mean = y.mean()
        num = ((x - x_mean) * (y - y_mean)).sum()
        result[i] = num / x_var
    return result


@ScoringModelRegistry.register("DivergenceEdgeScorer")
class DivergenceEdgeScorer(ScoringModel):

    meta = ModelMeta(
        name="DivergenceEdgeScorer",
        required_indicators=["RSI", "MACD", "MFI", "Momentum", "LinReg", "ATR"],
        required_fields=[
            "RSI", "MACD", "MFI", "Momentum", "LinReg", "ATR",
            "eng_volume_adjusted_momentum", "eng_atr_normalized_return",
            "eng_residual_momentum",
            "eng_altcoin_market_momentum", "eng_altcoin_beta",
        ],
        hyperparameter_schema={
            "divergence_lookback": ParamDef(type="int", default=14, low=8, high=30, step=1),
            "weight_rsi": ParamDef(type="float", default=0.4, low=0.1, high=0.6, step=0.05),
            "weight_macd": ParamDef(type="float", default=0.35, low=0.1, high=0.6, step=0.05),
            "weight_mfi": ParamDef(type="float", default=0.25, low=0.1, high=0.5, step=0.05),
            "min_confirming_indicators": ParamDef(type="int", default=2, low=1, high=3, step=1),
            "min_divergence_magnitude": ParamDef(type="float", default=0.1, low=0.01, high=0.5, step=0.01),
            "vam_confirm_boost": ParamDef(type="float", default=0.2, low=0.0, high=0.5, step=0.05),
            "vam_contradict_penalty": ParamDef(type="float", default=0.15, low=0.0, high=0.4, step=0.05),
            "norm_scale": ParamDef(type="float", default=100.0, low=50.0, high=200.0, step=10.0),
            "residual_weight": ParamDef(type="float", default=0.15, low=0.0, high=0.4, step=0.05),
            "market_divergence_weight": ParamDef(type="float", default=0.2, low=0.0, high=0.5, step=0.05),
            "beta_penalty_weight": ParamDef(type="float", default=0.3, low=0.0, high=0.6, step=0.05),
            "base_conviction": ParamDef(type="float", default=0.3, low=0.1, high=0.5, step=0.05),
            "agreement_bonus": ParamDef(type="float", default=0.35, low=0.1, high=0.5, step=0.05),
            "magnitude_bonus": ParamDef(type="float", default=0.35, low=0.1, high=0.5, step=0.05),
            "divergence_saturation": ParamDef(type="float", default=2.0, low=0.5, high=5.0, step=0.5),
        },
        min_history_bars=50,
    )

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params or {})
        lookback = self.params["divergence_lookback"]
        self._rsi_buf: collections.deque = collections.deque(maxlen=lookback)
        self._macd_hist_buf: collections.deque = collections.deque(maxlen=lookback)
        self._mfi_buf: collections.deque = collections.deque(maxlen=lookback)
        self._price_slope_buf: collections.deque = collections.deque(maxlen=lookback)

    # ------------------------------------------------------------------
    # Single-tick evaluation
    # ------------------------------------------------------------------

    def evaluate(self, features: FeatureVector) -> ScoringOutput:
        p = self.params
        f = features.features

        zero = ScoringOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            edge_score=0.0,
            conviction=0.0,
        )

        # Extract indicator values
        rsi = f.get("RSI")
        macd_data = f.get("MACD")
        macd_hist = macd_data.get("histogram") if isinstance(macd_data, dict) else None
        mfi = f.get("MFI")
        linreg_data = f.get("LinReg")
        # LinReg might be scalar (value) or dict with slope
        if isinstance(linreg_data, dict):
            price_slope = linreg_data.get("slope", linreg_data.get("value"))
        else:
            price_slope = linreg_data
        atr = f.get("ATR")
        close = features.bar_data.get("close", 0.0)

        # Engineered features
        vam = f.get("eng_volume_adjusted_momentum")
        res_mom = f.get("eng_residual_momentum")
        altcoin_mom = f.get("eng_altcoin_market_momentum")
        altcoin_beta = f.get("eng_altcoin_beta")

        # Append to rolling buffers
        if rsi is not None:
            self._rsi_buf.append(rsi)
        if macd_hist is not None:
            self._macd_hist_buf.append(macd_hist)
        if mfi is not None:
            self._mfi_buf.append(mfi)
        if price_slope is not None:
            self._price_slope_buf.append(close)

        # Need enough history for slope
        lookback = p["divergence_lookback"]
        if (
            len(self._rsi_buf) < lookback
            or len(self._macd_hist_buf) < lookback
            or len(self._mfi_buf) < lookback
            or len(self._price_slope_buf) < lookback
        ):
            return zero

        # Step 1: Compute slopes
        p_slope = _ols_slope(self._price_slope_buf)
        rsi_slope = _ols_slope(self._rsi_buf)
        macd_hist_slope = _ols_slope(self._macd_hist_buf)
        mfi_slope = _ols_slope(self._mfi_buf)

        if p_slope is None or rsi_slope is None or macd_hist_slope is None or mfi_slope is None:
            return zero

        # Step 2: Detect divergences per indicator
        weights = {
            "rsi": (rsi_slope, p["weight_rsi"]),
            "macd": (macd_hist_slope, p["weight_macd"]),
            "mfi": (mfi_slope, p["weight_mfi"]),
        }

        divergences: dict[str, float] = {}
        for name, (ind_slope, weight) in weights.items():
            div = 0.0
            if p_slope > 0 and ind_slope < 0:
                # Bearish divergence
                div = -(abs(p_slope) + abs(ind_slope)) * weight
            elif p_slope < 0 and ind_slope > 0:
                # Bullish divergence
                div = (abs(p_slope) + abs(ind_slope)) * weight
            divergences[name] = div

        # Gate: count confirming indicators (same sign)
        signs = [np.sign(d) for d in divergences.values() if d != 0.0]
        if not signs:
            return zero

        # Dominant direction
        pos_count = sum(1 for s in signs if s > 0)
        neg_count = sum(1 for s in signs if s < 0)
        if pos_count >= neg_count:
            dominant_sign = 1.0
            n_confirming = pos_count
        else:
            dominant_sign = -1.0
            n_confirming = neg_count

        if n_confirming < p["min_confirming_indicators"]:
            return zero

        # Step 3: Aggregate raw divergence (only same-direction components)
        raw_divergence = sum(
            d for d in divergences.values() if np.sign(d) == dominant_sign
        )

        if abs(raw_divergence) <= p["min_divergence_magnitude"]:
            return zero

        # Step 4: VAM confirmation
        vam_multiplier = 1.0
        if vam is not None:
            if np.sign(vam) == np.sign(raw_divergence):
                vam_multiplier = 1.0 + p["vam_confirm_boost"]
            elif np.sign(vam) != np.sign(raw_divergence) and vam != 0:
                vam_multiplier = 1.0 - p["vam_contradict_penalty"]

        # Step 5: ATR normalization
        normalized_divergence = raw_divergence
        if atr is not None and atr > 0 and close > 0:
            volatility_scalar = atr / close
            normalized_divergence = raw_divergence / (volatility_scalar * p["norm_scale"])

        # Step 6: Residual momentum boost
        residual_boost = 1.0
        if res_mom is not None:
            if np.sign(res_mom) == np.sign(raw_divergence):
                residual_boost = 1.0 + p["residual_weight"]

        # Step 7: Cross-sectional context
        market_divergence_bonus = 1.0
        if altcoin_mom is not None and abs(altcoin_mom) > 0.5:
            if np.sign(raw_divergence) != np.sign(altcoin_mom):
                market_divergence_bonus = 1.0 + p["market_divergence_weight"]

        beta_dampener = 1.0
        if altcoin_beta is not None and altcoin_beta > 1.5:
            beta_dampener = 1.0 / (1.0 + (altcoin_beta - 1.5) * p["beta_penalty_weight"])

        # Step 8: Final edge
        edge_score = (
            normalized_divergence
            * vam_multiplier
            * residual_boost
            * market_divergence_bonus
            * beta_dampener
        )

        # Conviction
        min_conf = p["min_confirming_indicators"]
        denom = 3 - min_conf if 3 - min_conf > 0 else 1
        conviction = (
            p["base_conviction"]
            + p["agreement_bonus"] * (n_confirming - min_conf) / denom
            + p["magnitude_bonus"] * min(abs(raw_divergence) / p["divergence_saturation"], 1.0)
        )
        conviction = max(0.0, min(conviction, 1.0))

        return ScoringOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            edge_score=edge_score,
            conviction=conviction,
            metadata={
                "n_confirming": n_confirming,
                "raw_divergence": raw_divergence,
                "normalized_divergence": normalized_divergence,
                "vam_multiplier": vam_multiplier,
                "residual_boost": residual_boost,
                "market_divergence_bonus": market_divergence_bonus,
                "beta_dampener": beta_dampener,
                "price_slope": p_slope,
                "rsi_slope": rsi_slope,
                "macd_hist_slope": macd_hist_slope,
                "mfi_slope": mfi_slope,
            },
        )

    # ------------------------------------------------------------------
    # Batch evaluation
    # ------------------------------------------------------------------

    def batch_evaluate(self, feature_df: pd.DataFrame) -> pd.Series:
        p = self.params
        lookback = p["divergence_lookback"]
        n = len(feature_df)
        result = pd.Series(0.0, index=feature_df.index)

        # Need RSI, MACD_histogram, MFI, close columns
        rsi_col = feature_df.get("RSI")
        macd_hist_col = feature_df.get("MACD_histogram")
        mfi_col = feature_df.get("MFI")
        close_col = feature_df.get("close")
        atr_col = feature_df.get("ATR")

        if rsi_col is None or macd_hist_col is None or mfi_col is None or close_col is None:
            return result

        # Compute rolling slopes
        price_slopes = _np_rolling_slope(close_col.values.astype(float), lookback)
        rsi_slopes = _np_rolling_slope(rsi_col.values.astype(float), lookback)
        macd_slopes = _np_rolling_slope(macd_hist_col.values.astype(float), lookback)
        mfi_slopes = _np_rolling_slope(mfi_col.values.astype(float), lookback)

        w_rsi = p["weight_rsi"]
        w_macd = p["weight_macd"]
        w_mfi = p["weight_mfi"]

        for i in range(n):
            if np.isnan(price_slopes[i]) or np.isnan(rsi_slopes[i]) or np.isnan(macd_slopes[i]) or np.isnan(mfi_slopes[i]):
                continue

            ps = price_slopes[i]
            divs = []

            # RSI divergence
            d_rsi = 0.0
            if ps > 0 and rsi_slopes[i] < 0:
                d_rsi = -(abs(ps) + abs(rsi_slopes[i])) * w_rsi
            elif ps < 0 and rsi_slopes[i] > 0:
                d_rsi = (abs(ps) + abs(rsi_slopes[i])) * w_rsi
            divs.append(d_rsi)

            # MACD divergence
            d_macd = 0.0
            if ps > 0 and macd_slopes[i] < 0:
                d_macd = -(abs(ps) + abs(macd_slopes[i])) * w_macd
            elif ps < 0 and macd_slopes[i] > 0:
                d_macd = (abs(ps) + abs(macd_slopes[i])) * w_macd
            divs.append(d_macd)

            # MFI divergence
            d_mfi = 0.0
            if ps > 0 and mfi_slopes[i] < 0:
                d_mfi = -(abs(ps) + abs(mfi_slopes[i])) * w_mfi
            elif ps < 0 and mfi_slopes[i] > 0:
                d_mfi = (abs(ps) + abs(mfi_slopes[i])) * w_mfi
            divs.append(d_mfi)

            signs = [np.sign(d) for d in divs if d != 0.0]
            if not signs:
                continue

            pos_count = sum(1 for s in signs if s > 0)
            neg_count = sum(1 for s in signs if s < 0)
            if pos_count >= neg_count:
                dominant_sign = 1.0
                n_conf = pos_count
            else:
                dominant_sign = -1.0
                n_conf = neg_count

            if n_conf < p["min_confirming_indicators"]:
                continue

            raw_div = sum(d for d in divs if np.sign(d) == dominant_sign)
            if abs(raw_div) <= p["min_divergence_magnitude"]:
                continue

            # ATR normalization
            normalized = raw_div
            if atr_col is not None:
                atr_val = atr_col.iloc[i]
                close_val = close_col.iloc[i]
                if atr_val > 0 and close_val > 0:
                    vol_scalar = atr_val / close_val
                    normalized = raw_div / (vol_scalar * p["norm_scale"])

            result.iloc[i] = normalized

        return result
