"""Feature requirements for _TemplateModel."""
from __future__ import annotations

# Indicators this model requires from the feature pipeline
REQUIRED_INDICATORS: list[str] = [
    # e.g. "RSI", "BollingerBands"
]

# Specific fields used from indicator output
REQUIRED_FIELDS: list[str] = [
    # e.g. "RSI", "BollingerBands_upper", "BollingerBands_lower"
]
