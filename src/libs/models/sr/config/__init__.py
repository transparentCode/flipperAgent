"""Canonical SR configuration schema, loading, and resolution."""

from __future__ import annotations

from .resolved import ResolvedSRConfig
from .schema import SRConfig
from .sections import (
    AssociationConfig,
    DetectionConfig,
    LifecycleConfig,
    RuntimeConfig,
)
from .resolver import SRConfigResolver

__all__ = [
    "AssociationConfig",
    "DetectionConfig",
    "LifecycleConfig",
    "ResolvedSRConfig",
    "RuntimeConfig",
    "SRConfig",
    "SRConfigResolver",
]
