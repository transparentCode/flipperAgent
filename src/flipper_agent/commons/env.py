"""Minimal environment helpers for shared configuration."""

from __future__ import annotations

import os


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def get_env(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)


def get_bool_env(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False

    raise ValueError(f"Environment variable {name} must be a boolean-like value.")
