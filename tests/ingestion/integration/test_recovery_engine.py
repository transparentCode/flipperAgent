from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.providers.binance_native import (
    BinanceNativeHistoricalProvider,
)
from apps.ingestion_app.providers.ccxt import CCXTHistoricalProvider
from apps.ingestion_app.services.candle_ingestion import CandleIngestionService
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.services.recovery import RecoveryEngine
from apps.ingestion_app.settings import load_ingestion_settings
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.repository import CandleRepository
from libs.common.config import ConfigManager
from libs.common.exceptions import DataIngestionError

if os.getenv("INGESTION_RUN_RECOVERY_INTEGRATION") != "1":
    pytest.skip(
        "set INGESTION_RUN_RECOVERY_INTEGRATION=1 to run recovery integration",
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
async def test_instrument_ids(db_pool: asyncpg.Pool) -> tuple[str, str]:
    instrument_ids = (
        f"package_f_primary_{uuid4().hex}",
        f"package_f_fallback_{uuid4().hex}",
    )
    yield instrument_ids
    async with db_pool.acquire() as connection, connection.transaction():
        for instrument_id in instrument_ids:
            await connection.execute(
                "DELETE FROM ingestion.outbox WHERE payload->>'instrument_id' = $1",
                instrument_id,
            )
            await connection.execute(
                "DELETE FROM ingestion.candles WHERE instrument_id = $1",
                instrument_id,
            )
            candle_count = await connection.fetchval(
                "SELECT COUNT(*) FROM ingestion.candles WHERE instrument_id = $1",
                instrument_id,
            )
            outbox_count = await connection.fetchval(
                """
                SELECT COUNT(*)
                FROM ingestion.outbox
                WHERE payload->>'instrument_id' = $1
                """,
                instrument_id,
            )
            assert candle_count == 0
            assert outbox_count == 0


def _load_settings():
    repository_root = Path(__file__).parents[3]
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(repository_root / "configs"))
    try:
        return load_ingestion_settings(manager)
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


async def _count(
    pool: asyncpg.Pool,
    instrument_id: str,
    timeframe: str | None = None,
) -> int:
    async with pool.acquire() as connection:
        if timeframe is None:
            return await connection.fetchval(
                "SELECT COUNT(*) FROM ingestion.candles WHERE instrument_id = $1",
                instrument_id,
            )
        return await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM ingestion.candles
            WHERE instrument_id = $1 AND timeframe = $2
            """,
            instrument_id,
            timeframe,
        )


async def _outbox_count(pool: asyncpg.Pool, instrument_id: str) -> int:
    async with pool.acquire() as connection:
        return await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM ingestion.outbox
            WHERE payload->>'instrument_id' = $1
            """,
            instrument_id,
        )


class _FailingPrimary:
    provider_id = "test_primary"

    async def fetch_closed_candles(self, **kwargs: object) -> tuple[object, ...]:
        del kwargs
        raise DataIngestionError("intentional Package F primary failure")


