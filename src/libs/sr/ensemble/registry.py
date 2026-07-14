"""
S/R v2 Ensemble — Registry
===========================
Decorator-based plugin registry for ensemble strategies,
mirroring ``KernelRegistry`` and ``DetectorRegistry``.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Type

from app.sr.ensemble.base import BaseEnsembleStrategy

logger = logging.getLogger(__name__)


class EnsembleRegistry:
    """Registry of ensemble strategy classes, keyed by name."""

    _registry: Dict[str, Type[BaseEnsembleStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_cls: Type[BaseEnsembleStrategy]) -> None:
        if name in cls._registry:
            logger.warning("Overwriting ensemble strategy: %s", name)
        cls._registry[name] = strategy_cls
        logger.debug("Registered ensemble strategy: %s", name)

    @classmethod
    def get(cls, name: str) -> Optional[Type[BaseEnsembleStrategy]]:
        strategy_cls = cls._registry.get(name)
        if strategy_cls is None:
            logger.warning("Ensemble strategy not found: %s", name)
        return strategy_cls

    @classmethod
    def has(cls, name: str) -> bool:
        return name in cls._registry

    @classmethod
    def list_all(cls) -> List[str]:
        return list(cls._registry.keys())

    @classmethod
    def create(cls, name: str) -> Optional[BaseEnsembleStrategy]:
        strategy_cls = cls.get(name)
        return strategy_cls() if strategy_cls is not None else None

    @classmethod
    def clear(cls) -> None:
        cls._registry.clear()


def register_ensemble(name: str):
    """Decorator to register an ensemble strategy class."""

    def decorator(cls: Type[BaseEnsembleStrategy]) -> Type[BaseEnsembleStrategy]:
        EnsembleRegistry.register(name, cls)
        return cls

    return decorator
