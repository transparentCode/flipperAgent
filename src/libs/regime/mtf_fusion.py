"""
Multi-Timeframe Regime Fusion.

Combines regime signals from multiple timeframes into a unified view.
Higher TF regimes provide structural context; lower TF regimes provide
execution-level precision.

Fusion strategy: hierarchical override with confidence weighting.
- If higher TF is CHOPPY -> suppress lower TF trend signals (reduce position_scale)
- If higher TF confirms lower TF trend -> boost confidence (increase position_scale)
- If higher TF is trending but lower TF is mean-reverting -> use lower TF for entries
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional

from app.regime.aggregation.rule_based import CHOPPY, TREND_REGIMES

# Agreement classifications
CONFIRMING = "CONFIRMING"
CONFLICTING = "CONFLICTING"
SUPPRESSING = "SUPPRESSING"


@dataclass(frozen=True)
class MTFConfig:
    """Config for multi-timeframe fusion."""

    higher_tf: str = ""  # e.g., "4h" -- empty means disabled
    higher_tf_weight: float = 0.4  # Weight of higher TF in fusion (0-1)
    conflict_penalty: float = 0.5  # Scale factor when TFs disagree
    confirmation_boost: float = 1.2  # Scale factor when TFs agree (magnitude capped at 1.0)


def _is_trending(regime: str) -> bool:
    """Check if a regime label is a trending regime."""
    return regime in TREND_REGIMES


def classify_agreement(primary_regime: str, higher_regime: str) -> str:
    """
    Classify the agreement between primary and higher TF regimes.

    Returns one of: CONFIRMING, CONFLICTING, SUPPRESSING.

    - SUPPRESSING: higher TF is CHOPPY (regardless of lower TF)
    - CONFIRMING:  both TFs trending, or both non-trending
    - CONFLICTING: one trending, other non-trending
    """
    if higher_regime == CHOPPY:
        return SUPPRESSING

    primary_trending = _is_trending(primary_regime)
    higher_trending = _is_trending(higher_regime)

    if primary_trending == higher_trending:
        return CONFIRMING
    return CONFLICTING


def adjust_position_scale(
    primary_scale: float,
    agreement: str,
    config: MTFConfig,
) -> float:
    """
    Adjust position_scale based on MTF agreement.

    - CONFIRMING:  boost (magnitude capped at 1.0)
    - SUPPRESSING: heavy penalty using conflict_penalty * (1 - higher_tf_weight)
    - CONFLICTING: moderate penalty using conflict_penalty
    """
    if agreement == CONFIRMING:
        return max(-1.0, min(1.0, primary_scale * config.confirmation_boost))
    elif agreement == SUPPRESSING:
        return round(
            primary_scale * config.conflict_penalty * (1.0 - config.higher_tf_weight),
            4,
        )
    elif agreement == CONFLICTING:
        return round(primary_scale * config.conflict_penalty, 4)
    # Fallback: no adjustment
    return primary_scale


class MTFFusion:
    """Fuses regime signals from two timeframes."""

    def __init__(self, config: Optional[MTFConfig] = None):
        self.config = config or MTFConfig()

    @property
    def enabled(self) -> bool:
        return bool(self.config.higher_tf)

    def fuse_series(
        self,
        primary_df: pd.DataFrame,  # Lower TF regime output (e.g., 1h)
        higher_df: pd.DataFrame,  # Higher TF regime output (e.g., 4h)
    ) -> pd.DataFrame:
        """
        Fuse higher TF regime context into primary (execution) TF.

        The higher TF DataFrame has fewer rows. Align by forward-filling
        the higher TF regime to the primary TF index (each higher TF bar
        covers multiple primary TF bars).

        Required columns in both DataFrames:
            regime, p_trending, position_scale

        Returns modified primary_df with adjusted position_scale and
        additional columns: htf_regime, htf_p_trending, mtf_agreement.
        """
        result = primary_df.copy()

        # Preserve original position_scale before MTF adjustment
        result["position_scale_raw"] = result["position_scale"].copy()

        # Align higher TF to primary TF index via forward-fill
        htf_regime = higher_df["regime"].reindex(primary_df.index, method="ffill")
        htf_p_trending = higher_df["p_trending"].reindex(
            primary_df.index, method="ffill"
        )

        result["htf_regime"] = htf_regime
        result["htf_p_trending"] = htf_p_trending

        # Classify agreement per bar
        result["mtf_agreement"] = [
            classify_agreement(pri, htf)
            for pri, htf in zip(result["regime"].values, htf_regime.values)
        ]

        # Adjust position_scale based on agreement
        result["position_scale"] = [
            adjust_position_scale(scale, agreement, self.config)
            for scale, agreement in zip(
                result["position_scale_raw"].values,
                result["mtf_agreement"].values,
            )
        ]

        return result
