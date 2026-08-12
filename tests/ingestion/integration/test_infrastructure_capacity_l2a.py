"""Real local Timescale and Valkey capacity certification for ingestion.

This module is intentionally opt-in.  It uses one unique run prefix and one
cleanup boundary so that the certification can exercise the real A-K storage
and publication boundaries without touching production identities.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import tracemalloc
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import asyncpg
import pytest

from apps.ingestion_app.domain.candle import CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.publication.outbox import build_candle_committed_event
from apps.ingestion_app.publication.publisher import OutboxPublisher
from apps.ingestion_app.publication.stream_keys import canonical_lane_stream_key
from apps.ingestion_app.services.candle_ingestion import CandleIngestionService
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.settings import (
    IngestionSettings,
    load_ingestion_settings,
)
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.repository import (
    CandleCommitStatus,
    CandleRepository,
)
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.db.pool_manager import DBPoolManager

if os.getenv("INGESTION_RUN_L2A_CERTIFICATION") != "1":
    pytest.skip(
        "set INGESTION_RUN_L2A_CERTIFICATION=1 to run L2A certification",
        allow_module_level=True,
    )


BASE_BOUNDARY = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
FIFTEEN_MINUTE_BOUNDARY = BASE_BOUNDARY + timedelta(minutes=15)
ONE_HOUR_BOUNDARY = BASE_BOUNDARY + timedelta(hours=1)
PUBLISHED_AT = datetime(2026, 8, 10, 1, 0, tzinfo=UTC)
ALL_HTF_TARGETS = ("15m", "30m", "1h", "4h", "6h", "12h", "1d", "1w")
LANE_COUNT = 500
CAPACITY_DEADLINE_SECONDS = 60.0


def _emit(label: str, value: object) -> None:
    print(f"L2A {label}: {value}", flush=True)


def _duration_seconds(started: float) -> float:
    return round(time.perf_counter() - started, 3)


def _instrument_id(prefix: str, stage: str, index: int) -> str:
    return f"{prefix}_{stage}_S{index:04d}-USDT-PERP"


def _lane(
    prefix: str,
    stage: str,
    index: int,
    timeframe: str = "1m",
) -> MarketLane:
    return MarketLane(
        venue="binance",
        instrument_id=_instrument_id(prefix, stage, index),
        timeframe=timeframe,
    )


def _provider_values(ordinal: int) -> tuple[Decimal, ...]:
    base = Decimal(100) + Decimal(ordinal)
    return (
        base,
        base + Decimal(2),
        base - Decimal(1),
        base + Decimal(1),
        Decimal(10) + Decimal(ordinal % 100),
        Decimal(4) + Decimal(ordinal % 50),
    )


def _provider_candle(
    lane: MarketLane,
    open_time: datetime,
    *,
    ordinal: int,
    duration: timedelta = timedelta(minutes=1),
) -> CanonicalCandle:
    open_price, high, low, close, volume, taker_buy_base = _provider_values(ordinal)
    return CanonicalCandle(
        lane=lane,
        open_time=open_time,
        close_time=open_time + duration,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        taker_buy_base=taker_buy_base,
        source_type="provider",
        source_provider="binance_native",
        source_timeframe=None,
    )


def _derived_candle(
    lane: MarketLane,
    open_time: datetime,
    *,
    duration: timedelta,
    ordinal: int,
) -> CanonicalCandle:
    open_price, high, low, close, volume, taker_buy_base = _provider_values(ordinal)
    return CanonicalCandle(
        lane=lane,
        open_time=open_time,
        close_time=open_time + duration,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        taker_buy_base=taker_buy_base,
        source_type="derived",
        source_provider=None,
        source_timeframe="1m",
    )


def _stream_key_for_lane(lane: MarketLane) -> str:
    return canonical_lane_stream_key(
        build_candle_committed_event(_provider_candle(lane, BASE_BOUNDARY, ordinal=0))
    )


def _candle_row(candle: CanonicalCandle) -> tuple[object, ...]:
    return (
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


def _utc_payload_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


_EXPECTED_EVENT_PAYLOAD_FIELDS = {
    "venue",
    "instrument_id",
    "timeframe",
    "open_time",
    "close_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "taker_buy_base",
    "source_type",
    "source_provider",
    "source_timeframe",
}


def _base_rows(
    lanes: tuple[MarketLane, ...],
    *,
    start: datetime,
    count: int,
) -> Iterable[tuple[object, ...]]:
    for lane_index, lane in enumerate(lanes):
        for offset in range(count):
            candle = _provider_candle(
                lane,
                start + timedelta(minutes=offset),
                ordinal=lane_index * 100_000 + offset,
            )
            yield _candle_row(candle)


_CANDLE_COLUMNS = (
    "venue",
    "instrument_id",
    "timeframe",
    "open_time",
    "close_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "taker_buy_base",
    "source_type",
    "source_provider",
    "source_timeframe",
)


async def _copy_candle_records(
    pool: asyncpg.Pool,
    *,
    schema_name: str,
    table_name: str,
    records: Iterable[tuple[object, ...]],
    count: int,
) -> int:
    async with pool.acquire() as connection:
        await connection.copy_records_to_table(
            table_name,
            schema_name=schema_name,
            records=records,
            columns=_CANDLE_COLUMNS,
        )
    return count


async def _copy_base_rows(
    pool: asyncpg.Pool,
    lanes: tuple[MarketLane, ...],
    *,
    start: datetime,
    count: int,
    schema_name: str = "ingestion",
    table_name: str = "candles",
) -> int:
    return await _copy_candle_records(
        pool,
        schema_name=schema_name,
        table_name=table_name,
        records=_base_rows(lanes, start=start, count=count),
        count=len(lanes) * count,
    )


def _representative_lanes(lane_count: int) -> tuple[MarketLane, ...]:
    return tuple(
        MarketLane(
            venue="binance",
            instrument_id=f"S{index:04d}-USDT-PERP",
            timeframe="1m",
        )
        for index in range(lane_count)
    )


def _representative_weekly_counts(
    settings: IngestionSettings,
) -> dict[str, int]:
    week_seconds = 7 * 24 * 60 * 60
    ordered_timeframes = sorted(
        settings.timeframes.items(),
        key=lambda item: (item[1].duration_seconds, item[0]),
    )
    counts: dict[str, int] = {}
    for timeframe, timeframe_settings in ordered_timeframes:
        duration_seconds = timeframe_settings.duration_seconds
        if week_seconds % duration_seconds:
            raise ValueError(
                f"{timeframe} does not divide a complete representative week"
            )
        counts[timeframe] = week_seconds // duration_seconds
    return counts


def _representative_population_counts(
    settings: IngestionSettings,
    *,
    lane_count: int,
) -> dict[str, int]:
    per_lane = _representative_weekly_counts(settings)
    return {timeframe: count * lane_count for timeframe, count in per_lane.items()}


def _representative_candles(
    settings: IngestionSettings,
    *,
    lanes: tuple[MarketLane, ...],
) -> Iterable[CanonicalCandle]:
    weekly_counts = _representative_weekly_counts(settings)
    start = BASE_BOUNDARY - timedelta(weeks=1)
    ordered_timeframes = tuple(weekly_counts)
    for lane_index, base_lane in enumerate(lanes):
        for timeframe_index, timeframe in enumerate(ordered_timeframes):
            duration_seconds = settings.timeframes[timeframe].duration_seconds
            duration = timedelta(seconds=duration_seconds)
            lane = (
                base_lane
                if timeframe == settings.base_timeframe
                else MarketLane(
                    venue=base_lane.venue,
                    instrument_id=base_lane.instrument_id,
                    timeframe=timeframe,
                )
            )
            for offset in range(weekly_counts[timeframe]):
                open_time = start + timedelta(seconds=duration_seconds * offset)
                ordinal = lane_index * 1_000_000 + timeframe_index * 100_000 + offset
                if timeframe == settings.base_timeframe:
                    yield _provider_candle(
                        lane,
                        open_time,
                        ordinal=ordinal,
                        duration=duration,
                    )
                else:
                    yield _derived_candle(
                        lane,
                        open_time,
                        duration=duration,
                        ordinal=ordinal,
                    )


def _representative_candle_rows(
    settings: IngestionSettings,
    *,
    lanes: tuple[MarketLane, ...],
) -> Iterable[tuple[object, ...]]:
    for candle in _representative_candles(settings, lanes=lanes):
        yield _candle_row(candle)


def _representative_event_rows(
    settings: IngestionSettings,
    *,
    lanes: tuple[MarketLane, ...],
) -> Iterable[tuple[object, ...]]:
    for candle in _representative_candles(settings, lanes=lanes):
        event = build_candle_committed_event(candle)
        yield (
            event.event_id,
            event.event_type,
            event.schema_version,
            event.producer,
            event.occurred_at,
            event.payload_json,
        )


async def _copy_outbox_rows(
    pool: asyncpg.Pool,
    *,
    schema_name: str,
    records: Iterable[tuple[object, ...]],
    count: int,
) -> int:
    async with pool.acquire() as connection:
        await connection.copy_records_to_table(
            "outbox",
            schema_name=schema_name,
            records=records,
            columns=(
                "event_id",
                "event_type",
                "schema_version",
                "producer",
                "occurred_at",
                "payload",
            ),
        )
    return count


async def _commit_candles(
    ingestion: CandleIngestionService,
    candles: tuple[CanonicalCandle, ...],
    *,
    deadline: float = CAPACITY_DEADLINE_SECONDS,
) -> tuple[tuple[CandleCommitStatus, ...], float]:
    started = time.perf_counter()
    tasks = [
        asyncio.create_task(
            ingestion.commit_candle(candle),
            name=f"l2a-commit-{candle.lane.instrument_id}-{candle.lane.timeframe}",
        )
        for candle in candles
    ]
    gather_task = asyncio.gather(*tasks)
    try:
        statuses = await asyncio.wait_for(gather_task, timeout=deadline)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return tuple(statuses), _duration_seconds(started)


async def _pool_monitor(
    pool: asyncpg.Pool,
    stop_event: asyncio.Event,
    samples: list[tuple[int, int]],
) -> None:
    while not stop_event.is_set():
        size = pool.get_size()
        idle = pool.get_idle_size()
        samples.append((size - idle, idle))
        await asyncio.sleep(0.001)
    size = pool.get_size()
    idle = pool.get_idle_size()
    samples.append((size - idle, idle))


async def _db_counts(
    pool: asyncpg.Pool,
    prefix: str,
) -> dict[str, int]:
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT
                (SELECT COUNT(*)
                 FROM ingestion.candles
                 WHERE position($1 in instrument_id) = 1) AS candles,
                (SELECT COUNT(*)
                 FROM ingestion.outbox
                 WHERE position($1 in payload->>'instrument_id') = 1) AS outbox,
                (SELECT COUNT(*)
                 FROM ingestion.outbox
                 WHERE position($1 in payload->>'instrument_id') = 1
                   AND published_at IS NULL) AS pending
            """,
            prefix,
        )
    return {key: int(row[key]) for key in ("candles", "outbox", "pending")}


