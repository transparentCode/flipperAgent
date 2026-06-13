from __future__ import annotations

import asyncio
from typing import Any

from apps.ingestion_app.constants import EXCHANGE_BINANCE
from apps.ingestion_app.coordination import IngestionCoordinator, IngestionState
from apps.ingestion_app.models.asset_registry import IngestionAssetRecord
from apps.ingestion_app.runtime.shared import logger
from apps.ingestion_app.runtime.websocket import verify_and_launch_ws


async def initialize_asset_runtime(
    asset: IngestionAssetRecord,
    arq_pool: Any,
    coordinator: IngestionCoordinator,
    task_registry: set[asyncio.Task[Any]],
) -> None:
    symbol = asset.symbol
    base_timeframe = asset.base_timeframe
    try:
        try:
            stale = await coordinator.is_stale(symbol, base_timeframe)
        except Exception as stale_error:
            logger.warning(f"[{symbol}] is_stale() check failed ({stale_error}), treating as stale.")
            stale = True

        if stale:
            logger.info(f"[{symbol}] Stale/missing data. Dispatching REST gap-fill.")
            await arq_pool.enqueue_job("run_rest_gap_fill", [symbol], EXCHANGE_BINANCE)
        else:
            logger.info(f"[{symbol}] Data is up-to-date. Marking WARMING.")
            await coordinator.transition(symbol, base_timeframe, IngestionState.WARMING)

        await verify_and_launch_ws(
            symbol,
            list(asset.publish_timeframes),
            arq_pool,
            coordinator,
            task_registry,
        )
    except asyncio.CancelledError:
        await coordinator.transition(symbol, base_timeframe, IngestionState.COLD)
        raise
    except Exception as exc:
        logger.error(f"[{symbol}] Asset runtime bootstrap failed: {exc}", exc_info=True)
        await coordinator.transition(symbol, base_timeframe, IngestionState.ERROR)
