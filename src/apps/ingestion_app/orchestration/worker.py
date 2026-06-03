import os
from typing import Dict, Any

from arq.connections import RedisSettings

# Local imports
from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from apps.ingestion_app.adapters.crypto_ccxt import CCXTAdapter
from apps.ingestion_app.constants import EXCHANGE_BINANCE
from apps.ingestion_app.coordination import IngestionCoordinator
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger
from .tasks import poll_binance_ohlcv, run_rest_gap_fill, scheduled_gap_fill
from .schedules import IngestionScheduler

config_manager = ConfigManager()

logger = bind_logger(__name__, system_component=SystemComponent.DATA_INGESTION_ENGINE)

async def startup(ctx: Dict[str, Any]) -> None:
    """
    Worker startup hook.
    Initializes database handles (TimescaleDB) and extraction adapters.
    Adds them to the `ctx` dictionary so tasks can access them.
    """
    logger.info("Initializing arq worker and external connections...")
    
    # Initialize adapters
    # For now, using mock API keys or unauthenticated mode as defaults mapping
    # to what's defined in the adapters module.
    try:
        binance_key = config_manager.get("ingestion.credentials.api_key", "")
        binance_secret = config_manager.get("ingestion.credentials.api_secret", "")
        binance_adapter = BinanceNativeAdapter(key=binance_key, secret=binance_secret)
        ccxt_gateway = CCXTAdapter(exchange_id=EXCHANGE_BINANCE)

        ctx["binance_adapter"] = binance_adapter
        ctx["ccxt_adapter"] = ccxt_gateway

        # Initialize Shared DB pools
        await DBPoolManager.init_pools(config_manager=config_manager)
        await apply_ingestion_schema(DBPoolManager.get_writer_pool())

        # Valkey client + coordinator for cross-service state management
        valkey_client = await create_valkey_client(config_manager)
        ctx["valkey_client"] = valkey_client
        ctx["coordinator"] = IngestionCoordinator(valkey_client, config_manager)

        logger.info("Adapters, DB pools, and coordinator loaded into worker context.")
    except Exception as e:
        logger.error(f"Failed to initialize resources during startup: {e}")
        raise

async def shutdown(ctx: Dict[str, Any]) -> None:
    """
    Worker shutdown hook.
    Cleanly closes connections to DBs and terminates WS background loops.
    """
    logger.info("Shutting down arq worker, cleaning up resources...")
    
    await DBPoolManager.close_pools()

    ccxt_adapter = ctx.get("ccxt_adapter")
    if ccxt_adapter:
        await ccxt_adapter.close()

    valkey_client = ctx.get("valkey_client")
    if valkey_client:
        await valkey_client.aclose()

    logger.info("Worker shutdown complete.")


class WorkerSettings:
    """
    Settings for the arq worker. 
    Valkey connects seamlessly via arq's RedisSettings.
    """
    functions = [
        poll_binance_ohlcv,
        run_rest_gap_fill,
        scheduled_gap_fill,
    ]
    
    cron_jobs = IngestionScheduler().get_cron_jobs()
    
    on_startup = startup
    on_shutdown = shutdown
    
    # Respect VALKEY_URI / REDIS_URI env vars (Docker override) before falling back to config
    redis_settings = RedisSettings.from_dsn(
        os.getenv("VALKEY_URI") or os.getenv("REDIS_URI")
        or config_manager.get("valkey.uri", "redis://localhost:6379/0")
    )
    
    # Maximum concurrent tasks processed by this worker
    max_jobs = config_manager.get("ingestion.concurrency.worker_max_jobs", 20)
    
    # Job execution timeout bounds
    job_timeout = config_manager.get("ingestion.concurrency.worker_job_timeout", 300)
    
    # Concurrency and event loop
    allow_abort_jobs = True
