"""Compatibility facade for the pre-modular SR configuration import path.

Canonical ownership lives in ``sections``, ``schema``, and ``resolved``.
Existing callers may continue importing the public configuration contracts here.
"""

from __future__ import annotations

from libs.models.sr.domain.identity import ContractValidationError

from .resolved import ResolvedSRConfig
from .schema import SRConfig
from .sections import (
    AssociationConfig,
    DetectionConfig,
    LifecycleConfig,
    RuntimeConfig,
)

__all__ = [
    "ContractValidationError",
    "DetectionConfig",
    "AssociationConfig",
    "LifecycleConfig",
    "RuntimeConfig",
    "SRConfig",
    "ResolvedSRConfig",
]