async def _global_pending_count(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as connection:
        return int(
            await connection.fetchval(
                "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
            )
        )


async def _stage_counts(pool: asyncpg.Pool, stage_prefix: str) -> dict[str, int]:
    return await _db_counts(pool, stage_prefix)


async def _outbox_event_ids(
    pool: asyncpg.Pool,
    prefix: str,
) -> tuple[str, ...]:
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT event_id
            FROM ingestion.outbox
            WHERE position($1 in payload->>'instrument_id') = 1
              AND published_at IS NOT NULL
            ORDER BY occurred_at ASC, event_id ASC
            """,
            prefix,
        )
    return tuple(str(row["event_id"]) for row in rows)


async def _stream_keys(client: Any, prefix: str) -> tuple[str, ...]:
    encoded_prefix = quote(prefix, safe="")
    pattern = f"stream:ohlcv:ingestion:binance:{encoded_prefix}*"
    keys: list[str] = []
    async for key in client.scan_iter(match=pattern):
        keys.append(key.decode() if isinstance(key, bytes) else str(key))
    return tuple(sorted(set(keys)))


async def _stream_event_ids(
    client: Any,
    keys: tuple[str, ...],
) -> set[str]:
    event_ids: set[str] = set()
    for offset in range(0, len(keys), 100):
        batch = keys[offset : offset + 100]
        entries = await asyncio.gather(*(client.xrange(key, "-", "+") for key in batch))
        for stream_entries in entries:
            for _, fields in stream_entries:
                event_id = fields.get("event_id")
                if event_id is not None:
                    event_ids.add(str(event_id))
    return event_ids


async def _wait_prefix_pending_zero(
    pool: asyncpg.Pool,
    prefix: str,
    *,
    publisher_task: asyncio.Task[None] | None = None,
    deadline: float = CAPACITY_DEADLINE_SECONDS,
) -> float:
    started = time.perf_counter()
    while True:
        if publisher_task is not None and publisher_task.done():
            publisher_task.result()
            raise RuntimeError("publisher exited before pending rows drained")
        if (await _db_counts(pool, prefix))["pending"] == 0:
            return _duration_seconds(started)
        if time.perf_counter() - started >= deadline:
            raise TimeoutError(f"pending rows did not drain within {deadline}s")
        await asyncio.sleep(0.05)


async def _drain_prefix(
    publisher: OutboxPublisher,
    repository: CandleRepository,
    pool: asyncpg.Pool,
    prefix: str,
    *,
    batch_size: int,
    deadline: float = CAPACITY_DEADLINE_SECONDS,
) -> tuple[int, float, tuple[str, ...]]:
    started = time.perf_counter()
    batches = 0
    published_order: list[str] = []
    while True:
        pending = (await _db_counts(pool, prefix))["pending"]
        if pending == 0:
            return batches, _duration_seconds(started), tuple(published_order)
        if time.perf_counter() - started >= deadline:
            raise TimeoutError(f"publisher drain did not finish within {deadline}s")
        events = await repository.fetch_pending_outbox(limit=batch_size)
        if not events:
            raise RuntimeError(
                "pending count was non-zero but no pending events were read"
            )
        published = await publisher.publish_once()
        if published != len(events):
            raise RuntimeError(
                f"publisher marked {published} rows after reading {len(events)}"
            )
        published_order.extend(str(event.event_id) for event in events)
        batches += 1


async def _db_snapshot(pool: asyncpg.Pool) -> dict[str, object]:
    async with pool.acquire() as connection:
        version = await connection.fetchval("SELECT version()")
        timescale_version = await connection.fetchval(
            "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'"
        )
        database_size = await connection.fetchval(
            "SELECT pg_database_size(current_database())"
        )
        candles_size = await connection.fetchrow(
            """
            SELECT
                COALESCE(SUM(table_bytes), 0)::bigint AS table_bytes,
                COALESCE(SUM(index_bytes), 0)::bigint AS index_bytes,
                COALESCE(SUM(toast_bytes), 0)::bigint AS toast_bytes,
                COALESCE(SUM(total_bytes), 0)::bigint AS total_bytes
            FROM hypertable_detailed_size('ingestion.candles'::regclass)
            """
        )
        outbox_relation_size = await connection.fetchval(
            "SELECT pg_total_relation_size('ingestion.outbox'::regclass)"
        )
        outbox_index_size = await connection.fetchval(
            "SELECT pg_indexes_size('ingestion.outbox'::regclass)"
        )
        counts = await connection.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM ingestion.candles) AS candles,
                (SELECT COUNT(*) FROM ingestion.outbox) AS outbox
            """
        )
        try:
            jobs = await connection.fetch(
                "SELECT to_jsonb(job)::text AS job_json "
                "FROM timescaledb_information.jobs AS job"
            )
        except asyncpg.UndefinedTableError:
            jobs = ()
    retention_jobs = [
        row["job_json"]
        for row in jobs
        if "retention" in row["job_json"].lower()
        and "ingestion" in row["job_json"].lower()
    ]
    outbox_cleanup_jobs = [
        row["job_json"]
        for row in jobs
        if "outbox" in row["job_json"].lower()
        and any(
            term in row["job_json"].lower()
            for term in ("delete", "cleanup", "retention")
        )
    ]
    return {
        "postgres_version": version,
        "timescale_version": timescale_version,
        "database_size": int(database_size),
        "candles_table_bytes": int(candles_size["table_bytes"]),
        "candles_index_bytes": int(candles_size["index_bytes"]),
        "candles_toast_bytes": int(candles_size["toast_bytes"]),
        "candles_total_bytes": int(candles_size["total_bytes"]),
        "outbox_relation_size": int(outbox_relation_size),
        "outbox_index_size": int(outbox_index_size),
        "candles": int(counts["candles"]),
        "outbox": int(counts["outbox"]),
        "candle_retention_jobs": tuple(retention_jobs),
        "outbox_cleanup_jobs": tuple(outbox_cleanup_jobs),
    }


