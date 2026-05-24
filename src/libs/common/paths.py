"""Shared path helpers for flipperAgent."""

from __future__ import annotations

from pathlib import Path

from .constants import (
    DIR_GIT,
    DIR_LOGS,
    DIR_SRC,
    FILE_APP_LOG,
    FILE_PYPROJECT_TOML,
)


def find_project_root(start: Path | None = None) -> Path:
    current_path = start.resolve() if start is not None else Path(__file__).resolve().parent
    search_root = current_path if current_path.is_dir() else current_path.parent

    for candidate in (search_root, *search_root.parents):
        if (candidate / FILE_PYPROJECT_TOML).exists() or (candidate / DIR_GIT).exists():
            return candidate

    return Path.cwd()


PROJECT_ROOT = find_project_root()
SRC_ROOT = PROJECT_ROOT / DIR_SRC
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def get_logs_dir(*, create: bool = False) -> Path:
    logs_dir = PROJECT_ROOT / DIR_LOGS
    if create:
        logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def default_log_file(*, create_parent: bool = False) -> Path:
    return get_logs_dir(create=create_parent) / FILE_APP_LOG
