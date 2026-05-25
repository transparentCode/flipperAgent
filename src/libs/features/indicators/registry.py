from typing import Dict, Type
from libs.features.indicators.base import Indicator

class IndicatorRegistry:
    _registry: Dict[str, Type[Indicator]] = {}

    @classmethod
    def register(cls, name: str):
        def wrapper(indicator_class: Type[Indicator]):
            cls._registry[name] = indicator_class
            return indicator_class
        return wrapper

    @classmethod
    def get(cls, name: str) -> Type[Indicator]:
        if name not in cls._registry:
            raise KeyError(f"Indicator '{name}' not found in registry.")
        return cls._registry[name]
