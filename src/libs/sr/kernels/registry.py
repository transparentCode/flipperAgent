"""
Kernel Registry
===============
Decorator-based registry for S/R detection kernels.

Aligned with the existing ``DetectorRegistry`` and regression
``PluginRegistry`` patterns.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Type
import logging

from app.sr.kernels.base import BaseSRKernel

logger = logging.getLogger("app.sr.kernels")


class KernelRegistry:
    """
    Registry for S/R kernel classes.

    Usage::

        # Registration (via decorator — preferred)
        @register_kernel("pivot_hl")
        class PivotHighLowKernel(BaseSRKernel): ...

        # Manual registration
        KernelRegistry.register("custom", MyKernel)

        # Lookup
        cls = KernelRegistry.get("pivot_hl")
        kernel = cls()

        # List all
        names = KernelRegistry.list_all()
    """

    _registry: Dict[str, Type[BaseSRKernel]] = {}

    @classmethod
    def register(cls, name: str, kernel_class: Type[BaseSRKernel]) -> None:
        if name in cls._registry:
            logger.warning("Overwriting kernel: %s", name)
        cls._registry[name] = kernel_class
        logger.debug("Registered kernel: %s", name)

    @classmethod
    def get(cls, name: str) -> Optional[Type[BaseSRKernel]]:
        kernel_class = cls._registry.get(name)
        if kernel_class is None:
            logger.warning("Kernel not found: %s", name)
        return kernel_class

    @classmethod
    def has(cls, name: str) -> bool:
        return name in cls._registry

    @classmethod
    def list_all(cls) -> List[str]:
        return list(cls._registry.keys())

    @classmethod
    def create(cls, name: str) -> Optional[BaseSRKernel]:
        """Instantiate a registered kernel (kernels are stateless)."""
        kernel_class = cls.get(name)
        if kernel_class is None:
            return None
        return kernel_class()

    @classmethod
    def clear(cls) -> None:
        """Clear all registrations (for testing)."""
        cls._registry.clear()


def register_kernel(name: str):
    """
    Decorator to register a kernel class.

    Usage::

        @register_kernel("pivot_hl")
        class PivotHighLowKernel(BaseSRKernel):
            def compute(self, df, config): ...
    """
    def decorator(cls: Type[BaseSRKernel]) -> Type[BaseSRKernel]:
        KernelRegistry.register(name, cls)
        return cls
    return decorator
