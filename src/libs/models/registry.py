"""Decorator-based model registry mirroring IndicatorRegistry."""

from __future__ import annotations

from typing import Type

from libs.models.base import BaseModel


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
