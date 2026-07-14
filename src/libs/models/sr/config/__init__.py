"""SR configuration: typed groups, strict validation, and resolution."""

from __future__ import annotations

from .models import (
    AssociationConfig,
    DetectionConfig,
    LifecycleConfig,
    ResolvedSRConfig,
    RuntimeConfig,
    SRConfig,
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
