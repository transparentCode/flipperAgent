from __future__ import annotations

import uvicorn

from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging


def main() -> None:
    config_manager = ConfigManager()
    telemetry_service_name = config_manager.get(
        "ingestion.telemetry.service_name",
        default="ingestion_app",
    )

    try:
        from libs.common.telemetry.bootstrap import init_telemetry

        init_telemetry(telemetry_service_name)
    except ImportError:
        pass

    log_level = config_manager.get("logging.level", default="INFO")
    configure_logging(
        level=log_level,
        enable_file_logging=True,
        console_format=config_manager.get("logging.console_format", "json"),
        log_file=config_manager.get("logging.log_file"),
    )

    try:
        from libs.common.telemetry.bootstrap import attach_otel_log_handler

        attach_otel_log_handler()
    except ImportError:
        pass

    logger = bind_logger(component=SystemComponent.DATA_INGESTION_ENGINE)
    host = config_manager.get("ingestion.server.host", default="0.0.0.0")
    port = config_manager.get("ingestion.server.port", default=8001)

    logger.info(f"Starting Ingestion controller on {host}:{port}")
    uvicorn.run("apps.ingestion_app.runtime.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
