"""alert_app runtime entrypoint."""

from __future__ import annotations

import asyncio
import os

from apps.alert_app.runtime import AlertRuntimeRunner
from apps.alert_app.settings import AlertAppSettings, create_alert_config_manager
from apps.alert_app.storage import apply_alert_schema
from libs.common.connections import create_valkey_client, init_db_pools
from libs.common.db.pool_manager import DBPoolManager
from libs.common.logging.logger_utils import bind_logger, configure_logging

logger = bind_logger(__name__, system_component="ALERTING")


async def _run() -> None:
    config_mgr = create_alert_config_manager()

    try:
        from libs.common.telemetry.bootstrap import init_telemetry

        init_telemetry("alert_app")
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
    db_pool = DBPoolManager.get_writer_pool()
    await apply_alert_schema(db_pool)
    settings = AlertAppSettings.from_config(config_mgr)
    runner = AlertRuntimeRunner(
        settings=settings,
        redis_client=redis_client,
        db_pool=db_pool,
        config_manager=config_mgr,
    )

    try:
        await runner.run()
    finally:
        await runner.stop()
        await redis_client.aclose()
        await DBPoolManager.close_pools()
        config_mgr.shutdown()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
