"""Static boundaries for the pure Momentum core and thin plugin adapter."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[3] / "src/libs/models/momentum"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_pure_config_and_core_have_no_runtime_or_legacy_contract_imports() -> None:
    for relative in ("config.py", "core.py"):
        imports = _imports(PACKAGE_ROOT / relative)
        assert not any(
            item.startswith(("apps.", "pandas", "numpy", "optuna")) for item in imports
        )
        assert not any(
            item.startswith(("libs.contracts.decision", "libs.contracts.signal"))
            for item in imports
        )
        assert not any(
            token in item.lower()
            for item in imports
            for token in (
                "redis",
                "valkey",
                "asyncpg",
                "sqlalchemy",
                "httpx",
                "requests",
            )
        )


def test_decision_adapter_imports_only_shared_contracts_own_core_and_stdlib() -> None:
    imports = _imports(PACKAGE_ROOT / "adapters/decision_plugin.py")
    assert "libs.contracts.decision" in imports
    assert "libs.models.momentum.config" in imports
    assert "libs.models.momentum.core" in imports
    assert not any(
        item.startswith(
            (
                "apps.",
                "libs.contracts.signal",
                "libs.contracts.strategy_model",
                "libs.models.strategy_model_v2",
                "pandas",
                "numpy",
                "optuna",
            )
        )
        for item in imports
    )
    assert not any(
        token in item.lower()
        for item in imports
        for token in (
            "redis",
            "valkey",
            "asyncpg",
            "sqlalchemy",
            "httpx",
            "requests",
        )
    )


def test_no_duplicate_momentum_feature_manifest_remains() -> None:
    assert not (PACKAGE_ROOT / "features.py").exists()


def test_new_adapter_path_has_no_legacy_feature_or_generic_framework_symbols() -> None:
    source = (PACKAGE_ROOT / "adapters/decision_plugin.py").read_text(encoding="utf-8")
    for forbidden in (
        "FeatureVector",
        "StrategyModelV2",
        "PluginBase",
        "ModelAdapterBase",
        "UniversalModelInput",
        "GenericFeatureTranslator",
        "discover_plugins",
        "ThreadPoolExecutor",
        "ProcessPoolExecutor",
    ):
        assert forbidden not in source
