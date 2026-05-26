"""execution_app entrypoint — discovers assets, spawns ExecutionWorker(s)."""

from __future__ import annotations

import asyncio

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging
from libs.execution.fill_tracker import FillTracker
from libs.execution.idempotency import IdempotencyStore
from libs.execution.order_manager import OrderManager
from libs.execution.paper_executor import PaperExecutor
from libs.execution.binance_executor import BinanceExecutor

from apps.execution_app.execution_worker import ExecutionWorker

CONFIG_FILE_EXECUTION = "configs/execution.yaml"
CONFIG_FILE_MODELS = "configs/models.yaml"
KEY_MODELS = "models"
KEY_ASSETS = "assets"
KEY_DEFAULT = "default"
KEY_EXECUTION = "execution"

logger = bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)


def _discover_assets(config_mgr: ConfigManager) -> list[str]:
    """Read models.yaml to find all assets."""
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
    config_mgr.register_file(CONFIG_FILE_EXECUTION)
    config_mgr.register_file(CONFIG_FILE_MODELS)

    log_level = config_mgr.get("logging.level", default="INFO")
    configure_logging(level=log_level, enable_file_logging=False)

    # Discover assets from models.yaml
    assets = _discover_assets(config_mgr)
    if not assets:
        logger.warning("No assets found in models.yaml. Exiting.")
        return

    logger.info(f"Discovered {len(assets)} assets: {assets}")

    # --- Connection setup ---
    await init_db_pools(config_mgr)
    redis_client = await create_valkey_client(config_mgr)

    # Load execution config
    exec_config = config_mgr.get(KEY_EXECUTION, {})
    mode = exec_config.get("mode", "paper")

    # Build executor
    if mode == "paper":
        paper_cfg = exec_config.get("paper", {})
        executor = PaperExecutor(
            slippage_bps=paper_cfg.get("slippage_bps", 5.0),
            slippage_jitter_bps=paper_cfg.get("slippage_jitter_bps", 2.0),
            commission_bps=paper_cfg.get("commission_bps", 4.0),
            fill_delay_ms=paper_cfg.get("fill_delay_ms", 50.0),
        )
        logger.info("Using PaperExecutor")
    elif mode == "live":
        executor = BinanceExecutor()
        logger.info("Using BinanceExecutor (stub)")
    else:
        logger.error(f"Unknown execution mode: {mode}")
        return

    # Build shared components
    idem_cfg = exec_config.get("idempotency", {})
    idempotency_store = IdempotencyStore(
        max_size=idem_cfg.get("max_memory_keys", 10_000),
    )
    fill_tracker = FillTracker()
    order_manager = OrderManager(
        executor=executor,
        idempotency_store=idempotency_store,
        fill_tracker=fill_tracker,
    )

    try:
        # Spawn one ExecutionWorker per asset
        tasks = []
        for asset in assets:
            worker = ExecutionWorker(
                asset=asset,
                order_manager=order_manager,
                exec_config=exec_config,
            )
            await worker.connect(redis_client)
            tasks.append(asyncio.create_task(worker.start()))

        await asyncio.gather(*tasks)
    finally:
        await redis_client.aclose()
        await DBPoolManager.close_pools()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
