"""Strict SR v2 configuration resolution."""

from .resolver import (
    ResolvedSRV2Config,
    SRV2ConfigError,
    SRV2ConfigResolver,
    load_sr_v2_yaml,
)

__all__ = [
    "ResolvedSRV2Config",
    "SRV2ConfigError",
    "SRV2ConfigResolver",
    "load_sr_v2_yaml",
]
