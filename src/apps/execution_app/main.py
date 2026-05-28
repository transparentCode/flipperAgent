"""execution_app entrypoint — discovers assets, spawns ExecutionWorker(s)."""

from __future__ import annotations

import asyncio
import os

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.constants import CONFIG_FILE_EXECUTION, CONFIG_FILE_MODELS
from libs.common.db.pool_manager import DBPoolManager
from libs.common.discovery import discover_assets
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging
from libs.execution.fill_tracker import FillTracker
from libs.execution.idempotency import IdempotencyStore
from libs.execution.order_manager import OrderManager
from libs.execution.paper_executor import PaperExecutor
from libs.execution.binance_executor import BinanceExecutor

from apps.execution_app.execution_worker import ExecutionWorker

KEY_EXECUTION = "execution"

logger = bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)


async def _run() -> None:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_EXECUTION)
    config_mgr.register_file(CONFIG_FILE_MODELS)

    log_level = config_mgr.get("logging.level", default="INFO")
    configure_logging(
        level=log_level,
        enable_file_logging=True,
        console_format=os.environ.get("LOG_FORMAT", "json"),
        log_file=os.environ.get("LOG_FILE"),
    )

    # Discover assets from models.yaml
    assets = discover_assets(config_mgr)
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
            seed=paper_cfg.get("seed", 42),
        )
        logger.info("Using PaperExecutor")
    elif mode == "live":
        raise NotImplementedError(
            "Live execution is not yet implemented. "
            "Set execution.mode to 'paper' in configs/execution.yaml"
        )
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
