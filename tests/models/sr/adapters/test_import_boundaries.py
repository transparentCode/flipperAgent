from __future__ import annotations

import ast
from pathlib import Path


_FORBIDDEN_PREFIXES = ("app" + ".sr", "libs" + ".sr")
_YAML_MODULE = "yaml"


def _is_module_or_child(module_name: str, module: str) -> bool:
    return module_name == module or module_name.startswith(f"{module}.")


def _runtime_files() -> list[Path]:
    package_dir = Path(__file__).parents[4] / "src" / "libs" / "models" / "sr"
    return [path for path in package_dir.rglob("*.py") if "tests" not in path.parts]


def _is_baseline_integration(path: Path, package_dir: Path) -> bool:
    return path.relative_to(package_dir).parts[:2] == ("scripts", "baseline_trial")


def test_runtime_package_has_no_sr_legacy_imports() -> None:
    forbidden_imports: list[str] = []
    package_dir = Path(__file__).parents[4] / "src" / "libs" / "models" / "sr"
    allowed_yaml_loader = package_dir / "config" / "loader.py"
    for path in _runtime_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(_FORBIDDEN_PREFIXES):
                    forbidden_imports.append(f"{path}: {node.module}")
                if _is_module_or_child(node.module, "pandas") and not _is_baseline_integration(path, package_dir):
                    forbidden_imports.append(f"{path}: {node.module}")
                if _is_module_or_child(node.module, _YAML_MODULE):
                    if path != allowed_yaml_loader and not _is_baseline_integration(path, package_dir):
                        forbidden_imports.append(f"{path}: {node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(_FORBIDDEN_PREFIXES):
                        forbidden_imports.append(f"{path}: {alias.name}")
                    if _is_module_or_child(alias.name, "pandas") and not _is_baseline_integration(path, package_dir):
                        forbidden_imports.append(f"{path}: {alias.name}")
                    if (
                        _is_module_or_child(alias.name, _YAML_MODULE)
                        and path != allowed_yaml_loader
                        and not _is_baseline_integration(path, package_dir)
                    ):
                        forbidden_imports.append(f"{path}: {alias.name}")
    assert forbidden_imports == []
