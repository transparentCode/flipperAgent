"""Feature requirements for squeeze_breakout models.

SqueezeBreakout (direction) and SqueezeBreakoutScorer (scoring) share
most indicators; the scorer additionally requires ATR.
"""
from __future__ import annotations

# ---------- SqueezeBreakout (direction model) ----------

DIRECTION_REQUIRED_INDICATORS: list[str] = [
    "KAMA_fast",
    "KAMA_slow",
    "BollingerBands",
    "KeltnerChannel",
    "CCI",
    "ADX",
    "ADLine",
    "MFI",
    "Momentum",
]

DIRECTION_REQUIRED_FIELDS: list[str] = [
    "KAMA_fast",
    "KAMA_slow",
    "BollingerBands_upper",
    "BollingerBands_lower",
    "KeltnerChannel_upper",
    "KeltnerChannel_lower",
    "CCI",
    "ADX",
    "ADLine",
    "MFI",
    "Momentum",
]

# ---------- SqueezeBreakoutScorer (scoring model) ----------

SCORER_REQUIRED_INDICATORS: list[str] = [
    "KAMA_fast",
    "KAMA_slow",
    "BollingerBands",
    "KeltnerChannel",
    "CCI",
    "ADX",
    "ADLine",
    "MFI",
    "Momentum",
    "ATR",
]

SCORER_REQUIRED_FIELDS: list[str] = [
    "KAMA_fast",
    "KAMA_slow",
    "BollingerBands_upper",
    "BollingerBands_lower",
    "KeltnerChannel_upper",
    "KeltnerChannel_lower",
    "CCI",
    "ADX",
    "ADLine",
    "MFI",
    "Momentum",
    "ATR",
]

# ---------- Union (all indicators needed by any model in this package) ----------

REQUIRED_INDICATORS: list[str] = sorted(set(DIRECTION_REQUIRED_INDICATORS + SCORER_REQUIRED_INDICATORS))
REQUIRED_FIELDS: list[str] = sorted(set(DIRECTION_REQUIRED_FIELDS + SCORER_REQUIRED_FIELDS))
