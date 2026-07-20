"""Explicit forwarding support for deprecated trendline-family module paths."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType
from typing import Any


def reexport_module(namespace: dict[str, Any], canonical_module_name: str) -> None:
    """Expose canonical module symbols without retaining a second implementation."""

    module: ModuleType = import_module(canonical_module_name)
    names = tuple(getattr(module, "__all__", ()) or (name for name in vars(module) if not name.startswith("_")))
    for name in names:
        namespace[name] = getattr(module, name)
    namespace["__all__"] = names
    namespace["__getattr__"] = lambda name: getattr(module, name)
