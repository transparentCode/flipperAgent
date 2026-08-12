"""Fixed-duration UTC bucket alignment for ingestion services."""

from __future__ import annotations

from datetime import datetime, timedelta


def aligned_bucket_start(
    timestamp: datetime,
    duration: timedelta,
    alignment_origin: datetime,
) -> datetime:
    """Return the fixed-duration bucket start containing ``timestamp``."""
    return alignment_origin + ((timestamp - alignment_origin) // duration) * duration


__all__ = ["aligned_bucket_start"]
