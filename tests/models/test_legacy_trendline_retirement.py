"""Regression guard for the retired legacy Trendlines model surfaces."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import re
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_MODEL_ROOT = _REPOSITORY_ROOT / "src" / "libs" / "models"
_LEGACY_TRENDLINES_ROOT = _MODEL_ROOT / "trendlines"
_V4_TRENDLINES_ROOT = _MODEL_ROOT / "trendlines_v4"
_RETAINED_LEGACY_CSVS = {
    "optimization/results/ETHUSDT_1h_2023-01-01_2026-03-01.csv": (
        "96bc7f72e56a4ad70048a17caaa0013dd9ef854b11e7ba6aafc2681ce21d3e77"
    ),
    "optimization/results/SOLUSDT_1h_2023-01-01_2026-03-01.csv": (
        "0711849c9e665c8b5bdba85ffee4cda0eb16f9aa30f7b74678bf09d17bf19c46"
    ),
    "optimization/results/HYPEUSDT_1h_2022-01-01_2026-03-01.csv": (
        "26e7f4276c60ea4c4d3dbe196383c1ef63c1c58d6db1b6280b821490d694d050"
    ),
}
_RETIRED_TEST_TREE = _REPOSITORY_ROOT / "tests" / "models" / "trendline_family"
_RETIRED_PATHS = (
    _RETIRED_TEST_TREE,
    _RETIRED_TEST_TREE / "fixtures" / "native_pathfinding_reference.json",
    _RETIRED_TEST_TREE / "fixtures" / "pre_phase_1b_family_role.pickle",
)
_RETIRED_CONFIG_PATHS = (
    _REPOSITORY_ROOT / "configs" / "trendline_family.yaml",
    _REPOSITORY_ROOT / "configs" / "trendline",
    _REPOSITORY_ROOT / "configs" / "trendline" / "README.md",
    _REPOSITORY_ROOT / "configs" / "trendline_v2.yaml",
)
_RETIRED_PACKAGE_PATHS = (
    _MODEL_ROOT / "trendline",
    _MODEL_ROOT / "trendline_v2",
    _MODEL_ROOT / "trendlines_v3",
    _MODEL_ROOT / "trendline_family",
    _MODEL_ROOT / "trendlines_old",
    _REPOSITORY_ROOT / "src" / "libs" / "trendlines",
    _REPOSITORY_ROOT / "src" / "app" / "trendlines",
)
_RETIRED_NONSTANDARD_SURFACES = (
    _REPOSITORY_ROOT / "benchmarks" / "trendline_numba_atr.py",
    _REPOSITORY_ROOT / "research" / "trendline_family_research_lab.ipynb",
    _REPOSITORY_ROOT / "research" / "trendlines_research_lab.ipynb",
)
_RETIRED_IMPORT_PREFIXES = (
    "app.trendlines",
    "libs.trendlines",
    "libs.models.trendline_v2",
    "libs.models.trendlines",
    "libs.models.trendline",
    "libs.models.trendline_family",
    "libs.models.trendlines_old",
)
_SCAN_ROOTS = ("src", "tests", "scripts", "benchmarks", "research")
_NONSTANDARD_TEXT_ROOTS = ("benchmarks", "research")
_NONSTANDARD_TEXT_SUFFIXES = (".py", ".ipynb", ".md")
_RETIRED_NAMESPACE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    + "|".join(
        re.escape(prefix)
        for prefix in sorted(_RETIRED_IMPORT_PREFIXES, key=len, reverse=True)
    )
    + r")(?![A-Za-z0-9_])"
)
_REMOVED_MODULES = (
    "libs.integrations.trendline_regime_v2",
    "libs.integrations.trendline_configuration",
    "libs.models.regime_v2.adapters.trendline_family_feature_producer",
    "libs.models.trendline.optimization.ablation",
    "libs.models.trendline_family.optimization.ablation",
    "libs.models.trendline_v2",
    "libs.models.trendlines_v3",
    "libs.models.trendline",
    "libs.models.trendline_family",
    "libs.models.trendlines_old",
    "libs.trendlines",
    "app.trendlines",
)


def _is_retired_import(module: str) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in _RETIRED_IMPORT_PREFIXES
    )


def _literal_import_name(call: ast.Call) -> str | None:
    function = call.func
    function_name = (
        function.id
        if isinstance(function, ast.Name)
        else function.attr
        if isinstance(function, ast.Attribute)
        else None
    )
    if function_name not in {"import_module", "__import__"} or not call.args:
        return None

    argument = call.args[0]
    if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
        return argument.value
    return None


def _iter_imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Call):
            module = _literal_import_name(node)
            if module is not None:
                yield module


def _iter_scanned_python_files():
    for root_name in _SCAN_ROOTS:
        root = _REPOSITORY_ROOT / root_name
        if not root.exists():
            continue
        yield from sorted(root.rglob("*.py"))


def _iter_nonstandard_text_files():
    for root_name in _NONSTANDARD_TEXT_ROOTS:
        root = _REPOSITORY_ROOT / root_name
        if not root.exists():
            continue
        for file_path in sorted(root.rglob("*")):
            if (
                file_path.is_file()
                and file_path.suffix in _NONSTANDARD_TEXT_SUFFIXES
                and "__pycache__" not in file_path.parts
                and ".ipynb_checkpoints" not in file_path.parts
            ):
                yield file_path


def _nonstandard_retired_namespace_violations() -> list[str]:
    violations = []
    for file_path in _iter_nonstandard_text_files():
        text = file_path.read_text(encoding="utf-8")
        for match in _RETIRED_NAMESPACE_PATTERN.finditer(text):
            violations.append(f"{file_path}: {match.group()}")
    return violations


def _module_is_absent(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is None
    except ModuleNotFoundError:
        return True


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_retired_test_tree_and_fixtures_are_absent() -> None:
    assert not _RETIRED_TEST_TREE.exists()
    for path in _RETIRED_PATHS:
        assert not path.exists(), path


def test_retired_configuration_contract_is_absent() -> None:
    for path in _RETIRED_CONFIG_PATHS:
        assert not path.exists(), path


def test_retired_model_packages_are_absent() -> None:
    for path in _RETIRED_PACKAGE_PATHS:
        assert not path.exists(), path

    for module_name in (
        "libs.models.trendline",
        "libs.models.trendline_v2",
        "libs.models.trendlines_v3",
        "libs.models.trendline_family",
        "libs.models.trendlines_old",
    ):
        assert _module_is_absent(module_name), module_name


def test_retired_nonstandard_trendline_surfaces_are_absent() -> None:
    for path in _RETIRED_NONSTANDARD_SURFACES:
        assert not path.exists(), path


def test_nonstandard_active_roots_do_not_reference_retired_trendline_namespaces() -> (
    None
):
    violations = _nonstandard_retired_namespace_violations()

    assert not violations, "\n".join(violations)


def test_legacy_plural_shell_is_data_only_and_not_executable() -> None:
    assert _LEGACY_TRENDLINES_ROOT.is_dir()
    actual_files = {
        file_path.relative_to(_LEGACY_TRENDLINES_ROOT).as_posix()
        for file_path in _LEGACY_TRENDLINES_ROOT.rglob("*")
        if file_path.is_file()
    }
    assert actual_files == set(_RETAINED_LEGACY_CSVS)
    assert not (_LEGACY_TRENDLINES_ROOT / "__init__.py").exists()
    spec = importlib.util.find_spec("libs.models.trendlines")
    assert spec is None or spec.origin is None
    for relative_path, expected_sha in _RETAINED_LEGACY_CSVS.items():
        path = _LEGACY_TRENDLINES_ROOT / relative_path
        assert _sha256(path) == expected_sha


def test_only_v4_remains_as_executable_trendline_model() -> None:
    actual = {
        path.name
        for path in _MODEL_ROOT.iterdir()
        if path.is_dir() and path.name.startswith("trendline")
    }

    assert actual == {"trendlines", "trendlines_v4"}
    assert (_V4_TRENDLINES_ROOT / "__init__.py").is_file()


def test_no_executable_consumer_imports_retired_trendline_namespaces() -> None:
    violations = []
    for path in _iter_scanned_python_files():
        for module in _iter_imports(path):
            if _is_retired_import(module):
                violations.append(f"{path}: {module}")

    assert not violations, "\n".join(violations)


def test_earlier_retirement_boundaries_remain_absent() -> None:
    for module_name in _REMOVED_MODULES:
        assert _module_is_absent(module_name), module_name
