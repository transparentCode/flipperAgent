from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.binance_native import (
    BinanceNativeHistoricalProvider,
)
from apps.ingestion_app.services.candle_ingestion import CandleIngestionService
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.settings import load_ingestion_settings
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.repository import (
    CandleCommitStatus,
    CandleRepository,
)
from libs.common.config import ConfigManager

if os.getenv("INGESTION_RUN_HTF_INTEGRATION") != "1":
    pytest.skip(
        "set INGESTION_RUN_HTF_INTEGRATION=1 to run the live HTF test",
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
async def test_instrument_id(db_pool: asyncpg.Pool) -> str:
    instrument_id = f"package_e_{uuid4().hex}"
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


@pytest.mark.asyncio
async def test_real_binance_base_to_htf_parity(
    db_pool: asyncpg.Pool,
    test_instrument_id: str,
) -> None:
    settings = _load_settings()
    instrument = settings.assets["BTC"].instruments["BTC-USDT-PERP"]
    base_timeframe = settings.base_timeframe
    base_duration = timedelta(
        seconds=settings.timeframes[base_timeframe].duration_seconds
    )
    alignment_origin = settings.calendar.alignment_origin
    target_timeframes = ("15m", "30m", "1h", "4h")
    target_durations = {
        timeframe: timedelta(seconds=settings.timeframes[timeframe].duration_seconds)
        for timeframe in target_timeframes
    }
    since = datetime(2026, 8, 8, 8, 0, tzinfo=UTC)
    until = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    base_lane = MarketLane(instrument.venue, test_instrument_id, base_timeframe)
    repository = CandleRepository(db_pool)
    ingestion_service = CandleIngestionService(repository)
    aggregation_service = HTFAggregationService(
        repository=repository,
        ingestion_service=ingestion_service,
    )
    provider = BinanceNativeHistoricalProvider()

    try:
        observations = await provider.fetch_closed_candles(
            lane=base_lane,
            provider_symbol=instrument.provider_symbols["binance_native"],
            timeframe_duration=base_duration,
            since=since,
            until=until,
            limit=240,
        )
        assert len(observations) == 240

        for observation in observations:
            assert (
                await ingestion_service.commit_observation(observation)
                is CandleCommitStatus.INSERTED
            )

        base_candles = await repository.fetch_candles(
            lane=base_lane,
            since=since,
            until=until,
        )
        assert len(base_candles) == 240

        recovery_requests = []
        for candle in base_candles:
            recovery_requests.extend(
                await aggregation_service.process_base_candle(
                    candle,
                    base_duration=base_duration,
                    target_durations=target_durations,
                    alignment_origin=alignment_origin,
                )
            )
        assert recovery_requests == []

        expected_counts = {"15m": 16, "30m": 8, "1h": 4, "4h": 1}
        for timeframe in target_timeframes:
            duration = target_durations[timeframe]
            target_lane = MarketLane(instrument.venue, test_instrument_id, timeframe)
            derived = await repository.fetch_candles(
                lane=target_lane,
                since=since,
                until=until,
            )
            direct = await provider.fetch_closed_candles(
                lane=target_lane,
                provider_symbol=instrument.provider_symbols["binance_native"],
                timeframe_duration=duration,
                since=since,
                until=until,
                limit=expected_counts[timeframe],
            )

            assert len(derived) == expected_counts[timeframe]
            assert len(direct) == expected_counts[timeframe]
            assert [candle.open_time for candle in derived] == [
                observation.open_time for observation in direct
            ]
            for candle, observation in zip(derived, direct, strict=True):
                assert candle.close_time == observation.close_time
                assert candle.open == observation.open
                assert candle.high == observation.high
                assert candle.low == observation.low
                assert candle.close == observation.close
                assert candle.volume == observation.volume
                assert candle.taker_buy_base == observation.taker_buy_base
                assert candle.source_type == "derived"
                assert candle.source_provider is None
                assert candle.source_timeframe == base_timeframe

        weekly_duration = timedelta(weeks=1)
        weekly = await provider.fetch_closed_candles(
            lane=MarketLane(instrument.venue, test_instrument_id, "1w"),
            provider_symbol=instrument.provider_symbols["binance_native"],
            timeframe_duration=weekly_duration,
            since=datetime(2026, 7, 27, tzinfo=UTC),
            until=datetime(2026, 8, 3, tzinfo=UTC),
            limit=1,
        )
        assert len(weekly) == 1
        assert (weekly[0].open_time - alignment_origin) % weekly_duration == timedelta(
            0
        )
    finally:
        await provider.close()
