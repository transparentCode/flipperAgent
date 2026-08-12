from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from apps.ingestion_app.domain.candle import CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.publication.outbox import build_candle_committed_event
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.repository import (
    CandleCommitStatus,
    CandleRepository,
)

if os.getenv("INGESTION_RUN_INTEGRATION") != "1":
    pytest.skip(
        "set INGESTION_RUN_INTEGRATION=1 to run the live Timescale tests",
        allow_module_level=True,
    )


@pytest_asyncio.fixture
async def db_pool() -> asyncpg.Pool:
    dsn = os.getenv(
        "POSTGRES_URI",
        "postgresql://flipper:flipperpass@localhost:5432/flipper_db",
    )
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    await apply_ingestion_schema(pool)
    try:
        yield pool
    finally:
        await pool.close()


@pytest_asyncio.fixture
async def test_instrument_id(db_pool: asyncpg.Pool):
    instrument_id = f"package_c_{uuid4().hex}"
    yield instrument_id
    async with db_pool.acquire() as connection, connection.transaction():
        await connection.execute(
            "DELETE FROM ingestion.outbox WHERE payload->>'instrument_id' = $1",
            instrument_id,
        )
        await connection.execute(
            "DELETE FROM ingestion.candles WHERE instrument_id = $1",
            instrument_id,
        )


def _candle(
    instrument_id: str,
    *,
    source_provider: str = "binance_native",
    taker_buy_base: Decimal | None = Decimal(4),
) -> CanonicalCandle:
    open_time = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    return CanonicalCandle(
        lane=MarketLane("binance", instrument_id, "1m"),
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open=Decimal(100),
        high=Decimal(102),
        low=Decimal(99),
        close=Decimal(101),
        volume=Decimal(10),
        taker_buy_base=taker_buy_base,
        source_type="provider",
        source_provider=source_provider,
        source_timeframe=None,
    )


async def _count_candles(pool: asyncpg.Pool, instrument_id: str) -> int:
    async with pool.acquire() as connection:
        return await connection.fetchval(
            "SELECT COUNT(*) FROM ingestion.candles WHERE instrument_id = $1",
            instrument_id,
        )


async def _count_outbox(pool: asyncpg.Pool, instrument_id: str) -> int:
    async with pool.acquire() as connection:
        return await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM ingestion.outbox
            WHERE payload->>'instrument_id' = $1
            """,
            instrument_id,
        )


@pytest.mark.asyncio
async def test_schema_exists_and_candles_is_hypertable(db_pool: asyncpg.Pool) -> None:
    async with db_pool.acquire() as connection:
        assert await connection.fetchval(
            "SELECT to_regclass('ingestion.candles') IS NOT NULL"
        )
        assert await connection.fetchval(
            "SELECT to_regclass('ingestion.outbox') IS NOT NULL"
        )
        assert await connection.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM timescaledb_information.hypertables
                WHERE hypertable_schema = 'ingestion'
                AND hypertable_name = 'candles'
            )
            """
        )
        numeric_columns = await connection.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'ingestion'
              AND table_name = 'candles'
              AND data_type = 'numeric'
            """
        )
        assert {row["column_name"] for row in numeric_columns} == {
            "open",
            "high",
            "low",
            "close",
            "volume",
            "taker_buy_base",
        }
        constraint_names = await connection.fetch(
            """
            SELECT conname
            FROM pg_constraint constraint_row
            JOIN pg_class table_row ON table_row.oid = constraint_row.conrelid
            JOIN pg_namespace schema_row ON schema_row.oid = table_row.relnamespace
            WHERE schema_row.nspname = 'ingestion'
              AND table_row.relname = 'candles'
            """
        )
        assert {row["conname"] for row in constraint_names} >= {
            "candles_close_after_open",
            "candles_close_within_range",
            "candles_identity_non_blank",
            "candles_low_not_above_high",
            "candles_open_within_range",
            "candles_source_provenance_valid",
            "candles_source_type_valid",
            "candles_taker_buy_base_non_negative",
            "candles_volume_non_negative",
        }


@pytest.mark.asyncio
async def test_schema_bootstrap_is_idempotent(db_pool: asyncpg.Pool) -> None:
    await apply_ingestion_schema(db_pool)
    await apply_ingestion_schema(db_pool)


@pytest.mark.asyncio
async def test_new_commit_creates_one_candle_and_one_outbox(
    db_pool: asyncpg.Pool,
    test_instrument_id: str,
) -> None:
    candle = _candle(test_instrument_id)
    repository = CandleRepository(db_pool)

    status = await repository.commit_candle(
        candle,
        build_candle_committed_event(candle),
    )

    assert status is CandleCommitStatus.INSERTED
    assert await _count_candles(db_pool, test_instrument_id) == 1
    assert await _count_outbox(db_pool, test_instrument_id) == 1


@pytest.mark.asyncio
async def test_duplicate_creates_no_new_rows(
    db_pool: asyncpg.Pool,
    test_instrument_id: str,
) -> None:
    candle = _candle(test_instrument_id)
    repository = CandleRepository(db_pool)

    first = await repository.commit_candle(
        candle,
        build_candle_committed_event(candle),
    )
    second = await repository.commit_candle(
        candle,
        build_candle_committed_event(candle),
    )

    assert first is CandleCommitStatus.INSERTED
    assert second is CandleCommitStatus.DUPLICATE
    assert await _count_candles(db_pool, test_instrument_id) == 1
    assert await _count_outbox(db_pool, test_instrument_id) == 1


@pytest.mark.asyncio
async def test_conflict_leaves_stored_candle_and_outbox_unchanged(
    db_pool: asyncpg.Pool,
    test_instrument_id: str,
) -> None:
    candle = _candle(test_instrument_id)
    repository = CandleRepository(db_pool)
    await repository.commit_candle(candle, build_candle_committed_event(candle))

    conflict = replace(candle, close=Decimal("101.5"))
    status = await repository.commit_candle(
        conflict,
        build_candle_committed_event(conflict),
    )

    assert status is CandleCommitStatus.CONFLICT
    async with db_pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT open, high, low, close, volume
            FROM ingestion.candles
            WHERE instrument_id = $1
            """,
            test_instrument_id,
        )
    assert dict(row) == {
        "open": Decimal(100),
        "high": Decimal(102),
        "low": Decimal(99),
        "close": Decimal(101),
        "volume": Decimal(10),
    }
    assert await _count_outbox(db_pool, test_instrument_id) == 1


