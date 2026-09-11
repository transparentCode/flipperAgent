"""Canonical identities for SR v2 objects."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from hashlib import sha256
from math import isfinite
from typing import Any

from ..contracts import require_utc


def _canonical(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("non-finite float cannot be canonicalized")
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal cannot be canonicalized")
        return {"__decimal__": str(value.normalize())}
    if isinstance(value, datetime):
        require_utc(value, field_name="identity datetime")
        return {"__datetime__": value.isoformat(timespec="microseconds")}
    if isinstance(value, timedelta):
        return {"__timedelta_us__": value.days * 86_400_000_000 + value.seconds * 1_000_000 + value.microseconds}
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical(asdict(value))
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("identity mappings require string keys")
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    raise TypeError(f"unsupported identity value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonical(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def canonical_hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def bar_content_payload(bar: Any) -> dict[str, Any]:
    """Return the canonical, ordered-window identity payload for one closed bar."""

    required = (
        "timeframe",
        "bar_open_at",
        "bar_close_at",
        "market_as_of",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "taker_buy_base",
        "closed",
    )
    if any(not hasattr(bar, name) for name in required):
        raise TypeError("bar content identity requires an SRBar-like value")
    return {name: getattr(bar, name) for name in required}


def bar_content_fingerprint(bar: Any) -> str:
    """Hash one bar's complete point-in-time content identity."""

    return canonical_hash(bar_content_payload(bar))


def fingerprint_sequence_hash(fingerprints: Any) -> str:
    """Hash an ordered sequence of per-bar content fingerprints."""

    return canonical_hash(tuple(fingerprints))


def window_fingerprint(bars: Any) -> str:
    """Hash an ordered exact window, including times and OHLCV content."""

    return fingerprint_sequence_hash(bar_content_fingerprint(bar) for bar in tuple(bars))


def zone_identity_payload(
    *,
    venue: str,
    instrument_id: str,
    asset: str,
    source_timeframe: str,
    kernel_id: str,
    kernel_version: str,
    source_candidate_key: str,
    available_at: datetime,
    center: Decimal,
    lower: Decimal,
    upper: Decimal,
    predecessor_id: str | None,
    identity_schema_version: int = 1,
) -> dict[str, Any]:
    return {
        "identity_schema_version": identity_schema_version,
        "venue": venue,
        "instrument_id": instrument_id,
        "asset": asset,
        "source_timeframe": source_timeframe,
        "kernel_id": kernel_id,
        "kernel_version": kernel_version,
        "source_candidate_key": source_candidate_key,
        "available_at": available_at,
        "geometry": {"center": center, "lower": lower, "upper": upper},
        "predecessor_id": predecessor_id,
    }


def make_zone_id(**kwargs: Any) -> str:
    return canonical_hash(zone_identity_payload(**kwargs))


__all__ = [
    "bar_content_fingerprint",
    "bar_content_payload",
    "canonical_hash",
    "canonical_json",
    "fingerprint_sequence_hash",
    "make_zone_id",
    "window_fingerprint",
    "zone_identity_payload",
]
