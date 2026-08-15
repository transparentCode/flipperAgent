"""Explicit bootstrap boundary for legacy model and strategy registries."""

from __future__ import annotations

import logging
from importlib import import_module
from pathlib import Path

logger = logging.getLogger(__name__)


def bootstrap_legacy_model_registries() -> None:
    """Populate the legacy registries without making package imports implicit."""

    # Mirror the original ModelRegistry.auto_discover() traversal order. The
    # migrated Momentum package root is lazy, so import its decorator-bearing
    # modules at the same sorted package position as the old eager root did.
    package_dir = Path(__file__).parent
    for item in sorted(package_dir.iterdir()):
        if (
            not item.is_dir()
            or item.name.startswith("_")
            or not (item / "__init__.py").exists()
        ):
            continue

        module_name = f"libs.models.{item.name}"
        try:
            if item.name == "momentum":
                import_module(f"{module_name}.model")
                import_module(f"{module_name}.strategy_v2")
            else:
                import_module(module_name)
        except Exception:
            logger.warning(
                "Failed to bootstrap model subpackage %s", module_name, exc_info=True
            )


__all__ = ["bootstrap_legacy_model_registries"]
