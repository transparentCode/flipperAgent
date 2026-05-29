"""Deprecated — thin backward-compat wrapper over ModelRegistry."""

from __future__ import annotations

import warnings
from typing import Type

from libs.models.base import BaseModel
from libs.models.registry import ModelRegistry


class ScoringModelRegistry:
    """Deprecated: use ModelRegistry directly."""

    @classmethod
    def register(cls, name: str):
        """Delegate to ModelRegistry.register."""
        return ModelRegistry.register(name)

    @classmethod
    def get(cls, name: str) -> Type[BaseModel]:
        warnings.warn(
            "ScoringModelRegistry is deprecated. Use ModelRegistry.get().",
            DeprecationWarning,
            stacklevel=2,
        )
        return ModelRegistry.get(name)

    @classmethod
    def list_all(cls) -> list[str]:
        return ModelRegistry.list_by_type("scoring")

    # Expose _registry for tests that snapshot/restore it directly.
    @classmethod
    def _get_registry(cls):
        return ModelRegistry._registry