def _storage_schema_sql(schema_name: str) -> str:
    if not schema_name.startswith("l2a_storage_") or not all(
        character.isalnum() or character == "_" for character in schema_name
    ):
        raise ValueError("invalid L2A storage schema name")
    return f'"{schema_name}"'


def _storage_regclass(schema_name: str, table_name: str) -> str:
    _storage_schema_sql(schema_name)
    if table_name not in {"candles", "outbox"}:
        raise ValueError("invalid L2A storage table name")
    return f"'{schema_name}.{table_name}'::regclass"


async def _relation_columns(
    pool: asyncpg.Pool,
    *,
    schema_name: str,
    table_name: str,
) -> tuple[tuple[str, str, bool, str], ...]:
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
                attribute.attname AS name,
                format_type(attribute.atttypid, attribute.atttypmod)
                    AS data_type,
                attribute.attnotnull AS not_null,
                COALESCE(
                    pg_get_expr(default_value.adbin, default_value.adrelid),
                    ''
                ) AS default_expression
            FROM pg_attribute AS attribute
            JOIN pg_class AS relation
              ON relation.oid = attribute.attrelid
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            LEFT JOIN pg_attrdef AS default_value
              ON default_value.adrelid = attribute.attrelid
             AND default_value.adnum = attribute.attnum
            WHERE namespace.nspname = $1
              AND relation.relname = $2
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
            ORDER BY attribute.attnum
            """,
            schema_name,
            table_name,
        )
    return tuple(
        (
            str(row["name"]),
            str(row["data_type"]),
            bool(row["not_null"]),
            str(row["default_expression"]),
        )
        for row in rows
    )


async def _relation_indexes(
    pool: asyncpg.Pool,
    *,
    schema_name: str,
    table_name: str,
) -> tuple[tuple[bool, bool, str, tuple[str, ...], str], ...]:
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT
                index_info.indisprimary AS is_primary,
                index_info.indisunique AS is_unique,
                access_method.amname AS access_method,
                ARRAY(
                    SELECT attribute.attname
                    FROM unnest(index_info.indkey)
                        WITH ORDINALITY AS key(attnum, ordinal)
                    JOIN pg_attribute AS attribute
                      ON attribute.attrelid = index_info.indrelid
                     AND attribute.attnum = key.attnum
                    ORDER BY key.ordinal
                ) AS columns,
                COALESCE(
                    pg_get_expr(index_info.indpred, index_info.indrelid),
                    ''
                ) AS predicate
            FROM pg_index AS index_info
            JOIN pg_class AS relation
              ON relation.oid = index_info.indrelid
            JOIN pg_namespace AS namespace
              ON namespace.oid = relation.relnamespace
            JOIN pg_class AS index_relation
              ON index_relation.oid = index_info.indexrelid
            JOIN pg_am AS access_method
              ON access_method.oid = index_relation.relam
            WHERE namespace.nspname = $1
              AND relation.relname = $2
            ORDER BY
                index_info.indisprimary DESC,
                index_info.indisunique DESC,
                access_method.amname,
                index_relation.relname
            """,
            schema_name,
            table_name,
        )
    return tuple(
        (
            bool(row["is_primary"]),
            bool(row["is_unique"]),
            str(row["access_method"]),
            tuple(str(column) for column in row["columns"]),
            str(row["predicate"]),
        )
        for row in rows
    )


async def _relation_contract(
    pool: asyncpg.Pool,
    *,
    schema_name: str,
    table_name: str,
) -> dict[str, object]:
    return {
        "columns": await _relation_columns(
            pool,
            schema_name=schema_name,
            table_name=table_name,
        ),
        "indexes": await _relation_indexes(
            pool,
            schema_name=schema_name,
            table_name=table_name,
        ),
    }


async def _hypertable_contract(
    pool: asyncpg.Pool,
    *,
    schema_name: str,
    table_name: str,
) -> dict[str, object]:
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT
                dimension.column_name,
                dimension.dimension_type,
                dimension.time_interval,
                hypertable.compression_enabled
            FROM timescaledb_information.hypertables AS hypertable
            JOIN timescaledb_information.dimensions AS dimension
              USING (hypertable_schema, hypertable_name)
            WHERE hypertable.hypertable_schema = $1
              AND hypertable.hypertable_name = $2
            """,
            schema_name,
            table_name,
        )
    assert row is not None
    return {
        "time_column": str(row["column_name"]),
        "dimension_type": str(row["dimension_type"]),
        "chunk_interval": row["time_interval"],
        "compression_enabled": bool(row["compression_enabled"]),
    }


async def _hypertable_size(
    pool: asyncpg.Pool,
    *,
    schema_name: str,
    table_name: str,
) -> dict[str, int]:
    regclass = _storage_regclass(schema_name, table_name)
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            f"""
            SELECT
                COALESCE(SUM(table_bytes), 0)::bigint AS table_bytes,
                COALESCE(SUM(index_bytes), 0)::bigint AS index_bytes,
                COALESCE(SUM(toast_bytes), 0)::bigint AS toast_bytes,
                COALESCE(SUM(total_bytes), 0)::bigint AS total_bytes
            FROM public.hypertable_detailed_size({regclass})
            """
        )
    assert row is not None
    return {
        key: int(row[key])
        for key in ("table_bytes", "index_bytes", "toast_bytes", "total_bytes")
    }


async def _ordinary_relation_size(
    pool: asyncpg.Pool,
    *,
    schema_name: str,
    table_name: str,
) -> dict[str, int]:
    regclass = _storage_regclass(schema_name, table_name)
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            f"""
            SELECT
                pg_relation_size({regclass})::bigint AS table_bytes,
                pg_indexes_size({regclass})::bigint AS index_bytes,
                pg_total_relation_size({regclass})::bigint AS total_bytes
            """
        )
    assert row is not None
    return {key: int(row[key]) for key in ("table_bytes", "index_bytes", "total_bytes")}


async def _isolated_counts(
    pool: asyncpg.Pool,
    *,
    schema_name: str,
) -> dict[str, int]:
    schema_sql = _storage_schema_sql(schema_name)
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            f"""
            SELECT
                (SELECT COUNT(*) FROM {schema_sql}.candles) AS candles,
                (SELECT COUNT(*) FROM {schema_sql}.outbox) AS outbox,
                (
                    SELECT COUNT(*)
                    FROM timescaledb_information.chunks
                    WHERE hypertable_schema = $1
                      AND hypertable_name = 'candles'
                ) AS chunks
            """,
            schema_name,
        )
    assert row is not None
    return {key: int(row[key]) for key in ("candles", "outbox", "chunks")}


async def _isolated_candle_shape_counts(
    pool: asyncpg.Pool,
    *,
    schema_name: str,
) -> dict[tuple[str, str, str | None, str | None], int]:
    schema_sql = _storage_schema_sql(schema_name)
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            f"""
            SELECT
                timeframe,
                source_type,
                source_provider,
                source_timeframe,
                COUNT(*) AS row_count
            FROM {schema_sql}.candles
            GROUP BY timeframe, source_type, source_provider, source_timeframe
            ORDER BY timeframe, source_type
            """
        )
    return {
        (
            str(row["timeframe"]),
            str(row["source_type"]),
            None if row["source_provider"] is None else str(row["source_provider"]),
            None if row["source_timeframe"] is None else str(row["source_timeframe"]),
        ): int(row["row_count"])
        for row in rows
    }


async def _isolated_outbox_audit(
    pool: asyncpg.Pool,
    *,
    schema_name: str,
) -> dict[str, object]:
    schema_sql = _storage_schema_sql(schema_name)
    async with pool.acquire() as connection:
        counts = await connection.fetchrow(
            f"""
            SELECT
                COUNT(*) AS row_count,
                COUNT(DISTINCT event_id) AS unique_event_ids,
                COUNT(*) FILTER (WHERE published_at IS NULL) AS pending,
                COUNT(*) FILTER (WHERE published_at IS NOT NULL) AS published,
                MIN(octet_length(payload::text)) AS min_payload_bytes,
                MAX(octet_length(payload::text)) AS max_payload_bytes,
                AVG(octet_length(payload::text)) AS avg_payload_bytes
            FROM {schema_sql}.outbox
            """
        )
        unmatched = await connection.fetchval(
            f"""
            SELECT COUNT(*)
            FROM {schema_sql}.outbox AS outbox
            WHERE NOT EXISTS (
                SELECT 1
                FROM {schema_sql}.candles AS candle
                WHERE candle.venue = outbox.payload->>'venue'
                  AND candle.instrument_id = outbox.payload->>'instrument_id'
                  AND candle.timeframe = outbox.payload->>'timeframe'
                  AND candle.open_time =
                      (outbox.payload->>'open_time')::timestamptz
            )
            """
        )
        samples = await connection.fetch(
            f"""
            SELECT
                candle.venue,
                candle.instrument_id,
                candle.timeframe,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
                candle.taker_buy_base,
                candle.source_type,
                candle.source_provider,
                candle.source_timeframe,
                candle.open_time,
                candle.close_time,
                outbox.payload
            FROM {schema_sql}.outbox AS outbox
            JOIN {schema_sql}.candles AS candle
              ON candle.venue = outbox.payload->>'venue'
             AND candle.instrument_id = outbox.payload->>'instrument_id'
             AND candle.timeframe = outbox.payload->>'timeframe'
             AND candle.open_time =
                 (outbox.payload->>'open_time')::timestamptz
            ORDER BY outbox.occurred_at ASC, outbox.event_id ASC
            LIMIT 4
            """
        )
    assert counts is not None
    return {
        "row_count": int(counts["row_count"]),
        "unique_event_ids": int(counts["unique_event_ids"]),
        "pending": int(counts["pending"]),
        "published": int(counts["published"]),
        "unmatched": int(unmatched),
        "min_payload_bytes": int(counts["min_payload_bytes"]),
        "max_payload_bytes": int(counts["max_payload_bytes"]),
        "avg_payload_bytes": float(counts["avg_payload_bytes"]),
        "samples": tuple(samples),
    }


async def _set_isolated_outbox_published(
    pool: asyncpg.Pool,
    *,
    schema_name: str,
) -> dict[str, int]:
    schema_sql = _storage_schema_sql(schema_name)
    async with pool.acquire() as connection:
        await connection.execute(
            f"""
            UPDATE {schema_sql}.outbox
            SET published_at = $1
            """,
            PUBLISHED_AT,
        )
        row = await connection.fetchrow(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE published_at IS NULL) AS pending,
                COUNT(*) FILTER (WHERE published_at IS NOT NULL) AS published
            FROM {schema_sql}.outbox
            """
        )
    assert row is not None
    return {"pending": int(row["pending"]), "published": int(row["published"])}


