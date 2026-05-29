"""Feature requirements for Momentum."""
from __future__ import annotations

# Indicators this model requires from the feature pipeline
REQUIRED_INDICATORS: list[str] = [
    "RSI",
    "MACD",
]

# Specific fields used from indicator output
REQUIRED_FIELDS: list[str] = [
    "RSI",
    "MACD_histogram",
    "MACD_line",
]
