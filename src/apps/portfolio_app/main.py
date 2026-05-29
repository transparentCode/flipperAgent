"""portfolio_app entrypoint — discovers assets, spawns PortfolioWorker(s)."""

from __future__ import annotations

import asyncio
import os

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.constants import CONFIG_FILE_PORTFOLIO, CONFIG_FILE_MODELS
from libs.common.db.pool_manager import DBPoolManager
from libs.common.discovery import discover_assets
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging

from apps.portfolio_app.portfolio_worker import PortfolioWorker

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


async def _run() -> None:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_PORTFOLIO)
    config_mgr.register_file(CONFIG_FILE_MODELS)

    try:
        from libs.common.telemetry.bootstrap import init_telemetry
        init_telemetry("portfolio_app")
    except ImportError:
        pass

    log_level = config_mgr.get("logging.level", default="INFO")
    configure_logging(
        level=log_level,
        enable_file_logging=True,
        console_format=os.environ.get("LOG_FORMAT", "json"),
        log_file=os.environ.get("LOG_FILE"),
    )
    try:
        from libs.common.telemetry.bootstrap import attach_otel_log_handler
        attach_otel_log_handler()
    except ImportError:
        pass

    assets = discover_assets(config_mgr)
    logger.info(f"Portfolio tracker assets: {assets}")

    # --- Connection setup ---
    await init_db_pools(config_mgr)
    redis_client = await create_valkey_client(config_mgr)
    db_pool = DBPoolManager.get_writer_pool()

    try:
        workers: list[PortfolioWorker] = []
        tasks: list[asyncio.Task] = []

        for asset in assets:
            worker = PortfolioWorker(
                asset=asset,
                db_pool=db_pool,
                config_mgr=config_mgr,
            )
            await worker.connect(redis_client)
            workers.append(worker)
            tasks.append(asyncio.create_task(worker.start()))

        logger.info(f"Spawned {len(tasks)} portfolio workers")

        await asyncio.gather(*tasks)
    except BaseException:
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        raise
    finally:
        await redis_client.aclose()
        await DBPoolManager.close_pools()


if __name__ == "__main__":
    asyncio.run(_run())
