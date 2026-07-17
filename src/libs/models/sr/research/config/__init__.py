"""Shared fail-closed configuration primitives for SR research studies."""

from .identities import BundleReference, ConfigReference, ContentIdentity, SourceIdentity
from .input_resolution import (
    ResolvedInputConfig,
    load_and_resolve_input_config,
    resolve_input_config,
)
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
from .resolution import load_resolved_sr_config

__all__ = [
    "BundleReference",
    "ConfigReference",
    "ContentIdentity",
    "SourceIdentity",
    "ResolvedInputConfig",
    "load_and_resolve_input_config",
    "load_resolved_sr_config",
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
    "resolve_input_config",
]