async def _create_isolated_storage_schema(
    pool: asyncpg.Pool,
    *,
    schema_name: str,
    production_hypertable: dict[str, object],
) -> None:
    schema_sql = _storage_schema_sql(schema_name)
    chunk_interval = production_hypertable["chunk_interval"]
    if production_hypertable["compression_enabled"]:
        raise RuntimeError(
            "L2A isolated sizing currently requires the verified uncompressed "
            "production candle contract"
        )
    async with pool.acquire() as connection:
        await connection.execute(f"CREATE SCHEMA {schema_sql}")
        await connection.execute(
            f"""
            CREATE TABLE {schema_sql}.candles
            (LIKE ingestion.candles INCLUDING ALL)
            """
        )
        await connection.execute(
            f"""
            CREATE TABLE {schema_sql}.outbox
            (LIKE ingestion.outbox INCLUDING ALL)
            """
        )
        await connection.execute(
            f"""
            SELECT *
            FROM public.create_hypertable(
                {_storage_regclass(schema_name, "candles")},
                public.by_range('open_time', $1::interval),
                create_default_indexes => false,
                if_not_exists => false
            )
            """,
            chunk_interval,
        )


async def _drop_isolated_storage_schema(
    pool: asyncpg.Pool,
    *,
    schema_name: str,
) -> None:
    schema_sql = _storage_schema_sql(schema_name)
    async with pool.acquire() as connection:
        await connection.execute(f"DROP SCHEMA IF EXISTS {schema_sql} CASCADE")
        exists = await connection.fetchval(
            """
            SELECT EXISTS(
                SELECT 1
                FROM pg_namespace
                WHERE nspname = $1
            )
            """,
            schema_name,
        )
    assert exists is False


