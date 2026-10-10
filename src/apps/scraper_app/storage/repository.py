"""Append-only repository: asyncpg implementation and an in-memory twin.

Both implement the same write rule and the same read semantics. Clock values
for ``finished_at`` and ``observed_at`` come from the database
(``clock_timestamp()``); the in-memory twin takes an injected clock instead.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol

import asyncpg

from apps.scraper_app.domain.bars import Bar
from apps.scraper_app.domain.datasets import DatasetSpec
from apps.scraper_app.domain.payloads import (
    PAYLOAD_FORMAT,
    AcceptedPayload,
    decode_payload,
    encode_payload,
)

TRIGGERS = ("schedule", "catchup", "late_bar", "job")
_DETAIL_LIMIT = 500


@dataclass(frozen=True, slots=True)
class ReadRecord:
    read_id: int
    dataset_id: str
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime
    provider_time: datetime | None
    covered_from: datetime | None
    covered_to: datetime | None
    bars_seen: int
    bars_written: int
    gap_before: bool
    holes: int
    error_code: str | None
    error_detail: str | None
    meta: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class PayloadRecord:
    """One stored whole payload; ``payload`` is the gzip blob."""

    read_id: int
    dataset_id: str
    observed_at: datetime
    provider_time: datetime | None
    format: str
    raw_bytes: int
    content_hash: str
    payload: bytes

    def text(self) -> str:
        """The canonical JSON text."""
        return decode_payload(self.payload)


@dataclass(frozen=True, slots=True)
class PayloadMeta:
    """Payload row without the blob (``read_id`` is the observation id)."""

    read_id: int
    observed_at: datetime
    provider_time: datetime | None
    content_hash: str
    raw_bytes: int


@dataclass(frozen=True, slots=True)
class PayloadCommit:
    read_id: int
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class BarRecord:
    dataset_id: str
    bar_open: datetime
    bar_close: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    seq: int
    content_hash: str
    observed_at: datetime
    read_id: int
    backfilled: bool
    first_observed_at: datetime
    revision_count: int
    is_final: bool


@dataclass(frozen=True, slots=True)
class DatasetHead:
    """Cheap per-dataset summary. The bar opens are not filtered by ``at``."""

    first_ok_read_finished_at: datetime | None
    latest_ok_read: ReadRecord | None
    first_bar_open: datetime | None
    last_bar_open: datetime | None


@dataclass(frozen=True, slots=True)
class CommitOutcome:
    read_id: int
    bars_seen: int
    bars_written: int


class ScraperRepository(Protocol):
    async def commit_ok_read(
        self,
        spec: DatasetSpec,
        *,
        trigger: str,
        started_at: datetime,
        provider_time: datetime,
        bars: Sequence[Bar],
        gap_before: bool,
        holes: int = 0,
        bars_seen: int | None = None,
    ) -> CommitOutcome: ...

    async def record_failed_read(
        self,
        dataset_id: str,
        *,
        trigger: str,
        started_at: datetime,
        error_code: str,
        error_detail: str,
        provider_time: datetime | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> int: ...

    async def commit_ok_payload(
        self,
        dataset_id: str,
        *,
        trigger: str,
        started_at: datetime,
        accepted: AcceptedPayload,
        gap_before: bool,
        meta: Mapping[str, Any] | None = None,
    ) -> PayloadCommit: ...

    async def latest_payload(
        self, dataset_id: str, *, at: datetime | None = None, blob: bool = True
    ) -> PayloadRecord | None: ...

    async def list_payloads(
        self,
        dataset_id: str,
        *,
        start: datetime | None,
        end: datetime,
        limit: int,
        end_before_id: int | None = None,
    ) -> list[PayloadMeta]:
        """Metadata with ``start <= observed_at < end``, newest first."""
        ...

    async def payload_by_id(
        self, dataset_id: str, read_id: int, *, blob: bool = True
    ) -> PayloadRecord | None: ...

    async def server_time(self) -> datetime: ...

    async def fetch_bars(
        self,
        dataset_id: str,
        *,
        mode: Literal["final", "as_of"] = "final",
        as_of: datetime | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        newest_first: bool = False,
        limit: int,
    ) -> list[BarRecord]: ...

    async def dataset_head(
        self, dataset_id: str, *, at: datetime | None = None
    ) -> DatasetHead: ...

    async def revisions_after_horizon(self, dataset_id: str) -> int: ...

    async def latest_ok_read(self, dataset_id: str) -> ReadRecord | None: ...

    async def latest_read(self, dataset_id: str) -> ReadRecord | None: ...

    async def last_bar_open(self, dataset_id: str) -> datetime | None: ...

    async def first_bar_open(self, dataset_id: str) -> datetime | None: ...

    async def contiguous_from(
        self, dataset_id: str, *, not_before: datetime | None = None
    ) -> datetime | None: ...

    # Batched forms: one statement for all datasets, whatever their number.
    async def latest_reads(
        self, dataset_ids: Sequence[str]
    ) -> dict[str, tuple[ReadRecord | None, ReadRecord | None]]:
        """``{id: (latest ok read, latest read of any status)}``."""
        ...

    async def first_bar_opens(
        self, dataset_ids: Sequence[str]
    ) -> dict[str, datetime | None]: ...

    async def dataset_heads(
        self, dataset_ids: Sequence[str], *, bar_ids: Sequence[str] | None = None
    ) -> dict[str, DatasetHead]:
        """Heads for every id; bar edges only for ``bar_ids`` (default: all)."""
        ...

    async def revisions_after_horizon_many(
        self, dataset_ids: Sequence[str]
    ) -> dict[str, int]: ...


@dataclass(frozen=True, slots=True)
class PurgeResult:
    """Rows deleted per table and the number of non-empty batches it took."""

    deleted: Mapping[str, int]
    batches: int


PURGE_TRADINGVIEW = "tradingview"
PURGE_COINGLASS = "coinglass"
PURGE_KINDS = (PURGE_TRADINGVIEW, PURGE_COINGLASS)


class PurgeRepository(Protocol):
    async def purge_dataset(
        self, dataset_id: str, *, kind: str, days: int, batch_rows: int
    ) -> PurgeResult:
        """Delete data older than ``days`` (database/injected clock) in batches.

        ``kind`` selects the evidence table: ``tradingview`` removes bar
        observations by ``bar_open``; ``coinglass`` removes payloads by
        ``observed_at``. Then the dataset's reads nothing references. The newest
        ok read of the dataset (and its payload) is never deleted.
        """
        ...


def _check_purge(kind: str, days: int, batch_rows: int) -> None:
    if kind not in PURGE_KINDS:
        raise ValueError(f"unknown purge kind {kind!r}")
    if days < 1 or batch_rows < 1:
        raise ValueError("days and batch_rows must be positive")


def _check_trigger(trigger: str) -> None:
    if trigger not in TRIGGERS:
        raise ValueError(f"unknown read trigger: {trigger!r}")


def _check_query(mode: str, as_of: datetime | None, limit: int) -> None:
    if mode not in ("final", "as_of"):
        raise ValueError(f"unknown mode: {mode!r}")
    if (mode == "as_of") != (as_of is not None):
        raise ValueError("as_of is required for mode='as_of' and invalid otherwise")
    if limit < 1:
        raise ValueError("limit must be positive")


def plan_writes(
    spec: DatasetSpec,
    provider_time: datetime,
    bars: Sequence[Bar],
    latest: Mapping[datetime, tuple[int, str]],
) -> list[tuple[Bar, int, bool]]:
    """Rows to insert as ``(bar, seq, backfilled)``, ascending by ``bar_open``.

    A bar with no row gets ``seq = 1``; a changed hash gets ``latest + 1``; an
    identical one is skipped.
    """
    rows: list[tuple[Bar, int, bool]] = []
    for bar in sorted(bars, key=lambda b: b.bar_open):
        known = latest.get(bar.bar_open)
        if known is None:
            seq = 1
        elif known[1] != bar.content_hash:
            seq = known[0] + 1
        else:
            continue
        lag = (provider_time - bar.bar_close).total_seconds()
        rows.append((bar, seq, lag > spec.max_live_lag_seconds))
    return rows


# ---------------------------------------------------------------------------
# asyncpg implementation
# ---------------------------------------------------------------------------

_READ_COLUMNS = (
    "read_id, dataset_id, trigger, status, started_at, finished_at, provider_time, "
    "covered_from, covered_to, bars_seen, bars_written, gap_before, holes, "
    "error_code, error_detail, meta::text AS meta"
)

# Batched lookups: the outer side is the bound id list and every inner side is a
# LIMIT 1 index probe, so no row estimate can turn them into a scan or a join.
_LATEST_READS_SQL = (
    f"SELECT 'ok' AS which, r.* FROM unnest($1::text[]) AS ids(dataset_id) "
    f"CROSS JOIN LATERAL (SELECT {_READ_COLUMNS} FROM scraper.reads "
    "WHERE dataset_id = ids.dataset_id AND status = 'ok' "
    "ORDER BY finished_at DESC, read_id DESC LIMIT 1) r "
    "UNION ALL "
    f"SELECT 'any' AS which, r.* FROM unnest($1::text[]) AS ids(dataset_id) "
    f"CROSS JOIN LATERAL (SELECT {_READ_COLUMNS} FROM scraper.reads "
    "WHERE dataset_id = ids.dataset_id "
    "ORDER BY finished_at DESC, read_id DESC LIMIT 1) r"
)
_FIRST_OK_READ_SQL = (
    "SELECT ids.dataset_id, f.finished_at FROM unnest($1::text[]) AS ids(dataset_id) "
    "CROSS JOIN LATERAL (SELECT finished_at FROM scraper.reads "
    "WHERE dataset_id = ids.dataset_id AND status = 'ok' "
    "ORDER BY finished_at ASC, read_id ASC LIMIT 1) f"
)
_BAR_EDGE_SQL = (
    "SELECT ids.dataset_id, f.bar_open FROM unnest($1::text[]) AS ids(dataset_id) "
    "CROSS JOIN LATERAL (SELECT bar_open FROM scraper.bar_observations "
    "WHERE dataset_id = ids.dataset_id ORDER BY bar_open {order} LIMIT 1) f"
)
_REVISIONS_MANY_SQL = (
    "SELECT d.dataset_id, c.n FROM unnest($1::text[], $2::double precision[]) "
    "AS d(dataset_id, horizon) CROSS JOIN LATERAL ("
    "SELECT count(*) AS n FROM scraper.bar_observations "
    "WHERE dataset_id = d.dataset_id AND seq > 1 "
    "AND observed_at > bar_close + d.horizon * interval '1 second') c"
)


def _read_record(row: Mapping[str, Any]) -> ReadRecord:
    values = dict(row)
    meta = values.get("meta")
    values["meta"] = json.loads(meta) if isinstance(meta, str) else meta
    return ReadRecord(**values)


def _meta_text(meta: Mapping[str, Any] | None) -> str | None:
    return None if meta is None else json.dumps(dict(meta), sort_keys=True)


_BAR_COLUMNS = (
    "dataset_id, bar_close, open, high, low, close, volume, seq, content_hash, "
    "observed_at, read_id, first_observed_at, first_backfilled"
)
_BAR_NULLS = (
    "NULL::text AS dataset_id, NULL::timestamptz AS bar_close, "
    "NULL::numeric AS open, NULL::numeric AS high, NULL::numeric AS low, "
    "NULL::numeric AS close, NULL::numeric AS volume, NULL::integer AS seq, "
    "NULL::text AS content_hash, NULL::timestamptz AS observed_at, "
    "NULL::bigint AS read_id, NULL::timestamptz AS first_observed_at, "
    "NULL::boolean AS first_backfilled"
)


def compose_fetch_bars(
    dataset_id: str,
    *,
    mode: str,
    as_of: datetime | None,
    start: datetime | None,
    end: datetime | None,
    newest_first: bool,
    final_gap_seconds: float,
    limit: int,
) -> tuple[str, list[object]]:
    """Statement text and arguments for one ``fetch_bars`` call.

    No join, no per-bar subquery, no ``$n IS NULL OR`` predicates: the text is
    composed from fixed fragments for the bounds, the mode and the order.

    Finality is one sweep. A read finalises the bar opens in
    ``[covered_from, least(covered_to, finished_at - (horizon + interval))]``
    (``bar_close = bar_open + interval``); reads and bars are merged ordered by
    (key, reads first) and a bar is final when the running maximum of those
    upper bounds, over reads starting at or before it, reaches it.
    """
    args: list[object] = [dataset_id]

    def arg(value: object) -> str:
        args.append(value)
        return f"${len(args)}"

    bar_where = ""
    read_where = ""
    if start is not None:
        ph = arg(start)
        bar_where += f" AND bar_open >= {ph}::timestamptz"
        read_where += f" AND covered_to >= {ph}::timestamptz"
    if end is not None:
        ph = arg(end)
        bar_where += f" AND bar_open < {ph}::timestamptz"
        read_where += f" AND covered_from < {ph}::timestamptz"
    if as_of is not None:
        ph = arg(as_of)
        bar_where += f" AND observed_at <= {ph}::timestamptz"
        read_where += f" AND finished_at <= {ph}::timestamptz"
    gap = arg(float(final_gap_seconds))
    limit_ph = arg(limit)
    final_filter = " AND best >= k" if mode == "final" else ""
    direction = "DESC" if newest_first else "ASC"
    sql = f"""
