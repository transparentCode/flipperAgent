"""Shared constants for the flipperAgent commons layer."""

from typing import Final

# Logging Constants
DEFAULT_LOGGER_NAMESPACE: Final[str] = "flipper_agent"
DEFAULT_LOG_LEVEL: Final[str] = "INFO"
DEFAULT_LOG_FILE_MAX_BYTES: Final[int] = 30 * 1024 * 1024  # 30 MB
DEFAULT_LOG_FILE_BACKUP_COUNT: Final[int] = 3

DEFAULT_CONTEXT_FIELDS: Final[tuple[str, ...]] = (
    "trace_id",
    "run_id",
    "job_name",
    "system_component",
    "source",
    "dataset",
    "symbol",
    "interval",
    "window",
    "attempt",
)

# Configuration Constants
DEFAULT_ENV: Final[str] = "dev"
DEFAULT_CONFIG_DIR_NAME: Final[str] = "configs"
CONFIG_BASE_FILENAME: Final[str] = "base.yaml"
CONFIG_LOCAL_FILENAME: Final[str] = "local.yaml"
CONFIG_DEBOUNCE_DELAY_SEC: Final[float] = 0.5

# Path Constants
FILE_PYPROJECT_TOML: Final[str] = "pyproject.toml"
DIR_GIT: Final[str] = ".git"
DIR_SRC: Final[str] = "src"
DIR_LOGS: Final[str] = "logs"
FILE_APP_LOG: Final[str] = "app.log"

