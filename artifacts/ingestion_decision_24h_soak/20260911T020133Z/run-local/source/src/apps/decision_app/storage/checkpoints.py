"""Latest-only D9A lane-state checkpoint persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from apps.decision_app.domain.state import LaneExecutionIdentity
from apps.decision_app.runtime.deadlines import (
    CleanupBudget,
    Deadline,
    acquire_db_connection,
    cleanup_with_timeout,
    native_timeout_kwargs,
    require_remaining,
    run_until,
)
from apps.decision_app.storage.state_codec import (
    StateCodecError,
    decode_state_payload,
    encode_state_payload,
    state_payload_sha256,
)
from libs.contracts.decision import (
    FrozenMapping,
    ModelState,
    freeze_model_state,
    require_utc,
)

CHECKPOINT_SCHEMA_VERSION = 1


class CheckpointCorruptionError(ValueError):
    """Raised when durable checkpoint evidence is not trustworthy."""


class CheckpointSaveResult(str, Enum):
    INSERTED = "INSERTED"
    UPDATED = "UPDATED"
    IDENTICAL = "IDENTICAL"
    CONFLICT = "CONFLICT"
    REJECTED_OLDER = "REJECTED_OLDER"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _normalize_states(
    values: Mapping[str, ModelState],
) -> FrozenMapping[str, ModelState]:
    if not isinstance(values, Mapping):
        raise TypeError("state_by_binding must be a mapping")
    normalized: dict[str, ModelState] = {}
    for binding_id, state in values.items():
        normalized[_text(binding_id, "binding_id")] = freeze_model_state(state)
    if not normalized:
        raise ValueError("state_by_binding must not be empty")
    return FrozenMapping(dict(sorted(normalized.items())))


@dataclass(frozen=True, slots=True, kw_only=True)
class LaneStateCheckpoint:
    """One latest atomic state batch for one exact D6 execution identity."""

    identity: LaneExecutionIdentity
    market_as_of: datetime
    state_inception_at: datetime
    state_by_binding: Mapping[str, ModelState]
    state_payload: str
    state_payload_sha256: str
    checkpoint_schema_version: int = CHECKPOINT_SCHEMA_VERSION
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, LaneExecutionIdentity):
            raise TypeError("identity must be LaneExecutionIdentity")
        require_utc(self.market_as_of, field_name="market_as_of")
        require_utc(self.state_inception_at, field_name="state_inception_at")
        if self.state_inception_at > self.market_as_of:
            raise ValueError("state_inception_at cannot be after market_as_of")
        if self.checkpoint_schema_version != CHECKPOINT_SCHEMA_VERSION:
            raise ValueError("unsupported checkpoint schema version")
        states = _normalize_states(self.state_by_binding)
        expected_payload = encode_state_payload(dict(states))
        if self.state_payload != expected_payload:
            raise CheckpointCorruptionError(
                "state_payload does not match state_by_binding"
            )
        expected_hash = state_payload_sha256(expected_payload)
        if self.state_payload_sha256 != expected_hash:
            raise CheckpointCorruptionError(
                "state_payload_sha256 does not match payload"
            )
        for field_name in ("created_at", "updated_at"):
            value = getattr(self, field_name)
            if value is not None:
                require_utc(value, field_name=field_name)
        object.__setattr__(self, "state_by_binding", states)

    @classmethod
    def create(
        cls,
        *,
        identity: LaneExecutionIdentity,
        market_as_of: datetime,
        state_inception_at: datetime,
        state_by_binding: Mapping[str, ModelState],
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> LaneStateCheckpoint:
        states = _normalize_states(state_by_binding)
        payload = encode_state_payload(dict(states))
        return cls(
            identity=identity,
            market_as_of=market_as_of,
            state_inception_at=state_inception_at,
            state_by_binding=states,
            state_payload=payload,
            state_payload_sha256=state_payload_sha256(payload),
            created_at=created_at,
            updated_at=updated_at,
        )

    def validate_binding_ids(self, expected: Sequence[str]) -> None:
        expected_ids = tuple(sorted(_text(item, "binding_id") for item in expected))
        if tuple(self.state_by_binding) != expected_ids:
            raise CheckpointCorruptionError(
                "checkpoint state binding IDs do not match stateful lane bindings"
            )


class InMemoryCheckpointRepository:
    """Deterministic test/runtime seam with the same latest-only semantics."""

    def __init__(self) -> None:
        self._items: dict[LaneExecutionIdentity, LaneStateCheckpoint] = {}

    async def load(
        self,
        identity: LaneExecutionIdentity,
        *,
        expected_binding_ids: Sequence[str] | None = None,
    ) -> LaneStateCheckpoint | None:
        if not isinstance(identity, LaneExecutionIdentity):
            raise TypeError("identity must be LaneExecutionIdentity")
        checkpoint = self._items.get(identity)
        if checkpoint is None:
            return None
        _validate_checkpoint(checkpoint, expected_binding_ids)
        return checkpoint

    async def save(self, checkpoint: LaneStateCheckpoint) -> CheckpointSaveResult:
        _validate_checkpoint(checkpoint, None)
        current = self._items.get(checkpoint.identity)
        if current is None:
            self._items[checkpoint.identity] = checkpoint
            return CheckpointSaveResult.INSERTED
        if checkpoint.market_as_of < current.market_as_of:
            return CheckpointSaveResult.REJECTED_OLDER
        if checkpoint.market_as_of == current.market_as_of:
            if (
                checkpoint.state_payload == current.state_payload
                and checkpoint.state_inception_at == current.state_inception_at
            ):
                return CheckpointSaveResult.IDENTICAL
            return CheckpointSaveResult.CONFLICT
        self._items[checkpoint.identity] = checkpoint
        return CheckpointSaveResult.UPDATED


def _validate_checkpoint(
    checkpoint: LaneStateCheckpoint,
    expected_binding_ids: Sequence[str] | None,
) -> None:
    if not isinstance(checkpoint, LaneStateCheckpoint):
        raise TypeError("checkpoint must be LaneStateCheckpoint")
    # Reconstructing through the codec also catches a mutated/tampered payload.
    try:
        decoded = decode_state_payload(checkpoint.state_payload)
    except StateCodecError as exc:
        raise CheckpointCorruptionError(str(exc)) from exc
    if not isinstance(decoded, Mapping) or dict(decoded) != dict(
        checkpoint.state_by_binding
    ):
        raise CheckpointCorruptionError("checkpoint payload does not match state map")
    if (
        state_payload_sha256(checkpoint.state_payload)
        != checkpoint.state_payload_sha256
    ):
        raise CheckpointCorruptionError("checkpoint payload hash mismatch")
    if expected_binding_ids is not None:
        checkpoint.validate_binding_ids(expected_binding_ids)


class CheckpointRepository:
    """Small asyncpg repository for ``decision.state_checkpoints``."""

    def __init__(
        self,
        pool: Any,
        *,
        io_timeout_seconds: float | None = None,
        operation_timeout_seconds: float | None = None,
        cleanup_timeout_seconds: float | None = None,
    ) -> None:
        if pool is None or not hasattr(pool, "acquire"):
            raise TypeError("pool must provide asyncpg acquire()")
        for value in (
            io_timeout_seconds,
            operation_timeout_seconds,
            cleanup_timeout_seconds,
        ):
            if value is not None:
                Deadline.after(value)
        if operation_timeout_seconds is not None and cleanup_timeout_seconds is None:
            cleanup_timeout_seconds = 5.0
        self._pool = pool
        self._io_timeout_seconds = io_timeout_seconds
        self._operation_timeout_seconds = operation_timeout_seconds
        self._cleanup_timeout_seconds = cleanup_timeout_seconds
        self._retained_cleanup_tasks: set[Any] = set()
        self._poisoned = False

    def _begin(self) -> Deadline | None:
        self._ensure_usable()
        if self._operation_timeout_seconds is None:
            return None
        return Deadline.after(self._operation_timeout_seconds)

    async def _phase(
        self,
        awaitable: Any,
        deadline: Deadline | None,
        operation: str,
    ) -> Any:
        if deadline is None:
            return await awaitable
        return await run_until(awaitable, deadline, operation=operation)

    def _finish(self, deadline: Deadline | None, operation: str) -> None:
        if deadline is not None:
            require_remaining(deadline, operation=operation)

    def _poison(self) -> None:
        self._poisoned = True

    @property
    def poisoned(self) -> bool:
        return self._poisoned

    def _ensure_usable(self) -> None:
        if self._poisoned:
            raise RuntimeError(
                "checkpoint repository is poisoned after lease cleanup failure"
            )

    async def load(
        self,
        identity: LaneExecutionIdentity,
        *,
        expected_binding_ids: Sequence[str] | None = None,
    ) -> LaneStateCheckpoint | None:
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
            operation="checkpoint load",
        ) as connection:
            row = await self._phase(
                connection.fetchrow(
                    """
                SELECT checkpoint_schema_version, lane_id,
                       effective_lane_revision, feature_plan_fingerprint,
                       data_plan_fingerprint, market_as_of, state_inception_at,
                       state_payload, state_payload_sha256, created_at, updated_at
                  FROM decision.state_checkpoints
                 WHERE lane_id = $1
                   AND effective_lane_revision = $2
                   AND feature_plan_fingerprint = $3
                   AND data_plan_fingerprint = $4
                """,
                    identity.lane_id,
                    identity.effective_lane_revision,
                    identity.feature_plan_fingerprint,
                    identity.data_plan_fingerprint,
                    **native_timeout_kwargs(
                        deadline,
                        operation="checkpoint load query",
                    ),
                ),
                deadline,
                "checkpoint load query",
            )
        self._finish(deadline, "checkpoint load")
        if row is None:
            return None
        checkpoint = _checkpoint_from_row(row, identity)
        _validate_checkpoint(checkpoint, expected_binding_ids)
        return checkpoint

    async def save(self, checkpoint: LaneStateCheckpoint) -> CheckpointSaveResult:
        _validate_checkpoint(checkpoint, None)
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
            operation="checkpoint save",
        ) as connection:
            transaction = getattr(connection, "transaction", None)
            if callable(transaction) and deadline is None:
                async with connection.transaction():
                    return await self._save_locked(connection, checkpoint, now)
            if callable(transaction):
                tx = connection.transaction()
                if deadline is not None:
                    require_remaining(
                        deadline,
                        operation="checkpoint transaction begin",
                    )
                await self._phase(tx.start(), deadline, "checkpoint transaction begin")
                try:
                    result = await self._save_locked(
                        connection,
                        checkpoint,
                        now,
                        deadline=deadline,
                    )
                except BaseException:
                    try:
                        await cleanup_with_timeout(
                            tx.rollback(),
                            cleanup_budget.remaining(),
                            operation="checkpoint transaction rollback",
                            retained_tasks=self._retained_cleanup_tasks,
                        )
                    except BaseException:  # noqa: BLE001
                        self._poison()
                    raise
                if deadline is not None:
                    require_remaining(
                        deadline,
                        operation="checkpoint transaction commit",
                    )
                await self._phase(
                    tx.commit(),
                    deadline,
                    "checkpoint transaction commit",
                )
            else:
                result = await self._save_locked(
                    connection,
                    checkpoint,
                    now,
                    deadline=deadline,
                )
        self._finish(deadline, "checkpoint save")
        return result

    async def _save_locked(
        self,
        connection: Any,
        checkpoint: LaneStateCheckpoint,
        now: datetime,
        *,
        deadline: Deadline | None = None,
    ) -> CheckpointSaveResult:
        row = await self._phase(
            connection.fetchrow(
                """
            SELECT checkpoint_schema_version, lane_id,
                   effective_lane_revision, feature_plan_fingerprint,
                   data_plan_fingerprint, market_as_of, state_inception_at,
                   state_payload, state_payload_sha256, created_at, updated_at
              FROM decision.state_checkpoints
             WHERE lane_id = $1
               AND effective_lane_revision = $2
               AND feature_plan_fingerprint = $3
               AND data_plan_fingerprint = $4
             FOR UPDATE
            """,
                checkpoint.identity.lane_id,
                checkpoint.identity.effective_lane_revision,
                checkpoint.identity.feature_plan_fingerprint,
                checkpoint.identity.data_plan_fingerprint,
                **native_timeout_kwargs(
                    deadline,
                    operation="checkpoint save query",
                ),
            ),
            deadline,
            "checkpoint save query",
        )
        if row is not None:
            current = _checkpoint_from_row(row, checkpoint.identity)
            _validate_checkpoint(current, None)
            if checkpoint.market_as_of < current.market_as_of:
                return CheckpointSaveResult.REJECTED_OLDER
            if checkpoint.market_as_of == current.market_as_of:
                if (
                    checkpoint.state_payload == current.state_payload
                    and checkpoint.state_inception_at == current.state_inception_at
                ):
                    return CheckpointSaveResult.IDENTICAL
                return CheckpointSaveResult.CONFLICT
            await self._phase(
                connection.execute(
                    """
                UPDATE decision.state_checkpoints
                   SET market_as_of = $5, state_inception_at = $6,
                       state_payload = $7, state_payload_sha256 = $8,
                       updated_at = $9
                 WHERE lane_id = $1 AND effective_lane_revision = $2
                   AND feature_plan_fingerprint = $3
                   AND data_plan_fingerprint = $4
                """,
                    checkpoint.identity.lane_id,
                    checkpoint.identity.effective_lane_revision,
                    checkpoint.identity.feature_plan_fingerprint,
                    checkpoint.identity.data_plan_fingerprint,
                    checkpoint.market_as_of,
                    checkpoint.state_inception_at,
                    checkpoint.state_payload,
                    checkpoint.state_payload_sha256,
                    now,
                    **native_timeout_kwargs(
                        deadline,
                        operation="checkpoint update",
                    ),
                ),
                deadline,
                "checkpoint update",
            )
            return CheckpointSaveResult.UPDATED
        await self._phase(
            connection.execute(
                """
            INSERT INTO decision.state_checkpoints (
                checkpoint_schema_version, lane_id, effective_lane_revision,
                feature_plan_fingerprint, data_plan_fingerprint, market_as_of,
                state_inception_at, state_payload, state_payload_sha256,
                created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$10)
            """,
                checkpoint.checkpoint_schema_version,
                checkpoint.identity.lane_id,
                checkpoint.identity.effective_lane_revision,
                checkpoint.identity.feature_plan_fingerprint,
                checkpoint.identity.data_plan_fingerprint,
                checkpoint.market_as_of,
                checkpoint.state_inception_at,
                checkpoint.state_payload,
                checkpoint.state_payload_sha256,
                now,
                **native_timeout_kwargs(
                    deadline,
                    operation="checkpoint insert",
                ),
            ),
            deadline,
            "checkpoint insert",
        )
        return CheckpointSaveResult.INSERTED


def _row_value(row: Any, name: str) -> Any:
    try:
        return row[name]
    except (KeyError, TypeError, IndexError) as exc:
        raise CheckpointCorruptionError(f"checkpoint row missing {name}") from exc


def _checkpoint_from_row(
    row: Any, identity: LaneExecutionIdentity
) -> LaneStateCheckpoint:
    row_identity = LaneExecutionIdentity(
        lane_id=_row_value(row, "lane_id"),
        effective_lane_revision=_row_value(row, "effective_lane_revision"),
        feature_plan_fingerprint=_row_value(row, "feature_plan_fingerprint"),
        data_plan_fingerprint=_row_value(row, "data_plan_fingerprint"),
    )
    if row_identity != identity:
        raise CheckpointCorruptionError("checkpoint identity does not match query")
    payload = _row_value(row, "state_payload")
    if not isinstance(payload, str):
        raise CheckpointCorruptionError("checkpoint state_payload must be text")
    try:
        decoded = decode_state_payload(payload)
    except (StateCodecError, TypeError, ValueError) as exc:
        raise CheckpointCorruptionError(
            "checkpoint state payload is not valid canonical state"
        ) from exc
    if not isinstance(decoded, Mapping):
        raise CheckpointCorruptionError("checkpoint state payload must map bindings")
    try:
        return LaneStateCheckpoint(
            identity=row_identity,
            market_as_of=_row_value(row, "market_as_of"),
            state_inception_at=_row_value(row, "state_inception_at"),
            state_by_binding=decoded,
            state_payload=payload,
            state_payload_sha256=_row_value(row, "state_payload_sha256"),
            checkpoint_schema_version=_row_value(row, "checkpoint_schema_version"),
            created_at=_row_value(row, "created_at"),
            updated_at=_row_value(row, "updated_at"),
        )
    except CheckpointCorruptionError:
        raise
    except (TypeError, ValueError) as exc:
        raise CheckpointCorruptionError(
            "checkpoint row contains invalid state evidence"
        ) from exc


__all__ = [
    "CHECKPOINT_SCHEMA_VERSION",
    "CheckpointCorruptionError",
    "CheckpointRepository",
    "CheckpointSaveResult",
    "InMemoryCheckpointRepository",
    "LaneStateCheckpoint",
]
