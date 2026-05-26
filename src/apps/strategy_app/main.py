"""strategy_app entrypoint — boots StrategyWorker(s) per asset/timeframe from config."""

from __future__ import annotations

import asyncio

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging
from apps.strategy_app.strategy_worker import StrategyWorker

CONFIG_FILE_MODELS = "configs/models.yaml"
KEY_MODELS = "models"
KEY_ASSETS = "assets"
KEY_TIMEFRAMES = "timeframes"
KEY_DEFAULT = "default"

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)


def _discover_pairs(config_mgr: ConfigManager) -> list[tuple[str, str]]:
    """Return (asset, timeframe) pairs configured in models.yaml (excluding defaults)."""
    models_config = config_mgr.get(KEY_MODELS, {})
    assets_config = models_config.get(KEY_ASSETS, {})
    pairs: list[tuple[str, str]] = []
    for asset, asset_cfg in assets_config.items():
        if asset == KEY_DEFAULT:
            continue
        if not isinstance(asset_cfg, dict):
            continue
        tfs = asset_cfg.get(KEY_TIMEFRAMES, {})
        for tf in tfs:
            if tf == KEY_DEFAULT:
                continue
            pairs.append((asset, tf))
    return pairs


async def _run() -> None:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_MODELS)

    log_level = config_mgr.get("logging.level", default="INFO")
    configure_logging(level=log_level, enable_file_logging=False)

    pairs = _discover_pairs(config_mgr)
    if not pairs:
        logger.warning("No asset/timeframe pairs found in models.yaml. Exiting.")
        return

    logger.info(f"Discovered {len(pairs)} asset/timeframe pairs: {pairs}")

    # --- Connection setup ---
    redis_client = await create_valkey_client(config_mgr)

    try:
        tasks = []
        for asset, tf in pairs:
            worker = StrategyWorker(asset, tf)
            await worker.connect(redis_client)
            tasks.append(asyncio.create_task(worker.start()))

        await asyncio.gather(*tasks)
    finally:
        await redis_client.aclose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
