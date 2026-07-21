"""Storage-neutral trendline repository contract and snapshot serialization."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..contracts import ContractValidationError
from ..domain import TrendlineContext, TrendlineEvent, TrendlineFamily, TrendlineSnapshot
from .serialization import deserialize_snapshot, serialize_snapshot


class SnapshotVersionError(ContractValidationError):
    """Raised when immutable repository lineage or identity is invalid."""


class TrendlineRepository(Protocol):
    """Current-head and causal historical state boundary for one model store."""

    def latest_snapshot(self, asset: str, timeframe: str) -> TrendlineSnapshot | None: ...

    def save_snapshot(self, snapshot: TrendlineSnapshot) -> None: ...

    def save_family(self, family: TrendlineFamily) -> None: ...

    def save_event(self, event: TrendlineEvent) -> None: ...

    def get_family(self, family_id: str) -> TrendlineFamily | None: ...

    def get_state_at(self, *, asset: str, timeframe: str, as_of: datetime) -> TrendlineContext: ...


# Existing tracker and consumers retain this protocol name.
TrendlineFamilyRepository = TrendlineRepository


__all__ = [
    "SnapshotVersionError",
    "TrendlineFamilyRepository",
    "TrendlineRepository",
    "deserialize_snapshot",
    "serialize_snapshot",
]
