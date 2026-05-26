"""portfolio_app entrypoint — discovers assets, spawns PortfolioWorker(s)."""

from __future__ import annotations

import asyncio

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging

from apps.portfolio_app.portfolio_worker import PortfolioWorker

CONFIG_FILE_PORTFOLIO = "configs/portfolio.yaml"
CONFIG_FILE_MODELS = "configs/models.yaml"
KEY_MODELS = "models"
KEY_ASSETS = "assets"
KEY_DEFAULT = "default"

logger = bind_logger(__name__, system_component=SystemComponent.PORTFOLIO_TRACKER)


def _discover_assets(config_mgr: ConfigManager) -> list[str]:
    """Read models.yaml to find all asset symbols."""
    models_config = config_mgr.get(KEY_MODELS, {})
    assets_config = models_config.get(KEY_ASSETS, {})
    result: list[str] = []

    for asset, asset_cfg in assets_config.items():
        if asset == KEY_DEFAULT:
            continue
        if not isinstance(asset_cfg, dict):
            continue
        result.append(asset)

    return result


async def _run() -> None:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_PORTFOLIO)
    config_mgr.register_file(CONFIG_FILE_MODELS)

    log_level = config_mgr.get("logging.level", default="INFO")
    configure_logging(level=log_level, enable_file_logging=False)

    assets = _discover_assets(config_mgr)
    logger.info(f"Portfolio tracker assets: {assets}")

    # DB pool setup (same pattern as risk_app)
    db_pool = None  # TODO: create asyncpg pool from config

    # Valkey client setup
    redis_client = None  # TODO: create redis.asyncio client from config

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

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logger.info("Portfolio app shutting down")


if __name__ == "__main__":
    asyncio.run(_run())
