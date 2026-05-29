from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple


class StateManager(ABC):
    """Protocol for managing plugin state across ticks.

    Keys are (asset, timeframe, plugin_name) tuples.
    Stateless plugins use NullStateManager (no-op).
    """

    @abstractmethod
    def get(self, asset: str, timeframe: str, plugin_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored state for a plugin instance. Returns None if no state."""
        ...

    @abstractmethod
    def set(self, asset: str, timeframe: str, plugin_name: str, state: Dict[str, Any]) -> None:
        """Store state for a plugin instance."""
        ...

    @abstractmethod
    def reset(self, asset: str, timeframe: str, plugin_name: str) -> None:
        """Clear state for a plugin instance."""
        ...

    @abstractmethod
    def reset_all(self) -> None:
        """Clear all stored state."""
        ...

    @abstractmethod
    def list_keys(self) -> list[Tuple[str, str, str]]:
        """List all stored (asset, timeframe, plugin_name) keys."""
        ...


class NullStateManager(StateManager):
    """No-op state manager for stateless pipeline execution (default)."""

    def get(self, asset: str, timeframe: str, plugin_name: str) -> Optional[Dict[str, Any]]:
        return None

    def set(self, asset: str, timeframe: str, plugin_name: str, state: Dict[str, Any]) -> None:
        pass

    def reset(self, asset: str, timeframe: str, plugin_name: str) -> None:
        pass

    def reset_all(self) -> None:
        pass

    def list_keys(self) -> list[Tuple[str, str, str]]:
        return []


class InMemoryStateManager(StateManager):
    """In-memory state manager for live tick execution."""

    def __init__(self) -> None:
        self._store: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    def get(self, asset: str, timeframe: str, plugin_name: str) -> Optional[Dict[str, Any]]:
        return self._store.get((asset, timeframe, plugin_name))

    def set(self, asset: str, timeframe: str, plugin_name: str, state: Dict[str, Any]) -> None:
        self._store[(asset, timeframe, plugin_name)] = state

    def reset(self, asset: str, timeframe: str, plugin_name: str) -> None:
        self._store.pop((asset, timeframe, plugin_name), None)

    def reset_all(self) -> None:
        self._store.clear()

    def list_keys(self) -> list[Tuple[str, str, str]]:
        return list(self._store.keys())
