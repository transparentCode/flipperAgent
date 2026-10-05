"""Fixed-duration UTC bucket alignment for ingestion domain concepts."""

from __future__ import annotations

from datetime import datetime, timedelta


def aligned_bucket_start(
    timestamp: datetime,
    duration: timedelta,
    alignment_origin: datetime,
) -> datetime:
    """Return the fixed-duration bucket start containing ``timestamp``."""
    return alignment_origin + ((timestamp - alignment_origin) // duration) * duration


def is_aligned(
    timestamp: datetime,
    duration: timedelta,
    alignment_origin: datetime,
) -> bool:
    """Return whether ``timestamp`` is a bucket start on the fixed-duration grid."""
    return aligned_bucket_start(timestamp, duration, alignment_origin) == timestamp


__all__ = ["aligned_bucket_start", "is_aligned"]
