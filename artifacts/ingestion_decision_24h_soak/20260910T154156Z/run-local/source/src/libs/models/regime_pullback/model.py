"""RegimePullbackScorer — mean-reversion edge conditional on confirmed regime."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from libs.contracts.signal import ParamDef, ScoringOutput
from libs.contracts.schemas import FeatureVector
from libs.models.base import ModelMeta
from libs.models.scoring_base import ScoringModel
from libs.models.registry import ModelRegistry


@ModelRegistry.register("RegimePullbackScorer")
class RegimePullbackScorer(ScoringModel):

    meta = ModelMeta(
        name="RegimePullbackScorer",
        model_type="scoring",
        required_indicators=["KAMA_slow", "ATR", "ADX", "RSI", "BollingerBands", "KeltnerChannel"],
        required_fields=[
            "KAMA_slow", "ATR", "RSI",
            "eng_regime_score", "eng_mean_reversion_z", "eng_squeeze_intensity",
            "eng_btc_dominance_regime", "eng_market_cap_breadth",
            "eng_cross_asset_regime_state", "eng_regime_alignment_score",
        ],
        hyperparameter_schema={
            "regime_threshold": ParamDef(type="float", default=-0.1, low=-0.5, high=0.3, step=0.05),
            "min_z_depth": ParamDef(type="float", default=1.0, low=0.5, high=2.5, step=0.1),
            "rsi_oversold_gate": ParamDef(type="int", default=40, low=25, high=50, step=1),
            "rsi_overbought_gate": ParamDef(type="int", default=60, low=50, high=75, step=1),
            "squeeze_weight": ParamDef(type="float", default=0.3, low=0.0, high=0.8, step=0.05),
            "breadth_weight": ParamDef(type="float", default=0.2, low=0.0, high=0.5, step=0.05),
            "btc_dom_weight": ParamDef(type="float", default=0.3, low=0.0, high=0.6, step=0.05),
            "base_conviction": ParamDef(type="float", default=0.3, low=0.1, high=0.5, step=0.05),
            "depth_bonus": ParamDef(type="float", default=0.4, low=0.1, high=0.6, step=0.05),
            "max_z_for_full_conviction": ParamDef(type="float", default=3.0, low=1.5, high=5.0, step=0.5),
            "regime_bonus": ParamDef(type="float", default=0.3, low=0.0, high=0.5, step=0.05),
            "regime_overlay_weight": ParamDef(type="float", default=0.3, low=0.0, high=0.8, step=0.05),
            "suppress_broad_selloff": ParamDef(type="int", default=1, low=0, high=1, step=1),
        },
        min_history_bars=50,
    )

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params or {})

    # ------------------------------------------------------------------
    # Single-tick evaluation
    # ------------------------------------------------------------------

    def evaluate(self, features: FeatureVector) -> ScoringOutput:
        p = self.params
        f = features.features

        regime_score = f.get("eng_regime_score")
        mr_z = f.get("eng_mean_reversion_z")
        rsi = f.get("RSI")
        squeeze_intensity = f.get("eng_squeeze_intensity")
        btc_dom_regime = f.get("eng_btc_dominance_regime")
        market_breadth = f.get("eng_market_cap_breadth")

        zero = ScoringOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            edge_score=0.0,
            conviction=0.0,
        )

        # Gate 0: suppress during BROAD_SELLOFF
        regime_state = f.get("eng_cross_asset_regime_state")
        alignment = f.get("eng_regime_alignment_score", 0.0)
        if p["suppress_broad_selloff"] and regime_state == 3:
            return zero

        # Gate 1: regime must be ranging
        if regime_score is None or regime_score >= p["regime_threshold"]:
            return zero

        # Gate 2: pullback must be deep enough
        if mr_z is None or abs(mr_z) <= p["min_z_depth"]:
            return zero

        # Direction: negative z → LONG, positive z → SHORT
        direction = -1 if mr_z > 0 else 1

        # Gate 3: RSI must confirm direction
        if rsi is None:
            return zero
        if direction == 1 and rsi >= p["rsi_oversold_gate"]:
            return zero
        if direction == -1 and rsi <= p["rsi_overbought_gate"]:
            return zero

        # Compute edge components
        raw_edge = abs(mr_z) - p["min_z_depth"]

        regime_multiplier = max(0.0, min((-regime_score + 1.0) / 2.0, 1.0))

        squeeze_bonus = 0.0
        if squeeze_intensity is not None:
            squeeze_bonus = max(0.0, 1.0 - squeeze_intensity) * p["squeeze_weight"]

        breadth_adjustment = 1.0
        if market_breadth is not None:
            breadth_adjustment = max(0.5, min(1.0 + market_breadth * p["breadth_weight"], 1.5))

        btc_dom_penalty = 1.0
        if direction == 1 and features.asset != "BTCUSDT":
            if btc_dom_regime is not None:
                btc_dom_penalty = max(0.5, min(1.0 - btc_dom_regime * p["btc_dom_weight"], 1.0))

        edge_score = (
            direction
            * raw_edge
            * regime_multiplier
            * (1.0 + squeeze_bonus)
            * breadth_adjustment
            * btc_dom_penalty
        )

        # Regime overlay: scale edge by alignment
        edge_score *= (1.0 + alignment * p["regime_overlay_weight"])

        # Conviction
        conviction = (
            p["base_conviction"]
            + p["depth_bonus"] * min(abs(mr_z) / p["max_z_for_full_conviction"], 1.0)
            + p["regime_bonus"] * max(0.0, -regime_score)
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
                "regime_score": regime_score,
                "mr_z": mr_z,
                "rsi": rsi,
                "raw_edge": raw_edge,
                "regime_multiplier": regime_multiplier,
                "squeeze_bonus": squeeze_bonus,
                "breadth_adjustment": breadth_adjustment,
                "btc_dom_penalty": btc_dom_penalty,
                "regime_state": regime_state,
                "regime_alignment": alignment,
            },
        )

    # ------------------------------------------------------------------
    # Batch evaluation
    # ------------------------------------------------------------------

    def _batch_evaluate_impl(self, feature_df: pd.DataFrame) -> pd.Series:
        p = self.params

        regime = feature_df.get("eng_regime_score")
        mr_z = feature_df.get("eng_mean_reversion_z")
        rsi = feature_df.get("RSI")
        squeeze = feature_df.get("eng_squeeze_intensity")
        btc_dom = feature_df.get("eng_btc_dominance_regime")
        breadth = feature_df.get("eng_market_cap_breadth")

        n = len(feature_df)
        result = pd.Series(0.0, index=feature_df.index)

        if regime is None or mr_z is None or rsi is None:
            return result

        # Gate 0: suppress BROAD_SELLOFF
        regime_state_col = feature_df.get("eng_cross_asset_regime_state")
        alignment_col = feature_df.get("eng_regime_alignment_score")
        if p["suppress_broad_selloff"] and regime_state_col is not None:
            broad_selloff = regime_state_col == 3
        else:
            broad_selloff = pd.Series(False, index=feature_df.index)

        # Gate 1: regime < threshold
        gate1 = regime < p["regime_threshold"]
        # Gate 2: |z| > min_z_depth
        gate2 = mr_z.abs() > p["min_z_depth"]
        # Direction
        direction = np.where(mr_z < 0, 1, -1)
        # Gate 3: RSI confirms
        rsi_long_ok = rsi < p["rsi_oversold_gate"]
        rsi_short_ok = rsi > p["rsi_overbought_gate"]
        gate3 = np.where(direction == 1, rsi_long_ok, rsi_short_ok)

        valid = gate1 & gate2 & gate3

        raw_edge = mr_z.abs() - p["min_z_depth"]
        regime_multiplier = ((-regime + 1.0) / 2.0).clip(0.0, 1.0)

        squeeze_bonus = pd.Series(0.0, index=feature_df.index)
        if squeeze is not None:
            squeeze_bonus = (1.0 - squeeze).clip(lower=0.0) * p["squeeze_weight"]

        breadth_adj = pd.Series(1.0, index=feature_df.index)
        if breadth is not None:
            breadth_adj = (1.0 + breadth * p["breadth_weight"]).clip(0.5, 1.5)

        # BTC dom penalty is asset-specific — in batch we cannot check asset per row
        # so we skip it (batch is for single-asset backtesting anyway)
        btc_dom_pen = pd.Series(1.0, index=feature_df.index)

        edge = (
            direction
            * raw_edge
            * regime_multiplier
            * (1.0 + squeeze_bonus)
            * breadth_adj
            * btc_dom_pen
        )

        # Regime overlay: scale by alignment
        if alignment_col is not None:
            edge = edge * (1.0 + alignment_col * p["regime_overlay_weight"])

        valid = valid & ~broad_selloff
        result[valid] = edge[valid]
        return result
