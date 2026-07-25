"""Rolling boundary snapshot history for trendline temporal context.

This module intentionally stays storage-agnostic.  It provides an in-memory
container that live adapters, shadow collectors, or tests can use before a
persistent snapshot store exists.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, Iterable, List, Tuple

from app.trendlines.boundary.contracts import BoundaryResult

SnapshotKey = Tuple[str, str]


@dataclass(frozen=True)
class TrendlineSnapshot:
    """One timestamped boundary snapshot for an asset/timeframe pair."""

    asset: str
    timeframe: str
    timestamp: datetime
    boundary: BoundaryResult
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_boundary(
        cls,
        boundary: BoundaryResult,
        *,
        metadata: Dict[str, Any] | None = None,
    ) -> "TrendlineSnapshot":
        return cls(
            asset=boundary.asset.upper(),
            timeframe=boundary.timeframe,
            timestamp=boundary.timestamp,
            boundary=boundary,
            metadata=dict(metadata or {}),
        )

    @property
    def key(self) -> SnapshotKey:
        return self.asset.upper(), self.timeframe

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "timestamp": str(self.timestamp),
            "boundary": self.boundary.to_dict(),
            "metadata": dict(self.metadata),
        }


@dataclass
class TrendlineSnapshotHistory:
    """Bounded rolling history of ``BoundaryResult`` snapshots."""

    maxlen: int = 256
    _snapshots: Dict[SnapshotKey, Deque[TrendlineSnapshot]] = field(
        default_factory=lambda: defaultdict(deque),
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.maxlen < 1:
            raise ValueError("maxlen must be >= 1")

    def add(
        self,
        boundary: BoundaryResult,
        *,
        metadata: Dict[str, Any] | None = None,
    ) -> TrendlineSnapshot:
        snapshot = TrendlineSnapshot.from_boundary(boundary, metadata=metadata)
        bucket = self._bucket(snapshot.key)
        bucket.append(snapshot)
        return snapshot

    def extend(
        self,
        boundaries: Iterable[BoundaryResult],
        *,
        metadata: Dict[str, Any] | None = None,
    ) -> List[TrendlineSnapshot]:
        return [self.add(boundary, metadata=metadata) for boundary in boundaries]

    def latest(self, asset: str, timeframe: str) -> BoundaryResult | None:
        bucket = self._snapshots.get(self._key(asset, timeframe))
        if not bucket:
            return None
        return bucket[-1].boundary

    def history(
        self,
        asset: str,
        timeframe: str,
        *,
        limit: int | None = None,
        exclude_latest: bool = False,
    ) -> List[BoundaryResult]:
        bucket = list(self._snapshots.get(self._key(asset, timeframe), ()))
        if exclude_latest and bucket:
            bucket = bucket[:-1]
        if limit is not None:
            if limit < 1:
                return []
            bucket = bucket[-limit:]
        return [snapshot.boundary for snapshot in bucket]

    def snapshots(
        self,
        asset: str,
        timeframe: str,
        *,
        limit: int | None = None,
    ) -> List[TrendlineSnapshot]:
        bucket = list(self._snapshots.get(self._key(asset, timeframe), ()))
        if limit is not None:
            if limit < 1:
                return []
            bucket = bucket[-limit:]
        return bucket

    def history_before(
        self,
        asset: str,
        timeframe: str,
        timestamp: datetime,
        *,
        limit: int | None = None,
    ) -> List[BoundaryResult]:
        bucket = [
            snapshot
            for snapshot in self._snapshots.get(self._key(asset, timeframe), ())
            if snapshot.timestamp < timestamp
        ]
        if limit is not None:
            if limit < 1:
                return []
            bucket = bucket[-limit:]
        return [snapshot.boundary for snapshot in bucket]

    def temporal_history(
        self,
        current: BoundaryResult,
        *,
        min_history: int = 3,
        limit: int | None = None,
    ) -> List[BoundaryResult]:
        resolved_limit = limit if limit is not None else max(int(min_history), 1)
        return self.history_before(current.asset, current.timeframe, current.timestamp, limit=resolved_limit)

    def clear(self, asset: str | None = None, timeframe: str | None = None) -> None:
        if asset is None and timeframe is None:
            self._snapshots.clear()
            return
        if asset is None or timeframe is None:
            raise ValueError("asset and timeframe must be provided together")
        self._snapshots.pop(self._key(asset, timeframe), None)

    def count(self, asset: str | None = None, timeframe: str | None = None) -> int:
        if asset is None and timeframe is None:
            return sum(len(bucket) for bucket in self._snapshots.values())
        if asset is None or timeframe is None:
            raise ValueError("asset and timeframe must be provided together")
        return len(self._snapshots.get(self._key(asset, timeframe), ()))

    def keys(self) -> List[SnapshotKey]:
        return sorted(self._snapshots.keys())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "maxlen": self.maxlen,
            "keys": [list(key) for key in self.keys()],
            "count": self.count(),
        }

    def _bucket(self, key: SnapshotKey) -> Deque[TrendlineSnapshot]:
        bucket = self._snapshots[key]
        if bucket.maxlen != self.maxlen:
            self._snapshots[key] = deque(bucket, maxlen=self.maxlen)
            bucket = self._snapshots[key]
        return bucket

    @staticmethod
    def _key(asset: str, timeframe: str) -> SnapshotKey:
        return asset.upper(), timeframe


__all__ = ["SnapshotKey", "TrendlineSnapshot", "TrendlineSnapshotHistory"]
