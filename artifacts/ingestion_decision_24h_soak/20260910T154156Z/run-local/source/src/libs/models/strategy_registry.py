"""Registry for canonical StrategyModelV2 implementations."""

from __future__ import annotations

from typing import Type

from libs.models.strategy_model_v2 import StrategyModelV2


class StrategyModelRegistry:
    _registry: dict[str, Type[StrategyModelV2]] = {}

    @classmethod
    def register(cls, name: str):
        def wrapper(model_class: Type[StrategyModelV2]):
            cls._registry[name] = model_class
            return model_class

        return wrapper

    @classmethod
    def get(cls, name: str) -> Type[StrategyModelV2]:
        if name not in cls._registry:
            raise KeyError(f"Strategy model '{name}' not found in registry.")
        return cls._registry[name]

    @classmethod
    def list_all(cls) -> list[str]:
        return list(cls._registry.keys())


__all__ = ["StrategyModelRegistry"]