WITH revs AS (
    SELECT dataset_id, bar_open, bar_close, open, high, low, close, volume, seq,
           content_hash, observed_at, read_id,
           first_value(observed_at) OVER w AS first_observed_at,
           first_value(backfilled) OVER w AS first_backfilled,
           lead(seq) OVER w AS next_seq
    FROM scraper.bar_observations
    WHERE dataset_id = $1{bar_where}
    WINDOW w AS (PARTITION BY bar_open ORDER BY seq)
), events AS (
    SELECT covered_from AS k, 0 AS kind,
           least(covered_to, finished_at - {gap}::double precision * interval '1 second')
               AS reach,
           {_BAR_NULLS}
    FROM scraper.reads
    WHERE dataset_id = $1 AND status = 'ok'{read_where}
    UNION ALL
    SELECT bar_open, 1, NULL::timestamptz, {_BAR_COLUMNS}
    FROM revs WHERE next_seq IS NULL
), swept AS (
    SELECT *, max(reach) OVER (
               ORDER BY k, kind ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS best
    FROM events
)
SELECT dataset_id, k AS bar_open, bar_close, open, high, low, close, volume, seq,
       content_hash, observed_at, read_id, first_backfilled AS backfilled,
       first_observed_at, seq - 1 AS revision_count,
       coalesce(best >= k, false) AS is_final
FROM swept
WHERE kind = 1{final_filter}
ORDER BY k {direction}
LIMIT {limit_ph}
"""
    return sql, args


# Start of the gap-free run ending at the latest stored bar, looking back no
# further than the newest bar at or before $3 (all history when $3 is NULL).
# One ordered scan with lag(): no self-join, so a wrong row estimate (stale or
# missing statistics) cannot turn it into a nested loop.
_CONTIGUOUS_FROM_SQL = """
WITH anchor AS (
    SELECT coalesce(
        (SELECT max(bar_open) FROM scraper.bar_observations
          WHERE dataset_id = $1 AND bar_open <= $3::timestamptz),
        (SELECT min(bar_open) FROM scraper.bar_observations WHERE dataset_id = $1)
    ) AS at
), b AS (
    SELECT bar_open, lag(bar_open) OVER (ORDER BY bar_open) AS prev
    FROM (
        SELECT DISTINCT o.bar_open FROM scraper.bar_observations o, anchor
        WHERE o.dataset_id = $1 AND o.bar_open >= anchor.at
    ) d
)
SELECT coalesce(
    (SELECT max(bar_open) FROM b
      WHERE prev IS NOT NULL
        AND extract(epoch FROM bar_open - prev) <> $2::double precision),
    (SELECT min(bar_open) FROM b)
)
"""


class PostgresScraperRepository:
    """asyncpg repository. The pool's role needs only SELECT and INSERT."""

    def __init__(self, pool: asyncpg.Pool, specs: Mapping[str, DatasetSpec]) -> None:
        self._pool = pool
        self._specs = dict(specs)

    async def commit_ok_read(
        self,
        spec: DatasetSpec,
        *,
        trigger: str,
        started_at: datetime,
        provider_time: datetime,
        bars: Sequence[Bar],
        gap_before: bool,
        holes: int = 0,
        bars_seen: int | None = None,
    ) -> CommitOutcome:
        _check_trigger(trigger)
        if not bars:
            raise ValueError("an ok read needs at least one bar")
        ordered = sorted(bars, key=lambda b: b.bar_open)
        seen = len(ordered) if bars_seen is None else bars_seen
        async with self._pool.acquire() as connection, connection.transaction():
            existing = await connection.fetch(
                "SELECT DISTINCT ON (bar_open) bar_open, seq, content_hash "
                "FROM scraper.bar_observations "
                "WHERE dataset_id = $1 AND bar_open BETWEEN $2 AND $3 "
                "ORDER BY bar_open, seq DESC",
                spec.id,
                ordered[0].bar_open,
                ordered[-1].bar_open,
            )
            latest = {
                row["bar_open"]: (row["seq"], row["content_hash"]) for row in existing
            }
            rows = plan_writes(spec, provider_time, ordered, latest)
            read = await connection.fetchrow(
                "INSERT INTO scraper.reads (dataset_id, trigger, status, started_at, "
                "provider_time, covered_from, covered_to, bars_seen, bars_written, "
                "gap_before, holes) VALUES ($1, $2, 'ok', $3, $4, $5, $6, $7, $8, $9, $10) "
                "RETURNING read_id, finished_at",
                spec.id,
                trigger,
                started_at,
                provider_time,
                ordered[0].bar_open,
                ordered[-1].bar_open,
                seen,
                len(rows),
                gap_before,
                holes,
            )
            read_id = read["read_id"]
            if rows:
                await connection.executemany(
                    "INSERT INTO scraper.bar_observations (dataset_id, bar_open, seq, "
                    "bar_close, open, high, low, close, volume, content_hash, read_id, "
                    "backfilled, observed_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)",
                    [
                        (
                            spec.id,
                            bar.bar_open,
                            seq,
                            bar.bar_close,
                            bar.open,
                            bar.high,
                            bar.low,
                            bar.close,
                            bar.volume,
                            bar.content_hash,
                            read_id,
                            backfilled,
                            read["finished_at"],
                        )
                        for bar, seq, backfilled in rows
                    ],
                )
        return CommitOutcome(read_id=read_id, bars_seen=seen, bars_written=len(rows))

    async def record_failed_read(
        self,
        dataset_id: str,
        *,
        trigger: str,
        started_at: datetime,
        error_code: str,
        error_detail: str,
        provider_time: datetime | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> int:
        _check_trigger(trigger)
        async with self._pool.acquire() as connection:
            return await connection.fetchval(
                "INSERT INTO scraper.reads (dataset_id, trigger, status, started_at, "
                "provider_time, error_code, error_detail, meta) "
                "VALUES ($1, $2, 'failed', $3, $4, $5, $6, $7::jsonb) RETURNING read_id",
                dataset_id,
                trigger,
                started_at,
                provider_time,
                error_code,
                error_detail[:_DETAIL_LIMIT],
                _meta_text(meta),
            )

    async def commit_ok_payload(
        self,
        dataset_id: str,
        *,
        trigger: str,
        started_at: datetime,
        accepted: AcceptedPayload,
        gap_before: bool,
        meta: Mapping[str, Any] | None = None,
    ) -> PayloadCommit:
        _check_trigger(trigger)
        # CPU-bound (up to max_payload_bytes): never on the event loop.
        blob = await asyncio.to_thread(encode_payload, accepted.text)
        async with self._pool.acquire() as connection, connection.transaction():
            row = await connection.fetchrow(
                "INSERT INTO scraper.reads (dataset_id, trigger, status, started_at, "
                "provider_time, covered_from, covered_to, bars_seen, bars_written, "
                "gap_before, holes, meta) "
                "VALUES ($1, $2, 'ok', $3, $4, $5, $6, $7, 1, $8, $9, $10::jsonb) "
                "RETURNING read_id, finished_at",
                dataset_id,
                trigger,
                started_at,
                accepted.provider_time,
                accepted.covered_from,
                accepted.covered_to,
                accepted.bars_seen,
                gap_before,
                accepted.holes,
                _meta_text(meta),
            )
            await connection.execute(
                "INSERT INTO scraper.payload_observations (read_id, dataset_id, "
                "observed_at, provider_time, format, raw_bytes, content_hash, payload) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                row["read_id"],
                dataset_id,
                row["finished_at"],
                accepted.provider_time,
                PAYLOAD_FORMAT,
                accepted.raw_bytes,
                accepted.content_hash,
                blob,
            )
        return PayloadCommit(read_id=row["read_id"], observed_at=row["finished_at"])

    async def latest_payload(
        self, dataset_id: str, *, at: datetime | None = None, blob: bool = True
    ) -> PayloadRecord | None:
        bound = "" if at is None else " AND observed_at <= $2"
        args = (dataset_id,) if at is None else (dataset_id, at)
        column = "payload" if blob else "''::bytea AS payload"
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT read_id, dataset_id, observed_at, provider_time, format, "
                f"raw_bytes, content_hash, {column} FROM scraper.payload_observations "
                f"WHERE dataset_id = $1{bound} "
                "ORDER BY observed_at DESC, read_id DESC LIMIT 1",
                *args,
            )
        return None if row is None else PayloadRecord(**dict(row))

    async def list_payloads(
        self,
        dataset_id: str,
        *,
        start: datetime | None,
        end: datetime,
        limit: int,
        end_before_id: int | None = None,
    ) -> list[PayloadMeta]:
        lower = "" if start is None else " AND observed_at >= $4"
        args: tuple[Any, ...] = (dataset_id, end, limit)
        args += () if start is None else (start,)
        upper = "observed_at < $2"
        if end_before_id is not None:
            # Keyset: (observed_at, read_id) strictly before the cursor.
            args += (end_before_id,)
            upper = f"(observed_at, read_id) < ($2, ${len(args)})"
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT read_id, observed_at, provider_time, content_hash, raw_bytes "
                "FROM scraper.payload_observations "
                f"WHERE dataset_id = $1 AND {upper}{lower} "
                "ORDER BY observed_at DESC, read_id DESC LIMIT $3",
                *args,
            )
        return [PayloadMeta(**dict(row)) for row in rows]

    async def payload_by_id(
        self, dataset_id: str, read_id: int, *, blob: bool = True
    ) -> PayloadRecord | None:
        column = "payload" if blob else "''::bytea AS payload"
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT read_id, dataset_id, observed_at, provider_time, format, "
                f"raw_bytes, content_hash, {column} FROM scraper.payload_observations "
                "WHERE read_id = $1 AND dataset_id = $2",
                read_id,
                dataset_id,
            )
        return None if row is None else PayloadRecord(**dict(row))

    async def server_time(self) -> datetime:
        async with self._pool.acquire() as connection:
            return await connection.fetchval("SELECT clock_timestamp()")

    async def fetch_bars(
        self,
        dataset_id: str,
        *,
        mode: Literal["final", "as_of"] = "final",
        as_of: datetime | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        newest_first: bool = False,
        limit: int,
    ) -> list[BarRecord]:
        _check_query(mode, as_of, limit)
        spec = self._specs[dataset_id]
        sql, args = compose_fetch_bars(
            dataset_id,
            mode=mode,
            as_of=as_of,
            start=start,
            end=end,
            newest_first=newest_first,
            final_gap_seconds=spec.finality_horizon_seconds + spec.interval_seconds,
            limit=limit,
        )
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(sql, *args)
        return [BarRecord(**dict(row)) for row in rows]

    async def dataset_head(
        self, dataset_id: str, *, at: datetime | None = None
    ) -> DatasetHead:
        latest_filter = "" if at is None else " AND finished_at <= $2"
        latest_args = (dataset_id,) if at is None else (dataset_id, at)
        async with self._pool.acquire() as connection:
            first_read = await connection.fetchval(
                "SELECT finished_at FROM scraper.reads "
                "WHERE dataset_id = $1 AND status = 'ok' "
                "ORDER BY finished_at ASC, read_id ASC LIMIT 1",
                dataset_id,
            )
            latest = await connection.fetchrow(
                f"SELECT {_READ_COLUMNS} FROM scraper.reads "
                f"WHERE dataset_id = $1 AND status = 'ok'{latest_filter} "
                "ORDER BY finished_at DESC, read_id DESC LIMIT 1",
                *latest_args,
            )
            first_bar = await connection.fetchval(
                "SELECT bar_open FROM scraper.bar_observations "
                "WHERE dataset_id = $1 ORDER BY bar_open ASC LIMIT 1",
                dataset_id,
            )
            last_bar = await connection.fetchval(
                "SELECT bar_open FROM scraper.bar_observations "
                "WHERE dataset_id = $1 ORDER BY bar_open DESC LIMIT 1",
                dataset_id,
            )
        return DatasetHead(
            first_ok_read_finished_at=first_read,
            latest_ok_read=None if latest is None else _read_record(latest),
            first_bar_open=first_bar,
            last_bar_open=last_bar,
        )

    async def revisions_after_horizon(self, dataset_id: str) -> int:
        horizon = float(self._specs[dataset_id].finality_horizon_seconds)
        async with self._pool.acquire() as connection:
            return await connection.fetchval(
                "SELECT count(*) FROM scraper.bar_observations "
                "WHERE dataset_id = $1 AND seq > 1 "
                "AND observed_at > bar_close + $2::double precision * interval '1 second'",
                dataset_id,
                horizon,
            )

    async def latest_ok_read(self, dataset_id: str) -> ReadRecord | None:
        return await self._latest(dataset_id, ok_only=True)

    async def latest_read(self, dataset_id: str) -> ReadRecord | None:
        return await self._latest(dataset_id, ok_only=False)

    async def _latest(self, dataset_id: str, *, ok_only: bool) -> ReadRecord | None:
        status_filter = "AND status = 'ok' " if ok_only else ""
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                f"SELECT {_READ_COLUMNS} FROM scraper.reads "
                f"WHERE dataset_id = $1 {status_filter}"
                "ORDER BY finished_at DESC, read_id DESC LIMIT 1",
                dataset_id,
            )
        return None if row is None else _read_record(row)

    async def last_bar_open(self, dataset_id: str) -> datetime | None:
        async with self._pool.acquire() as connection:
            return await connection.fetchval(
                "SELECT max(bar_open) FROM scraper.bar_observations WHERE dataset_id = $1",
                dataset_id,
            )

    async def first_bar_open(self, dataset_id: str) -> datetime | None:
        async with self._pool.acquire() as connection:
            return await connection.fetchval(
                "SELECT min(bar_open) FROM scraper.bar_observations WHERE dataset_id = $1",
                dataset_id,
            )

    async def contiguous_from(
        self, dataset_id: str, *, not_before: datetime | None = None
    ) -> datetime | None:
        step = float(self._specs[dataset_id].interval_seconds)
        async with self._pool.acquire() as connection:
            return await connection.fetchval(
                _CONTIGUOUS_FROM_SQL, dataset_id, step, not_before
            )

    async def latest_reads(
        self, dataset_ids: Sequence[str]
    ) -> dict[str, tuple[ReadRecord | None, ReadRecord | None]]:
        ids = list(dataset_ids)
        if not ids:
            return {}
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(_LATEST_READS_SQL, ids)
        ok: dict[str, ReadRecord] = {}
        anyone: dict[str, ReadRecord] = {}
        for row in rows:
            values = dict(row)
            which = values.pop("which")
            (ok if which == "ok" else anyone)[values["dataset_id"]] = _read_record(
                values
            )
        return {i: (ok.get(i), anyone.get(i)) for i in ids}

    async def first_bar_opens(
        self, dataset_ids: Sequence[str]
    ) -> dict[str, datetime | None]:
        ids = list(dataset_ids)
        if not ids:
            return {}
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(_BAR_EDGE_SQL.format(order="ASC"), ids)
        found = {r["dataset_id"]: r["bar_open"] for r in rows}
        return {i: found.get(i) for i in ids}

    async def dataset_heads(
        self, dataset_ids: Sequence[str], *, bar_ids: Sequence[str] | None = None
    ) -> dict[str, DatasetHead]:
        ids = list(dataset_ids)
        if not ids:
            return {}
        bars = ids if bar_ids is None else list(bar_ids)
        async with self._pool.acquire() as connection:
            first_reads = await connection.fetch(_FIRST_OK_READ_SQL, ids)
            latest = await connection.fetch(_LATEST_READS_SQL, ids)
            first_bars = last_bars = []
            if bars:
                first_bars = await connection.fetch(
                    _BAR_EDGE_SQL.format(order="ASC"), bars
                )
                last_bars = await connection.fetch(
                    _BAR_EDGE_SQL.format(order="DESC"), bars
                )
        first_read = {r["dataset_id"]: r["finished_at"] for r in first_reads}
        latest_ok = {
            r["dataset_id"]: _read_record(
                {k: v for k, v in dict(r).items() if k != "which"}
            )
            for r in latest
            if r["which"] == "ok"
        }
        first_bar = {r["dataset_id"]: r["bar_open"] for r in first_bars}
        last_bar = {r["dataset_id"]: r["bar_open"] for r in last_bars}
        return {
            i: DatasetHead(
                first_ok_read_finished_at=first_read.get(i),
                latest_ok_read=latest_ok.get(i),
                first_bar_open=first_bar.get(i),
                last_bar_open=last_bar.get(i),
            )
            for i in ids
        }

    async def revisions_after_horizon_many(
        self, dataset_ids: Sequence[str]
    ) -> dict[str, int]:
        ids = list(dataset_ids)
        if not ids:
            return {}
        horizons = [float(self._specs[i].finality_horizon_seconds) for i in ids]
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(_REVISIONS_MANY_SQL, ids, horizons)
        return {r["dataset_id"]: r["n"] for r in rows}


