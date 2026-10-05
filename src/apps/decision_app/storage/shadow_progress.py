"""Latest durable effect progress for one exact Decision lane identity.

The physical table retains its historical ``shadow_progress`` name.  The
semantic contract is authority-neutral so authoritative SIGNAL/NO_SIGNAL
effects and non-authoritative shadow observations use the same monotonic
durability boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from apps.decision_app.domain.state import LaneExecutionIdentity
from apps.decision_app.runtime.deadlines import (
    CleanupBudget,
    Deadline,
    acquire_db_connection,
    native_timeout_kwargs,
)
from apps.decision_app.storage.bounded_asyncpg import BoundedAsyncpgRepository
from libs.contracts.decision import require_utc

LANE_EFFECT_PROGRESS_SCHEMA_VERSION = 1
LaneEffectDisposition = Literal["shadow", "published", "no_signal"]


class LaneEffectProgressCorruptionError(ValueError):
    """Raised when durable lane-effect evidence is not trustworthy."""


class LaneEffectProgressSaveResult(str, Enum):
    INSERTED = "INSERTED"
    UPDATED = "UPDATED"
    IDENTICAL = "IDENTICAL"
    CONFLICT = "CONFLICT"
    REJECTED_OLDER = "REJECTED_OLDER"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class LaneEffectProgress:
    """One latest-only effect-progress record for an exact lane identity."""

    identity: LaneExecutionIdentity
    market_as_of: datetime
    last_disposition: LaneEffectDisposition | None = None
    progress_schema_version: int = LANE_EFFECT_PROGRESS_SCHEMA_VERSION
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, LaneExecutionIdentity):
            raise TypeError("identity must be LaneExecutionIdentity")
        require_utc(self.market_as_of, field_name="market_as_of")
        if self.progress_schema_version != LANE_EFFECT_PROGRESS_SCHEMA_VERSION:
            raise ValueError("unsupported lane effect progress schema version")
        if self.last_disposition not in {None, "shadow", "published", "no_signal"}:
            raise ValueError(
                "last_disposition must be None, shadow, published, or no_signal"
            )
        for field_name in ("created_at", "updated_at"):
            value = getattr(self, field_name)
            if value is not None:
                require_utc(value, field_name=field_name)

    @classmethod
    def create(
        cls,
        *,
        identity: LaneExecutionIdentity,
        market_as_of: datetime,
        last_disposition: LaneEffectDisposition | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> LaneEffectProgress:
        return cls(
            identity=identity,
            market_as_of=market_as_of,
            last_disposition=last_disposition,
            created_at=created_at,
            updated_at=updated_at,
        )


def _validate_progress(progress: LaneEffectProgress) -> None:
    if not isinstance(progress, LaneEffectProgress):
        raise TypeError("progress must be LaneEffectProgress")
    # Reconstruct the value so a tampered or non-UTC row cannot cross the seam.
    LaneEffectProgress(
        identity=progress.identity,
        market_as_of=progress.market_as_of,
        last_disposition=progress.last_disposition,
        progress_schema_version=progress.progress_schema_version,
        created_at=progress.created_at,
        updated_at=progress.updated_at,
    )


class InMemoryLaneEffectProgressRepository:
    """Deterministic test/runtime seam with monotonic latest-only semantics."""

    def __init__(self) -> None:
        self._items: dict[LaneExecutionIdentity, LaneEffectProgress] = {}

    async def load(self, identity: LaneExecutionIdentity) -> LaneEffectProgress | None:
        if not isinstance(identity, LaneExecutionIdentity):
            raise TypeError("identity must be LaneExecutionIdentity")
        progress = self._items.get(identity)
        if progress is not None:
            _validate_progress(progress)
        return progress

    async def save(self, progress: LaneEffectProgress) -> LaneEffectProgressSaveResult:
        _validate_progress(progress)
        current = self._items.get(progress.identity)
        if current is None:
            self._items[progress.identity] = progress
            return LaneEffectProgressSaveResult.INSERTED
        if progress.market_as_of < current.market_as_of:
            return LaneEffectProgressSaveResult.REJECTED_OLDER
        if progress.market_as_of == current.market_as_of:
            if progress.last_disposition == current.last_disposition:
                return LaneEffectProgressSaveResult.IDENTICAL
            return LaneEffectProgressSaveResult.CONFLICT
        self._items[progress.identity] = progress
        return LaneEffectProgressSaveResult.UPDATED


class LaneEffectProgressRepository(BoundedAsyncpgRepository):
    """Small asyncpg repository for the historical progress table."""

    _POISONED_MESSAGE = "lane-effect repository is poisoned after lease cleanup failure"

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

    async def load(self, identity: LaneExecutionIdentity) -> LaneEffectProgress | None:
        if not isinstance(identity, LaneExecutionIdentity):
            raise TypeError("identity must be LaneExecutionIdentity")
        deadline = self._begin()
        async with acquire_db_connection(
            self._pool,
            deadline=deadline,
            io_timeout_seconds=self._io_timeout_seconds,
            cleanup_timeout_seconds=self._cleanup_timeout_seconds or 5.0,
            retained_tasks=self._retained_cleanup_tasks,
            poison=self._poison,
            operation="lane-effect load",
        ) as connection:
            row = await self._phase(
                connection.fetchrow(
                    """
                SELECT progress_schema_version, lane_id,
                       effective_lane_revision, feature_plan_fingerprint,
                       data_plan_fingerprint, market_as_of, last_disposition,
                       created_at, updated_at
                  FROM decision.shadow_progress
                 WHERE lane_id = $1
                   AND effective_lane_revision = $2
                   AND feature_plan_fingerprint = $3
                   AND data_plan_fingerprint = 'none'
                """,
                    identity.lane_id,
                    identity.effective_lane_revision,
                    identity.feature_plan_fingerprint,
                    **native_timeout_kwargs(
                        deadline,
                        operation="lane-effect load query",
                    ),
                ),
                deadline,
                "lane-effect load query",
            )
        self._finish(deadline, "lane-effect load")
        if row is None:
            return None
        return _progress_from_row(row, identity)

    async def save(self, progress: LaneEffectProgress) -> LaneEffectProgressSaveResult:
        _validate_progress(progress)
        deadline = self._begin()
        cleanup_budget = CleanupBudget(self._cleanup_timeout_seconds or 5.0)
        now = datetime.now(UTC)
        async with acquire_db_connection(
            self._pool,
            deadline=deadline,
            io_timeout_seconds=self._io_timeout_seconds,
            cleanup_timeout_seconds=self._cleanup_timeout_seconds or 5.0,
            retained_tasks=self._retained_cleanup_tasks,
            cleanup_budget=cleanup_budget,
            poison=self._poison,
            operation="lane-effect save",
        ) as connection:
            result = await self._run_in_transaction(
                connection,
                deadline=deadline,
                cleanup_budget=cleanup_budget,
                label="lane-effect",
                locked=lambda locked_deadline: self._save_locked(
                    connection, progress, now, deadline=locked_deadline
                ),
            )
        self._finish(deadline, "lane-effect save")
        return result

    async def _save_locked(
        self,
        connection: Any,
        progress: LaneEffectProgress,
        now: datetime,
        *,
        deadline: Deadline | None = None,
    ) -> LaneEffectProgressSaveResult:
        identity = progress.identity
        row = await self._phase(
            connection.fetchrow(
                """
            SELECT progress_schema_version, lane_id,
                   effective_lane_revision, feature_plan_fingerprint,
                   data_plan_fingerprint, market_as_of, last_disposition,
                   created_at, updated_at
              FROM decision.shadow_progress
             WHERE lane_id = $1
               AND effective_lane_revision = $2
               AND feature_plan_fingerprint = $3
               AND data_plan_fingerprint = 'none'
             FOR UPDATE
            """,
                identity.lane_id,
                identity.effective_lane_revision,
                identity.feature_plan_fingerprint,
                **native_timeout_kwargs(
                    deadline,
                    operation="lane-effect save query",
                ),
            ),
            deadline,
            "lane-effect save query",
        )
        if row is not None:
            current = _progress_from_row(row, identity)
            if progress.market_as_of < current.market_as_of:
                return LaneEffectProgressSaveResult.REJECTED_OLDER
            if progress.market_as_of == current.market_as_of:
                if progress.last_disposition == current.last_disposition:
                    return LaneEffectProgressSaveResult.IDENTICAL
                return LaneEffectProgressSaveResult.CONFLICT
            await self._phase(
                connection.execute(
                    """
                UPDATE decision.shadow_progress
                   SET market_as_of = $4, last_disposition = $5,
                       updated_at = $6
                 WHERE lane_id = $1 AND effective_lane_revision = $2
                   AND feature_plan_fingerprint = $3
                   AND data_plan_fingerprint = 'none'
                """,
                    identity.lane_id,
                    identity.effective_lane_revision,
                    identity.feature_plan_fingerprint,
                    progress.market_as_of,
                    progress.last_disposition,
                    now,
                    **native_timeout_kwargs(
                        deadline,
                        operation="lane-effect update",
                    ),
                ),
                deadline,
                "lane-effect update",
            )
            return LaneEffectProgressSaveResult.UPDATED
        await self._phase(
            connection.execute(
                """
            INSERT INTO decision.shadow_progress (
                progress_schema_version, lane_id, effective_lane_revision,
                feature_plan_fingerprint, data_plan_fingerprint, market_as_of,
                last_disposition, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,'none',$5,$6,$7,$7)
            """,
                progress.progress_schema_version,
                identity.lane_id,
                identity.effective_lane_revision,
                identity.feature_plan_fingerprint,
                progress.market_as_of,
                progress.last_disposition,
                now,
                **native_timeout_kwargs(
                    deadline,
                    operation="lane-effect insert",
                ),
            ),
            deadline,
            "lane-effect insert",
        )
        return LaneEffectProgressSaveResult.INSERTED


def _row_value(row: Any, name: str) -> Any:
    try:
        return row[name]
    except (KeyError, TypeError, IndexError) as exc:
        raise LaneEffectProgressCorruptionError(
            f"lane effect progress row missing {name}"
        ) from exc


def _progress_from_row(
    row: Any,
    identity: LaneExecutionIdentity,
) -> LaneEffectProgress:
    if _row_value(row, "data_plan_fingerprint") != "none":
        raise LaneEffectProgressCorruptionError(
            "lane effect data_plan_fingerprint must use the neutral value"
        )
    row_identity = LaneExecutionIdentity(
        lane_id=_row_value(row, "lane_id"),
        effective_lane_revision=_row_value(row, "effective_lane_revision"),
        feature_plan_fingerprint=_row_value(row, "feature_plan_fingerprint"),
    )
    if row_identity != identity:
        raise LaneEffectProgressCorruptionError(
            "lane effect progress identity does not match query"
        )
    try:
        progress = LaneEffectProgress(
            identity=row_identity,
            market_as_of=_row_value(row, "market_as_of"),
            last_disposition=_row_value(row, "last_disposition"),
            progress_schema_version=_row_value(row, "progress_schema_version"),
            created_at=_row_value(row, "created_at"),
            updated_at=_row_value(row, "updated_at"),
        )
    except (TypeError, ValueError) as exc:
        raise LaneEffectProgressCorruptionError(
            "lane effect progress row contains invalid evidence"
        ) from exc
    _validate_progress(progress)
    return progress


__all__ = [
    "LANE_EFFECT_PROGRESS_SCHEMA_VERSION",
    "InMemoryLaneEffectProgressRepository",
    "LaneEffectProgress",
    "LaneEffectProgressCorruptionError",
    "LaneEffectProgressRepository",
    "LaneEffectProgressSaveResult",
]
