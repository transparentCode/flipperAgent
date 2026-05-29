"""Feature requirements for MeanReversion."""
from __future__ import annotations

# Indicators this model requires from the feature pipeline
REQUIRED_INDICATORS: list[str] = [
    "RSI",
    "BollingerBands",
    "ADX",
]

# Specific fields used from indicator output
REQUIRED_FIELDS: list[str] = [
    "RSI",
    "BollingerBands_upper",
    "BollingerBands_lower",
    "ADX",
]
