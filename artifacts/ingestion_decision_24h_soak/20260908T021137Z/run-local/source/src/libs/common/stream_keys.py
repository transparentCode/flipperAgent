"""Shared hot-path stream key helpers."""

from __future__ import annotations


def feature_stream_key(
    asset: str,
    timeframe: str,
    *,
    trigger_timeframe: str | None = None,
) -> str:
    normalized_asset = str(asset).upper().strip()
    decision_timeframe = str(timeframe).strip()
    trigger = str(trigger_timeframe or decision_timeframe).strip()
    if trigger and trigger != decision_timeframe:
        return f"features:{normalized_asset}:{decision_timeframe}@{trigger}"
    return f"features:{normalized_asset}:{decision_timeframe}"


def price_update_stream_key(asset: str, timeframe: str) -> str:
    normalized_asset = str(asset).upper().strip()
    normalized_timeframe = str(timeframe).strip()
    return f"price_update:{normalized_asset}:{normalized_timeframe}"


__all__ = ["feature_stream_key", "price_update_stream_key"]
