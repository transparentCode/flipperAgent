"""strategy_app entrypoint — boots StrategyWorker(s) per asset/timeframe from config."""

from __future__ import annotations

import asyncio
import os

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.constants import CONFIG_FILE_MODELS
from libs.common.discovery import discover_pairs
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging
from apps.strategy_app.strategy_worker import StrategyWorker

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)


async def _run_worker(asset: str, tf: str, redis_client) -> None:
    """Run one worker in isolation so a single pair crash does not stop others."""
    try:
        worker = StrategyWorker(asset, tf)
        await worker.connect(redis_client)
        await worker.start()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            f"Strategy worker crashed for {asset}/{tf}; other workers will continue running"
        )


async def _run() -> None:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_MODELS)

    try:
        from libs.common.telemetry.bootstrap import init_telemetry
        init_telemetry("strategy_app")
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

    pairs = discover_pairs(config_mgr)
    if not pairs:
        logger.warning("No asset/timeframe pairs found in models.yaml. Exiting.")
        return

    logger.info(f"Discovered {len(pairs)} asset/timeframe pairs: {pairs}")

    # --- Connection setup ---
    redis_client = await create_valkey_client(config_mgr)

    tasks: list[asyncio.Task] = []
    try:
        for asset, tf in pairs:
            tasks.append(asyncio.create_task(_run_worker(asset, tf, redis_client)))

        await asyncio.gather(*tasks)
    except BaseException:
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        raise
    finally:
        await redis_client.aclose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