@pytest.mark.asyncio
async def test_real_recovery_repairs_base_htf_and_fallback_is_idempotent(
    db_pool: asyncpg.Pool,
    test_instrument_ids: tuple[str, str],
) -> None:
    settings = _load_settings()
    instrument = settings.assets["BTC"].instruments["BTC-USDT-PERP"]
    base_timeframe = settings.base_timeframe
    base_duration = timedelta(
        seconds=settings.timeframes[base_timeframe].duration_seconds
    )
    alignment_origin = settings.calendar.alignment_origin
    target_timeframes = ("15m", "30m")
    target_durations = {
        timeframe: timedelta(seconds=settings.timeframes[timeframe].duration_seconds)
        for timeframe in target_timeframes
    }
    recovery = settings.recovery
    native: BinanceNativeHistoricalProvider | None = None
    ccxt_provider: CCXTHistoricalProvider | None = None

    primary_instrument_id, fallback_instrument_id = test_instrument_ids
    primary_lane = MarketLane(instrument.venue, primary_instrument_id, base_timeframe)
    fallback_lane = MarketLane(
        instrument.venue,
        fallback_instrument_id,
        base_timeframe,
    )
    primary_since = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    primary_until = primary_since + timedelta(minutes=30)
    fallback_since = datetime(2026, 8, 8, 13, 0, tzinfo=UTC)
    fallback_until = fallback_since + timedelta(minutes=5)

    try:
        native = BinanceNativeHistoricalProvider()
        ccxt_settings = settings.providers["ccxt_binance"]
        assert ccxt_settings.exchange_id is not None
        ccxt_provider = CCXTHistoricalProvider(
            provider_id="ccxt_binance",
            exchange_id=ccxt_settings.exchange_id,
        )
        repository = CandleRepository(db_pool)
        ingestion_service = CandleIngestionService(repository)
        htf_service = HTFAggregationService(
            repository=repository,
            ingestion_service=ingestion_service,
        )
        engine = RecoveryEngine(
            providers={
                "binance_native": native,
                "ccxt_binance": ccxt_provider,
            },
            repository=repository,
            ingestion_service=ingestion_service,
            htf_service=htf_service,
            max_concurrency=recovery.max_concurrency,
            page_limit=recovery.page_limit,
            max_attempts_per_provider=recovery.max_attempts_per_provider,
            retry_backoff_seconds=recovery.retry_backoff_seconds,
            rest_finalization_grace_seconds=recovery.rest_finalization_grace_seconds,
        )

        primary_request = RecoveryRequest(
            lane=primary_lane,
            since=primary_since,
            until=primary_until,
            reason="integration_primary",
        )
        primary_follow_ups = await engine.recover(
            primary_request,
            base_timeframe=base_timeframe,
            base_duration=base_duration,
            provider_order=instrument.historical_providers,
            provider_symbols=instrument.provider_symbols,
            target_durations=target_durations,
            alignment_origin=alignment_origin,
        )
        assert primary_follow_ups == ()
        assert await _count(db_pool, primary_instrument_id, "1m") == 30
        assert await _count(db_pool, primary_instrument_id, "15m") == 2
        assert await _count(db_pool, primary_instrument_id, "30m") == 1
        assert await _outbox_count(db_pool, primary_instrument_id) == 33

        async with db_pool.acquire() as connection:
            provenance = await connection.fetch(
                """
                SELECT timeframe, source_type, source_provider, source_timeframe
                FROM ingestion.candles
                WHERE instrument_id = $1
                ORDER BY timeframe, open_time
                """,
                primary_instrument_id,
            )
        assert all(
            row["source_provider"] == "binance_native"
            for row in provenance
            if row["timeframe"] == "1m"
        )
        assert all(
            (row["source_type"], row["source_provider"], row["source_timeframe"])
            == ("derived", None, "1m")
            for row in provenance
            if row["timeframe"] in {"15m", "30m"}
        )

        counts_before = {
            timeframe: await _count(db_pool, primary_instrument_id, timeframe)
            for timeframe in ("1m", "15m", "30m")
        }
        outbox_before = await _outbox_count(db_pool, primary_instrument_id)
        assert (
            await engine.recover(
                primary_request,
                base_timeframe=base_timeframe,
                base_duration=base_duration,
                provider_order=instrument.historical_providers,
                provider_symbols=instrument.provider_symbols,
                target_durations=target_durations,
                alignment_origin=alignment_origin,
            )
            == ()
        )
        assert {
            timeframe: await _count(db_pool, primary_instrument_id, timeframe)
            for timeframe in counts_before
        } == counts_before
        assert await _outbox_count(db_pool, primary_instrument_id) == outbox_before

        fallback_engine = RecoveryEngine(
            providers={
                "test_primary": _FailingPrimary(),  # type: ignore[arg-type]
                "ccxt_binance": ccxt_provider,
            },
            repository=repository,
            ingestion_service=ingestion_service,
            htf_service=htf_service,
            max_concurrency=recovery.max_concurrency,
            page_limit=recovery.page_limit,
            max_attempts_per_provider=recovery.max_attempts_per_provider,
            retry_backoff_seconds=0,
            rest_finalization_grace_seconds=recovery.rest_finalization_grace_seconds,
        )
        fallback_request = RecoveryRequest(
            lane=fallback_lane,
            since=fallback_since,
            until=fallback_until,
            reason="integration_fallback",
        )
        assert (
            await fallback_engine.recover(
                fallback_request,
                base_timeframe=base_timeframe,
                base_duration=base_duration,
                provider_order=("test_primary", "ccxt_binance"),
                provider_symbols={
                    "test_primary": "BTCUSDT",
                    "ccxt_binance": instrument.provider_symbols["ccxt_binance"],
                },
                target_durations={},
                alignment_origin=alignment_origin,
            )
            == ()
        )
        assert await _count(db_pool, fallback_instrument_id, "1m") == 5
        async with db_pool.acquire() as connection:
            fallback_providers = await connection.fetch(
                """
                SELECT DISTINCT source_provider
                FROM ingestion.candles
                WHERE instrument_id = $1
                """,
                fallback_instrument_id,
            )
        assert {row["source_provider"] for row in fallback_providers} == {
            "ccxt_binance"
        }
    finally:
        if native is not None:
            await native.close()
        if ccxt_provider is not None:
            await ccxt_provider.close()
