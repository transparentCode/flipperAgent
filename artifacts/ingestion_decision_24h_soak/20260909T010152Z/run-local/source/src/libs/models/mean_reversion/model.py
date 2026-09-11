"""MeanReversionModel v2 — continuous z-score scoring model.

Three-component z-score formula (RSI + BB position + KAMA/ATR deviation)
with ADX sigmoid soft scaling.  Emits continuous ``ScoringOutput`` on every bar.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from numba import njit

from libs.contracts.schemas import FeatureVector, ParamDef
from libs.contracts.signal import ScoringOutput
from libs.models.base import ModelMeta
from libs.models.feature_extractors import extract_rsi
from libs.models.registry import ModelRegistry
from libs.models.scoring_base import ScoringModel


@njit(cache=True)
def _batch_mr_zscore(
    rsi: np.ndarray,
    bb_upper: np.ndarray,
    bb_lower: np.ndarray,
    close: np.ndarray,
    kama: np.ndarray,
    atr: np.ndarray,
    adx: np.ndarray,
    rsi_scale: float,
    w_rsi: float,
    w_bb: float,
    w_kama: float,
    adx_center: float,
    adx_steepness: float,
) -> np.ndarray:
    """Numba-accelerated batch z-score computation."""
    n = len(rsi)
    edge = np.empty(n, dtype=np.float64)

    for i in range(n):
        # RSI z-score
        if np.isnan(rsi[i]):
            z_rsi = 0.0
        else:
            z_rsi = -(rsi[i] - 50.0) / rsi_scale

        # BB position z-score
        bb_range = bb_upper[i] - bb_lower[i]
        if bb_range > 0 and not np.isnan(close[i]):
            bb_pct = (close[i] - bb_lower[i]) / bb_range
            z_bb = -(bb_pct - 0.5) * 2.0
        else:
            z_bb = 0.0

        # KAMA deviation
        if not np.isnan(kama[i]) and not np.isnan(atr[i]) and atr[i] > 0:
            z_kama = -(close[i] - kama[i]) / atr[i]
        else:
            z_kama = 0.0

        # Raw composite
        raw = w_rsi * z_rsi + w_bb * z_bb + w_kama * z_kama

        # ADX soft scaling
        if not np.isnan(adx[i]):
            adx_scale = 1.0 / (1.0 + np.exp((adx[i] - adx_center) / adx_steepness))
        else:
            adx_scale = 0.5

        edge[i] = raw * adx_scale

    return edge


@ModelRegistry.register("MeanReversion")
class MeanReversionModel(ScoringModel):

    meta = ModelMeta(
        name="MeanReversion",
        model_type="scoring",
        required_indicators=["RSI", "BollingerBands", "ADX", "KAMA_fast", "ATR"],
        required_fields=[
            "RSI",
            "BollingerBands_upper", "BollingerBands_lower",
            "ADX",
            "KAMA_fast",
            "ATR",
        ],
        hyperparameter_schema={
            "rsi_scale": ParamDef(type="float", default=15.0, low=5.0, high=30.0, step=1.0),
            "w_rsi": ParamDef(type="float", default=0.4, low=0.1, high=0.8, step=0.05),
            "w_bb": ParamDef(type="float", default=0.4, low=0.1, high=0.8, step=0.05),
            "w_kama": ParamDef(type="float", default=0.2, low=0.0, high=0.5, step=0.05),
            "adx_center": ParamDef(type="float", default=25.0, low=15.0, high=40.0, step=1.0),
            "adx_steepness": ParamDef(type="float", default=5.0, low=2.0, high=15.0, step=1.0),
        },
        min_history_bars=30,
    )

    # ------------------------------------------------------------------
    # Live single-tick evaluation
    # ------------------------------------------------------------------

    def evaluate(self, features: FeatureVector) -> ScoringOutput:
        rsi = extract_rsi(features.features)
        bb_upper = self._extract_bb(features.features, "upper")
        bb_lower = self._extract_bb(features.features, "lower")
        close = features.bar_data.get("close")
        kama = self._extract_scalar(features.features, "KAMA_fast")
        atr = self._extract_scalar(features.features, "ATR")
        adx = self._extract_adx(features.features)

        # Bail-out if close is missing
        if close is None or close == 0.0:
            return ScoringOutput(
                model_name=self.meta.name,
                asset=features.asset,
                timeframe=features.timeframe,
                timestamp=features.timestamp,
                edge_score=0.0,
                conviction=0.0,
                metadata={"trigger": "missing_close"},
            )

        # Component z-scores (graceful degradation)
        z_rsi = -(rsi - 50.0) / self.params["rsi_scale"] if rsi is not None else 0.0

        if bb_upper is not None and bb_lower is not None:
            bb_range = bb_upper - bb_lower
            if bb_range > 0:
                bb_pct = (close - bb_lower) / bb_range
                z_bb = -(bb_pct - 0.5) * 2.0
            else:
                z_bb = 0.0
        else:
            z_bb = 0.0

        if kama is not None and atr is not None and atr > 0:
            z_kama = -(close - kama) / atr
        else:
            z_kama = 0.0

        # Raw composite edge
        raw_edge = (
            self.params["w_rsi"] * z_rsi
            + self.params["w_bb"] * z_bb
            + self.params["w_kama"] * z_kama
        )

        # ADX soft scaling
        if adx is not None:
            adx_scale = 1.0 / (1.0 + math.exp(
                (adx - self.params["adx_center"]) / self.params["adx_steepness"]
            ))
        else:
            adx_scale = 0.5

        edge_score = raw_edge * adx_scale

        # Conviction from raw_edge (before ADX scaling)
        conviction = abs(math.tanh(raw_edge))

        return ScoringOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            edge_score=edge_score,
            conviction=conviction,
            metadata={
                "z_rsi": z_rsi,
                "z_bb": z_bb,
                "z_kama": z_kama,
                "raw_edge": raw_edge,
                "adx_scale": adx_scale,
                "rsi": rsi,
                "adx": adx,
                "close": close,
            },
        )

    # ------------------------------------------------------------------
    # Batch evaluation for optimization / backtest
    # ------------------------------------------------------------------

    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        """Vectorized batch evaluation returning continuous float edge_scores."""
        n = len(feature_df)
        nan_arr = np.full(n, np.nan)

        rsi = feature_df["RSI"].values.astype(np.float64) if "RSI" in feature_df.columns else nan_arr.copy()
        bb_upper = feature_df["BollingerBands_upper"].values.astype(np.float64) if "BollingerBands_upper" in feature_df.columns else nan_arr.copy()
        bb_lower = feature_df["BollingerBands_lower"].values.astype(np.float64) if "BollingerBands_lower" in feature_df.columns else nan_arr.copy()
        close = feature_df["close"].values.astype(np.float64) if "close" in feature_df.columns else nan_arr.copy()
        kama = feature_df["KAMA_fast"].values.astype(np.float64) if "KAMA_fast" in feature_df.columns else nan_arr.copy()
        atr = feature_df["ATR"].values.astype(np.float64) if "ATR" in feature_df.columns else nan_arr.copy()
        adx = feature_df["ADX_adx"].values.astype(np.float64) if "ADX_adx" in feature_df.columns else nan_arr.copy()

        edge_arr = _batch_mr_zscore(
            rsi, bb_upper, bb_lower, close, kama, atr, adx,
            self.params["rsi_scale"],
            self.params["w_rsi"],
            self.params["w_bb"],
            self.params["w_kama"],
            self.params["adx_center"],
            self.params["adx_steepness"],
        )

        return pd.Series(edge_arr, index=feature_df.index)

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
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, dict):
            return val.get("value")
        return None

    @staticmethod
    def _extract_adx(features: dict[str, Any]) -> float | None:
        adx_data = features.get("ADX")
        if isinstance(adx_data, dict):
            val = adx_data.get("adx")
            if isinstance(val, (int, float)):
                return float(val)
        return None
