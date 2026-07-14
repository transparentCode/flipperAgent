from __future__ import annotations

import ast
from pathlib import Path
import sys


_SR_IMPORT_PREFIX = "libs.models.sr"
_YAML_ADAPTER = "adapters/yaml_config.py"


def _runtime_files() -> list[Path]:
    package_dir = Path(__file__).parents[3] / "src" / "libs" / "models" / "sr"
    return [path for path in package_dir.rglob("*.py") if "tests" not in path.parts]


def _relative_import_module(
    path: Path,
    node: ast.ImportFrom,
    package_dir: Path,
) -> str | None:
    if node.level == 0:
        return node.module
    try:
        relative = path.relative_to(package_dir).with_suffix("")
    except ValueError:
        return None
    package_parts = ("libs", "models", "sr", *relative.parts[:-1])
    if node.level > len(package_parts):
        return None
    base_parts = package_parts[: len(package_parts) - node.level + 1]
    if node.module:
        base_parts += tuple(node.module.split("."))
    return ".".join(base_parts)


def _allowed_import(path: Path, node: ast.Import | ast.ImportFrom) -> bool:
    package_dir = Path(__file__).parents[3] / "src" / "libs" / "models" / "sr"
    if isinstance(node, ast.Import):
        modules = [alias.name for alias in node.names]
    else:
        module = _relative_import_module(path, node, package_dir)
        if module is None:
            return False
        modules = [module]

    for module in modules:
        if module == "__future__":
            continue
        root = module.split(".", 1)[0]
        if root in sys.stdlib_module_names:
            continue
        if module == _SR_IMPORT_PREFIX or module.startswith(
            f"{_SR_IMPORT_PREFIX}."
        ):
            continue
        if (
            (module == "yaml" or module.startswith("yaml."))
            and path.as_posix().endswith(_YAML_ADAPTER)
        ):
            continue
        return False
    return True


def test_sr_runtime_uses_only_approved_imports() -> None:
    violations: list[str] = []
    for path in _runtime_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)) and not _allowed_import(
                path, node
            ):
                violations.append(f"{path}:{node.lineno}")
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
            if module is not None and not path.as_posix().endswith(
                _YAML_ADAPTER
            ):
                violations.append(f"{path}: {module}")
    assert violations == []
