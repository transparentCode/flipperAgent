"""scraper_app entrypoint for the internal scraper service."""

from __future__ import annotations

import os

import uvicorn

from libs.common.config import ConfigManager
from libs.common.logging.logger_utils import configure_logging


def main() -> None:
    config_mgr = ConfigManager()

    try:
        from libs.common.telemetry.bootstrap import init_telemetry

        init_telemetry("scraper_service")
    except ImportError:
        pass

    log_level = config_mgr.get("logging.level", default="INFO")
    configure_logging(
        level=log_level,
        enable_file_logging=True,
        console_format=os.environ.get("LOG_FORMAT", "json"),
        log_file=os.environ.get("LOG_FILE"),
    )

    host = config_mgr.get("scraper_service.host", default="0.0.0.0")
    port = int(config_mgr.get("scraper_service.port", default=8081))
    uvicorn.run("apps.scraper_app.api.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
