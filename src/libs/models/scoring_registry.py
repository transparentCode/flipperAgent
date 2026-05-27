"""Decorator-based registry for ScoringModel subclasses."""

from __future__ import annotations

from typing import Type

from libs.models.scoring_base import ScoringModel


class ScoringModelRegistry:
    _registry: dict[str, Type[ScoringModel]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator: @ScoringModelRegistry.register("RegimePullbackScorer")."""
        def wrapper(model_class: Type[ScoringModel]):
            cls._registry[name] = model_class
            return model_class
        return wrapper

    @classmethod
    def get(cls, name: str) -> Type[ScoringModel]:
        if name not in cls._registry:
            raise KeyError(f"Scoring model '{name}' not found in registry.")
        return cls._registry[name]

    @classmethod
    def list_all(cls) -> list[str]:
        return list(cls._registry.keys())