@pytest.mark.asyncio
async def test_source_provider_overlap_is_duplicate_and_preserves_first_provenance(
    db_pool: asyncpg.Pool,
    test_instrument_id: str,
) -> None:
    first_candle = _candle(test_instrument_id, source_provider="ccxt_binance")
    overlap = replace(first_candle, source_provider="binance_native")
    repository = CandleRepository(db_pool)

    assert (
        await repository.commit_candle(
            first_candle,
            build_candle_committed_event(first_candle),
        )
        is CandleCommitStatus.INSERTED
    )
    assert (
        await repository.commit_candle(
            overlap,
            build_candle_committed_event(overlap),
        )
        is CandleCommitStatus.DUPLICATE
    )

    async with db_pool.acquire() as connection:
        source_provider = await connection.fetchval(
            """
            SELECT source_provider
            FROM ingestion.candles
            WHERE instrument_id = $1
            """,
            test_instrument_id,
        )
    assert source_provider == "ccxt_binance"
    assert await _count_outbox(db_pool, test_instrument_id) == 1


@pytest.mark.asyncio
async def test_missing_taker_value_is_duplicate_without_mutation(
    db_pool: asyncpg.Pool,
    test_instrument_id: str,
) -> None:
    first_candle = _candle(test_instrument_id, taker_buy_base=None)
    overlap = replace(first_candle, taker_buy_base=Decimal(4))
    repository = CandleRepository(db_pool)

    await repository.commit_candle(
        first_candle,
        build_candle_committed_event(first_candle),
    )
    status = await repository.commit_candle(
        overlap,
        build_candle_committed_event(overlap),
    )

    assert status is CandleCommitStatus.DUPLICATE
    async with db_pool.acquire() as connection:
        stored_taker = await connection.fetchval(
            """
            SELECT taker_buy_base
            FROM ingestion.candles
            WHERE instrument_id = $1
            """,
            test_instrument_id,
        )
    assert stored_taker is None
    assert await _count_outbox(db_pool, test_instrument_id) == 1


@pytest.mark.asyncio
async def test_fetch_candles_returns_ordered_canonical_rows(
    db_pool: asyncpg.Pool,
    test_instrument_id: str,
) -> None:
    first = _candle(test_instrument_id)
    second = replace(
        first,
        open_time=first.open_time + timedelta(minutes=1),
        close_time=first.close_time + timedelta(minutes=1),
    )
    derived = replace(
        first,
        lane=MarketLane("binance", test_instrument_id, "15m"),
        close_time=first.open_time + timedelta(minutes=15),
        source_type="derived",
        source_provider=None,
        source_timeframe="1m",
    )
    repository = CandleRepository(db_pool)

    for candle in (first, second, derived):
        assert (
            await repository.commit_candle(
                candle,
                build_candle_committed_event(candle),
            )
            is CandleCommitStatus.INSERTED
        )

    base_rows = await repository.fetch_candles(
        lane=first.lane,
        since=first.open_time,
        until=first.open_time + timedelta(minutes=2),
    )
    derived_rows = await repository.fetch_candles(
        lane=derived.lane,
        since=derived.open_time,
        until=derived.close_time,
    )

    assert base_rows == (first, second)
    assert base_rows[0].volume == Decimal(10)
    assert derived_rows == (derived,)
    assert derived_rows[0].source_type == "derived"
    assert derived_rows[0].source_provider is None
    assert derived_rows[0].source_timeframe == "1m"

    latest = await repository.fetch_latest_candle(
        lane=first.lane,
        before=second.close_time,
    )
    latest_before_second = await repository.fetch_latest_candle(
        lane=first.lane,
        before=first.close_time,
    )
    assert latest == second
    assert latest_before_second == first


@pytest.mark.asyncio
async def test_concurrent_duplicate_commit_has_one_insert_and_one_outbox(
    db_pool: asyncpg.Pool,
    test_instrument_id: str,
) -> None:
    candle = _candle(test_instrument_id)
    repository = CandleRepository(db_pool)

    statuses = await asyncio.gather(
        repository.commit_candle(
            candle,
            build_candle_committed_event(candle),
        ),
        repository.commit_candle(
            candle,
            build_candle_committed_event(candle),
        ),
    )

    assert {status for status in statuses} == {
        CandleCommitStatus.INSERTED,
        CandleCommitStatus.DUPLICATE,
    }
    assert await _count_candles(db_pool, test_instrument_id) == 1
    assert await _count_outbox(db_pool, test_instrument_id) == 1
