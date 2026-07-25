from __future__ import annotations

import importlib.util
from pathlib import Path


_ROOT = Path(__file__).parents[3]
_REMOVED_MODULES = (
    ".".join(("libs", "integrations", "trendline_configuration")),
    ".".join(("libs", "integrations", "trendline_configuration", "loader")),
)


def _find_spec_or_none(module_name: str):
    try:
        return importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        return None


def test_removed_configuration_integration_modules_are_absent() -> None:
    removed_paths = (
        _ROOT / "src" / "libs" / "integrations" / "trendline_configuration" / "__init__.py",
        _ROOT / "src" / "libs" / "integrations" / "trendline_configuration" / "loader.py",
    )

    assert all(_find_spec_or_none(module_name) is None for module_name in _REMOVED_MODULES)
    assert all(not path.exists() for path in removed_paths)


def test_canonical_loader_and_compatibility_facades_remain_functional() -> None:
    from libs.models.trendline.config_loader import (
        load_trendline_family_config as canonical_facade_loader,
    )
    from libs.models.trendline.configuration.loader import (
        load_trendline_family_config as canonical_loader,
    )
    from libs.models.trendline_family.config_loader import (
        load_trendline_family_config as family_facade_loader,
    )

    assert canonical_facade_loader is canonical_loader
    assert family_facade_loader is canonical_loader

    payload = canonical_loader(_ROOT / "configs" / "trendline_family.yaml")
    assert isinstance(payload, dict)
    assert payload["version"] == 1
