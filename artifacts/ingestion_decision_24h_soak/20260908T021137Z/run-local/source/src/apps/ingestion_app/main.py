"""Runnable ingestion process entrypoint."""

from __future__ import annotations

import uvicorn

from apps.ingestion_app.bootstrap import create_application
from apps.ingestion_app.settings import (
    INGESTION_CONFIG_FILE,
    INGESTION_CONFIG_NAMESPACE,
    ServerSettings,
)
from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger, configure_logging
from libs.common.telemetry.bootstrap import (
    attach_otel_log_handler,
    init_telemetry,
    shutdown_telemetry_nonblocking,
)


def _load_server_settings(config_manager: ConfigManager) -> ServerSettings:
    config_manager.register_file(INGESTION_CONFIG_FILE)
    raw_config = config_manager.get(INGESTION_CONFIG_NAMESPACE)
    if not isinstance(raw_config, dict):
        raise TypeError("ingestion global configuration must be a mapping")
    return ServerSettings.model_validate(raw_config.get("server"))


def main() -> None:
    global app
    config_manager = ConfigManager()
    telemetry_initialized = False
    try:
        server = _load_server_settings(config_manager)
        try:
            init_telemetry("ingestion")
            telemetry_initialized = True
        except Exception:  # noqa: BLE001 - telemetry is non-authoritative
            # Telemetry is non-authoritative; an exporter/bootstrap problem must
            # not prevent canonical ingestion from starting.
            telemetry_initialized = False
        configure_logging(
            level=config_manager.get("logging.level", default="INFO"),
            enable_file_logging=True,
            console_format=config_manager.get("logging.console_format", "json"),
            log_file=config_manager.get("logging.log_file"),
        )
        if telemetry_initialized:
            attach_otel_log_handler()
        logger = bind_logger(
            component=SystemComponent.DATA_INGESTION_ENGINE,
        )
        logger.info(
            "Starting Ingestion controller on %s:%s",
            server.host,
            server.port,
        )
        app = create_application(config_manager=config_manager)
        uvicorn.run(app, host=server.host, port=server.port)
    finally:
        config_manager.shutdown()
        if telemetry_initialized:
            shutdown_telemetry_nonblocking()


app = None


if __name__ == "__main__":
    main()


__all__ = ["app", "main"]
