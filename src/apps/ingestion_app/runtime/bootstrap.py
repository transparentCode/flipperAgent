from __future__ import annotations

import asyncio
from typing import Any

from apps.ingestion_app.constants import EXCHANGE_BINANCE
from apps.ingestion_app.coordination import IngestionCoordinator, IngestionState
from apps.ingestion_app.models.asset_registry import IngestionAssetRecord
from apps.ingestion_app.runtime.shared import logger, runtime_stream_timeframes
from apps.ingestion_app.runtime.websocket import verify_and_launch_ws


async def initialize_asset_runtime(
    asset: IngestionAssetRecord,
    arq_pool: Any,
    coordinator: IngestionCoordinator,
    task_registry: set[asyncio.Task[Any]],
) -> None:
    symbol = asset.symbol
    base_timeframe = asset.base_timeframe
    stream_timeframes = list(
        runtime_stream_timeframes(base_timeframe, asset.publish_timeframes)
    )
    try:
        force_backfill = False
        try:
            force_backfill = await coordinator.resume_backfill_required(symbol, base_timeframe)
        except Exception as resume_backfill_error:
            logger.warning(
                f"[{symbol}] resume_backfill_required() check failed ({resume_backfill_error}), "
                "falling back to staleness-only bootstrap."
            )

        try:
            stale = await coordinator.is_stale(symbol, base_timeframe)
        except Exception as stale_error:
            logger.warning(f"[{symbol}] is_stale() check failed ({stale_error}), treating as stale.")
            stale = True

        if force_backfill:
            logger.info(f"[{symbol}] Resume backfill required. Dispatching REST gap-fill before live launch.")
            await arq_pool.enqueue_job("run_rest_gap_fill", [symbol], EXCHANGE_BINANCE)
        elif stale:
            logger.info(f"[{symbol}] Stale/missing data. Dispatching REST gap-fill.")
            await arq_pool.enqueue_job("run_rest_gap_fill", [symbol], EXCHANGE_BINANCE)
        else:
            logger.info(f"[{symbol}] Data is up-to-date. Marking WARMING.")
            await coordinator.transition(
                symbol,
                base_timeframe,
                IngestionState.WARMING,
                reason="history_already_fresh",
                provenance="bootstrap",
            )

        await verify_and_launch_ws(
            symbol,
            stream_timeframes,
            arq_pool,
            coordinator,
            task_registry,
            base_timeframe=base_timeframe,
        )
    except asyncio.CancelledError:
        await coordinator.transition(
            symbol,
            base_timeframe,
            IngestionState.COLD,
            reason="bootstrap_cancelled",
            provenance="bootstrap",
        )
        raise
    except Exception as exc:
        logger.error(f"[{symbol}] Asset runtime bootstrap failed: {exc}", exc_info=True)
        await coordinator.transition(
            symbol,
            base_timeframe,
            IngestionState.ERROR,
            reason="bootstrap_failed",
            provenance="bootstrap",
        )