# Index-ordered selections bounded by LIMIT, then deletes by primary key: no
# self-join, nothing that depends on planner statistics. Each batch runs in its
# own transaction.
_PURGE_KEEP_SQL = (
    "SELECT read_id FROM scraper.reads WHERE dataset_id = $1 AND status = 'ok' "
    "ORDER BY finished_at DESC, read_id DESC LIMIT 1"
)
PURGE_PAYLOAD_SELECT_SQL = (
    "SELECT read_id FROM scraper.payload_observations "
    "WHERE dataset_id = $1 AND observed_at < $2 AND read_id <> $3 "
    "ORDER BY observed_at LIMIT $4"
)
PURGE_PAYLOAD_DELETE_SQL = (
    "DELETE FROM scraper.payload_observations WHERE read_id = ANY($1::bigint[])"
)
# Whole bars only: the batch boundary is a bar_open and every row of every bar
# up to it goes, so a bar is never left half-purged. The newest bar of the
# dataset is always kept (the collector's anchor), like the newest payload read.
PURGE_BAR_SELECT_SQL = (
    "SELECT bar_open FROM scraper.bar_observations "
    "WHERE dataset_id = $1 AND bar_open < $2 AND bar_open < ("
    "SELECT max(bar_open) FROM scraper.bar_observations WHERE dataset_id = $1) "
    "ORDER BY bar_open, seq LIMIT $3"
)
PURGE_BAR_DELETE_SQL = (
    "DELETE FROM scraper.bar_observations WHERE dataset_id = $1 AND bar_open <= $2"
)
_PURGE_READ_SELECT = (
    "SELECT r.read_id FROM scraper.reads r "
    "WHERE r.dataset_id = $1 AND r.finished_at < $2 AND r.read_id <> $3 "
    "AND NOT EXISTS (SELECT 1 FROM {table} x WHERE x.read_id = r.read_id) "
    "ORDER BY r.finished_at LIMIT $4"
)
PURGE_READ_SELECT_SQL = {
    PURGE_COINGLASS: _PURGE_READ_SELECT.format(table="scraper.payload_observations"),
    PURGE_TRADINGVIEW: _PURGE_READ_SELECT.format(table="scraper.bar_observations"),
}
PURGE_READ_DELETE_SQL = "DELETE FROM scraper.reads WHERE read_id = ANY($1::bigint[])"
_PURGE_CUTOFF_SQL = "SELECT now() - make_interval(days => $1)"


