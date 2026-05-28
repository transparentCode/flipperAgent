"""api_app entrypoint — serves the flipperAgent REST API."""

from __future__ import annotations

import os

import uvicorn

from libs.common.config import ConfigManager
from libs.common.logging.logger_utils import configure_logging


def main() -> None:
    config_mgr = ConfigManager()
    log_level = config_mgr.get("logging.level", default="INFO")
    configure_logging(
        level=log_level,
        enable_file_logging=True,
        console_format=os.environ.get("LOG_FORMAT", "json"),
        log_file=os.environ.get("LOG_FILE"),
    )

    host = config_mgr.get("api.host", default="0.0.0.0")
    port = int(config_mgr.get("api.port", default=8080))

    uvicorn.run("apps.api_app.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
