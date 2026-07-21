from __future__ import annotations

import ast
from importlib.util import resolve_name
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
_OWNER_PACKAGES = frozenset(
    {"configuration", "discovery", "interaction", "mtf", "storage", "tracking"}
)
_TRANSITIONAL_FACADES = frozenset(
    {
        "libs.models.trendline.contracts",
        "libs.models.trendline.config",
        "libs.models.trendline.config_loader",
        "libs.models.trendline.config_resolver",
        "libs.models.trendline.corridors",
        "libs.models.trendline.event_lifecycle",
        "libs.models.trendline.events",
        "libs.models.trendline.features",
        "libs.models.trendline.fitting",
        "libs.models.trendline.interactions",
        "libs.models.trendline.matching",
        "libs.models.trendline.mtf",
        "libs.models.trendline.pivots",
        "libs.models.trendline.provider",
        "libs.models.trendline.rails",
        "libs.models.trendline.ranking",
        "libs.models.trendline.registry",
        "libs.models.trendline.repository",
        "libs.models.trendline.tracker",
    }
)
_REGIME_COMPATIBILITY_FILES = frozenset(
    {
        ("optimization", "__init__.py"),
        ("optimization", "ablation.py"),
    }
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


def _owner_files() -> list[Path]:
    package_dir = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline"
    return [
        path
        for owner in sorted(_OWNER_PACKAGES)
        for path in (package_dir / owner).rglob("*.py")
    ]


def _direct_owner_implementation_files() -> list[Path]:
    root = Path(__file__).parents[3]
    return [
        root / "src" / "libs" / "models" / "trendline" / "api.py",
        root / "src" / "libs" / "models" / "trendline" / "config_loader.py",
        root / "src" / "libs" / "integrations" / "trendline_regime_v2" / "ablation.py",
        root / "src" / "libs" / "integrations" / "trendline_regime_v2" / "shadow.py",
    ]


def _package_name(path: Path) -> str:
    src_root = Path(__file__).parents[3] / "src"
    relative = path.relative_to(src_root).with_suffix("")
    return ".".join(relative.parts[:-1])


def _resolved_import(path: Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    package = _package_name(path)
    return resolve_name(f"{'.' * node.level}{node.module or ''}", package)


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


def test_only_deprecated_ablation_facades_may_reference_regime_integration() -> None:
    package_dir = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline"
    core_files = [
        path
        for path in _canonical_files()
        if path.relative_to(package_dir).parts not in _REGIME_COMPATIBILITY_FILES
    ]
    assert _forbidden_imports(core_files, _FORBIDDEN_CANONICAL_UPSTREAM_PREFIXES) == []


def test_owner_packages_do_not_depend_on_transitional_facades() -> None:
    violations: list[str] = []
    for path in _owner_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = _resolved_import(path, node)
                if imported in _TRANSITIONAL_FACADES:
                    violations.append(f"{path}: {imported}")
            elif isinstance(node, ast.Import):
                violations.extend(
                    f"{path}: {alias.name}"
                    for alias in node.names
                    if alias.name in _TRANSITIONAL_FACADES
                )
    assert violations == []


def test_api_and_integration_implementations_use_direct_owners() -> None:
    violations: list[str] = []
    for path in _direct_owner_implementation_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = _resolved_import(path, node)
                if imported in _TRANSITIONAL_FACADES:
                    violations.append(f"{path}: {imported}")
            elif isinstance(node, ast.Import):
                violations.extend(
                    f"{path}: {alias.name}"
                    for alias in node.names
                    if alias.name in _TRANSITIONAL_FACADES
                )
    assert violations == []


def test_relative_facade_import_resolves_from_containing_package() -> None:
    package_dir = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline"
    path = package_dir / "tracking" / "service.py"
    tree = ast.parse("from ..contracts import ContractValidationError")
    node = tree.body[0]
    assert isinstance(node, ast.ImportFrom)

    imported = _resolved_import(path, node)

    assert imported == "libs.models.trendline.contracts"
    assert imported in _TRANSITIONAL_FACADES


def test_discovery_contracts_do_not_import_provider_implementation() -> None:
    package_dir = Path(__file__).parents[3] / "src" / "libs" / "models" / "trendline"
    path = package_dir / "discovery" / "contracts.py"
    imports = {
        imported
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        if isinstance(node, ast.ImportFrom)
        if (imported := _resolved_import(path, node)) is not None
    }
    assert "libs.models.trendline.discovery.provider" not in imports


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
