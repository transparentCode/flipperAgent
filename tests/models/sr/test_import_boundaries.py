from __future__ import annotations

import ast
from pathlib import Path


_FORBIDDEN_PREFIXES = (
    "app.sr",
    "libs.sr",
    "pandas",
    "numpy",
    "polars",
    "scipy",
    "sklearn",
)


def _runtime_files() -> list[Path]:
    package_dir = Path(__file__).parents[3] / "src" / "libs" / "models" / "sr"
    return [path for path in package_dir.rglob("*.py") if "tests" not in path.parts]


def test_sr_runtime_has_no_forbidden_imports() -> None:
    violations: list[str] = []
    for path in _runtime_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                continue
            for name in imported:
                if any(
                    name == prefix or name.startswith(f"{prefix}.")
                    for prefix in _FORBIDDEN_PREFIXES
                ):
                    violations.append(f"{path}: {name}")
    assert violations == []


def test_yaml_imports_remain_confined_to_adapter() -> None:
    violations: list[str] = []
    for path in _runtime_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.Import):
                if any(alias.name == "yaml" for alias in node.names):
                    module = "yaml"
            elif isinstance(node, ast.ImportFrom) and node.module == "yaml":
                module = "yaml"
            if module is not None and path.name != "yaml_config.py":
                violations.append(f"{path}: {module}")
    assert violations == []
