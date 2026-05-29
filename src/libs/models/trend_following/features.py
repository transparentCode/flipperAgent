"""Feature requirements for TrendFollowing."""
from __future__ import annotations

# Indicators this model requires from the feature pipeline
REQUIRED_INDICATORS: list[str] = [
    "EMA",
    "MACD",
    "ATR",
]

# Specific fields used from indicator output
REQUIRED_FIELDS: list[str] = [
    "EMA_fast",
    "EMA_slow",
    "MACD_line",
    "MACD_signal",
    "MACD_histogram",
    "ATR",
]
