import logging
from typing import Dict, Any

from arq.connections import RedisSettings

# Local imports
from libs.common.config import ConfigManager
from libs.common.logging.logger_utils import bind_logger
from libs.common.enums import SystemComponent
from libs.common.db.pool_manager import DBPoolManager
from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from apps.ingestion_app.adapters.crypto_ccxt import CCXTAdapter
from apps.ingestion_app.constants import EXCHANGE_BINANCE
from .tasks import poll_binance_ohlcv, poll_funding_rates, run_rest_gap_fill, scheduled_gap_fill
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
        binance_adapter = BinanceNativeAdapter(key="", secret="")
        ccxt_gateway = CCXTAdapter(exchange_id=EXCHANGE_BINANCE)
        
        ctx["binance_adapter"] = binance_adapter
        ctx["ccxt_adapter"] = ccxt_gateway
        
        # Initialize Shared DB pools
        await DBPoolManager.init_pools()
        # Tasks can grab the pool via DBPoolManager.get_writer_pool() or similar
        logger.info("Adapters and shared DB pools successfully loaded into worker context.")
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
    
    logger.info("Worker shutdown complete.")


class WorkerSettings:
    """
    Settings for the arq worker. 
    Valkey connects seamlessly via arq's RedisSettings.
    """
    functions = [
        poll_binance_ohlcv,
        poll_funding_rates,
        run_rest_gap_fill,
        scheduled_gap_fill,
    ]
    
    cron_jobs = IngestionScheduler().get_cron_jobs()
    
    on_startup = startup
    on_shutdown = shutdown
    
    # Example Valkey/Redis connection string
    # E.g. valkey container defined in docker-compose at localhost:6379
    redis_settings = RedisSettings.from_dsn(
        config_manager.get("redis.uri", "redis://localhost:6379/0")
    )
    
    # Maximum concurrent tasks processed by this worker
    max_jobs = config_manager.get("ingestion.concurrency.worker_max_jobs", 20)
    
    # Job execution timeout bounds
    job_timeout = config_manager.get("ingestion.concurrency.worker_job_timeout", 300)
    
    # Concurrency and event loop
    allow_abort_jobs = True
