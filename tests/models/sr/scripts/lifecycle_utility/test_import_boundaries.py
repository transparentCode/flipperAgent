from __future__ import annotations

import ast
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[5] / "src/libs/models/sr/scripts/lifecycle_utility"
FORBIDDEN_PREFIXES = (
    "libs.sr",
    "apps.ingestion_app",
    "apps.exchange",
    "ccxt",
    "requests",
    "httpx",
    "urllib",
    "pandas",
    "sqlalchemy",
    "holdout",
    "database",
)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_lifecycle_utility_has_no_provider_holdout_database_or_legacy_imports():
    modules = set().union(*(imported_modules(path) for path in PACKAGE.glob("*.py")))
    assert not any(module == prefix or module.startswith(prefix + ".") for module in modules for prefix in FORBIDDEN_PREFIXES)


def test_lifecycle_utility_does_not_import_viewer_or_production_surfaces():
    modules = set().union(*(imported_modules(path) for path in PACKAGE.glob("*.py")))
    assert not any("tools.zone_viewer" in module or module.startswith("apps.") for module in modules)
