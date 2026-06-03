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

from apps.execution_app.execution_worker import ExecutionWorker

KEY_EXECUTION = "execution"

logger = bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)


async def _supervise_worker(
    label: str,
    build_worker,
    redis_client,
    restart_delay_seconds: int = 5,
) -> None:
    """Restart a worker if it exits or crashes unexpectedly."""
    while True:
        worker = build_worker()
        await worker.connect(redis_client)
        try:
            await worker.start()
            logger.error(
                f"{label} exited unexpectedly; restarting in {restart_delay_seconds}s",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                f"{label} crashed; restarting in {restart_delay_seconds}s",
            )
        await asyncio.sleep(restart_delay_seconds)


async def _run() -> None:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_EXECUTION)
    config_mgr.register_file(CONFIG_FILE_MODELS)

    try:
        from libs.common.telemetry.bootstrap import init_telemetry
        init_telemetry("execution_app")
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
    max_memory_keys = idem_cfg.get("max_memory_keys", 10_000)
    persist_to_db = idem_cfg.get("persist_to_db", False)

    # Restore idempotency keys from DB if persistence is enabled.
    # This prevents re-executing orders that were already filled but whose
    # stream messages were unacked at crash time (still in the PEL).
    if persist_to_db:
        try:
            reader_pool = DBPoolManager.get_reader_pool()
            idempotency_store = await IdempotencyStore.load(reader_pool, max_size=max_memory_keys)
            logger.info(f"Restored {len(idempotency_store._seen)} idempotency keys from DB")
        except Exception:
            logger.warning("Could not load idempotency keys from DB — starting empty", exc_info=True)
            idempotency_store = IdempotencyStore(max_size=max_memory_keys)
    else:
        idempotency_store = IdempotencyStore(max_size=max_memory_keys)

    fill_tracker = FillTracker()
    writer_pool = DBPoolManager.get_writer_pool()
    restart_delay_seconds = exec_config.get("consumer_restart_delay_seconds", 5)

    tasks: list[asyncio.Task] = []
    try:
        # Spawn one ExecutionWorker per asset
        for asset in assets:
            tasks.append(
                asyncio.create_task(
                    _supervise_worker(
                        label=f"ExecutionWorker[{asset}]",
                        build_worker=lambda asset=asset: ExecutionWorker(
                            asset=asset,
                            order_manager=OrderManager(
                                executor=executor,
                                idempotency_store=idempotency_store,
                                fill_tracker=fill_tracker,
                                db_pool=writer_pool,
                            ),
                            exec_config=exec_config,
                        ),
                        redis_client=redis_client,
                        restart_delay_seconds=restart_delay_seconds,
                    ),
                ),
            )

        await asyncio.gather(*tasks)
    except BaseException:
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        raise
    finally:
        # Persist idempotency keys so the next startup can dedup PEL replays.
        if persist_to_db:
            try:
                writer_pool = DBPoolManager.get_writer_pool()
                await idempotency_store.save(writer_pool)
                logger.info("Idempotency keys persisted to DB")
            except Exception:
                logger.warning("Could not persist idempotency keys to DB", exc_info=True)

        await redis_client.aclose()
        await DBPoolManager.close_pools()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
