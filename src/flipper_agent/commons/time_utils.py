"""Shared UTC time helpers."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def to_utc_iso(timestamp: datetime | None = None) -> str:
    current = timestamp.astimezone(UTC) if timestamp is not None else utc_now()
    return current.isoformat(timespec="seconds").replace("+00:00", "Z")
