"""Shared fail-closed configuration primitives for SR research studies."""

from .primitives import (
    require_exact_keys,
    require_finite_number,
    require_git_commit,
    require_integer,
    require_mapping,
    require_nonempty_string,
    require_safe_relative_path,
    require_sha256,
    require_utc_timestamp,
)
from .strict_yaml import load_strict_research_yaml

__all__ = [
    "load_strict_research_yaml",
    "require_exact_keys",
    "require_finite_number",
    "require_git_commit",
    "require_integer",
    "require_mapping",
    "require_nonempty_string",
    "require_safe_relative_path",
    "require_sha256",
    "require_utc_timestamp",
]
