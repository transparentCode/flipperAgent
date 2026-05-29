"""Feature requirements for RegimeRelativeValueScorer."""
from __future__ import annotations

# Indicators this model requires from the feature pipeline
REQUIRED_INDICATORS: list[str] = [
    "RSI",
    "ATR",
]

# Specific fields used from indicator output
REQUIRED_FIELDS: list[str] = [
    "RSI",
    "ATR",
    "eng_cross_asset_regime_state",
    "eng_regime_alignment_score",
    "eng_relative_strength_vs_total3",
    "eng_btc_dominance_momentum",
]
