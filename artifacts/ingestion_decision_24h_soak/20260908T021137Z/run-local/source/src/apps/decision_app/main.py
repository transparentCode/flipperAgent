"""Runnable Decision process entrypoint."""

from __future__ import annotations

import logging
from collections.abc import Mapping

import uvicorn

from apps.decision_app.bootstrap import create_application
from apps.decision_app.settings import (
    DECISION_CONFIG_FILE,
    DECISION_CONFIG_NAMESPACE,
    DecisionServerSettings,
)
from libs.common.config import ConfigManager
from libs.common.logging.logger_utils import configure_logging
from libs.common.telemetry.bootstrap import (
    attach_otel_log_handler,
    init_telemetry,
    shutdown_telemetry_nonblocking,
)

logger = logging.getLogger(__name__)


def _load_server_settings(config_manager: ConfigManager) -> DecisionServerSettings:
    config_manager.register_file(DECISION_CONFIG_FILE)
    raw = config_manager.get(DECISION_CONFIG_NAMESPACE)
    if not isinstance(raw, Mapping):
        raise TypeError("decision global configuration must be a mapping")
    return DecisionServerSettings.model_validate(raw.get("server", {}))


def main() -> None:
    global app
    config_manager = ConfigManager()
    telemetry_initialized = False
    try:
        server = _load_server_settings(config_manager)
        try:
            init_telemetry("decision")
            telemetry_initialized = True
        except Exception:  # noqa: BLE001 - telemetry is non-authoritative
            telemetry_initialized = False
        configure_logging(
            level=config_manager.get("logging.level", default="INFO"),
            enable_file_logging=True,
            console_format=config_manager.get("logging.console_format", "json"),
            log_file=config_manager.get("logging.log_file"),
        )
        if telemetry_initialized:
            attach_otel_log_handler()
        logger.info("Starting Decision service on %s:%s", server.host, server.port)
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
