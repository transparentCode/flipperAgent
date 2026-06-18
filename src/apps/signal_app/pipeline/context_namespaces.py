"""Helpers for attaching shared lower-timeframe context into feature payloads."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

LTF_CONTEXT_PREFIX = "ctx_ltf"
TRANSPORT_CONTEXT_KEY = "ctx_transport"


def ltf_context_key(profile: str) -> str:
    """Return the canonical feature namespace key for a lower-timeframe profile."""

    cleaned = profile.strip()
    if not cleaned:
        raise ValueError("context profile must be non-empty")
    return f"{LTF_CONTEXT_PREFIX}_{cleaned}"


def merge_ltf_context(
    features: Mapping[str, Any],
    *,
    profiles: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge lower-timeframe shared context under stable namespaced keys."""

    merged = dict(features)
    if not profiles:
        return merged
    for profile, values in profiles.items():
        merged[ltf_context_key(profile)] = dict(values)
    return merged


def build_transport_context(candle: Any) -> dict[str, Any]:
    """Return canonical transport metadata derived from an OHLCV candle payload."""

    return {
        "base_timeframe": getattr(candle, "base_timeframe", "1m"),
        "bar_span_seconds": int(getattr(candle, "bar_span_seconds", 60) or 60),
        "close_timestamp": float(getattr(candle, "close_timestamp", 0.0) or 0.0),
        "ingestion_timestamp": float(getattr(candle, "ingestion_timestamp", 0.0) or 0.0),
        "publication_lag_ms": int(getattr(candle, "publication_lag_ms", 0) or 0),
        "provider": str(getattr(candle, "provider", "") or ""),
        "origin": str(getattr(candle, "origin", "") or ""),
    }


__all__ = [
    "LTF_CONTEXT_PREFIX",
    "TRANSPORT_CONTEXT_KEY",
    "build_transport_context",
    "ltf_context_key",
    "merge_ltf_context",
]
