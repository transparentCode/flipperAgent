"""Regime config loading via the shared ConfigManager."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from libs.common.config import ConfigManager


REGIME_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "regime.yaml"


def load_regime_config() -> dict[str, Any]:
    """Load the regime YAML through the shared config subsystem."""
    return load_yaml_config(REGIME_CONFIG_PATH)


def load_yaml_config(path: str | Path) -> dict[str, Any]:
    """Load an arbitrary YAML file through the shared config subsystem."""
    config_mgr = ConfigManager()
    resolved = Path(path).resolve()
    config_mgr.register_file(resolved)
    for entry in config_mgr.get_all_file_states():
        file_path = entry.get("filePath")
        if not file_path:
            continue
        if Path(file_path).resolve() == resolved:
            contents = entry.get("contents") or {}
            return contents if isinstance(contents, dict) else {}
    return {}