async def _run_isolated_storage_measurement(
    pool: asyncpg.Pool,
    *,
    settings: IngestionSettings,
    run_number: int,
    production_candle_contract: dict[str, object],
    production_outbox_contract: dict[str, object],
    production_hypertable: dict[str, object],
) -> dict[str, object]:
    schema_name = f"l2a_storage_{uuid4().hex}"
    try:
        await _create_isolated_storage_schema(
            pool,
            schema_name=schema_name,
            production_hypertable=production_hypertable,
        )
        assert (
            await _relation_contract(
                pool,
                schema_name=schema_name,
                table_name="candles",
            )
            == production_candle_contract
        )
        assert (
            await _relation_contract(
                pool,
                schema_name=schema_name,
                table_name="outbox",
            )
            == production_outbox_contract
        )
        assert (
            await _hypertable_contract(
                pool,
                schema_name=schema_name,
                table_name="candles",
            )
            == production_hypertable
        )

        before_counts = await _isolated_counts(pool, schema_name=schema_name)
        before_candles = await _hypertable_size(
            pool,
            schema_name=schema_name,
            table_name="candles",
        )
        before_outbox = await _ordinary_relation_size(
            pool,
            schema_name=schema_name,
            table_name="outbox",
        )
        assert before_counts == {"candles": 0, "outbox": 0, "chunks": 0}

        lanes = _representative_lanes(50)
        population_counts = _representative_population_counts(
            settings,
            lane_count=len(lanes),
        )
        canonical_rows = sum(population_counts.values())
        identity_lengths = tuple(len(lane.instrument_id) for lane in lanes)
        assert all("l2a_storage_" not in lane.instrument_id for lane in lanes)
        copy_started = time.perf_counter()
        candle_rows = await _copy_candle_records(
            pool,
            schema_name=schema_name,
            table_name="candles",
            records=_representative_candle_rows(settings, lanes=lanes),
            count=canonical_rows,
        )
        outbox_rows = await _copy_outbox_rows(
            pool,
            schema_name=schema_name,
            records=_representative_event_rows(settings, lanes=lanes),
            count=canonical_rows,
        )
        copy_seconds = _duration_seconds(copy_started)

        after_counts = await _isolated_counts(pool, schema_name=schema_name)
        shape_counts = await _isolated_candle_shape_counts(
            pool,
            schema_name=schema_name,
        )
        expected_shape_counts = {
            (
                timeframe,
                "provider" if timeframe == settings.base_timeframe else "derived",
                "binance_native" if timeframe == settings.base_timeframe else None,
                None if timeframe == settings.base_timeframe else "1m",
            ): row_count
            for timeframe, row_count in population_counts.items()
        }
        assert shape_counts == expected_shape_counts
        outbox_audit = await _isolated_outbox_audit(
            pool,
            schema_name=schema_name,
        )
        assert outbox_audit["row_count"] == canonical_rows
        assert outbox_audit["unique_event_ids"] == canonical_rows
        assert outbox_audit["pending"] == canonical_rows
        assert outbox_audit["published"] == 0
        assert outbox_audit["unmatched"] == 0
        assert len(outbox_audit["samples"]) == 4
        for sample in outbox_audit["samples"]:
            payload = sample["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            assert isinstance(payload, dict)
            assert set(payload) == _EXPECTED_EVENT_PAYLOAD_FIELDS
            assert payload["open_time"] == _utc_payload_time(sample["open_time"])
            assert payload["close_time"] == _utc_payload_time(sample["close_time"])
            for field_name in (
                "open",
                "high",
                "low",
                "close",
                "volume",
                "taker_buy_base",
            ):
                sample_value = sample[field_name]
                assert payload[field_name] == (
                    None if sample_value is None else str(sample_value)
                )
            for field_name in (
                "venue",
                "instrument_id",
                "timeframe",
                "source_type",
                "source_provider",
                "source_timeframe",
            ):
                assert payload[field_name] == sample[field_name]

        after_candles = await _hypertable_size(
            pool,
            schema_name=schema_name,
            table_name="candles",
        )
        pending_outbox = await _ordinary_relation_size(
            pool,
            schema_name=schema_name,
            table_name="outbox",
        )
        outbox_state = await _set_isolated_outbox_published(
            pool,
            schema_name=schema_name,
        )
        assert outbox_state == {"pending": 0, "published": canonical_rows}
        after_outbox = await _ordinary_relation_size(
            pool,
            schema_name=schema_name,
            table_name="outbox",
        )
        assert after_counts == {
            "candles": candle_rows,
            "outbox": outbox_rows,
            "chunks": after_counts["chunks"],
        }
        assert candle_rows == canonical_rows
        assert outbox_rows == canonical_rows
        assert after_counts["chunks"] > 0

        candle_delta = {
            key: after_candles[key] - before_candles[key] for key in after_candles
        }
        outbox_delta = {
            key: after_outbox[key] - before_outbox[key] for key in after_outbox
        }
        assert candle_delta["total_bytes"] > 0
        assert outbox_delta["total_bytes"] > 0
        return {
            "run": run_number,
            "schema": schema_name,
            "copy_seconds": copy_seconds,
            "candle_rows": candle_rows,
            "candle_chunks": after_counts["chunks"],
            "rows_by_timeframe": population_counts,
            "identity_length_min": min(identity_lengths),
            "identity_length_max": max(identity_lengths),
            "identity_length_median": median(identity_lengths),
            "candle_before": before_candles,
            "candle_after": after_candles,
            "candle_delta": candle_delta,
            "candle_bytes_per_row": {
                key: value / candle_rows for key, value in candle_delta.items()
            },
            "outbox_rows": outbox_rows,
            "outbox_before": before_outbox,
            "outbox_pending": pending_outbox,
            "outbox_after": after_outbox,
            "outbox_delta": outbox_delta,
            "outbox_bytes_per_row": {
                key: value / outbox_rows for key, value in outbox_delta.items()
            },
            "outbox_payload": {
                key: value for key, value in outbox_audit.items() if key != "samples"
            },
            "outbox_state": outbox_state,
        }
    finally:
        await _drop_isolated_storage_schema(pool, schema_name=schema_name)


async def _valkey_snapshot(client: Any) -> dict[str, object]:
    server_info = await client.info("server")
    memory_info = await client.info("memory")
    maxmemory = await client.config_get("maxmemory")
    maxmemory_policy = await client.config_get("maxmemory-policy")
    return {
        "version": server_info.get("redis_version"),
        "maxmemory": maxmemory.get("maxmemory"),
        "maxmemory_policy": maxmemory_policy.get("maxmemory-policy"),
        "used_memory": memory_info.get("used_memory"),
        "dbsize": int(await client.dbsize()),
    }


def _docker_snapshot(container_name: str) -> dict[str, object]:
    completed = subprocess.run(
        ["docker", "inspect", container_name],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)[0]
    state = payload["State"]
    health = state.get("Health") or {}
    return {
        "status": state.get("Status"),
        "health": health.get("Status"),
        "restart_count": int(payload.get("RestartCount", 0)),
        "memory_limit": payload.get("HostConfig", {}).get("Memory"),
        "nano_cpus": payload.get("HostConfig", {}).get("NanoCpus"),
    }


async def _assert_derived_rows(
    pool: asyncpg.Pool,
    prefix: str,
    *,
    expected_count: int,
) -> None:
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT source_type, source_provider, source_timeframe
            FROM ingestion.candles
            WHERE position($1 in instrument_id) = 1
              AND source_type = 'derived'
            """,
            prefix,
        )
    assert len(rows) == expected_count
    assert all(
        (row["source_type"], row["source_provider"], row["source_timeframe"])
        == ("derived", None, "1m")
        for row in rows
    )


async def _cleanup_run(
    pool: asyncpg.Pool,
    client: Any,
    prefix: str,
) -> dict[str, int]:
    async with pool.acquire() as connection, connection.transaction():
        outbox_status = await connection.execute(
            """
            DELETE FROM ingestion.outbox
            WHERE position($1 in payload->>'instrument_id') = 1
            """,
            prefix,
        )
        candle_status = await connection.execute(
            """
            DELETE FROM ingestion.candles
            WHERE position($1 in instrument_id) = 1
            """,
            prefix,
        )
    keys = await _stream_keys(client, prefix)
    if keys:
        await client.delete(*keys)
    counts = await _db_counts(pool, prefix)
    remaining_keys = await _stream_keys(client, prefix)
    return {
        "outbox_deleted": int(outbox_status.rsplit(" ", 1)[-1]),
        "candles_deleted": int(candle_status.rsplit(" ", 1)[-1]),
        "candles_remaining": counts["candles"],
        "outbox_remaining": counts["outbox"],
        "streams_remaining": len(remaining_keys),
    }


def _workload_model(
    settings: IngestionSettings,
    *,
    lane_count: int,
) -> dict[str, object]:
    day_seconds = Decimal(86_400)
    base_duration = Decimal(
        settings.timeframes[settings.base_timeframe].duration_seconds
    )
    base_per_lane = day_seconds / base_duration
    outputs_by_timeframe = {
        timeframe: Decimal(lane_count)
        * day_seconds
        / Decimal(timeframe_settings.duration_seconds)
        for timeframe, timeframe_settings in settings.timeframes.items()
        if timeframe != settings.base_timeframe
    }
    base_events = Decimal(lane_count) * base_per_lane
    return {
        "base_candles_per_lane_per_day": base_per_lane,
        "base_candles_per_day": base_events,
        "htf_outputs_per_timeframe_per_day": outputs_by_timeframe,
        "total_canonical_events_per_day": base_events
        + sum(outputs_by_timeframe.values(), Decimal(0)),
        "worst_aligned_boundary_events": lane_count * (1 + len(outputs_by_timeframe)),
    }


@pytest.mark.asyncio
async def test_real_timescale_valkey_capacity_l2a() -> None:
    """Run the complete opt-in local infrastructure certification."""
    repository_root = Path(__file__).parents[3]
    prefix = f"l2a_{uuid4().hex}"
    manager: ConfigManager | None = None
    pool: asyncpg.Pool | None = None
    client: Any | None = None
    publisher: OutboxPublisher | None = None
    publisher_task: asyncio.Task[None] | None = None
    monitor_task: asyncio.Task[None] | None = None
    monitor_stop = asyncio.Event()
    pool_samples: list[tuple[int, int]] = []
    tracemalloc_started = False

    try:
        ConfigManager.reset_singleton()
        manager = ConfigManager(config_dir=str(repository_root / "configs"))
        settings = load_ingestion_settings(manager)
        base_duration = timedelta(
            seconds=settings.timeframes[settings.base_timeframe].duration_seconds
        )
        target_durations = {
            timeframe: timedelta(
                seconds=settings.timeframes[timeframe].duration_seconds
            )
            for timeframe in settings.timeframes
            if timeframe != settings.base_timeframe
        }
        target_timeframes = tuple(
            sorted(
                target_durations,
                key=lambda timeframe: (target_durations[timeframe], timeframe),
            )
        )
        assert target_timeframes == ALL_HTF_TARGETS
        assert settings.base_timeframe == "1m"
        assert settings.publication.batch_size == 500
        assert settings.publication.stream_maxlen == 1000
        assert settings.publication.stream_approximate is True

        await init_db_pools(manager)
        pool = DBPoolManager.get_writer_pool()
        await apply_ingestion_schema(pool)
        pool_min = pool.get_min_size()
        pool_max = pool.get_max_size()
        _emit("configured_pool", {"min": pool_min, "max": pool_max})
        _emit("workload_model", _workload_model(settings, lane_count=LANE_COUNT))

        client = await create_valkey_client(manager)
        pre_db = await _db_snapshot(pool)
        pre_valkey = await _valkey_snapshot(client)
        pre_db_container = _docker_snapshot("flipperagent-db-1")
        pre_broker_container = _docker_snapshot("flipperagent-broker-1")
        _emit("pre_db", pre_db)
        _emit("pre_valkey", pre_valkey)
        _emit("pre_db_container", pre_db_container)
        _emit("pre_broker_container", pre_broker_container)

        global_pending = await _global_pending_count(pool)
        if global_pending:
            raise RuntimeError(
                "L2A requires an empty global pending outbox to preserve test isolation; "
                f"found {global_pending} rows"
            )

        repository = CandleRepository(pool)
        ingestion = CandleIngestionService(repository)
        htf = HTFAggregationService(
            repository=repository,
            ingestion_service=ingestion,
        )
        publisher = OutboxPublisher(
            repository=repository,
            valkey_client=client,
            publication=settings.publication,
        )
        monitor_task = asyncio.create_task(
            _pool_monitor(pool, monitor_stop, pool_samples),
            name="l2a-pool-monitor",
        )

        # Stage A: one concurrent 500-lane provider wave.
        stage_a_lanes = tuple(_lane(prefix, "A", index) for index in range(LANE_COUNT))
        stage_a_candles = tuple(
            _provider_candle(lane, BASE_BOUNDARY, ordinal=index)
            for index, lane in enumerate(stage_a_lanes)
        )
        statuses, duration = await _commit_candles(ingestion, stage_a_candles)
        assert statuses.count(CandleCommitStatus.INSERTED) == LANE_COUNT
        assert await _stage_counts(pool, f"{prefix}_A_") == {
            "candles": LANE_COUNT,
            "outbox": LANE_COUNT,
            "pending": LANE_COUNT,
        }
        _emit("stage_a", {"duration_seconds": duration, "inserted": len(statuses)})

        # Stage B: duplicate replay and one content conflict.
        duplicate_statuses, duplicate_duration = await _commit_candles(
            ingestion,
            stage_a_candles,
        )
        assert duplicate_statuses.count(CandleCommitStatus.DUPLICATE) == LANE_COUNT
        selected = stage_a_candles[0]
        conflict = CanonicalCandle(
            lane=selected.lane,
            open_time=selected.open_time,
            close_time=selected.close_time,
            open=selected.open,
            high=selected.high,
            low=selected.low,
            close=selected.close + Decimal("0.5"),
            volume=selected.volume,
            taker_buy_base=selected.taker_buy_base,
            source_type=selected.source_type,
            source_provider=selected.source_provider,
            source_timeframe=selected.source_timeframe,
        )
        conflict_statuses, _ = await _commit_candles(ingestion, (conflict,))
        assert conflict_statuses == (CandleCommitStatus.CONFLICT,)
        assert await _stage_counts(pool, f"{prefix}_A_") == {
            "candles": LANE_COUNT,
            "outbox": LANE_COUNT,
            "pending": LANE_COUNT,
        }
        _emit(
            "stage_b",
            {
                "duplicate_duration_seconds": duplicate_duration,
                "duplicates": len(duplicate_statuses),
                "conflict": conflict_statuses[0],
            },
        )

        # Stage C: one real publisher task and ten sequential 500-lane waves.
        publisher_task = asyncio.create_task(
            publisher.run(),
            name="l2a-outbox-publisher",
        )
        await _wait_prefix_pending_zero(
            pool, f"{prefix}_A_", publisher_task=publisher_task
        )
        stage_c_lanes = tuple(_lane(prefix, "C", index) for index in range(LANE_COUNT))
        stage_c_wave_durations: list[float] = []
        for wave in range(10):
            boundary = BASE_BOUNDARY + timedelta(hours=2, minutes=wave)
            wave_candles = tuple(
                _provider_candle(
                    lane,
                    boundary,
                    ordinal=10_000 + wave * LANE_COUNT + index,
                )
                for index, lane in enumerate(stage_c_lanes)
            )
            wave_statuses, wave_duration = await _commit_candles(
                ingestion,
                wave_candles,
            )
            assert wave_statuses.count(CandleCommitStatus.INSERTED) == LANE_COUNT
            assert wave_duration < CAPACITY_DEADLINE_SECONDS
            stage_c_wave_durations.append(wave_duration)
        stage_c_pending_drain = await _wait_prefix_pending_zero(
            pool,
            f"{prefix}_C_",
            publisher_task=publisher_task,
        )
        assert (await _stage_counts(pool, f"{prefix}_C_")) == {
            "candles": LANE_COUNT * 10,
            "outbox": LANE_COUNT * 10,
            "pending": 0,
        }
        for lane in stage_c_lanes:
            key = _stream_key_for_lane(lane)
            assert await client.xlen(key) == 10
        assert not publisher_task.done()
        publisher.stop()
        await publisher_task
        publisher_task = None
        _emit(
            "stage_c",
            {
                "wave_durations_seconds": stage_c_wave_durations,
                "pending_drain_seconds": stage_c_pending_drain,
                "rows": LANE_COUNT * 10,
            },
        )

        # Stage D: 500 real 15m aggregations from COPY-seeded base rows.
        stage_d_lanes = tuple(_lane(prefix, "D", index) for index in range(LANE_COUNT))
        stage_d_start = FIFTEEN_MINUTE_BOUNDARY - timedelta(minutes=15)
        copied = await _copy_base_rows(
            pool,
            stage_d_lanes,
            start=stage_d_start,
            count=15,
        )
        assert copied == LANE_COUNT * 15
        stage_d_started = time.perf_counter()
        stage_d_follow_ups: list[object] = []
        for index, lane in enumerate(stage_d_lanes):
            stage_d_follow_ups.extend(
                await htf.process_base_candle(
                    _provider_candle(
                        lane,
                        FIFTEEN_MINUTE_BOUNDARY - base_duration,
                        ordinal=index * 100_000 + 14,
                    ),
                    base_duration=base_duration,
                    target_durations={"15m": target_durations["15m"]},
                    alignment_origin=settings.calendar.alignment_origin,
                )
            )
        stage_d_duration = _duration_seconds(stage_d_started)
        assert stage_d_duration < CAPACITY_DEADLINE_SECONDS
        assert stage_d_follow_ups == []
        assert await _stage_counts(pool, f"{prefix}_D_") == {
            "candles": LANE_COUNT * 15 + LANE_COUNT,
            "outbox": LANE_COUNT,
            "pending": LANE_COUNT,
        }
        await _assert_derived_rows(pool, f"{prefix}_D_", expected_count=LANE_COUNT)
        stage_d_batches, stage_d_publish_duration, _ = await _drain_prefix(
            publisher,
            repository,
            pool,
            f"{prefix}_D_",
            batch_size=settings.publication.batch_size,
        )
        _emit(
            "stage_d",
            {
                "fixture_rows": copied,
                "derived_rows": LANE_COUNT,
                "duration_seconds": stage_d_duration,
                "publication_batches": stage_d_batches,
                "publication_seconds": stage_d_publish_duration,
            },
        )

        # Stage E: 500 real 1h aggregations with the larger range read.
        stage_e_lanes = tuple(_lane(prefix, "E", index) for index in range(LANE_COUNT))
        stage_e_start = ONE_HOUR_BOUNDARY - timedelta(hours=1)
        copied = await _copy_base_rows(
            pool,
            stage_e_lanes,
            start=stage_e_start,
            count=60,
        )
        assert copied == LANE_COUNT * 60
        stage_e_started = time.perf_counter()
        stage_e_follow_ups: list[object] = []
        for index, lane in enumerate(stage_e_lanes):
            stage_e_follow_ups.extend(
                await htf.process_base_candle(
                    _provider_candle(
                        lane,
                        ONE_HOUR_BOUNDARY - base_duration,
                        ordinal=index * 100_000 + 59,
                    ),
                    base_duration=base_duration,
                    target_durations={"1h": target_durations["1h"]},
                    alignment_origin=settings.calendar.alignment_origin,
                )
            )
        stage_e_duration = _duration_seconds(stage_e_started)
        assert stage_e_duration < CAPACITY_DEADLINE_SECONDS
        assert stage_e_follow_ups == []
        assert await _stage_counts(pool, f"{prefix}_E_") == {
            "candles": LANE_COUNT * 60 + LANE_COUNT,
            "outbox": LANE_COUNT,
            "pending": LANE_COUNT,
        }
        await _assert_derived_rows(pool, f"{prefix}_E_", expected_count=LANE_COUNT)
        stage_e_batches, stage_e_publish_duration, _ = await _drain_prefix(
            publisher,
            repository,
            pool,
            f"{prefix}_E_",
            batch_size=settings.publication.batch_size,
        )
        _emit(
            "stage_e",
            {
                "fixture_rows": copied,
                "derived_rows": LANE_COUNT,
                "duration_seconds": stage_e_duration,
                "publication_batches": stage_e_batches,
                "publication_seconds": stage_e_publish_duration,
            },
        )

        # Stage F: a representative 50-lane, one-week, all-HTF database workload.
        stage_f_lanes = tuple(_lane(prefix, "F", index) for index in range(50))
        stage_f_start = BASE_BOUNDARY - timedelta(weeks=1)
        tracemalloc.start()
        tracemalloc_started = True
        stage_f_copy_started = time.perf_counter()
        copied = await _copy_base_rows(
            pool,
            stage_f_lanes,
            start=stage_f_start,
            count=10_080,
        )
        stage_f_copy_duration = _duration_seconds(stage_f_copy_started)
        assert copied == 50 * 10_080

        original_fetch_candles = repository.fetch_candles
        stage_f_read_rows = 0
        stage_f_fetch_metrics = {
            timeframe: {
                "query_count": 0,
                "rows": 0,
                "fetch_seconds": 0.0,
            }
            for timeframe in target_timeframes
        }
        stage_f_duration_to_timeframe = {
            duration: timeframe for timeframe, duration in target_durations.items()
        }

        async def traced_fetch_candles(
            *,
            lane: MarketLane,
            since: datetime,
            until: datetime,
        ) -> tuple[CanonicalCandle, ...]:
            nonlocal stage_f_read_rows
            fetch_started = time.perf_counter()
            rows = await original_fetch_candles(
                lane=lane,
                since=since,
                until=until,
            )
            if lane.instrument_id.startswith(f"{prefix}_F_"):
                target_timeframe = stage_f_duration_to_timeframe[until - since]
                metrics = stage_f_fetch_metrics[target_timeframe]
                metrics["query_count"] += 1
                metrics["rows"] += len(rows)
                metrics["fetch_seconds"] += time.perf_counter() - fetch_started
                stage_f_read_rows += len(rows)
            return rows

        repository.fetch_candles = traced_fetch_candles  # type: ignore[method-assign]
        stage_f_started = time.perf_counter()
        stage_f_follow_ups: list[object] = []
        for index, lane in enumerate(stage_f_lanes):
            stage_f_follow_ups.extend(
                await htf.process_base_candle(
                    _provider_candle(
                        lane,
                        BASE_BOUNDARY - base_duration,
                        ordinal=index * 100_000 + 10_079,
                    ),
                    base_duration=base_duration,
                    target_durations=target_durations,
                    alignment_origin=settings.calendar.alignment_origin,
                )
            )
        stage_f_duration = _duration_seconds(stage_f_started)
        _, stage_f_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        tracemalloc_started = False
        expected_stage_f_reads = 50 * sum(
            duration // base_duration for duration in target_durations.values()
        )
        expected_stage_f_queries = len(stage_f_lanes) * len(target_durations)
        assert stage_f_read_rows == expected_stage_f_reads
        assert (
            sum(metrics["query_count"] for metrics in stage_f_fetch_metrics.values())
            == expected_stage_f_queries
        )
        assert stage_f_follow_ups == []
        await _assert_derived_rows(
            pool,
            f"{prefix}_F_",
            expected_count=50 * len(target_durations),
        )
        _emit(
            "stage_f",
            {
                "fixture_rows": copied,
                "copy_seconds": stage_f_copy_duration,
                "direct_base_read_rows": stage_f_read_rows,
                "expected_direct_base_read_rows": expected_stage_f_reads,
                "derived_rows": 50 * len(target_durations),
                "aggregation_seconds": stage_f_duration,
                "tracemalloc_peak_bytes": stage_f_peak,
                "range_query_count": expected_stage_f_queries,
                "fetch_metrics_by_timeframe": stage_f_fetch_metrics,
            },
        )
        assert stage_f_duration < CAPACITY_DEADLINE_SECONDS
        stage_f_batches, stage_f_publish_duration, _ = await _drain_prefix(
            publisher,
            repository,
            pool,
            f"{prefix}_F_",
            batch_size=settings.publication.batch_size,
        )
        _emit(
            "stage_f",
            {
                "fixture_rows": copied,
                "copy_seconds": stage_f_copy_duration,
                "direct_base_read_rows": stage_f_read_rows,
                "expected_direct_base_read_rows": expected_stage_f_reads,
                "derived_rows": 50 * len(target_durations),
                "aggregation_seconds": stage_f_duration,
                "tracemalloc_peak_bytes": stage_f_peak,
                "publication_batches": stage_f_batches,
                "publication_seconds": stage_f_publish_duration,
                "range_query_count": expected_stage_f_queries,
                "fetch_metrics_by_timeframe": stage_f_fetch_metrics,
            },
        )

        # Stage G/H: 4,500 aligned canonical writes followed by a real drain.
        stage_g_lanes = tuple(_lane(prefix, "G", index) for index in range(LANE_COUNT))
        stage_g_candles: list[CanonicalCandle] = [
            _provider_candle(lane, BASE_BOUNDARY, ordinal=index)
            for index, lane in enumerate(stage_g_lanes)
        ]
        stage_g_boundary_duration = {
            timeframe: target_durations[timeframe] for timeframe in target_timeframes
        }
        for index, lane in enumerate(stage_g_lanes):
            for target_index, timeframe in enumerate(target_timeframes):
                stage_g_candles.append(
                    _derived_candle(
                        MarketLane(
                            lane.venue,
                            lane.instrument_id,
                            timeframe,
                        ),
                        BASE_BOUNDARY,
                        duration=stage_g_boundary_duration[timeframe],
                        ordinal=200_000 + index * 10 + target_index,
                    )
                )
        assert len(stage_g_candles) == 4_500
        stage_g_statuses, stage_g_write_duration = await _commit_candles(
            ingestion,
            tuple(stage_g_candles),
        )
        assert stage_g_statuses.count(CandleCommitStatus.INSERTED) == 4_500
        assert await _stage_counts(pool, f"{prefix}_G_") == {
            "candles": 4_500,
            "outbox": 4_500,
            "pending": 4_500,
        }
        stage_g_batches, stage_g_publish_duration, stage_g_order = await _drain_prefix(
            publisher,
            repository,
            pool,
            f"{prefix}_G_",
            batch_size=settings.publication.batch_size,
        )
        assert (
            stage_g_batches
            == (4_500 + settings.publication.batch_size - 1)
            // settings.publication.batch_size
        )
        assert stage_g_publish_duration < CAPACITY_DEADLINE_SECONDS
        assert stage_g_order == await _outbox_event_ids(pool, f"{prefix}_G_")
        _emit(
            "stage_g_h",
            {
                "writes": len(stage_g_statuses),
                "write_seconds": stage_g_write_duration,
                "publication_batches": stage_g_batches,
                "publication_seconds": stage_g_publish_duration,
                "expected_batches": (4_500 + settings.publication.batch_size - 1)
                // settings.publication.batch_size,
            },
        )

        # Stage I: approximate MAXLEN boundedness on one isolated stream.
        retention_lane = _lane(prefix, "RETENTION", 0)
        retention_candle = _provider_candle(
            retention_lane,
            BASE_BOUNDARY,
            ordinal=900_000,
        )
        retention_event = build_candle_committed_event(retention_candle)
        retention_key = canonical_lane_stream_key(retention_event)
        retention_lengths: list[int] = []
        for index in range(settings.publication.stream_maxlen * 10):
            await client.xadd(
                retention_key,
                {
                    "event_id": f"{prefix}-retention-{index}",
                    "payload": "{}",
                },
                maxlen=settings.publication.stream_maxlen,
                approximate=settings.publication.stream_approximate,
            )
            if (index + 1) % settings.publication.stream_maxlen == 0:
                retention_lengths.append(await client.xlen(retention_key))
        assert retention_lengths[-1] < settings.publication.stream_maxlen * 2
        assert await client.xrange(retention_key, "-", "+")
        _emit("stage_i", {"stream_key": retention_key, "lengths": retention_lengths})

        # Stage J: read-only retention audit and storage-growth estimates.
        post_workload_db = await _db_snapshot(pool)
        post_workload_valkey = await _valkey_snapshot(client)
        post_db_container = _docker_snapshot("flipperagent-db-1")
        post_broker_container = _docker_snapshot("flipperagent-broker-1")
        run_counts = await _db_counts(pool, prefix)
        candle_size_delta = max(
            0,
            int(post_workload_db["candles_total_bytes"])
            - int(pre_db["candles_total_bytes"]),
        )
        outbox_size_delta = max(
            0,
            int(post_workload_db["outbox_relation_size"])
            - int(pre_db["outbox_relation_size"]),
        )
        approx_candle_bytes = (
            candle_size_delta / run_counts["candles"] if run_counts["candles"] else 0
        )
        approx_outbox_bytes = (
            outbox_size_delta / run_counts["outbox"] if run_counts["outbox"] else 0
        )
        assert candle_size_delta > 0
        assert approx_candle_bytes > 0
        model = _workload_model(settings, lane_count=LANE_COUNT)
        projected_daily_bytes = (approx_candle_bytes + approx_outbox_bytes) * float(
            model["total_canonical_events_per_day"]
        )
        projections = {
            days: round(projected_daily_bytes * days, 2) for days in (7, 30, 90)
        }
        _emit(
            "stage_j",
            {
                "db": post_workload_db,
                "valkey": post_workload_valkey,
                "db_container": post_db_container,
                "broker_container": post_broker_container,
                "run_counts": run_counts,
                "candle_size_delta_bytes": candle_size_delta,
                "outbox_size_delta_bytes": outbox_size_delta,
                "approx_candle_bytes": approx_candle_bytes,
                "approx_outbox_bytes": approx_outbox_bytes,
                "projected_daily_bytes": projected_daily_bytes,
                "retention_days_projection_bytes": projections,
                "TIMESCALE_CANDLE_RETENTION_POLICY": (
                    "PRESENT" if post_workload_db["candle_retention_jobs"] else "ABSENT"
                ),
                "PUBLISHED_OUTBOX_CLEANUP_SCHEDULER": (
                    "PRESENT" if post_workload_db["outbox_cleanup_jobs"] else "ABSENT"
                ),
            },
        )

        keys = await _stream_keys(client, prefix)
        assert retention_key in keys
        publication_keys = tuple(key for key in keys if key != retention_key)
        durable_event_ids = set(await _outbox_event_ids(pool, prefix))
        stream_event_ids = await _stream_event_ids(client, publication_keys)
        assert durable_event_ids == stream_event_ids
        _emit(
            "event_id_reconciliation",
            {
                "durable": len(durable_event_ids),
                "streams": len(stream_event_ids),
                "publication_stream_count": len(publication_keys),
                "retention_key": retention_key,
            },
        )
    finally:
        if tracemalloc_started:
            tracemalloc.stop()
        if monitor_task is not None:
            monitor_stop.set()
            await monitor_task
        if publisher is not None and publisher_task is not None:
            publisher.stop()
            await publisher_task
        if pool is not None and client is not None:
            cleanup = await _cleanup_run(pool, client, prefix)
            _emit("cleanup", cleanup)
            assert cleanup["candles_remaining"] == 0
            assert cleanup["outbox_remaining"] == 0
            assert cleanup["streams_remaining"] == 0
        if pool_samples:
            max_checked_out = max(sample[0] for sample in pool_samples)
            min_idle = min(sample[1] for sample in pool_samples)
            _emit(
                "pool_high_water",
                {
                    "max_checked_out": max_checked_out,
                    "min_idle": min_idle,
                    "configured_max": pool.get_max_size() if pool is not None else None,
                    "sample_count": len(pool_samples),
                },
            )
            assert pool is None or max_checked_out <= pool.get_max_size()
        if client is not None:
            await client.aclose()
        await DBPoolManager.close_pools()
        if manager is not None:
            manager.shutdown()
        ConfigManager.reset_singleton()


@pytest.mark.asyncio
async def test_l2a_isolated_storage_measurement() -> None:
    """Measure candle and outbox storage on three disposable schemas."""
    repository_root = Path(__file__).parents[3]
    manager: ConfigManager | None = None
    pool: asyncpg.Pool | None = None

    try:
        ConfigManager.reset_singleton()
        manager = ConfigManager(config_dir=str(repository_root / "configs"))
        settings = load_ingestion_settings(manager)
        await init_db_pools(manager)
        pool = DBPoolManager.get_writer_pool()
        await apply_ingestion_schema(pool)

        production_candle_contract = await _relation_contract(
            pool,
            schema_name="ingestion",
            table_name="candles",
        )
        production_outbox_contract = await _relation_contract(
            pool,
            schema_name="ingestion",
            table_name="outbox",
        )
        production_hypertable = await _hypertable_contract(
            pool,
            schema_name="ingestion",
            table_name="candles",
        )
        _emit(
            "isolated_storage_production_contract",
            {
                "candle": production_candle_contract,
                "outbox": production_outbox_contract,
                "hypertable": production_hypertable,
            },
        )

        results: list[dict[str, object]] = []
        for run_number in range(1, 4):
            result = await _run_isolated_storage_measurement(
                pool,
                settings=settings,
                run_number=run_number,
                production_candle_contract=production_candle_contract,
                production_outbox_contract=production_outbox_contract,
                production_hypertable=production_hypertable,
            )
            results.append(result)
            _emit(f"isolated_storage_run_{run_number}", result)

        expected_population = _representative_population_counts(
            settings,
            lane_count=50,
        )
        expected_total = sum(expected_population.values())
        provider_rows = expected_population[settings.base_timeframe]
        derived_rows = expected_total - provider_rows
        assert expected_total == 567_400
        assert all(
            result["candle_rows"] == expected_total
            and result["outbox_rows"] == expected_total
            and result["rows_by_timeframe"] == expected_population
            and result["outbox_state"]
            == {
                "pending": 0,
                "published": expected_total,
            }
            for result in results
        )
        identity_summary = {
            "min": results[0]["identity_length_min"],
            "max": results[0]["identity_length_max"],
            "median": results[0]["identity_length_median"],
            "btc_usdt_perp_length": len("BTC-USDT-PERP"),
        }
        assert all(
            (
                result["identity_length_min"],
                result["identity_length_max"],
                result["identity_length_median"],
            )
            == (
                identity_summary["min"],
                identity_summary["max"],
                identity_summary["median"],
            )
            for result in results
        )
        _emit(
            "representative_population",
            {
                "rows_by_timeframe": expected_population,
                "total_rows": expected_total,
                "provider_rows": provider_rows,
                "derived_rows": derived_rows,
                "identity_lengths": identity_summary,
                "outbox_payload_fields": sorted(_EXPECTED_EVENT_PAYLOAD_FIELDS),
                "published_at": PUBLISHED_AT.isoformat(),
            },
        )

        candle_total_per_row = [
            float(result["candle_bytes_per_row"]["total_bytes"]) for result in results
        ]
        candle_table_per_row = [
            float(result["candle_bytes_per_row"]["table_bytes"]) for result in results
        ]
        candle_index_per_row = [
            float(result["candle_bytes_per_row"]["index_bytes"]) for result in results
        ]
        candle_toast_per_row = [
            float(result["candle_bytes_per_row"]["toast_bytes"]) for result in results
        ]
        outbox_total_per_row = [
            float(result["outbox_bytes_per_row"]["total_bytes"]) for result in results
        ]
        outbox_table_per_row = [
            float(result["outbox_bytes_per_row"]["table_bytes"]) for result in results
        ]
        outbox_index_per_row = [
            float(result["outbox_bytes_per_row"]["index_bytes"]) for result in results
        ]
        candle_total_median = median(candle_total_per_row)
        outbox_total_median = median(outbox_total_per_row)
        total_events_per_day = float(
            _workload_model(settings, lane_count=LANE_COUNT)[
                "total_canonical_events_per_day"
            ]
        )
        daily_candle_bytes = candle_total_median * total_events_per_day
        daily_outbox_bytes = outbox_total_median * total_events_per_day
        daily_combined_bytes = daily_candle_bytes + daily_outbox_bytes
        projections = {
            days: {
                "candle_bytes": round(daily_candle_bytes * days, 2),
                "outbox_bytes": round(daily_outbox_bytes * days, 2),
                "combined_bytes": round(daily_combined_bytes * days, 2),
            }
            for days in (7, 30, 90)
        }
        _emit(
            "isolated_storage_projection",
            {
                "total_events_per_day": total_events_per_day,
                "candle_total_bytes_per_row": candle_total_per_row,
                "candle_table_bytes_per_row": candle_table_per_row,
                "candle_index_bytes_per_row": candle_index_per_row,
                "candle_toast_bytes_per_row": candle_toast_per_row,
                "candle_total_median_bytes_per_row": candle_total_median,
                "outbox_total_bytes_per_row": outbox_total_per_row,
                "outbox_table_bytes_per_row": outbox_table_per_row,
                "outbox_index_bytes_per_row": outbox_index_per_row,
                "outbox_total_median_bytes_per_row": outbox_total_median,
                "daily_candle_bytes": daily_candle_bytes,
                "daily_outbox_bytes": daily_outbox_bytes,
                "daily_combined_bytes": daily_combined_bytes,
                "retention_days": projections,
            },
        )
        assert all(
            result["candle_delta"]["total_bytes"] > 0
            and result["outbox_delta"]["total_bytes"] > 0
            and result["candle_chunks"] > 0
            for result in results
        )
        assert candle_total_median > 0
        assert outbox_total_median > 0
    finally:
        await DBPoolManager.close_pools()
        if manager is not None:
            manager.shutdown()
        ConfigManager.reset_singleton()
