"""Canonical candle persistence and transactional outbox commit semantics."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

import asyncpg

from apps.ingestion_app.domain.candle import CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.publication.outbox import OutboxEvent


class CandleCommitStatus(StrEnum):
    """Result of attempting to commit one canonical candle."""

    INSERTED = "inserted"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"


_INSERT_CANDLE_SQL = """
INSERT INTO ingestion.candles (
    venue,
    instrument_id,
    timeframe,
    open_time,
    close_time,
    open,
    high,
    low,
    close,
    volume,
    taker_buy_base,
    source_type,
    source_provider,
    source_timeframe
)
VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14
)
ON CONFLICT (venue, instrument_id, timeframe, open_time) DO NOTHING
RETURNING venue
"""

_SELECT_EXISTING_SQL = """
SELECT
    close_time,
    open,
    high,
    low,
    close,
    volume,
    taker_buy_base,
    source_type,
    source_timeframe
FROM ingestion.candles
WHERE venue = $1
  AND instrument_id = $2
  AND timeframe = $3
  AND open_time = $4
"""

_INSERT_OUTBOX_SQL = """
INSERT INTO ingestion.outbox (
    event_id,
    event_type,
    schema_version,
    producer,
    occurred_at,
    payload
)
VALUES ($1, $2, $3, $4, $5, $6::jsonb)
"""

_SELECT_CANDLES_SQL = """
SELECT
    venue,
    instrument_id,
    timeframe,
    open_time,
    close_time,
    open,
    high,
    low,
    close,
    volume,
    taker_buy_base,
    source_type,
    source_provider,
    source_timeframe
FROM ingestion.candles
WHERE venue = $1
  AND instrument_id = $2
  AND timeframe = $3
  AND open_time >= $4
  AND open_time < $5
ORDER BY open_time ASC
"""

_SELECT_LATEST_CANDLE_SQL = """
SELECT
    venue,
    instrument_id,
    timeframe,
    open_time,
    close_time,
    open,
    high,
    low,
    close,
    volume,
    taker_buy_base,
    source_type,
    source_provider,
    source_timeframe
FROM ingestion.candles
WHERE venue = $1
  AND instrument_id = $2
  AND timeframe = $3
  AND close_time <= $4
ORDER BY open_time DESC
LIMIT 1
"""

_SELECT_PENDING_OUTBOX_SQL = """
SELECT
    event_id,
    event_type,
    schema_version,
    producer,
    occurred_at,
    payload
FROM ingestion.outbox
WHERE published_at IS NULL
ORDER BY occurred_at ASC, event_id ASC
LIMIT $1
"""

_SELECT_PENDING_OUTBOX_STATE_SQL = """
SELECT
    COUNT(*)::bigint AS pending_count,
    MIN(occurred_at) AS oldest_pending
FROM ingestion.outbox
WHERE published_at IS NULL
"""

_MARK_OUTBOX_PUBLISHED_SQL = """
UPDATE ingestion.outbox
SET published_at = $2
WHERE event_id = $1
  AND published_at IS NULL