def _deleted_count(tag: str) -> int:
    return int(tag.rsplit(" ", 1)[-1])


class PostgresPurgeRepository:
    """Deletes expired rows. Its pool must use the ``scraper_purge`` role."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def purge_dataset(
        self, dataset_id: str, *, kind: str, days: int, batch_rows: int
    ) -> PurgeResult:
        _check_purge(kind, days, batch_rows)
        async with self._pool.acquire() as connection:
            cutoff = await connection.fetchval(_PURGE_CUTOFF_SQL, days)
        evidence_table = (
            "bar_observations" if kind == PURGE_TRADINGVIEW else "payload_observations"
        )
        evidence = 0
        batches = 0
        while True:
            removed = await self._evidence_batch(dataset_id, kind, cutoff, batch_rows)
            if removed:
                batches += 1
            evidence += removed
            if removed < batch_rows:
                break
        reads = 0
        while True:
            removed = await self._read_batch(dataset_id, kind, cutoff, batch_rows)
            if removed:
                batches += 1
            reads += removed
            if removed < batch_rows:
                break
        return PurgeResult({evidence_table: evidence, "reads": reads}, batches)

    async def _evidence_batch(
        self, dataset_id: str, kind: str, cutoff: datetime, batch_rows: int
    ) -> int:
        async with self._pool.acquire() as connection, connection.transaction():
            if kind == PURGE_TRADINGVIEW:
                keys = await connection.fetch(
                    PURGE_BAR_SELECT_SQL, dataset_id, cutoff, batch_rows
                )
                if not keys:
                    return 0
                tag = await connection.execute(
                    PURGE_BAR_DELETE_SQL, dataset_id, keys[-1]["bar_open"]
                )
                return _deleted_count(tag)
            keep = await connection.fetchval(_PURGE_KEEP_SQL, dataset_id)
            ids = await connection.fetch(
                PURGE_PAYLOAD_SELECT_SQL,
                dataset_id,
                cutoff,
                -1 if keep is None else keep,
                batch_rows,
            )
            if not ids:
                return 0
            tag = await connection.execute(
                PURGE_PAYLOAD_DELETE_SQL, [row["read_id"] for row in ids]
            )
            return _deleted_count(tag)

    async def _read_batch(
        self, dataset_id: str, kind: str, cutoff: datetime, batch_rows: int
    ) -> int:
        async with self._pool.acquire() as connection, connection.transaction():
            keep = await connection.fetchval(_PURGE_KEEP_SQL, dataset_id)
            ids = await connection.fetch(
                PURGE_READ_SELECT_SQL[kind],
                dataset_id,
                cutoff,
                -1 if keep is None else keep,
                batch_rows,
            )
            if not ids:
                return 0
            tag = await connection.execute(
                PURGE_READ_DELETE_SQL, [row["read_id"] for row in ids]
            )
            return _deleted_count(tag)


# ---------------------------------------------------------------------------
# In-memory twin
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Observation:
    bar: Bar
    seq: int
    observed_at: datetime
    read_id: int
    backfilled: bool


class InMemoryScraperRepository:
    """Same semantics as the SQL repository, for tests and offline runs."""

    def __init__(
        self,
        specs: Mapping[str, DatasetSpec],
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._specs = dict(specs)
        self._clock = clock
        self._reads: list[ReadRecord] = []
        self._payloads: list[PayloadRecord] = []
        self._observations: dict[str, dict[datetime, list[_Observation]]] = {}
        self._last_read_id = 0

    def _take_read_id(self) -> int:
        # Read ids are never reused, also after the purge removed rows.
        self._last_read_id += 1
        return self._last_read_id

    @property
    def reads(self) -> list[ReadRecord]:
        return list(self._reads)

    def observation_count(self, dataset_id: str) -> int:
        return sum(
            len(rows) for rows in self._observations.get(dataset_id, {}).values()
        )

    async def commit_ok_read(
        self,
        spec: DatasetSpec,
        *,
        trigger: str,
        started_at: datetime,
        provider_time: datetime,
        bars: Sequence[Bar],
        gap_before: bool,
        holes: int = 0,
        bars_seen: int | None = None,
    ) -> CommitOutcome:
        _check_trigger(trigger)
        if not bars:
            raise ValueError("an ok read needs at least one bar")
        ordered = sorted(bars, key=lambda b: b.bar_open)
        seen = len(ordered) if bars_seen is None else bars_seen
        stored = self._observations.setdefault(spec.id, {})
        latest = {
            bar_open: (rows[-1].seq, rows[-1].bar.content_hash)
            for bar_open, rows in stored.items()
        }
        rows = plan_writes(spec, provider_time, ordered, latest)
        now = self._clock()
        read_id = self._take_read_id()
        self._reads.append(
            ReadRecord(
                read_id=read_id,
                dataset_id=spec.id,
                trigger=trigger,
                status="ok",
                started_at=started_at,
                finished_at=now,
                provider_time=provider_time,
                covered_from=ordered[0].bar_open,
                covered_to=ordered[-1].bar_open,
                bars_seen=seen,
                bars_written=len(rows),
                gap_before=gap_before,
                holes=holes,
                error_code=None,
                error_detail=None,
            )
        )
        for bar, seq, backfilled in rows:
            stored.setdefault(bar.bar_open, []).append(
                _Observation(bar, seq, now, read_id, backfilled)
            )
        return CommitOutcome(read_id=read_id, bars_seen=seen, bars_written=len(rows))

    async def record_failed_read(
        self,
        dataset_id: str,
        *,
        trigger: str,
        started_at: datetime,
        error_code: str,
        error_detail: str,
        provider_time: datetime | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> int:
        _check_trigger(trigger)
        read_id = self._take_read_id()
        self._reads.append(
            ReadRecord(
                read_id=read_id,
                dataset_id=dataset_id,
                trigger=trigger,
                status="failed",
                started_at=started_at,
                finished_at=self._clock(),
                provider_time=provider_time,
                covered_from=None,
                covered_to=None,
                bars_seen=0,
                bars_written=0,
                gap_before=False,
                holes=0,
                error_code=error_code,
                error_detail=error_detail[:_DETAIL_LIMIT],
                meta=None if meta is None else dict(meta),
            )
        )
        return read_id

    @property
    def payloads(self) -> list[PayloadRecord]:
        return list(self._payloads)

    async def commit_ok_payload(
        self,
        dataset_id: str,
        *,
        trigger: str,
        started_at: datetime,
        accepted: AcceptedPayload,
        gap_before: bool,
        meta: Mapping[str, Any] | None = None,
    ) -> PayloadCommit:
        _check_trigger(trigger)
        now = self._clock()
        read_id = self._take_read_id()
        self._reads.append(
            ReadRecord(
                read_id=read_id,
                dataset_id=dataset_id,
                trigger=trigger,
                status="ok",
                started_at=started_at,
                finished_at=now,
                provider_time=accepted.provider_time,
                covered_from=accepted.covered_from,
                covered_to=accepted.covered_to,
                bars_seen=accepted.bars_seen,
                bars_written=1,
                gap_before=gap_before,
                holes=accepted.holes,
                error_code=None,
                error_detail=None,
                meta=None if meta is None else dict(meta),
            )
        )
        self._payloads.append(
            PayloadRecord(
                read_id=read_id,
                dataset_id=dataset_id,
                observed_at=now,
                provider_time=accepted.provider_time,
                format=PAYLOAD_FORMAT,
                raw_bytes=accepted.raw_bytes,
                content_hash=accepted.content_hash,
                payload=encode_payload(accepted.text),
            )
        )
        return PayloadCommit(read_id=read_id, observed_at=now)

    async def purge_dataset(
        self, dataset_id: str, *, kind: str, days: int, batch_rows: int
    ) -> PurgeResult:
        _check_purge(kind, days, batch_rows)
        cutoff = self._clock() - timedelta(days=days)
        keep = max(
            (r for r in self._reads if r.dataset_id == dataset_id and r.status == "ok"),
            key=lambda r: (r.finished_at, r.read_id),
            default=None,
        )
        keep_id = None if keep is None else keep.read_id
        batches = 0
        if kind == PURGE_TRADINGVIEW:
            evidence_table = "bar_observations"
            stored = self._observations.setdefault(dataset_id, {})
            newest = max(stored, default=None)
            keys = sorted(
                (bar_open, row.seq)
                for bar_open, rows in stored.items()
                if bar_open < cutoff and bar_open != newest
                for row in rows
            )
            evidence = 0
            # Batches of batch_rows rows, extended to the end of the last bar.
            while keys:
                boundary = keys[min(batch_rows, len(keys)) - 1][0]
                taken = [k for k in keys if k[0] <= boundary]
                keys = keys[len(taken) :]
                evidence += len(taken)
                batches += 1
                for bar_open in {k[0] for k in taken}:
                    del stored[bar_open]
            referenced = {row.read_id for rows in stored.values() for row in rows}
        else:
            evidence_table = "payload_observations"
            doomed = sorted(
                (
                    p
                    for p in self._payloads
                    if p.dataset_id == dataset_id
                    and p.observed_at < cutoff
                    and p.read_id != keep_id
                ),
                key=lambda p: p.observed_at,
            )
            evidence = len(doomed)
            batches += -(-len(doomed) // batch_rows)
            gone = {p.read_id for p in doomed}
            self._payloads = [p for p in self._payloads if p.read_id not in gone]
            referenced = {p.read_id for p in self._payloads}
        old_reads = sorted(
            (
                r
                for r in self._reads
                if r.dataset_id == dataset_id
                and r.finished_at < cutoff
                and r.read_id != keep_id
                and r.read_id not in referenced
            ),
            key=lambda r: r.finished_at,
        )
        batches += -(-len(old_reads) // batch_rows)
        gone_reads = {r.read_id for r in old_reads}
        self._reads = [r for r in self._reads if r.read_id not in gone_reads]
        return PurgeResult({evidence_table: evidence, "reads": len(old_reads)}, batches)

    async def latest_payload(
        self, dataset_id: str, *, at: datetime | None = None, blob: bool = True
    ) -> PayloadRecord | None:
        eligible = [
            p
            for p in self._payloads
            if p.dataset_id == dataset_id and (at is None or p.observed_at <= at)
        ]
        best = max(eligible, key=lambda p: (p.observed_at, p.read_id), default=None)
        if best is None or blob:
            return best
        return replace(best, payload=b"")

    async def list_payloads(
        self,
        dataset_id: str,
        *,
        start: datetime | None,
        end: datetime,
        limit: int,
        end_before_id: int | None = None,
    ) -> list[PayloadMeta]:
        rows = sorted(
            (
                p
                for p in self._payloads
                if p.dataset_id == dataset_id
                and (
                    p.observed_at < end
                    if end_before_id is None
                    else (p.observed_at, p.read_id) < (end, end_before_id)
                )
                and (start is None or p.observed_at >= start)
            ),
            key=lambda p: (p.observed_at, p.read_id),
            reverse=True,
        )
        return [
            PayloadMeta(
                p.read_id, p.observed_at, p.provider_time, p.content_hash, p.raw_bytes
            )
            for p in rows[:limit]
        ]

    async def payload_by_id(
        self, dataset_id: str, read_id: int, *, blob: bool = True
    ) -> PayloadRecord | None:
        found = next(
            (
                p
                for p in self._payloads
                if p.read_id == read_id and p.dataset_id == dataset_id
            ),
            None,
        )
        if found is None or blob:
            return found
        return replace(found, payload=b"")

    async def server_time(self) -> datetime:
        return self._clock()

    async def fetch_bars(
        self,
        dataset_id: str,
        *,
        mode: Literal["final", "as_of"] = "final",
        as_of: datetime | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        newest_first: bool = False,
        limit: int,
    ) -> list[BarRecord]:
        _check_query(mode, as_of, limit)
        spec = self._specs[dataset_id]
        horizon = timedelta(seconds=spec.finality_horizon_seconds)
        covering = [
            r
            for r in self._reads
            if r.dataset_id == dataset_id
            and r.status == "ok"
            and (as_of is None or r.finished_at <= as_of)
        ]
        out: list[BarRecord] = []
        for bar_open in sorted(self._observations.get(dataset_id, {})):
            if start is not None and bar_open < start:
                continue
            if end is not None and bar_open >= end:
                continue
            rows = self._observations[dataset_id][bar_open]
            visible = [row for row in rows if as_of is None or row.observed_at <= as_of]
            if not visible:
                continue
            chosen = visible[-1]
            is_final = any(
                r.covered_from <= bar_open <= r.covered_to
                and r.finished_at >= chosen.bar.bar_close + horizon
                for r in covering
            )
            if mode == "final" and not is_final:
                continue
            bar = chosen.bar
            out.append(
                BarRecord(
                    dataset_id=dataset_id,
                    bar_open=bar.bar_open,
                    bar_close=bar.bar_close,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    seq=chosen.seq,
                    content_hash=bar.content_hash,
                    observed_at=chosen.observed_at,
                    read_id=chosen.read_id,
                    backfilled=rows[0].backfilled,
                    first_observed_at=rows[0].observed_at,
                    revision_count=chosen.seq - 1,
                    is_final=is_final,
                )
            )
        if newest_first:
            out.reverse()
        return out[:limit]

    async def dataset_head(
        self, dataset_id: str, *, at: datetime | None = None
    ) -> DatasetHead:
        ok = [r for r in self._reads if r.dataset_id == dataset_id and r.status == "ok"]
        eligible = [r for r in ok if at is None or r.finished_at <= at]
        opens = self._observations.get(dataset_id)
        return DatasetHead(
            first_ok_read_finished_at=min((r.finished_at for r in ok), default=None),
            latest_ok_read=max(
                eligible, key=lambda r: (r.finished_at, r.read_id), default=None
            ),
            first_bar_open=min(opens) if opens else None,
            last_bar_open=max(opens) if opens else None,
        )

    async def revisions_after_horizon(self, dataset_id: str) -> int:
        horizon = timedelta(seconds=self._specs[dataset_id].finality_horizon_seconds)
        return sum(
            1
            for rows in self._observations.get(dataset_id, {}).values()
            for row in rows
            if row.seq > 1 and row.observed_at > row.bar.bar_close + horizon
        )

    async def latest_ok_read(self, dataset_id: str) -> ReadRecord | None:
        return self._latest(dataset_id, ok_only=True)

    async def latest_read(self, dataset_id: str) -> ReadRecord | None:
        return self._latest(dataset_id, ok_only=False)

    def _latest(self, dataset_id: str, *, ok_only: bool) -> ReadRecord | None:
        candidates = [
            r
            for r in self._reads
            if r.dataset_id == dataset_id and (not ok_only or r.status == "ok")
        ]
        return max(candidates, key=lambda r: (r.finished_at, r.read_id), default=None)

    async def last_bar_open(self, dataset_id: str) -> datetime | None:
        opens = self._observations.get(dataset_id)
        return max(opens) if opens else None

    async def first_bar_open(self, dataset_id: str) -> datetime | None:
        opens = self._observations.get(dataset_id)
        return min(opens) if opens else None

    async def contiguous_from(
        self, dataset_id: str, *, not_before: datetime | None = None
    ) -> datetime | None:
        opens = sorted(self._observations.get(dataset_id, {}))
        if not opens:
            return None
        if not_before is not None:
            at_or_before = [o for o in opens if o <= not_before]
            if at_or_before:
                opens = [o for o in opens if o >= at_or_before[-1]]
        step = timedelta(seconds=self._specs[dataset_id].interval_seconds)
        start = opens[-1]
        for previous in reversed(opens[:-1]):
            if previous + step != start:
                break
            start = previous
        return start

    async def latest_reads(
        self, dataset_ids: Sequence[str]
    ) -> dict[str, tuple[ReadRecord | None, ReadRecord | None]]:
        return {
            i: (await self.latest_ok_read(i), await self.latest_read(i))
            for i in dataset_ids
        }

    async def first_bar_opens(
        self, dataset_ids: Sequence[str]
    ) -> dict[str, datetime | None]:
        return {i: await self.first_bar_open(i) for i in dataset_ids}

    async def dataset_heads(
        self, dataset_ids: Sequence[str], *, bar_ids: Sequence[str] | None = None
    ) -> dict[str, DatasetHead]:
        with_bars = set(dataset_ids if bar_ids is None else bar_ids)
        heads: dict[str, DatasetHead] = {}
        for i in dataset_ids:
            head = await self.dataset_head(i)
            if i not in with_bars:
                head = replace(head, first_bar_open=None, last_bar_open=None)
            heads[i] = head
        return heads

    async def revisions_after_horizon_many(
        self, dataset_ids: Sequence[str]
    ) -> dict[str, int]:
        return {i: await self.revisions_after_horizon(i) for i in dataset_ids}


__all__ = [
    "TRIGGERS",
    "BarRecord",
    "CommitOutcome",
    "DatasetHead",
    "InMemoryScraperRepository",
    "PayloadCommit",
    "PayloadMeta",
    "PayloadRecord",
    "PostgresPurgeRepository",
    "PostgresScraperRepository",
    "PurgeRepository",
    "PurgeResult",
    "ReadRecord",
    "ScraperRepository",
    "compose_fetch_bars",
    "plan_writes",
]
