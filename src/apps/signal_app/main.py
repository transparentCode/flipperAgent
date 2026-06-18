"""signal_app entrypoint — boots modular runtime workers from config."""

from __future__ import annotations

import asyncio
import os

from apps.signal_app.catalog import SignalPairCatalog
from apps.signal_app.runtime_pairs import build_signal_pairs
from apps.signal_app.runtime.runner import SignalRuntimeRunner
from libs.common.config import ConfigManager
from libs.common.asset_manifest import AssetManifestStore
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.constants import CONFIG_FILE_FEATURES, CONFIG_FILE_MODELS
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging
from apps.signal_app.settings import SignalWorkerSettings

logger = bind_logger(__name__, system_component=SystemComponent.SIGNAL_APP)


async def _run() -> None:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_MODELS)
    config_mgr.register_file(CONFIG_FILE_FEATURES)

    try:
        from libs.common.telemetry.bootstrap import init_telemetry
        init_telemetry("signal_app")
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

    await init_db_pools(config_mgr)
    redis_client = await create_valkey_client(config_mgr)
    full_catalog = SignalPairCatalog(config_manager=config_mgr)
    manifest_store = AssetManifestStore(redis_client)
    manifest_assets = await manifest_store.list_assets()
    resolved_pairs = build_signal_pairs(
        config_mgr,
        live_manifests=manifest_assets if manifest_assets else None,
    )
    if not resolved_pairs:
        logger.warning("No asset/timeframe pairs found in canonical manifest or models.yaml. Exiting.")
        await redis_client.aclose()
        await DBPoolManager.close_pools()
        return

    runner = SignalRuntimeRunner(
        catalog=full_catalog,
        initial_pairs=resolved_pairs,
        worker_settings=SignalWorkerSettings.from_config(config_mgr),
    )
    logger.info(
        "Discovered %s signal asset/timeframe pairs from %s: %s",
        len(resolved_pairs),
        "asset manifest" if manifest_assets else "models.yaml",
        [
            (
                pair.asset,
                pair.timeframe,
                pair.trigger_timeframe or pair.timeframe,
                pair.trigger_mode,
                pair.base_timeframe,
                list(pair.required_context_profiles),
            )
            for pair in resolved_pairs
        ],
    )

    try:
        await runner.connect(redis_client)
        await runner.start()
    finally:
        await runner.stop()
        await redis_client.aclose()
        await DBPoolManager.close_pools()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
