"""strategy_app entrypoint — boots StrategyWorker(s) per asset/timeframe from config."""

from __future__ import annotations

import asyncio
import os

from apps.strategy_app.runtime import StrategyRuntimeRunner
from apps.strategy_app.state import StrategyPair
from apps.strategy_app.settings import StrategyWorkerSettings, create_strategy_config_manager
from libs.common.asset_manifest import AssetManifestStore
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.discovery import discover_pairs
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)


async def _run() -> None:
    config_mgr = create_strategy_config_manager(ConfigManager())

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

    redis_client = await create_valkey_client(config_mgr)
    settings = StrategyWorkerSettings.from_config(config_mgr)
    manifest_pairs = await AssetManifestStore(redis_client).list_runtime_pairs()
    pairs = manifest_pairs or discover_pairs(config_mgr)
    if not pairs:
        logger.warning("No asset/timeframe pairs found in canonical manifest or models.yaml. Exiting.")
        await redis_client.aclose()
        return

    logger.info(
        "Discovered %s strategy asset/timeframe pairs from %s: %s",
        len(pairs),
        "asset manifest" if manifest_pairs else "models.yaml",
        pairs,
    )

    runner = StrategyRuntimeRunner(
        [StrategyPair(asset=asset, timeframe=tf, source="asset_manifest" if manifest_pairs else "config") for asset, tf in pairs],
        config_manager=config_mgr,
        worker_settings=settings,
    )
    try:
        await runner.connect(redis_client)
        await runner.start()
    finally:
        await runner.stop()
        await redis_client.aclose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
