"""Feature requirements for RegimePullbackScorer."""
from __future__ import annotations

# Indicators this model requires from the feature pipeline
REQUIRED_INDICATORS: list[str] = [
    "KAMA_slow",
    "ATR",
    "ADX",
    "RSI",
    "BollingerBands",
    "KeltnerChannel",
]

# Specific fields used from indicator output
REQUIRED_FIELDS: list[str] = [
    "KAMA_slow",
    "ATR",
    "RSI",
    "eng_regime_score",
    "eng_mean_reversion_z",
    "eng_squeeze_intensity",
    "eng_btc_dominance_regime",
    "eng_market_cap_breadth",
    "eng_cross_asset_regime_state",
    "eng_regime_alignment_score",
]
