"""Shared helpers for timeframe normalization and span math."""

from __future__ import annotations


def timeframe_to_seconds(timeframe: str, *, default: int = 60) -> int:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    if not timeframe:
        return default
    try:
        value = int(str(timeframe)[:-1])
    except (TypeError, ValueError):
        return default
    unit_seconds = units.get(str(timeframe)[-1].lower())
    if unit_seconds is None:
        return default
    return value * unit_seconds


__all__ = ["timeframe_to_seconds"]