RETURNING event_id
"""

_DELETE_PUBLISHED_OUTBOX_SQL = """
WITH candidates AS (
    SELECT event_id
    FROM ingestion.outbox
    WHERE published_at IS NOT NULL
      AND published_at < $1
    ORDER BY published_at ASC, event_id ASC
    LIMIT $2
)
DELETE FROM ingestion.outbox AS outbox
USING candidates
WHERE outbox.event_id = candidates.event_id
RETURNING outbox.event_id
"""

_SELECT_CANDLE_CHUNKS_SQL = """
SELECT show_chunks(
    'ingestion.candles',
    older_than => $1::timestamptz
)::text AS chunk_name
"""

_DROP_CANDLE_CHUNKS_SQL = """
SELECT drop_chunks('ingestion.candles', older_than => $1::timestamptz)
"""


def _validate_positive_limit(limit: object) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be a strict positive int")
    if limit <= 0:
        raise ValueError("limit must be a strict positive int")
    return limit


def _validate_utc_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value.astimezone(UTC)


def _canonical_payload_json(payload: object) -> str:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError("outbox payload must contain valid JSON") from exc
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _canonical_content_matches(
    existing: Mapping[str, object],
    incoming: CanonicalCandle,
) -> bool:
    for field_name, incoming_value in (
        ("close_time", incoming.close_time),
        ("open", incoming.open),
        ("high", incoming.high),
        ("low", incoming.low),
        ("close", incoming.close),
        ("volume", incoming.volume),
        ("source_type", incoming.source_type),
    ):
        if existing[field_name] != incoming_value:
            return False

    if (
        incoming.source_type == "derived"
        and existing["source_timeframe"] != incoming.source_timeframe
    ):
        return False

    existing_taker_buy_base = existing["taker_buy_base"]
    return not (
        existing_taker_buy_base is not None
        and incoming.taker_buy_base is not None
        and existing_taker_buy_base != incoming.taker_buy_base
    )


class CandleRepository:
    """Persist canonical candles and their publication intent atomically."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    @staticmethod
    def _row_to_canonical(row: Mapping[str, object]) -> CanonicalCandle:
        return CanonicalCandle(
            lane=MarketLane(
                row["venue"],
                row["instrument_id"],
                row["timeframe"],
            ),
            open_time=row["open_time"],
            close_time=row["close_time"],
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row["volume"],
            taker_buy_base=row["taker_buy_base"],
            source_type=row["source_type"],
            source_provider=row["source_provider"],
            source_timeframe=row["source_timeframe"],
        )

    @staticmethod
    def _row_to_outbox_event(row: Mapping[str, object]) -> OutboxEvent:
        return OutboxEvent(
            event_id=row["event_id"],
            event_type=row["event_type"],
            schema_version=row["schema_version"],
            producer=row["producer"],
            occurred_at=row["occurred_at"],
            payload_json=_canonical_payload_json(row["payload"]),
        )

    async def fetch_candles(
        self,
        *,
        lane: MarketLane,
        since: datetime,
        until: datetime,
    ) -> tuple[CanonicalCandle, ...]:
        """Read canonical candles in the half-open UTC interval [since, until)."""
        if not isinstance(lane, MarketLane):
            raise TypeError("lane must be a MarketLane")
        for value, field_name in ((since, "since"), (until, "until")):
            if not isinstance(value, datetime):
                raise TypeError(f"{field_name} must be a datetime")
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError(f"{field_name} must be timezone-aware UTC")
        if until <= since:
            raise ValueError("until must be after since")

        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                _SELECT_CANDLES_SQL,
                lane.venue,
                lane.instrument_id,
                lane.timeframe,
                since,
                until,
            )

        return tuple(self._row_to_canonical(row) for row in rows)

    async def fetch_latest_candle(
        self,
        *,
        lane: MarketLane,
        before: datetime,
    ) -> CanonicalCandle | None:
        """Read the latest canonical candle closed no later than ``before``."""
        if not isinstance(lane, MarketLane):
            raise TypeError("lane must be a MarketLane")
        if not isinstance(before, datetime):
            raise TypeError("before must be a datetime")
        if before.tzinfo is None or before.utcoffset() != timedelta(0):
            raise ValueError("before must be timezone-aware UTC")

        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                _SELECT_LATEST_CANDLE_SQL,
                lane.venue,
                lane.instrument_id,
                lane.timeframe,
                before,
            )

        return None if row is None else self._row_to_canonical(row)

    async def fetch_pending_outbox(self, *, limit: int) -> tuple[OutboxEvent, ...]:
        """Read pending publication intents in deterministic occurred order."""
        resolved_limit = _validate_positive_limit(limit)

        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                _SELECT_PENDING_OUTBOX_SQL,
                resolved_limit,
            )

        return tuple(self._row_to_outbox_event(row) for row in rows)

    async def fetch_pending_outbox_state(self) -> tuple[int, datetime | None]:
        """Return the pending count and oldest pending occurrence timestamp."""
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(_SELECT_PENDING_OUTBOX_STATE_SQL)
        if row is None:
            return 0, None
        return int(row["pending_count"]), row["oldest_pending"]

    async def mark_outbox_published(
        self,
        *,
        event_id: UUID,
        published_at: datetime,
    ) -> bool:
        """Mark one pending event published without overwriting an earlier mark."""
        if not isinstance(event_id, UUID):
            raise TypeError("event_id must be a UUID")
        resolved_published_at = _validate_utc_datetime(
            published_at,
            field_name="published_at",
        )

        async with self.pool.acquire() as connection:
            marked_event_id = await connection.fetchval(
                _MARK_OUTBOX_PUBLISHED_SQL,
                event_id,
                resolved_published_at,
            )

        return marked_event_id is not None

    async def delete_published_outbox_before(
        self,
        *,
        cutoff: datetime,
        limit: int,
    ) -> int:
        """Delete a bounded batch of already-published historical intents."""
        resolved_cutoff = _validate_utc_datetime(cutoff, field_name="cutoff")
        resolved_limit = _validate_positive_limit(limit)

        async with self.pool.acquire() as connection:
            deleted_event_ids = await connection.fetch(
                _DELETE_PUBLISHED_OUTBOX_SQL,
                resolved_cutoff,
                resolved_limit,
            )

        return len(deleted_event_ids)

    async def drop_candle_chunks_before(self, *, cutoff: datetime) -> tuple[str, ...]:
        """Drop complete canonical candle chunks older than a UTC cutoff.

        The table name is intentionally fixed to the canonical ingestion hypertable;
        this primitive is not a general-purpose SQL table deletion API.
        """
        resolved_cutoff = _validate_utc_datetime(cutoff, field_name="cutoff")

        async with self.pool.acquire() as connection, connection.transaction():
            rows = await connection.fetch(_SELECT_CANDLE_CHUNKS_SQL, resolved_cutoff)
            await connection.execute(_DROP_CANDLE_CHUNKS_SQL, resolved_cutoff)

        return tuple(str(row["chunk_name"]) for row in rows)

    async def commit_candle(
        self,
        candle: CanonicalCandle,
        event: OutboxEvent,
    ) -> CandleCommitStatus:
        """Classify and commit one canonical candle without overwriting rows."""
        async with self.pool.acquire() as connection, connection.transaction():
            inserted = await connection.fetchrow(
                _INSERT_CANDLE_SQL,
                candle.lane.venue,
                candle.lane.instrument_id,
                candle.lane.timeframe,
                candle.open_time,
                candle.close_time,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
                candle.taker_buy_base,
                candle.source_type,
                candle.source_provider,
                candle.source_timeframe,
            )
            if inserted is not None:
                await connection.execute(
                    _INSERT_OUTBOX_SQL,
                    event.event_id,
                    event.event_type,
                    event.schema_version,
                    event.producer,
                    event.occurred_at,
                    event.payload_json,
                )
                return CandleCommitStatus.INSERTED

            existing = await connection.fetchrow(
                _SELECT_EXISTING_SQL,
                candle.lane.venue,
                candle.lane.instrument_id,
                candle.lane.timeframe,
                candle.open_time,
            )
            if existing is None:
                raise RuntimeError("canonical conflict row was not found")
            if _canonical_content_matches(existing, candle):
                return CandleCommitStatus.DUPLICATE
            return CandleCommitStatus.CONFLICT


__all__ = ["CandleCommitStatus", "CandleRepository"]
