"""Time conversion for bounded historical requests."""

from __future__ import annotations

from datetime import UTC, datetime

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def epoch_milliseconds(value: datetime) -> int:
    elapsed = value - _EPOCH
    return (
        elapsed.days * 86_400_000
        + elapsed.seconds * 1_000
        + elapsed.microseconds // 1_000
    )


__all__ = ["epoch_milliseconds"]
