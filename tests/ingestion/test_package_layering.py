from __future__ import annotations

import ast
from pathlib import Path

APP_IMPORT_PREFIX = "apps.ingestion_app"
APP_SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src/apps/ingestion_app"
_ROOT_PACKAGE = "__root__"
_LAYER_BY_PACKAGE = {
    "domain": 0,
    "settings": 0,
    "transport": 0,
    "observability": 1,
    "planning": 1,
    "providers": 2,
    "storage": 2,
    "publication": 3,
    "services": 4,
    "runtime": 5,
    "control": 6,
    "api": 7,
    _ROOT_PACKAGE: 8,
}
_BINANCE_USDM_PACKAGE = f"{APP_IMPORT_PREFIX}.providers.binance_usdm"


def _source_package(relative_path: Path) -> str:
    if len(relative_path.parts) > 1:
        return relative_path.parts[0]
    stem = relative_path.stem
    return stem if stem in _LAYER_BY_PACKAGE else _ROOT_PACKAGE


def _target_package(module: str) -> str | None:
    if module == APP_IMPORT_PREFIX:
        return _ROOT_PACKAGE
    prefix = f"{APP_IMPORT_PREFIX}."
    if not module.startswith(prefix):
        return None
    first = module[len(prefix) :].split(".", maxsplit=1)[0]
    return _ROOT_PACKAGE if first in {"bootstrap", "main"} else first


def _layer_violation(source_package: str, target_module: str) -> bool:
    target_package = _target_package(target_module)
    if target_package is None or target_package not in _LAYER_BY_PACKAGE:
        return False
    if source_package not in _LAYER_BY_PACKAGE:
        return False
    return source_package != target_package and (
        _LAYER_BY_PACKAGE[target_package] >= _LAYER_BY_PACKAGE[source_package]
    )


def _module_package(relative_path: Path) -> list[str]:
    return ["apps", "ingestion_app", *_source_directories(relative_path)]


def _source_directories(relative_path: Path) -> list[str]:
    return list(relative_path.parts[:-1])


def _resolve_import_from(
    node: ast.ImportFrom,
    package_parts: list[str],
) -> tuple[str, ...]:
    if node.level == 0:
        base = node.module or ""
    else:
        parent = package_parts[: len(package_parts) - node.level + 1]
        base = ".".join(parent)
        if node.module is not None:
            base = f"{base}.{node.module}"

    imports = [base] if base else []
    imports.extend(
        f"{base}.{alias.name}" if base else alias.name
        for alias in node.names
        if alias.name != "*"
    )
    return tuple(imports)


def _module_imports(source: Path, relative_path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    package_parts = _module_package(relative_path)
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.extend(
                (module, node.lineno)
                for module in _resolve_import_from(node, package_parts)
            )
    return imports


def _binance_usdm_boundary_violation(
    relative_path: Path,
    module: str,
) -> bool:
    if module != _BINANCE_USDM_PACKAGE and not module.startswith(
        f"{_BINANCE_USDM_PACKAGE}."
    ):
        return False
    if relative_path.as_posix() in {"bootstrap.py", "providers/factory.py"}:
        return False
    return relative_path.parts[:2] != ("providers", "binance_usdm")


def test_layer_checker_rejects_known_downward_dependency_violations() -> None:
    assert _layer_violation("storage", f"{APP_IMPORT_PREFIX}.publication.outbox")
    assert _layer_violation("services", f"{APP_IMPORT_PREFIX}.runtime.controller")
    for module in ("settings", "planning", "observability"):
        assert _source_package(Path(f"{module}.py")) == module
    assert _layer_violation(
        _source_package(Path("settings.py")),
        f"{APP_IMPORT_PREFIX}.runtime.controller",
    )
    assert not _layer_violation(
        _source_package(Path("planning.py")),
        f"{APP_IMPORT_PREFIX}.settings",
    )
    assert _binance_usdm_boundary_violation(
        Path("runtime/supervisor.py"),
        f"{_BINANCE_USDM_PACKAGE}.rest_native",
    )
    assert not _binance_usdm_boundary_violation(
        Path("providers/binance_usdm/websocket.py"),
        f"{_BINANCE_USDM_PACKAGE}.websocket_session",
    )


def test_ingestion_imports_follow_package_layers_and_provider_boundary() -> None:
    violations: list[str] = []
    for source in sorted(APP_SOURCE_ROOT.rglob("*.py")):
        relative_path = source.relative_to(APP_SOURCE_ROOT)
        source_package = _source_package(relative_path)
        for module, line in _module_imports(source, relative_path):
            if _layer_violation(source_package, module):
                violations.append(
                    f"{relative_path}:{line}: {source_package} imports same-or-higher "
                    f"layer {module}"
                )
            if _binance_usdm_boundary_violation(
                relative_path,
                module,
            ):
                violations.append(
                    f"{relative_path}:{line}: concrete Binance USD-M import {module} "
                    "is restricted to bootstrap.py and providers/factory.py"
                )

    assert not violations, "\n".join(violations)
