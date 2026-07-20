from __future__ import annotations

import ast
from pathlib import Path
import sys


_SR_IMPORT_PREFIX = "libs.models.sr"
_YAML_IMPORT_PATHS = {
    "config/loader.py",
    "research/config/strict_yaml.py",
}
_BASELINE_EXTERNAL_IMPORTS = {
    "pandas",
    "libs.features.indicators.volatility.atr",
    "apps.ingestion_app.adapters.binance_native",
}

_V23_SOURCE_EXTERNAL_IMPORTS = {
    "apps.ingestion_app.adapters.binance_native",
}

_V24_SOURCE_EXTERNAL_IMPORTS = {
    "apps.ingestion_app.adapters.binance_native",
}


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
    relative = path.relative_to(package_dir)
    is_baseline_integration = relative.parts[:2] == (
        "scripts",
        "baseline_trial",
    ) or relative.parts[:3] == ("research", "studies", "baseline_trial")
    is_v23_source = relative.parts[:4] == (
        "research",
        "studies",
        "adaptive_context_calibration",
        "source.py",
    )
    is_v23_calibration = relative.parts[:4] == (
        "research",
        "studies",
        "adaptive_context_calibration",
        "calibration.py",
    )
    is_v23_metrics = relative.parts[:4] == (
        "research",
        "studies",
        "adaptive_context_calibration",
        "metrics.py",
    )
    is_v24_source = relative.parts[:4] == (
        "research",
        "studies",
        "relative_salience_rank_utility",
        "source.py",
    )
    is_v24_metrics = relative.parts[:4] == (
        "research",
        "studies",
        "relative_salience_rank_utility",
        "metrics.py",
    )
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
        if is_baseline_integration and module in _BASELINE_EXTERNAL_IMPORTS:
            continue
        if is_v23_source and module in _V23_SOURCE_EXTERNAL_IMPORTS:
            continue
        if is_v24_source and module in _V24_SOURCE_EXTERNAL_IMPORTS:
            continue
        if is_v23_calibration and module == "scipy.stats":
            continue
        if is_v23_metrics and module == "numpy":
            continue
        if is_v24_metrics and module == "numpy":
            continue
        if (
            (module == "yaml" or module.startswith("yaml."))
            and any(path.as_posix().endswith(allowed) for allowed in _YAML_IMPORT_PATHS)
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


def test_yaml_imports_remain_confined_to_canonical_config_loader() -> None:
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
            if module is not None and not any(
                path.as_posix().endswith(allowed) for allowed in _YAML_IMPORT_PATHS
            ):
                violations.append(f"{path}: {module}")
    assert violations == []


def test_root_and_empty_leaf_package_imports_are_side_effect_free() -> None:
    import subprocess

    package_code = (
        "import sys; import libs.models.sr; "
        "assert not any(name.startswith('libs.models.sr.scripts') or "
        "name.startswith('libs.models.sr.tools') for name in sys.modules)"
    )
    subprocess.run(
        [sys.executable, "-c", package_code],
        check=True,
        env={**dict(), "PYTHONPATH": "src"},
    )

    leaf_code = (
        "import sys; import libs.models.sr; before = set(sys.modules); "
        "import libs.models.sr.scripts; "
        "import libs.models.sr.scripts.baseline_trial; "
        "import libs.models.sr.tools; import libs.models.sr.tools.zone_viewer; "
        "assert not ({name for name in set(sys.modules) - before if name.startswith('pandas') or name == 'yaml'})"
    )
    subprocess.run(
        [sys.executable, "-c", leaf_code],
        check=True,
        env={**dict(), "PYTHONPATH": "src"},
    )
