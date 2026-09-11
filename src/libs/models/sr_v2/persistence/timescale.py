"""Injected-pool PostgreSQL adapter for the SR v2 latest state row.

The adapter deliberately uses only an existing asyncpg-compatible pool.  It
does not create or close the pool, retain a connection, create tasks, or store
anything besides the canonical structural state row defined in ``schema.sql``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..serialization.state_codec import decode_state
from .contracts import (
    CheckpointCorruptionError,
    CheckpointDisposition,
    CheckpointRecord,
    SRV2LaneIdentity,
    classify_commit,
)

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_SELECT_COLUMNS = """
    state_schema_version, generation, cutoff, state_checksum, state_payload,
    venue, instrument_id, asset, config_fingerprint
"""
_SELECT = f"""
    SELECT {_SELECT_COLUMNS}
      FROM sr_v2.checkpoints
     WHERE venue = $1
       AND instrument_id = $2
       AND asset = $3
       AND config_fingerprint = $4
"""
_SELECT_FOR_UPDATE = _SELECT + " FOR UPDATE"


class TimescaleCheckpointRepository:
    """Persist validated SR v2 checkpoints in one latest-only table."""

    def __init__(self, pool: Any) -> None:
        if pool is None or not callable(getattr(pool, "acquire", None)):
            raise TypeError("pool must provide asyncpg-compatible acquire()")
        self._pool = pool

    async def load(self, identity: SRV2LaneIdentity) -> CheckpointRecord | None:
        """Load and validate the latest state for ``identity``."""

        _validate_identity(identity)
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(_SELECT, *_identity_values(identity))
        if row is None:
            return None
        return _record_from_row(row, identity)

    async def commit(
        self,
        proposal: CheckpointRecord,
        *,
        expected_generation: int | None,
    ) -> CheckpointDisposition:
        """Apply one generation-CAS proposal in a short transaction."""

        if not isinstance(proposal, CheckpointRecord):
            raise TypeError("proposal must be CheckpointRecord")
        _validate_identity(proposal.identity)
        _validate_expected_generation(expected_generation)

        # CheckpointRecord.from_state performs serialization and canonical
        # checksum validation before this method acquires a connection.
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                _SELECT_FOR_UPDATE,
                *_identity_values(proposal.identity),
            )
            if row is None:
                absent_disposition = classify_commit(
                    None,
                    proposal,
                    expected_generation=expected_generation,
                )
                if absent_disposition is not CheckpointDisposition.INSERTED:
                    return absent_disposition
                inserted = await connection.execute(
                    """
                    INSERT INTO sr_v2.checkpoints (
                        venue, instrument_id, asset, config_fingerprint,
                        state_schema_version, generation, cutoff,
                        state_checksum, state_payload
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (venue, instrument_id, asset, config_fingerprint)
                    DO NOTHING
                    """,
                    *_record_values(proposal),
                )
                if _affected_rows(inserted) == 1:
                    return CheckpointDisposition.INSERTED
                # Resolve a concurrent genesis insert before classifying.  An
                # identical payload is an idempotent retry; a different one
                # remains a conflict under the absent-row CAS.
                raced_row = await connection.fetchrow(
                    _SELECT_FOR_UPDATE,
                    *_identity_values(proposal.identity),
                )
                if raced_row is None:
                    return CheckpointDisposition.CONFLICT
                raced = _record_from_row(raced_row, proposal.identity)
                return classify_commit(
                    raced,
                    proposal,
                    expected_generation=expected_generation,
                )

            current = _record_from_row(row, proposal.identity)
            disposition = classify_commit(
                current,
                proposal,
                expected_generation=expected_generation,
            )
            if disposition is not CheckpointDisposition.UPDATED:
                return disposition

            updated = await connection.execute(
                """
                UPDATE sr_v2.checkpoints
                   SET state_schema_version = $6,
                       generation = $7,
                       cutoff = $8,
                       state_checksum = $9,
                       state_payload = $10
                 WHERE venue = $1
                   AND instrument_id = $2
                   AND asset = $3
                   AND config_fingerprint = $4
                   AND generation = $5
                """,
                proposal.identity.venue,
                proposal.identity.instrument_id,
                proposal.identity.asset,
                proposal.identity.config_fingerprint,
                expected_generation,
                proposal.schema_version,
                proposal.generation,
                proposal.cutoff,
                proposal.state_checksum,
                proposal.state_payload,
            )
            if _affected_rows(updated) != 1:
                return CheckpointDisposition.CONFLICT
            return CheckpointDisposition.UPDATED


async def apply_schema(pool: Any) -> None:
    """Explicitly apply the SR v2 table schema using a caller-owned pool.

    Live execution never calls this function.  A consuming application may
    invoke it during its own startup/bootstrap sequence and remains responsible
    for the pool lifetime.
    """

    if pool is None or not callable(getattr(pool, "acquire", None)):
        raise TypeError("pool must provide asyncpg-compatible acquire()")
    schema = _SCHEMA_PATH.read_text(encoding="utf-8")
    async with pool.acquire() as connection:
        await connection.execute(schema)


def _validate_identity(identity: SRV2LaneIdentity) -> None:
    if not isinstance(identity, SRV2LaneIdentity):
        raise TypeError("identity must be SRV2LaneIdentity")


def _validate_expected_generation(expected_generation: int | None) -> None:
    if expected_generation is not None and (
        isinstance(expected_generation, bool)
        or not isinstance(expected_generation, int)
        or expected_generation < 0
    ):
        raise ValueError("expected_generation must be non-negative or None")


def _identity_values(identity: SRV2LaneIdentity) -> tuple[str, str, str, str]:
    return identity.venue, identity.instrument_id, identity.asset, identity.config_fingerprint


def _record_values(record: CheckpointRecord) -> tuple[object, ...]:
    return (
        record.identity.venue,
        record.identity.instrument_id,
        record.identity.asset,
        record.identity.config_fingerprint,
        record.schema_version,
        record.generation,
        record.cutoff,
        record.state_checksum,
        record.state_payload,
    )


def _affected_rows(status: object) -> int:
    """Parse asyncpg's ``COMMAND count`` status without trusting free text."""

    if not isinstance(status, str):
        return 0
    try:
        return int(status.rsplit(" ", 1)[-1])
    except (ValueError, IndexError):
        return 0


def _row_value(row: Any, name: str) -> Any:
    try:
        return row[name]
    except (KeyError, TypeError, IndexError) as exc:
        raise CheckpointCorruptionError(f"checkpoint row missing {name}") from exc


def _record_from_row(row: Any, expected_identity: SRV2LaneIdentity) -> CheckpointRecord:
    """Decode one DB row and verify every persisted identity/value binding."""

    _validate_identity(expected_identity)
    try:
        row_identity = SRV2LaneIdentity(
            venue=_row_value(row, "venue"),
            instrument_id=_row_value(row, "instrument_id"),
            asset=_row_value(row, "asset"),
            config_fingerprint=_row_value(row, "config_fingerprint"),
        )
    except (TypeError, ValueError) as exc:
        raise CheckpointCorruptionError("checkpoint identity columns are invalid") from exc
    if row_identity != expected_identity:
        raise CheckpointCorruptionError("checkpoint identity does not match query")

    payload = _row_value(row, "state_payload")
    if isinstance(payload, memoryview):
        payload = payload.tobytes()
    elif isinstance(payload, bytearray):
        payload = bytes(payload)
    if not isinstance(payload, bytes):
        raise CheckpointCorruptionError("checkpoint state_payload must be bytes")
    try:
        state = decode_state(
            payload,
            expected_config_fingerprint=expected_identity.config_fingerprint,
            expected_venue=expected_identity.venue,
            expected_instrument_id=expected_identity.instrument_id,
            expected_asset=expected_identity.asset,
        )
    except (TypeError, ValueError) as exc:
        raise CheckpointCorruptionError("checkpoint state payload is invalid") from exc
    try:
        return CheckpointRecord(
            identity=expected_identity,
            schema_version=_row_value(row, "state_schema_version"),
            generation=_row_value(row, "generation"),
            cutoff=_row_value(row, "cutoff"),
            state=state,
            state_payload=payload,
            state_checksum=_row_value(row, "state_checksum"),
        )
    except (TypeError, ValueError) as exc:
        raise CheckpointCorruptionError("checkpoint row is not a valid canonical state") from exc


__all__ = ["TimescaleCheckpointRepository", "apply_schema"]
