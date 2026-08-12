from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from apps.ingestion_app.domain.candle import CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.publication.publisher import OutboxPublisher
from apps.ingestion_app.publication.stream_keys import canonical_lane_stream_key
from apps.ingestion_app.services.candle_ingestion import CandleIngestionService
from apps.ingestion_app.settings import load_ingestion_settings
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.repository import (
    CandleCommitStatus,
    CandleRepository,
)
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client

if os.getenv("INGESTION_RUN_PUBLICATION_INTEGRATION") != "1":
    pytest.skip(
        "set INGESTION_RUN_PUBLICATION_INTEGRATION=1 to run publication integration",
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
async def valkey_client():
    client = await create_valkey_client()
    try:
        yield client
    finally:
        await client.aclose()


def _candle(instrument_id: str) -> CanonicalCandle:
    open_time = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
    return CanonicalCandle(
        lane=MarketLane("binance", instrument_id, "1m"),
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open=Decimal("100.0000"),
        high=Decimal("102.0000"),
        low=Decimal("99.0000"),
        close=Decimal("101.0000"),
        volume=Decimal("10.5000"),
        taker_buy_base=Decimal("4.0000"),
        source_type="provider",
        source_provider="binance_native",
        source_timeframe=None,
    )


async def _load_publication_settings():
    repository_root = Path(__file__).parents[3]
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(repository_root / "configs"))
    try:
        return load_ingestion_settings(manager).publication
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


@pytest.mark.asyncio
async def test_outbox_publisher_round_trip_and_normal_idempotence(
    db_pool: asyncpg.Pool,
    valkey_client,
) -> None:
    instrument_id = f"package_j_{uuid4().hex}"
    repository = CandleRepository(db_pool)
    candle = _candle(instrument_id)
    stream_key: str | None = None

    try:
        ingestion = CandleIngestionService(repository)
        assert await ingestion.commit_candle(candle) is CandleCommitStatus.INSERTED

        pending = await repository.fetch_pending_outbox(limit=10)
        assert len(pending) == 1
        event = pending[0]
        stream_key = canonical_lane_stream_key(event)

        publisher = OutboxPublisher(
            repository=repository,
            valkey_client=valkey_client,
            publication=await _load_publication_settings(),
        )
        assert await publisher.publish_once() == 1
        assert await repository.fetch_pending_outbox(limit=10) == ()

        entries = await valkey_client.xrange(stream_key, "-", "+")
        assert len(entries) == 1
        _, fields = entries[0]
        assert fields == {
            "event_id": str(event.event_id),
            "event_type": event.event_type,
            "schema_version": str(event.schema_version),
            "producer": event.producer,
            "occurred_at": event.occurred_at.isoformat().replace("+00:00", "Z"),
            "payload": event.payload_json,
        }

        assert await publisher.publish_once() == 0
        assert len(await valkey_client.xrange(stream_key, "-", "+")) == 1
    finally:
        async with db_pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "DELETE FROM ingestion.outbox WHERE payload->>'instrument_id' = $1",
                instrument_id,
            )
            await connection.execute(
                "DELETE FROM ingestion.candles WHERE instrument_id = $1",
                instrument_id,
            )
        if stream_key is not None:
            await valkey_client.delete(stream_key)

        async with db_pool.acquire() as connection:
            assert (
                await connection.fetchval(
                    "SELECT COUNT(*) FROM ingestion.candles WHERE instrument_id = $1",
                    instrument_id,
                )
                == 0
            )
            assert (
                await connection.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM ingestion.outbox
                    WHERE payload->>'instrument_id' = $1
                    """,
                    instrument_id,
                )
                == 0
            )
        if stream_key is not None:
            assert await valkey_client.exists(stream_key) == 0
