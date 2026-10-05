"""Durable compact evidence for cutoffs advanced without publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from apps.decision_app.domain.state import LaneExecutionIdentity
from apps.decision_app.runtime.deadlines import (
    acquire_db_connection,
    native_timeout_kwargs,
    require_remaining,
)
from apps.decision_app.storage.bounded_asyncpg import BoundedAsyncpgRepository
from libs.contracts.decision import require_utc

LaneEffectSkipReason = Literal[
    "restart",
    "restart_rewarm",
    "stale",
    "foreign_entry",
]


class LaneEffectSkipConflictError(ValueError):
    """Raised when one skip identity is assigned incompatible evidence."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LaneEffectSkip:
    identity: LaneExecutionIdentity
    skipped_from: datetime
    skipped_through: datetime
    cutoff_count: int
    reason: LaneEffectSkipReason
    recorded_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, LaneExecutionIdentity):
            raise TypeError("identity must be LaneExecutionIdentity")
        require_utc(self.skipped_from, field_name="skipped_from")
        require_utc(self.skipped_through, field_name="skipped_through")
        if self.skipped_through < self.skipped_from:
            raise ValueError("skipped_through must not precede skipped_from")
        if isinstance(self.cutoff_count, bool) or not isinstance(
            self.cutoff_count, int
        ):
            raise TypeError("cutoff_count must be an integer")
        if self.cutoff_count <= 0:
            raise ValueError("cutoff_count must be positive")
        if self.reason not in {
            "restart",
            "restart_rewarm",
            "stale",
            "foreign_entry",
        }:
            raise ValueError("unsupported lane effect skip reason")
        if self.recorded_at is not None:
            require_utc(self.recorded_at, field_name="recorded_at")


def _validate_skip(skip: LaneEffectSkip) -> None:
    if not isinstance(skip, LaneEffectSkip):
        raise TypeError("skip must be LaneEffectSkip")
    LaneEffectSkip(
        identity=skip.identity,
        skipped_from=skip.skipped_from,
        skipped_through=skip.skipped_through,
        cutoff_count=skip.cutoff_count,
        reason=skip.reason,
        recorded_at=skip.recorded_at,
    )


class InMemoryLaneEffectSkipsRepository:
    """Idempotent test/runtime twin of the durable skip-row upsert."""

    def __init__(self) -> None:
        self._items: dict[tuple[LaneExecutionIdentity, datetime], LaneEffectSkip] = {}

    async def upsert(self, skip: LaneEffectSkip) -> LaneEffectSkip:
        _validate_skip(skip)
        key = (skip.identity, skip.skipped_from)
        current = self._items.get(key)
        if current is None:
            self._items[key] = skip
            return skip
        if current.reason != skip.reason:
            raise LaneEffectSkipConflictError(
                "lane effect skip start already has a different reason"
            )
        if current.skipped_through == skip.skipped_through:
            # Same range: keep the stored row, as the durable upsert does.
            return current
        if skip.skipped_through > current.skipped_through:
            merged = skip
        else:
            merged = current
        self._items[key] = merged
        return merged

    @property
    def records(self) -> tuple[LaneEffectSkip, ...]:
        return tuple(
            self._items[key]
            for key in sorted(
                self._items,
                key=lambda item: (item[0].lane_id, item[1]),
            )
        )


class LaneEffectSkipsRepository(BoundedAsyncpgRepository):
    """Small asyncpg upsert for immutable lane identity and skipped ranges."""

    _POISONED_MESSAGE = "lane effect skips repository is poisoned"

    def __init__(
        self,
        pool: Any,
        *,
        io_timeout_seconds: float | None = None,
        operation_timeout_seconds: float | None = None,
        cleanup_timeout_seconds: float | None = None,
    ) -> None:
        super().__init__(
            pool,
            io_timeout_seconds=io_timeout_seconds,
            operation_timeout_seconds=operation_timeout_seconds,
            cleanup_timeout_seconds=cleanup_timeout_seconds,
        )

    async def upsert(self, skip: LaneEffectSkip) -> LaneEffectSkip:
        _validate_skip(skip)
        deadline = self._begin()
        identity = skip.identity
        async with acquire_db_connection(
            self._pool,
            deadline=deadline,
            io_timeout_seconds=self._io_timeout_seconds,
            cleanup_timeout_seconds=self._cleanup_timeout_seconds or 5.0,
            retained_tasks=self._retained_cleanup_tasks,
            poison=self._poison,
            operation="lane effect skip upsert",
        ) as connection:
            row = await self._phase(
                connection.fetchrow(
                    """
                INSERT INTO decision.lane_effect_skips (
                    lane_id, effective_lane_revision, feature_plan_fingerprint,
                    skipped_from, skipped_through, cutoff_count, reason
                ) VALUES ($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT (
                    lane_id, effective_lane_revision,
                    feature_plan_fingerprint, skipped_from
                ) DO UPDATE SET
                    skipped_through = GREATEST(
                        decision.lane_effect_skips.skipped_through,
                        EXCLUDED.skipped_through
                    ),
                    cutoff_count = CASE
                        WHEN EXCLUDED.skipped_through >
                             decision.lane_effect_skips.skipped_through
                        THEN EXCLUDED.cutoff_count
                        ELSE decision.lane_effect_skips.cutoff_count
                    END
                WHERE decision.lane_effect_skips.reason = EXCLUDED.reason
                RETURNING skipped_from, skipped_through, cutoff_count, reason,
                          recorded_at
                """,
                    identity.lane_id,
                    identity.effective_lane_revision,
                    identity.feature_plan_fingerprint,
                    skip.skipped_from,
                    skip.skipped_through,
                    skip.cutoff_count,
                    skip.reason,
                    **native_timeout_kwargs(
                        deadline,
                        operation="lane effect skip upsert query",
                    ),
                ),
                deadline,
                "lane effect skip upsert query",
            )
        if row is None:
            raise LaneEffectSkipConflictError(
                "lane effect skip start already has a different reason"
            )
        if deadline is not None:
            require_remaining(deadline, operation="lane effect skip upsert")
        return LaneEffectSkip(
            identity=identity,
            skipped_from=row["skipped_from"],
            skipped_through=row["skipped_through"],
            cutoff_count=row["cutoff_count"],
            reason=row["reason"],
            recorded_at=row["recorded_at"],
        )


__all__ = [
    "InMemoryLaneEffectSkipsRepository",
    "LaneEffectSkip",
    "LaneEffectSkipConflictError",
    "LaneEffectSkipReason",
    "LaneEffectSkipsRepository",
]
