"""Ordered, revision-aware in-memory trendline snapshot history."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from libs.models.trendlines.boundary.contracts import BoundaryResult
from libs.models.trendlines.config.history_config import (
    SnapshotHistoryPolicies,
    SnapshotHistoryPolicy,
)
from libs.models.trendlines.contracts.identity import (
    TrendlineSnapshotIdentity,
    TrendlineSnapshotStage,
    canonical_point_text,
)

SnapshotKey = tuple[str, str]


class SnapshotHistoryContractError(ValueError):
    """Raised when a boundary or timestamp violates history contracts."""


class SnapshotIdentityConflictError(SnapshotHistoryContractError):
    """Raised when one logical or revision identity is reused inconsistently."""


class SnapshotRevisionCapacityError(SnapshotHistoryContractError):
    """Raised when a logical snapshot cannot retain another revision."""


class SnapshotRetentionError(SnapshotHistoryContractError):
    """Raised when an event is older than the retained logical history floor."""


def _as_datetime(value: Any, *, name: str, require_aware: bool = False) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif hasattr(value, "to_pydatetime"):
        result = value.to_pydatetime()
    else:
        raise TypeError(f"{name} must be a datetime-like value")
    if result.tzinfo is None or result.utcoffset() is None:
        if require_aware:
            raise SnapshotHistoryContractError(f"{name} must be timezone-aware")
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _event_time(snapshot: "TrendlineSnapshot") -> datetime:
    return _as_datetime(snapshot.timestamp, name="snapshot timestamp")


def _query_time(value: Any, *, name: str) -> datetime:
    return _as_datetime(value, name=name, require_aware=False)


@dataclass(frozen=True)
class TrendlineSnapshot:
    """One boundary revision with market event and knowledge timestamps."""

    asset: str
    timeframe: str
    timestamp: datetime
    boundary: BoundaryResult
    metadata: dict[str, Any] = field(default_factory=dict)
    snapshot_identity: TrendlineSnapshotIdentity | None = None
    known_at: datetime | None = None

    def __post_init__(self) -> None:
        event_time = _event_time(self)
        known_at = (
            event_time
            if self.known_at is None
            else _as_datetime(self.known_at, name="known_at", require_aware=True)
        )
        if known_at < event_time:
            raise SnapshotHistoryContractError("known_at must be >= snapshot as_of")
        object.__setattr__(self, "known_at", known_at)

    @classmethod
    def from_boundary(
        cls,
        boundary: BoundaryResult,
        *,
        metadata: dict[str, Any] | None = None,
        known_at: datetime | None = None,
    ) -> "TrendlineSnapshot":
        return cls(
            asset=boundary.asset.upper(),
            timeframe=boundary.timeframe,
            timestamp=boundary.timestamp,
            boundary=boundary,
            metadata=dict(metadata or {}),
            snapshot_identity=boundary.snapshot_identity,
            known_at=known_at,
        )

    @property
    def key(self) -> SnapshotKey:
        return self.asset.upper(), self.timeframe

    @property
    def as_of(self) -> datetime:
        return _event_time(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "timestamp": str(self.timestamp),
            "known_at": self.known_at.isoformat(),
            "boundary": self.boundary.to_dict(),
            "metadata": dict(self.metadata),
            "snapshot_identity": (
                self.snapshot_identity.to_dict() if self.snapshot_identity else None
            ),
        }


@dataclass
class _LogicalSnapshot:
    snapshot_id: str
    as_of: datetime
    revisions: list[TrendlineSnapshot] = field(default_factory=list)
    known_ats: list[datetime] = field(default_factory=list)
    by_revision: dict[str, TrendlineSnapshot] = field(default_factory=dict)


@dataclass
class _SnapshotBucket:
    logical: list[_LogicalSnapshot] = field(default_factory=list)
    as_ofs: list[datetime] = field(default_factory=list)
    by_snapshot_id: dict[str, _LogicalSnapshot] = field(default_factory=dict)


class TrendlineSnapshotHistory:
    """Causally queryable, bounded history keyed by asset and timeframe."""

    def __init__(self, policies: SnapshotHistoryPolicies) -> None:
        if not isinstance(policies, SnapshotHistoryPolicies):
            raise TypeError("policies must be a SnapshotHistoryPolicies")
        self.policies = policies
        self._buckets: dict[SnapshotKey, _SnapshotBucket] = {}
        self._snapshot_locations: dict[str, SnapshotKey] = {}

    @classmethod
    def from_config(cls, config: Any) -> "TrendlineSnapshotHistory":
        return cls(SnapshotHistoryPolicies.from_config(config))

    def policy(self, asset: str, timeframe: str) -> SnapshotHistoryPolicy:
        return self.policies.resolve(asset, timeframe)

    def context_limit(self, asset: str, timeframe: str) -> int:
        return self.policy(asset, timeframe).context_limit

    def add(
        self,
        boundary: BoundaryResult,
        *,
        metadata: dict[str, Any] | None = None,
        known_at: datetime | None = None,
    ) -> TrendlineSnapshot:
        identity = self._validate_boundary(boundary)
        key = self._key(boundary.asset, boundary.timeframe)
        bucket = self._buckets.setdefault(key, _SnapshotBucket())
        event_time = _as_datetime(boundary.timestamp, name="boundary timestamp")
        existing_location = self._snapshot_locations.get(identity.snapshot_id)
        if existing_location is not None and existing_location != key:
            raise SnapshotIdentityConflictError(
                f"snapshot_id {identity.snapshot_id} belongs to {existing_location}, not {key}"
            )

        logical = bucket.by_snapshot_id.get(identity.snapshot_id)
        if logical is not None and logical.as_of != event_time:
            raise SnapshotIdentityConflictError(
                f"snapshot_id {identity.snapshot_id} has conflicting as_of"
            )

        resolved_known_at = (
            _as_datetime(known_at, name="known_at", require_aware=True)
            if known_at is not None
            else event_time
        )
        if resolved_known_at < event_time:
            raise SnapshotHistoryContractError("known_at must be >= snapshot as_of")

        if logical is not None:
            existing = logical.by_revision.get(identity.revision_id)
            if existing is not None:
                if existing.snapshot_identity != identity:
                    raise SnapshotIdentityConflictError(
                        f"revision_id {identity.revision_id} has conflicting identity"
                    )
                if existing.known_at != resolved_known_at:
                    raise SnapshotIdentityConflictError(
                        f"revision_id {identity.revision_id} has conflicting known_at"
                    )
                return existing
            if known_at is None:
                raise SnapshotHistoryContractError(
                    "known_at is required for a new revision of an existing snapshot"
                )
            if resolved_known_at in logical.known_ats:
                raise SnapshotIdentityConflictError(
                    f"multiple revisions cannot share known_at {resolved_known_at.isoformat()}"
                )
            policy = self.policy(*key)
            if len(logical.revisions) >= policy.max_revisions_per_snapshot:
                raise SnapshotRevisionCapacityError(
                    f"snapshot {identity.snapshot_id} reached revision capacity "
                    f"{policy.max_revisions_per_snapshot}"
                )
            snapshot = TrendlineSnapshot.from_boundary(
                boundary, metadata=metadata, known_at=resolved_known_at
            )
            self._insert_revision(logical, snapshot)
            return snapshot

        policy = self.policy(*key)
        if len(bucket.logical) >= policy.max_logical_snapshots_per_key:
            if event_time < bucket.as_ofs[0]:
                raise SnapshotRetentionError(
                    f"snapshot as_of {event_time.isoformat()} is older than retained history floor "
                    f"{bucket.as_ofs[0].isoformat()}"
                )
            oldest = bucket.logical.pop(0)
            bucket.as_ofs.pop(0)
            bucket.by_snapshot_id.pop(oldest.snapshot_id, None)
            self._snapshot_locations.pop(oldest.snapshot_id, None)

        snapshot = TrendlineSnapshot.from_boundary(
            boundary, metadata=metadata, known_at=resolved_known_at
        )
        logical = _LogicalSnapshot(
            snapshot_id=identity.snapshot_id,
            as_of=event_time,
        )
        self._insert_revision(logical, snapshot)
        index = len(bucket.logical)
        if not bucket.logical or event_time >= bucket.as_ofs[-1]:
            bucket.logical.append(logical)
            bucket.as_ofs.append(event_time)
        else:
            index = bisect_left(bucket.as_ofs, event_time)
            bucket.logical.insert(index, logical)
            bucket.as_ofs.insert(index, event_time)
        bucket.by_snapshot_id[identity.snapshot_id] = logical
        self._snapshot_locations[identity.snapshot_id] = key
        return snapshot

    def extend(
        self,
        boundaries: Iterable[BoundaryResult],
        *,
        metadata: dict[str, Any] | None = None,
        known_at: datetime | None = None,
    ) -> list[TrendlineSnapshot]:
        return [
            self.add(boundary, metadata=metadata, known_at=known_at)
            for boundary in boundaries
        ]

    def latest(
        self,
        asset: str,
        timeframe: str,
        *,
        known_at: datetime | None = None,
    ) -> BoundaryResult | None:
        bucket = self._buckets.get(self._key(asset, timeframe))
        if not bucket:
            return None
        query_known_at = None if known_at is None else _as_datetime(
            known_at, name="known_at", require_aware=True
        )
        for logical in reversed(bucket.logical):
            snapshot = self._select_revision(logical, query_known_at)
            if snapshot is not None:
                return snapshot.boundary
        return None

    def history(
        self,
        asset: str,
        timeframe: str,
        *,
        limit: int | None = None,
        exclude_latest: bool = False,
        known_at: datetime | None = None,
    ) -> list[BoundaryResult]:
        selected = self._selected_history(asset, timeframe, known_at=known_at)
        if exclude_latest and selected:
            selected = selected[:-1]
        selected = self._apply_limit(selected, limit)
        return [snapshot.boundary for snapshot in selected]

    def snapshots(
        self,
        asset: str,
        timeframe: str,
        *,
        limit: int | None = None,
        known_at: datetime | None = None,
    ) -> list[TrendlineSnapshot]:
        selected = self._selected_history(asset, timeframe, known_at=known_at)
        return self._apply_limit(selected, limit)

    def get_exact_at(
        self,
        asset: str,
        timeframe: str,
        as_of: datetime,
        *,
        known_at: datetime | None = None,
    ) -> BoundaryResult | None:
        bucket = self._buckets.get(self._key(asset, timeframe))
        if not bucket:
            return None
        event_time = _query_time(as_of, name="as_of")
        query_known_at = self._resolve_query_known_at(event_time, known_at)
        index = bisect_left(bucket.as_ofs, event_time)
        if index >= len(bucket.as_ofs) or bucket.as_ofs[index] != event_time:
            return None
        snapshot = self._select_revision(bucket.logical[index], query_known_at)
        return snapshot.boundary if snapshot is not None else None

    def get_state_at(
        self,
        asset: str,
        timeframe: str,
        as_of: datetime,
        *,
        known_at: datetime | None = None,
    ) -> BoundaryResult | None:
        bucket = self._buckets.get(self._key(asset, timeframe))
        if not bucket:
            return None
        event_time = _query_time(as_of, name="as_of")
        query_known_at = self._resolve_query_known_at(event_time, known_at)
        index = bisect_right(bucket.as_ofs, event_time) - 1
        while index >= 0:
            snapshot = self._select_revision(bucket.logical[index], query_known_at)
            if snapshot is not None:
                return snapshot.boundary
            index -= 1
        return None

    def history_before(
        self,
        asset: str,
        timeframe: str,
        timestamp: datetime,
        *,
        limit: int | None = None,
        known_at: datetime | None = None,
    ) -> list[BoundaryResult]:
        bucket = self._buckets.get(self._key(asset, timeframe))
        if not bucket:
            return []
        event_time = _query_time(timestamp, name="timestamp")
        query_known_at = self._resolve_query_known_at(event_time, known_at)
        cutoff = bisect_left(bucket.as_ofs, event_time)
        selected: list[TrendlineSnapshot] = []
        for logical in bucket.logical[:cutoff]:
            snapshot = self._select_revision(logical, query_known_at)
            if snapshot is not None:
                selected.append(snapshot)
        selected = self._apply_limit(selected, limit)
        return [snapshot.boundary for snapshot in selected]

    def temporal_history(
        self,
        current: BoundaryResult,
        *,
        min_history: int | None = None,
        limit: int | None = None,
        known_at: datetime | None = None,
    ) -> list[BoundaryResult]:
        resolved_limit = (
            limit
            if limit is not None
            else min_history
            if min_history is not None
            else self.context_limit(current.asset, current.timeframe)
        )
        return self.history_before(
            current.asset,
            current.timeframe,
            current.timestamp,
            limit=resolved_limit,
            known_at=known_at,
        )

    def revision_history(
        self,
        asset: str,
        timeframe: str,
        snapshot_id: str,
    ) -> list[TrendlineSnapshot]:
        bucket = self._buckets.get(self._key(asset, timeframe))
        if not bucket:
            return []
        logical = bucket.by_snapshot_id.get(snapshot_id)
        return list(logical.revisions) if logical is not None else []

    def clear(self, asset: str | None = None, timeframe: str | None = None) -> None:
        if asset is None and timeframe is None:
            self._buckets.clear()
            self._snapshot_locations.clear()
            return
        if asset is None or timeframe is None:
            raise ValueError("asset and timeframe must be provided together")
        key = self._key(asset, timeframe)
        bucket = self._buckets.pop(key, None)
        if bucket is not None:
            for logical in bucket.logical:
                self._snapshot_locations.pop(logical.snapshot_id, None)

    def count(self, asset: str | None = None, timeframe: str | None = None) -> int:
        return self.logical_count(asset, timeframe)

    def logical_count(self, asset: str | None = None, timeframe: str | None = None) -> int:
        if asset is None and timeframe is None:
            return sum(len(bucket.logical) for bucket in self._buckets.values())
        if asset is None or timeframe is None:
            raise ValueError("asset and timeframe must be provided together")
        bucket = self._buckets.get(self._key(asset, timeframe))
        return len(bucket.logical) if bucket else 0

    def revision_count(self, asset: str | None = None, timeframe: str | None = None) -> int:
        if asset is None and timeframe is None:
            return sum(
                len(logical.revisions)
                for bucket in self._buckets.values()
                for logical in bucket.logical
            )
        if asset is None or timeframe is None:
            raise ValueError("asset and timeframe must be provided together")
        bucket = self._buckets.get(self._key(asset, timeframe))
        return (
            sum(len(logical.revisions) for logical in bucket.logical)
            if bucket
            else 0
        )

    def keys(self) -> list[SnapshotKey]:
        return sorted(self._buckets)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policies": self.policies.to_dict(),
            "keys": [list(key) for key in self.keys()],
            "logical_count": self.logical_count(),
            "revision_count": self.revision_count(),
        }

    @staticmethod
    def _key(asset: str, timeframe: str) -> SnapshotKey:
        return str(asset).upper(), str(timeframe)

    @staticmethod
    def _validate_boundary(boundary: BoundaryResult) -> TrendlineSnapshotIdentity:
        identity = boundary.snapshot_identity
        if identity is None:
            raise SnapshotHistoryContractError(
                "strict snapshot history requires BoundaryResult.snapshot_identity"
            )
        if identity.stage is not TrendlineSnapshotStage.BOUNDARY:
            raise SnapshotHistoryContractError(
                "snapshot history requires a boundary-stage snapshot identity"
            )
        if identity.asset != boundary.asset or identity.timeframe != boundary.timeframe:
            raise SnapshotIdentityConflictError(
                "boundary asset/timeframe does not match snapshot identity"
            )
        if identity.checkpoint.source.as_of != canonical_point_text(boundary.timestamp):
            raise SnapshotIdentityConflictError(
                "boundary timestamp does not match snapshot identity as_of"
            )
        return identity

    @staticmethod
    def _insert_revision(logical: _LogicalSnapshot, snapshot: TrendlineSnapshot) -> None:
        known_at = snapshot.known_at
        assert known_at is not None
        index = bisect_left(logical.known_ats, known_at)
        logical.known_ats.insert(index, known_at)
        logical.revisions.insert(index, snapshot)
        logical.by_revision[snapshot.snapshot_identity.revision_id] = snapshot  # type: ignore[union-attr]

    @staticmethod
    def _select_revision(
        logical: _LogicalSnapshot,
        known_at: datetime | None,
    ) -> TrendlineSnapshot | None:
        if not logical.revisions:
            return None
        if known_at is None:
            return logical.revisions[-1]
        index = bisect_right(logical.known_ats, known_at) - 1
        return logical.revisions[index] if index >= 0 else None

    def _selected_history(
        self,
        asset: str,
        timeframe: str,
        *,
        known_at: datetime | None,
    ) -> list[TrendlineSnapshot]:
        bucket = self._buckets.get(self._key(asset, timeframe))
        if not bucket:
            return []
        query_known_at = (
            None
            if known_at is None
            else _as_datetime(known_at, name="known_at", require_aware=True)
        )
        return [
            selected
            for logical in bucket.logical
            if (selected := self._select_revision(logical, query_known_at)) is not None
        ]

    @staticmethod
    def _apply_limit(
        values: list[TrendlineSnapshot],
        limit: int | None,
    ) -> list[TrendlineSnapshot]:
        if limit is None:
            return values
        if limit < 1:
            return []
        return values[-limit:]

    @staticmethod
    def _resolve_query_known_at(event_time: datetime, known_at: datetime | None) -> datetime:
        if known_at is None:
            return event_time
        return _as_datetime(known_at, name="known_at", require_aware=True)


__all__ = [
    "SnapshotHistoryContractError",
    "SnapshotIdentityConflictError",
    "SnapshotKey",
    "SnapshotRevisionCapacityError",
    "SnapshotRetentionError",
    "TrendlineSnapshot",
    "TrendlineSnapshotHistory",
]
