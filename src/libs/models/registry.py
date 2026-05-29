"""Decorator-based model registry with auto-discovery."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Type

from libs.models.base import BaseModel

logger = logging.getLogger(__name__)


class ModelRegistry:
    _registry: dict[str, Type[BaseModel]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator: ``@ModelRegistry.register("MeanReversion")``."""
        def wrapper(model_class: Type[BaseModel]):
            cls._registry[name] = model_class
            return model_class
        return wrapper

    @classmethod
    def get(cls, name: str) -> Type[BaseModel]:
        if name not in cls._registry:
            raise KeyError(f"Model '{name}' not found in registry.")
        return cls._registry[name]

    @classmethod
    def list_all(cls) -> list[str]:
        return list(cls._registry.keys())

    @classmethod
    def list_by_type(cls, model_type: str) -> list[str]:
        """Return registered model names filtered by model_type."""
        return [
            name for name, mcls in cls._registry.items()
            if hasattr(mcls, "meta") and mcls.meta.model_type == model_type
        ]

    @classmethod
    def auto_discover(cls) -> None:
        """Import all model subpackages to trigger @register decorators."""
        package_dir = Path(__file__).parent
        for item in sorted(package_dir.iterdir()):
            if item.is_dir() and not item.name.startswith("_") and (item / "__init__.py").exists():
                module_name = f"libs.models.{item.name}"
                try:
                    importlib.import_module(module_name)
                except Exception:
                    logger.warning("Failed to auto-discover model subpackage %s", module_name, exc_info=True)
