from __future__ import annotations

import ast
from pathlib import Path


_FORBIDDEN_PREFIXES = (
    "libs.trendlines",
    "libs.models.trendlines_old",
    "app.trendlines",
    "libs.models.sr",
)
_FORBIDDEN_CANONICAL_UPSTREAM_PREFIXES = (
    "libs.models.regime_v2",
    "libs.integrations.trendline_regime_v2",
)


def _runtime_files() -> list[Path]:
    package_dir = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline_family"
    return [path for path in package_dir.rglob("*.py") if "tests" not in path.parts]


def _canonical_runtime_files() -> list[Path]:
    package_dir = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline"
    return [
        path
        for path in package_dir.rglob("*.py")
        if not {"optimization", "research_lab"}.intersection(path.relative_to(package_dir).parts)
    ]


def _canonical_files() -> list[Path]:
    package_dir = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline"
    return list(package_dir.rglob("*.py"))


def _forbidden_imports(paths: list[Path], prefixes: tuple[str, ...]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(prefixes):
                violations.append(f"{path}: {node.module}")
            if isinstance(node, ast.Import):
                violations.extend(f"{path}: {name.name}" for name in node.names if name.name.startswith(prefixes))
    return violations


def test_runtime_package_has_no_recursive_legacy_trendline_imports() -> None:
    assert _forbidden_imports(_runtime_files(), _FORBIDDEN_PREFIXES) == []


def test_canonical_runtime_has_no_old_or_support_resistance_imports() -> None:
    assert _forbidden_imports(_canonical_runtime_files(), _FORBIDDEN_PREFIXES) == []


def test_canonical_runtime_does_not_depend_on_regime_v2() -> None:
    assert _forbidden_imports(_canonical_runtime_files(), _FORBIDDEN_CANONICAL_UPSTREAM_PREFIXES) == []


def test_entire_canonical_package_has_no_regime_integration_imports() -> None:
    assert _forbidden_imports(_canonical_files(), _FORBIDDEN_CANONICAL_UPSTREAM_PREFIXES) == []


def test_yaml_reads_are_confined_to_config_loader() -> None:
    violations: list[str] = []
    for path in _runtime_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(name.name == "yaml" for name in node.names) and path.name != "config_loader.py":
                violations.append(str(path))
            if isinstance(node, ast.ImportFrom) and node.module == "yaml" and path.name != "config_loader.py":
                violations.append(str(path))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"safe_load", "load"}:
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "yaml" and path.name != "config_loader.py":
                    violations.append(str(path))
    assert violations == []
