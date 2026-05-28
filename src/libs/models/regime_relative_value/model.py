"""RegimeRelativeValueScorer — mean-reversion edge from cross-asset relative value.

Core hypothesis: BTC.D rises + TOTAL3 falls → alts underperforming → mean-reversion LONG.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from libs.contracts.signal import ParamDef, ScoringOutput
from libs.contracts.schemas import FeatureVector
from libs.models.base import ModelMeta
from libs.models.scoring_base import ScoringModel
from libs.models.scoring_registry import ScoringModelRegistry


@ScoringModelRegistry.register("RegimeRelativeValueScorer")
class RegimeRelativeValueScorer(ScoringModel):

    meta = ModelMeta(
        name="RegimeRelativeValueScorer",
        required_indicators=["RSI", "ATR"],
        required_fields=[
            "RSI", "ATR",
            "eng_cross_asset_regime_state",
            "eng_regime_alignment_score",
            "eng_relative_strength_vs_total3",
            "eng_btc_dominance_momentum",
        ],
        hyperparameter_schema={
            "rs_underperformance_threshold": ParamDef(type="float", default=-0.5, low=-2.0, high=0.0, step=0.1),
            "rsi_oversold_gate": ParamDef(type="int", default=35, low=20, high=45, step=1),
            "regime_state_required": ParamDef(type="int", default=0, low=0, high=0, step=1),
            "min_btc_d_momentum": ParamDef(type="float", default=0.3, low=0.0, high=1.5, step=0.1),
            "conviction_base": ParamDef(type="float", default=0.3, low=0.1, high=0.5, step=0.05),
            "conviction_depth_bonus": ParamDef(type="float", default=0.4, low=0.1, high=0.6, step=0.05),
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

        zero = ScoringOutput(
            model_name=self.meta.name,
            asset=features.asset,
            timeframe=features.timeframe,
            timestamp=features.timestamp,
            edge_score=0.0,
            conviction=0.0,
        )

        regime_state = f.get("eng_cross_asset_regime_state")
        alignment = f.get("eng_regime_alignment_score", 0.0)
        rs = f.get("eng_relative_strength_vs_total3")
        btc_d_mom = f.get("eng_btc_dominance_momentum")
        rsi = f.get("RSI")
        atr = f.get("ATR")

        # Gate 1: regime state must be RISK_OFF (or configured state)
        if regime_state is None or regime_state != p["regime_state_required"]:
            return zero

        # Gate 2: asset must be underperforming TOTAL3
        if rs is None or rs >= p["rs_underperformance_threshold"]:
            return zero

        # Gate 3: RSI must confirm oversold
        if rsi is None or rsi >= p["rsi_oversold_gate"]:
            return zero

        # Gate 4: BTC.D momentum must be rising (confirming regime)
        if btc_d_mom is None or btc_d_mom <= p["min_btc_d_momentum"]:
            return zero

        # Direction: always LONG (mean-reversion from underperformance)
        direction = 1

        # Edge: magnitude of underperformance scaled by alignment and ATR
        raw_edge = abs(rs)
        edge_score = raw_edge * (1.0 + alignment * 0.5)

        # ATR normalization
        if atr is not None and atr > 0:
            close = features.bar_data.get("close", 0.0)
            if close > 0:
                edge_score = edge_score / (atr / close)

        edge_score = direction * edge_score

        # Conviction
        conviction = (
            p["conviction_base"]
            + p["conviction_depth_bonus"] * min(abs(rs) / 2.0, 1.0)
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
                "regime_state": regime_state,
                "relative_strength": rs,
                "rsi": rsi,
                "btc_d_momentum": btc_d_mom,
                "alignment": alignment,
            },
        )

    # ------------------------------------------------------------------
    # Batch evaluation
    # ------------------------------------------------------------------

    def batch_evaluate(self, feature_df: pd.DataFrame) -> pd.Series:
        p = self.params
        n = len(feature_df)
        result = pd.Series(0.0, index=feature_df.index)

        regime_state = feature_df.get("eng_cross_asset_regime_state")
        alignment = feature_df.get("eng_regime_alignment_score")
        rs = feature_df.get("eng_relative_strength_vs_total3")
        btc_d_mom = feature_df.get("eng_btc_dominance_momentum")
        rsi = feature_df.get("RSI")
        atr = feature_df.get("ATR")
        close = feature_df.get("close")

        if regime_state is None or rs is None or rsi is None or btc_d_mom is None:
            return result

        # Gates
        gate1 = regime_state == p["regime_state_required"]
        gate2 = rs < p["rs_underperformance_threshold"]
        gate3 = rsi < p["rsi_oversold_gate"]
        gate4 = btc_d_mom > p["min_btc_d_momentum"]

        valid = gate1 & gate2 & gate3 & gate4

        raw_edge = rs.abs()
        align_vals = alignment if alignment is not None else pd.Series(0.0, index=feature_df.index)
        edge = raw_edge * (1.0 + align_vals * 0.5)

        # ATR normalization
        if atr is not None and close is not None:
            vol_scalar = atr / close.clip(lower=1e-8)
            edge = edge / vol_scalar.clip(lower=1e-8)

        result[valid] = edge[valid]
        return result
