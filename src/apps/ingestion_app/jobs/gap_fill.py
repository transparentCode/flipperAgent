from __future__ import annotations

import asyncio
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from apps.ingestion_app.constants import EXCHANGE_BINANCE
from apps.ingestion_app.coordination import IngestionCoordinator, IngestionState
from apps.ingestion_app.events import publish_ingestion_runtime_event
from apps.ingestion_app.storage.timescale_writer import TimescaleWriter
from libs.common.db.pool_manager import DBPoolManager
from libs.common.db.timescale_reader import TimescaleReader
from libs.common.enums import SystemComponent
from libs.common.exceptions import DataIngestionError
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.schemas import IngestionEventType

from apps.ingestion_app.jobs.shared import (
    build_ohlcv_records,
    config_manager,
    list_schedulable_symbols,
    require_context_value,
    utc_now_ms,
)

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)


@retry(
    retry=retry_if_exception_type(DataIngestionError),
    stop=stop_after_attempt(5),
    wait=wait_exponential(min=4, max=60),
    reraise=True,
)
async def _fetch_asset_gap(ctx: dict[str, Any], ccxt_adapter: Any, symbol: str) -> None:
    logger.info(f"Fetching REST data for asset: {symbol}")

    historical_backfill_days = config_manager.get("ingestion.assets.historical_backfill_days", 2)
    base_timeframe = config_manager.get("ingestion.timeframes.base_gap_fill", "1m")
    since_ms = utc_now_ms() - historical_backfill_days * 86400 * 1000

    try:
        reader = TimescaleReader(DBPoolManager.get_reader_pool())
        max_ts = await reader.get_max_timestamp(symbol, base_timeframe)
        start_ts = max(since_ms, max_ts) if max_ts > 0 else since_ms
    except RuntimeError:
        logger.warning("DB reader pool not initialized. Starting from backfill days.")
        start_ts = since_ms

    try:
        ts_writer = TimescaleWriter(DBPoolManager.get_writer_pool())
    except RuntimeError as exc:
        raise DataIngestionError(
            f"DB writer pool not initialized — cannot persist gap-fill for {symbol}",
            context={"symbol": symbol},
        ) from exc

    limit = 1000
    sleep_seconds = config_manager.get("ingestion.concurrency.gap_fill_sleep_seconds", 0.5)

    while True:
        try:
            frame = await ccxt_adapter.get_historical_ohlcv(symbol, base_timeframe, since=start_ts, limit=limit)
            if frame.empty:
                logger.info(f"No more data returned for {symbol}.")
                break

            records = build_ohlcv_records(symbol, frame)
            if records:
                await ts_writer.insert_ohlcv(records, timeframe=base_timeframe)

            if len(frame) < limit:
                break

            start_ts = int(frame.iloc[-1]["timestamp"]) + 1
            await asyncio.sleep(sleep_seconds)
        except Exception as exc:
            logger.error(f"Error fetching page for {symbol} at {start_ts}: {exc}")
            raise


async def run_rest_gap_fill(ctx: dict[str, Any], assets: list[str], exchange: str) -> None:
    logger.info(f"Task run_rest_gap_fill started for exchange {exchange} with {len(assets)} assets")

    ccxt_adapter = require_context_value(
        ctx,
        "ccxt_adapter",
        error_message="ccxt adapter not found in worker context",
        context={"exchange": exchange, "assets": assets},
    )
    coordinator: IngestionCoordinator = require_context_value(
        ctx,
        "coordinator",
        error_message="coordinator not found in worker context — state machine cannot progress",
        context={"exchange": exchange, "assets": assets},
    )
    valkey_client = ctx.get("valkey_client")
    base_timeframe = config_manager.get("ingestion.timeframes.base_gap_fill", "1m")
    concurrency_limit = config_manager.get("ingestion.concurrency.gap_fill_limit", 5)
    sleep_seconds = config_manager.get("ingestion.concurrency.gap_fill_sleep_seconds", 0.5)

    semaphore = asyncio.Semaphore(concurrency_limit)
    successful_assets: list[str] = []
    failed_assets: list[str] = []

    async def process_asset(symbol: str) -> None:
        async with semaphore:
            await coordinator.transition(symbol, base_timeframe, IngestionState.BACKFILLING)
            try:
                await _fetch_asset_gap(ctx, ccxt_adapter, symbol)
                await coordinator.clear_resume_backfill_required(symbol, base_timeframe)
                await coordinator.transition(symbol, base_timeframe, IngestionState.WARMING)
                successful_assets.append(symbol)
            except Exception as exc:
                logger.error(f"Failed to gap-fill {symbol}: {exc}")
                await coordinator.transition(symbol, base_timeframe, IngestionState.ERROR)
                failed_assets.append(symbol)
            await asyncio.sleep(sleep_seconds)

    await asyncio.gather(*(process_asset(symbol) for symbol in assets))
    if failed_assets:
        await publish_ingestion_runtime_event(
            valkey_client,
            event_type=IngestionEventType.GAP_FILL_FAILED,
            symbol=exchange.upper(),
            timeframe=base_timeframe,
            severity="error",
            detail={
                "exchange": exchange,
                "successful_assets": successful_assets,
                "failed_assets": failed_assets,
                "asset_count": len(assets),
            },
        )
        logger.warning(
            "Gap fill completed with failures for %s. succeeded=%s failed=%s failed_assets=%s",
            exchange,
            len(successful_assets),
            len(failed_assets),
            failed_assets,
        )
        raise DataIngestionError(
            f"Gap fill incomplete for {exchange}",
            context={
                "exchange": exchange,
                "successful_assets": successful_assets,
                "failed_assets": failed_assets,
                "asset_count": len(assets),
            },
        )

    await publish_ingestion_runtime_event(
        valkey_client,
        event_type=IngestionEventType.GAP_FILL_COMPLETED,
        symbol=exchange.upper(),
        timeframe=base_timeframe,
        severity="info",
        detail={
            "exchange": exchange,
            "successful_assets": successful_assets,
            "asset_count": len(successful_assets),
        },
    )
    logger.info(f"Gap fill task completed successfully for {exchange}.")


async def scheduled_gap_fill(ctx: dict[str, Any]) -> None:
    target_list = await list_schedulable_symbols()
    if not target_list:
        logger.info("scheduled_gap_fill skipped: no schedulable assets.")
        return
    await run_rest_gap_fill(ctx, target_list, EXCHANGE_BINANCE)
