from __future__ import annotations

from typing import Any

from apps.ingestion_app.bootstrap import (
    build_redis_settings,
    cleanup_worker_context,
    populate_worker_context,
)
from apps.ingestion_app.jobs import (
    poll_binance_ohlcv,
    poll_l2_depth,
    purge_removed_asset,
    run_rest_gap_fill,
    scheduled_asset_cleanup,
    scheduled_gap_fill,
)
from apps.ingestion_app.schedules import IngestionScheduler
from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

config_manager = ConfigManager()
logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)


async def startup(ctx: dict[str, Any]) -> None:
    logger.info("Initializing arq worker and external connections...")
    try:
        await populate_worker_context(ctx, config_manager)
        logger.info("Adapters, DB pools, and coordinator loaded into worker context.")
    except Exception as exc:
        logger.error(f"Failed to initialize resources during startup: {exc}")
        await cleanup_worker_context(ctx)
        raise


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("Shutting down arq worker, cleaning up resources...")
    await cleanup_worker_context(ctx)
    logger.info("Worker shutdown complete.")


class WorkerSettings:
    functions = [
        poll_binance_ohlcv,
        run_rest_gap_fill,
        scheduled_gap_fill,
        poll_l2_depth,
        purge_removed_asset,
        scheduled_asset_cleanup,
    ]
    cron_jobs = IngestionScheduler().get_cron_jobs()
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = build_redis_settings(config_manager)
    max_jobs = config_manager.get("ingestion.concurrency.worker_max_jobs", 20)
    job_timeout = config_manager.get("ingestion.concurrency.worker_job_timeout", 300)
    allow_abort_jobs = True
