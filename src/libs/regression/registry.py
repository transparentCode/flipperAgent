from __future__ import annotations

from typing import Callable, Dict, Generic, Optional, Type, TypeVar

T = TypeVar("T")


class PluginRegistry(Generic[T]):
    """Generic decorator-based plugin registry.

    Usage:

        FeatureRegistry = PluginRegistry[FeatureExtractor]("feature")

        @FeatureRegistry.register("log_price")
        class LogPriceFeatures(FeatureExtractor):
            ...

        cls = FeatureRegistry.get("log_price")
        instance = cls(config)
    """

    def __init__(self, stage_name: str) -> None:
        self._stage_name = stage_name
        self._registry: Dict[str, Type[T]] = {}

    def register(self, name: str) -> Callable[[Type[T]], Type[T]]:
        """Decorator to register a plugin class under a name."""
        def decorator(cls: Type[T]) -> Type[T]:
            if name in self._registry:
                raise ValueError(
                    f"[{self._stage_name}] Plugin '{name}' already registered "
                    f"(existing: {self._registry[name].__name__}, new: {cls.__name__})"
                )
            self._registry[name] = cls
            return cls
        return decorator

    def get(self, name: str) -> Type[T]:
        """Get a registered plugin class by name. Raises KeyError if not found."""
        if name not in self._registry:
            available = sorted(self._registry.keys())
            raise KeyError(
                f"[{self._stage_name}] Plugin '{name}' not found. "
                f"Available: {available}"
            )
        return self._registry[name]

    def has(self, name: str) -> bool:
        return name in self._registry

    def list_names(self) -> list[str]:
        return sorted(self._registry.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._registry

    def __repr__(self) -> str:
        return f"PluginRegistry({self._stage_name}, plugins={self.list_names()})"
