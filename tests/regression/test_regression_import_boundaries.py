"""Removal guards for the retired regression execution stack."""

import ast
import importlib.util
import inspect
from pathlib import Path

from libs.regression import api

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGRESSION_ROOT = _REPO_ROOT / "src" / "libs" / "regression"
_CANONICAL_TESTS = _REPO_ROOT / "tests" / "regression"

_RETIRED_MODULES = (
    "libs.regression.compat",
    "libs.regression.pipeline",
    "libs.regression.state",
    "libs.regression.universe",
    "libs.regression.registry",
    "libs.regression.optimization",
    "libs.regression.features",
    "libs.regression.methods",
    "libs.regression.ensemble",
    "libs.regression.uncertainty",
    "libs.regression.contracts.context",
    "libs.regression.contracts.result",
    "libs.regression.config.validator",
)
_RETIRED_SYMBOLS = {
    "compute_single_tf",
    "compute_single_tf_series",
    "compute_mtf",
    "compute_universe",
    "optimize_regression",
    "RegressionPipeline",
}


def _import_references(path: Path) -> list[tuple[str, str]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    references: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            references.extend((alias.name, "") for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = ("." * node.level) + (node.module or "")
            references.extend((module, alias.name) for alias in node.names)
    return references


def _is_retired_module(module: str) -> bool:
    return any(
        module == retired or module.startswith(retired + ".")
        for retired in _RETIRED_MODULES
    )


def _retired_references(path: Path) -> list[tuple[str, str]]:
    references = _import_references(path)
    return [
        (module, symbol)
        for module, symbol in references
        if _is_retired_module(module)
        or (symbol in _RETIRED_SYMBOLS and module.startswith("libs.regression"))
        or module == "app.regression"
        or module.startswith("app.regression.")
    ]


def test_supported_api_contains_only_three_computations() -> None:
    public_functions = {
        name
        for name, value in vars(api).items()
        if not name.startswith("_") and inspect.isfunction(value)
    }

    assert public_functions == {
        "compute_structural_estimate",
        "compute_structural_channel",
        "compute_regression_context",
    }


def test_retired_modules_are_absent() -> None:
    retired_paths = (
        _REGRESSION_ROOT / "compat.py",
        _REGRESSION_ROOT / "pipeline.py",
        _REGRESSION_ROOT / "state.py",
        _REGRESSION_ROOT / "universe.py",
        _REGRESSION_ROOT / "registry.py",
        _REGRESSION_ROOT / "optimization",
        _REGRESSION_ROOT / "features",
        _REGRESSION_ROOT / "methods",
        _REGRESSION_ROOT / "ensemble",
        _REGRESSION_ROOT / "uncertainty",
        _REGRESSION_ROOT / "contracts" / "context.py",
        _REGRESSION_ROOT / "contracts" / "result.py",
        _REGRESSION_ROOT / "config" / "validator.py",
    )
    assert all(not path.exists() for path in retired_paths)

    for module_name in _RETIRED_MODULES:
        try:
            spec = importlib.util.find_spec(module_name)
        except ModuleNotFoundError:
            spec = None
        assert spec is None, module_name


def test_no_retired_production_imports_remain() -> None:
    violations: list[tuple[Path, list[tuple[str, str]]]] = []
    for path in (_REPO_ROOT / "src").rglob("*.py"):
        references = _retired_references(path)
        if references:
            violations.append((path, references))
    assert violations == []


def test_no_stale_regression_imports_remain_in_canonical_code_or_tests() -> None:
    violations: list[tuple[Path, list[tuple[str, str]]]] = []
    paths = list(_REGRESSION_ROOT.rglob("*.py")) + [
        path
        for path in _CANONICAL_TESTS.rglob("*.py")
        if path.name != Path(__file__).name
    ]
    for path in paths:
        references = _retired_references(path)
        if references:
            violations.append((path, references))
    assert violations == []
