from __future__ import annotations

import asyncio
import copy
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from apps.ingestion_app.providers.binance_native import (
    BinanceNativeHistoricalProvider,
)
from apps.ingestion_app.providers.ccxt import CCXTHistoricalProvider
from apps.ingestion_app.runtime.supervisor import RuntimeSupervisor
from apps.ingestion_app.runtime.websocket import BinanceWebSocketManager
from apps.ingestion_app.services.candle_ingestion import CandleIngestionService
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.services.recovery import RecoveryEngine
from apps.ingestion_app.settings import (
    IngestionSettings,
    load_ingestion_settings,
)
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.repository import CandleRepository
from libs.common.config import ConfigManager

if os.getenv("INGESTION_RUN_RUNTIME_INTEGRATION") != "1":
    pytest.skip(
        "set INGESTION_RUN_RUNTIME_INTEGRATION=1 to run the live runtime test",
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


def _load_settings() -> IngestionSettings:
    repository_root = Path(__file__).parents[3]
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(repository_root / "configs"))
    try:
        return load_ingestion_settings(manager)
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


def _unique_runtime_settings(
    settings: IngestionSettings,
    instrument_id: str,
) -> IngestionSettings:
    raw = copy.deepcopy(settings.model_dump())
    instrument = raw["assets"]["BTC"]["instruments"].pop("BTC-USDT-PERP")
    instrument["timeframes"] = [settings.base_timeframe]
    raw["assets"]["BTC"]["instruments"] = {instrument_id: instrument}
    return IngestionSettings.model_validate(raw)


class _RecordingIngestion:
    def __init__(self, delegate: CandleIngestionService) -> None:
        self.delegate = delegate
        self.websocket_observations = []

    async def commit_observation(self, observation):
        if observation.transport == "websocket":
            self.websocket_observations.append(observation)
        return await self.delegate.commit_observation(observation)

    async def commit_candle(self, candle):
        return await self.delegate.commit_candle(candle)


@pytest.mark.asyncio
async def test_runtime_supervisor_live_smoke(
    db_pool: asyncpg.Pool,
) -> None:
    base_settings = _load_settings()
    instrument_id = f"package_h_{uuid4().hex}"
    settings = _unique_runtime_settings(base_settings, instrument_id)
    instrument = settings.assets["BTC"].instruments[instrument_id]

    native: BinanceNativeHistoricalProvider | None = None
    ccxt_provider: CCXTHistoricalProvider | None = None
    supervisor: RuntimeSupervisor | None = None
    run_task: asyncio.Task[None] | None = None
    repository = CandleRepository(db_pool)

    try:
        native = BinanceNativeHistoricalProvider()
        ccxt_settings = settings.providers["ccxt_binance"]
        assert ccxt_settings.exchange_id is not None
        ccxt_provider = CCXTHistoricalProvider(
            provider_id="ccxt_binance",
            exchange_id=ccxt_settings.exchange_id,
        )
        ingestion = _RecordingIngestion(CandleIngestionService(repository))
        htf_service = HTFAggregationService(
            repository=repository,
            ingestion_service=ingestion,  # type: ignore[arg-type]
        )
        recovery = settings.recovery
        recovery_engine = RecoveryEngine(
            providers={
                "binance_native": native,
                "ccxt_binance": ccxt_provider,
            },
            repository=repository,
            ingestion_service=ingestion,  # type: ignore[arg-type]
            htf_service=htf_service,
            max_concurrency=recovery.max_concurrency,
            page_limit=recovery.page_limit,
            max_attempts_per_provider=recovery.max_attempts_per_provider,
            retry_backoff_seconds=recovery.retry_backoff_seconds,
            rest_finalization_grace_seconds=recovery.rest_finalization_grace_seconds,
        )
        live_provider = BinanceWebSocketManager(
            stream_url=settings.websocket.stream_url,
            queue_maxsize=settings.websocket.queue_maxsize,
        )
        supervisor = RuntimeSupervisor(
            settings=settings,
            live_provider=live_provider,
            repository=repository,
            ingestion_service=ingestion,  # type: ignore[arg-type]
            htf_service=htf_service,
            recovery_engine=recovery_engine,
        )

        run_task = asyncio.create_task(supervisor.run())
        try:
            await asyncio.wait_for(
                _wait_for_websocket_observation(ingestion),
                timeout=180,
            )
        finally:
            supervisor.stop()
            await asyncio.wait_for(run_task, timeout=15)

        assert len(ingestion.websocket_observations) >= 1
        observation = ingestion.websocket_observations[0]
        assert observation.provider_id == instrument.live_provider
        assert (
            observation.provider_symbol == instrument.provider_symbols["binance_native"]
        )
        assert observation.transport == "websocket"

        async with db_pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT source_type, source_provider
                FROM ingestion.candles
                WHERE instrument_id = $1
                  AND timeframe = $2
                  AND open_time = $3
                """,
                instrument_id,
                settings.base_timeframe,
                observation.open_time,
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
        assert row is not None
        assert dict(row) == {
            "source_type": "provider",
            "source_provider": "binance_native",
        }
        assert candle_count >= 2
        assert outbox_count >= 2
        assert supervisor.snapshot().state.value == "stopped"
    finally:
        if supervisor is not None:
            supervisor.stop()
        if run_task is not None and not run_task.done():
            await run_task
        if ccxt_provider is not None:
            await ccxt_provider.close()
        if native is not None:
            await native.close()
        async with db_pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "DELETE FROM ingestion.outbox WHERE payload->>'instrument_id' = $1",
                instrument_id,
            )
            await connection.execute(
                "DELETE FROM ingestion.candles WHERE instrument_id = $1",
                instrument_id,
            )
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


async def _wait_for_websocket_observation(
    recording_ingestion: _RecordingIngestion,
) -> None:
    while not recording_ingestion.websocket_observations:
        await asyncio.sleep(0.1)
