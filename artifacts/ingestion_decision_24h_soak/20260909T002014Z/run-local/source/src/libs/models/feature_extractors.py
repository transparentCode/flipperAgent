"""Shared feature extraction helpers for strategy models."""
from __future__ import annotations
from typing import Any


def extract_rsi(features: dict[str, Any]) -> float | None:
    """Extract RSI value from feature dict."""
    rsi = features.get("RSI")
    if isinstance(rsi, dict):
        return rsi.get("value")
    if isinstance(rsi, (int, float)):
        return float(rsi)
    return None


def extract_macd_field(features: dict[str, Any], field: str) -> float | None:
    """Extract a MACD sub-field (e.g., 'histogram', 'line') from feature dict."""
    macd = features.get("MACD")
    if isinstance(macd, dict):
        val = macd.get(field)
        if isinstance(val, (int, float)):
            return float(val)
    return None
