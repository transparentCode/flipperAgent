"""Compatibility exports for canonical trendline storage."""

from .storage import (
    InMemoryTrendlineFamilyRepository,
    InMemoryTrendlineRepository,
    SnapshotVersionError,
    TrendlineFamilyRepository,
    TrendlineRepository,
    deserialize_snapshot,
    serialize_snapshot,
)
# Retained for the historical Phase-G compatibility import path.  New callers
# use the storage boundary and do not depend on this internal lineage helper.
from .storage.memory import _phase_g_enabled  # noqa: F401

__all__ = [
    "InMemoryTrendlineFamilyRepository",
    "InMemoryTrendlineRepository",
    "SnapshotVersionError",
    "TrendlineFamilyRepository",
    "TrendlineRepository",
    "deserialize_snapshot",
    "serialize_snapshot",
]
