"""Feature requirements for DivergenceEdgeScorer."""
from __future__ import annotations

# Indicators this model requires from the feature pipeline
REQUIRED_INDICATORS: list[str] = [
    "RSI",
    "MACD",
    "MFI",
    "Momentum",
    "LinReg",
    "ATR",
]

# Specific fields used from indicator output
REQUIRED_FIELDS: list[str] = [
    "RSI",
    "MACD",
    "MFI",
    "Momentum",
    "LinReg",
    "ATR",
    "eng_volume_adjusted_momentum",
    "eng_atr_normalized_return",
    "eng_residual_momentum",
    "eng_altcoin_market_momentum",
    "eng_altcoin_beta",
    "eng_cross_asset_regime_state",
    "eng_regime_alignment_score",
]
