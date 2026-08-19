"""Latest durable progress for non-authoritative shadow effects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from apps.decision_app.domain.state import LaneExecutionIdentity
from libs.contracts.decision import require_utc

SHADOW_PROGRESS_SCHEMA_VERSION = 1
ShadowDisposition = Literal["shadow"]


class ShadowProgressCorruptionError(ValueError):
    """Raised when durable shadow-progress evidence is not trustworthy."""


class ShadowProgressSaveResult(str, Enum):
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
class ShadowProgress:
    """One latest-only effect-progress record for an exact lane identity."""

    identity: LaneExecutionIdentity
    market_as_of: datetime
    last_disposition: ShadowDisposition | None = None
    progress_schema_version: int = SHADOW_PROGRESS_SCHEMA_VERSION
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, LaneExecutionIdentity):
            raise TypeError("identity must be LaneExecutionIdentity")
        require_utc(self.market_as_of, field_name="market_as_of")
        if self.progress_schema_version != SHADOW_PROGRESS_SCHEMA_VERSION:
            raise ValueError("unsupported shadow progress schema version")
        if self.last_disposition not in {None, "shadow"}:
            raise ValueError("last_disposition must be None or shadow")
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
        last_disposition: ShadowDisposition | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> ShadowProgress:
        return cls(
            identity=identity,
            market_as_of=market_as_of,
            last_disposition=last_disposition,
            created_at=created_at,
            updated_at=updated_at,
        )


def _validate_progress(progress: ShadowProgress) -> None:
    if not isinstance(progress, ShadowProgress):
        raise TypeError("progress must be ShadowProgress")
    # Reconstruct the value so a tampered or non-UTC row cannot cross the seam.
    ShadowProgress(
        identity=progress.identity,
        market_as_of=progress.market_as_of,
        last_disposition=progress.last_disposition,
        progress_schema_version=progress.progress_schema_version,
        created_at=progress.created_at,
        updated_at=progress.updated_at,
    )


class InMemoryShadowProgressRepository:
    """Deterministic test/runtime seam with monotonic latest-only semantics."""

    def __init__(self) -> None:
        self._items: dict[LaneExecutionIdentity, ShadowProgress] = {}

    async def load(self, identity: LaneExecutionIdentity) -> ShadowProgress | None:
        if not isinstance(identity, LaneExecutionIdentity):
            raise TypeError("identity must be LaneExecutionIdentity")
        progress = self._items.get(identity)
        if progress is not None:
            _validate_progress(progress)
        return progress

    async def save(self, progress: ShadowProgress) -> ShadowProgressSaveResult:
        _validate_progress(progress)
        current = self._items.get(progress.identity)
        if current is None:
            self._items[progress.identity] = progress
            return ShadowProgressSaveResult.INSERTED
        if progress.market_as_of < current.market_as_of:
            return ShadowProgressSaveResult.REJECTED_OLDER
        if progress.market_as_of == current.market_as_of:
            if progress.last_disposition == current.last_disposition:
                return ShadowProgressSaveResult.IDENTICAL
            return ShadowProgressSaveResult.CONFLICT
        self._items[progress.identity] = progress
        return ShadowProgressSaveResult.UPDATED


class ShadowProgressRepository:
    """Small asyncpg repository for ``decision.shadow_progress``."""

    def __init__(self, pool: Any) -> None:
        if pool is None or not hasattr(pool, "acquire"):
            raise TypeError("pool must provide asyncpg acquire()")
        self._pool = pool

    async def load(self, identity: LaneExecutionIdentity) -> ShadowProgress | None:
        if not isinstance(identity, LaneExecutionIdentity):
            raise TypeError("identity must be LaneExecutionIdentity")
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT progress_schema_version, lane_id,
                       effective_lane_revision, feature_plan_fingerprint,
                       data_plan_fingerprint, market_as_of, last_disposition,
                       created_at, updated_at
                  FROM decision.shadow_progress
                 WHERE lane_id = $1
                   AND effective_lane_revision = $2
                   AND feature_plan_fingerprint = $3
                   AND data_plan_fingerprint = $4
                """,
                identity.lane_id,
                identity.effective_lane_revision,
                identity.feature_plan_fingerprint,
                identity.data_plan_fingerprint,
            )
        if row is None:
            return None
        return _progress_from_row(row, identity)

    async def save(self, progress: ShadowProgress) -> ShadowProgressSaveResult:
        _validate_progress(progress)
        now = datetime.now(UTC)
        async with self._pool.acquire() as connection:
            transaction = getattr(connection, "transaction", None)
            if callable(transaction):
                async with connection.transaction():
                    return await self._save_locked(connection, progress, now)
            return await self._save_locked(connection, progress, now)

    async def _save_locked(
        self,
        connection: Any,
        progress: ShadowProgress,
        now: datetime,
    ) -> ShadowProgressSaveResult:
        identity = progress.identity
        row = await connection.fetchrow(
            """
            SELECT progress_schema_version, lane_id,
                   effective_lane_revision, feature_plan_fingerprint,
                   data_plan_fingerprint, market_as_of, last_disposition,
                   created_at, updated_at
              FROM decision.shadow_progress
             WHERE lane_id = $1
               AND effective_lane_revision = $2
               AND feature_plan_fingerprint = $3
               AND data_plan_fingerprint = $4
             FOR UPDATE
            """,
            identity.lane_id,
            identity.effective_lane_revision,
            identity.feature_plan_fingerprint,
            identity.data_plan_fingerprint,
        )
        if row is not None:
            current = _progress_from_row(row, identity)
            if progress.market_as_of < current.market_as_of:
                return ShadowProgressSaveResult.REJECTED_OLDER
            if progress.market_as_of == current.market_as_of:
                if progress.last_disposition == current.last_disposition:
                    return ShadowProgressSaveResult.IDENTICAL
                return ShadowProgressSaveResult.CONFLICT
            await connection.execute(
                """
                UPDATE decision.shadow_progress
                   SET market_as_of = $5, last_disposition = $6,
                       updated_at = $7
                 WHERE lane_id = $1 AND effective_lane_revision = $2
                   AND feature_plan_fingerprint = $3
                   AND data_plan_fingerprint = $4
                """,
                identity.lane_id,
                identity.effective_lane_revision,
                identity.feature_plan_fingerprint,
                identity.data_plan_fingerprint,
                progress.market_as_of,
                progress.last_disposition,
                now,
            )
            return ShadowProgressSaveResult.UPDATED
        await connection.execute(
            """
            INSERT INTO decision.shadow_progress (
                progress_schema_version, lane_id, effective_lane_revision,
                feature_plan_fingerprint, data_plan_fingerprint, market_as_of,
                last_disposition, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$8)
            """,
            progress.progress_schema_version,
            identity.lane_id,
            identity.effective_lane_revision,
            identity.feature_plan_fingerprint,
            identity.data_plan_fingerprint,
            progress.market_as_of,
            progress.last_disposition,
            now,
        )
        return ShadowProgressSaveResult.INSERTED


