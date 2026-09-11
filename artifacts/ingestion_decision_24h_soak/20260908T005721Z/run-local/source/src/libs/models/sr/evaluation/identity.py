"""Deterministic identity helpers for SR evaluation contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from libs.models.sr.domain.identity import (
    deterministic_hash,
    require_utc,
    utc_isoformat,
)


def normalize_utc(value: datetime, *, field_name: str) -> datetime:
    """Normalize an evaluation timestamp using the domain UTC contract."""
    return require_utc(value, field_name=field_name)


def canonical_timestamp(value: datetime, *, field_name: str) -> str:
    """Return a normalized UTC timestamp for identity payloads."""
    return utc_isoformat(normalize_utc(value, field_name=field_name))


def evaluation_hash(payload: Mapping[str, Any]) -> str:
    """Hash an explicitly constructed semantic evaluation payload."""
    return deterministic_hash(payload)
