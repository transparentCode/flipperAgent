"""Bootstrap helpers for execution_app."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.constants import CONFIG_FILE_EXECUTION, CONFIG_FILE_MODELS
from libs.common.db.pool_manager import DBPoolManager
from libs.common.discovery import discover_assets
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging

KEY_EXECUTION = "execution"

logger = bind_logger(__name__, system_component=SystemComponent.TRADE_EXECUTION)


@dataclass(slots=True)
class ExecutionBootstrapContext:
    config_mgr: ConfigManager
    assets: list[str]
    redis_client: Any | None
    writer_pool: Any | None
    exec_config: dict[str, Any]
    restart_delay_seconds: int


def build_config_manager() -> ConfigManager:
    config_mgr = ConfigManager()
    config_mgr.register_file(CONFIG_FILE_EXECUTION)
    config_mgr.register_file(CONFIG_FILE_MODELS)
    return config_mgr


def configure_execution_logging(config_mgr: ConfigManager) -> None:
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


async def bootstrap_execution_app() -> ExecutionBootstrapContext:
    config_mgr = build_config_manager()
    configure_execution_logging(config_mgr)

    assets = discover_assets(config_mgr)
    if not assets:
        logger.warning("No assets found in models.yaml. Exiting.")
        return ExecutionBootstrapContext(
            config_mgr=config_mgr,
            assets=[],
            redis_client=None,
            writer_pool=None,
            exec_config=config_mgr.get(KEY_EXECUTION, {}),
            restart_delay_seconds=5,
        )

    logger.info("Discovered %s assets: %s", len(assets), assets)

    await init_db_pools(config_mgr)
    redis_client = await create_valkey_client(config_mgr)
    writer_pool = DBPoolManager.get_writer_pool()
    exec_config = config_mgr.get(KEY_EXECUTION, {})
    restart_delay_seconds = exec_config.get("consumer_restart_delay_seconds", 5)

    return ExecutionBootstrapContext(
        config_mgr=config_mgr,
        assets=assets,
        redis_client=redis_client,
        writer_pool=writer_pool,
        exec_config=exec_config,
        restart_delay_seconds=restart_delay_seconds,
    )
