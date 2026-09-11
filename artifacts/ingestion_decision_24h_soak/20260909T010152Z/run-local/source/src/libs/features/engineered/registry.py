from typing import Type

from libs.features.engineered.base import EngineeredFeature


class EngineeredFeatureRegistry:
    _registry: dict[str, Type[EngineeredFeature]] = {}

    @classmethod
    def register(cls, name: str):
        def wrapper(feature_class: Type[EngineeredFeature]):
            cls._registry[name] = feature_class
            return feature_class
        return wrapper

    @classmethod
    def get(cls, name: str) -> Type[EngineeredFeature]:
        if name not in cls._registry:
            raise KeyError(f"Engineered feature '{name}' not found in registry.")
        return cls._registry[name]

    @classmethod
    def list_all(cls) -> list[str]:
        return list(cls._registry.keys())
