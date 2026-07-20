"""Storage-neutral trendline repository contract and snapshot serialization."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Protocol

from ..contracts import ContractValidationError, TrendlineFamilySnapshot, canonical_json
from ..domain import TrendlineContext, TrendlineEvent, TrendlineFamily, TrendlineSnapshot


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


def serialize_snapshot(snapshot: TrendlineFamilySnapshot) -> str:
    return canonical_json(snapshot.to_dict())


def deserialize_snapshot(payload: str) -> TrendlineFamilySnapshot:
    if not isinstance(payload, str):
        raise ContractValidationError("snapshot payload must be a JSON string")
    try:
        value = json.loads(payload)
        return TrendlineFamilySnapshot.from_dict(value)
    except ContractValidationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ContractValidationError("snapshot payload is not valid JSON") from exc


__all__ = [
    "SnapshotVersionError",
    "TrendlineFamilyRepository",
    "TrendlineRepository",
    "deserialize_snapshot",
    "serialize_snapshot",
]
