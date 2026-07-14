from __future__ import annotations

import ast
from pathlib import Path


_FORBIDDEN_PREFIXES = ("libs.trendlines", "libs.models.trendlines_old", "app.trendlines")


def _runtime_files() -> list[Path]:
    package_dir = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline_family"
    return [path for path in package_dir.rglob("*.py") if "tests" not in path.parts]


def test_runtime_package_has_no_recursive_legacy_trendline_imports() -> None:
    forbidden_imports: list[str] = []
    for path in _runtime_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(_FORBIDDEN_PREFIXES):
                forbidden_imports.append(f"{path}: {node.module}")
            if isinstance(node, ast.Import):
                forbidden_imports.extend(f"{path}: {name.name}" for name in node.names if name.name.startswith(_FORBIDDEN_PREFIXES))
    assert forbidden_imports == []


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