def _row_value(row: Any, name: str) -> Any:
    try:
        return row[name]
    except (KeyError, TypeError, IndexError) as exc:
        raise ShadowProgressCorruptionError(
            f"shadow progress row missing {name}"
        ) from exc


def _progress_from_row(
    row: Any,
    identity: LaneExecutionIdentity,
) -> ShadowProgress:
    row_identity = LaneExecutionIdentity(
        lane_id=_row_value(row, "lane_id"),
        effective_lane_revision=_row_value(row, "effective_lane_revision"),
        feature_plan_fingerprint=_row_value(row, "feature_plan_fingerprint"),
        data_plan_fingerprint=_row_value(row, "data_plan_fingerprint"),
    )
    if row_identity != identity:
        raise ShadowProgressCorruptionError(
            "shadow progress identity does not match query"
        )
    try:
        progress = ShadowProgress(
            identity=row_identity,
            market_as_of=_row_value(row, "market_as_of"),
            last_disposition=_row_value(row, "last_disposition"),
            progress_schema_version=_row_value(row, "progress_schema_version"),
            created_at=_row_value(row, "created_at"),
            updated_at=_row_value(row, "updated_at"),
        )
    except (TypeError, ValueError) as exc:
        raise ShadowProgressCorruptionError(
            "shadow progress row contains invalid evidence"
        ) from exc
    _validate_progress(progress)
    return progress


__all__ = [
    "SHADOW_PROGRESS_SCHEMA_VERSION",
    "InMemoryShadowProgressRepository",
    "ShadowProgress",
    "ShadowProgressCorruptionError",
    "ShadowProgressRepository",
    "ShadowProgressSaveResult",
]
