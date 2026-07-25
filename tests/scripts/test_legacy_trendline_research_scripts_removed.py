from __future__ import annotations

import ast
from pathlib import Path


_ROOT = Path(__file__).parents[2]
_RETIRED_PATHS = (
    _ROOT / "scripts" / "analyze_trendline_family_candidate_density.py",
    _ROOT / "scripts" / "analyze_trendline_family_candidate_quality_normalization.py",
    _ROOT / "scripts" / "build_trendline_family_candidate_evidence_report.py",
    _ROOT / "scripts" / "diagnose_trendline_family_candidate_rejection.py",
    _ROOT / "scripts" / "run_trendline_family_candidate_geometry_trial.py",
    _ROOT / "scripts" / "run_trendline_family_saturating_quality_fresh_window_trial.py",
    _ROOT / "tests" / "scripts" / "test_trendline_family_candidate_density.py",
    _ROOT / "tests" / "scripts" / "test_trendline_family_candidate_quality_normalization.py",
    _ROOT / "tests" / "scripts" / "test_trendline_family_candidate_evidence_report.py",
    _ROOT / "tests" / "scripts" / "test_trendline_family_candidate_rejection.py",
    _ROOT / "tests" / "scripts" / "test_trendline_family_candidate_geometry_trial.py",
    _ROOT / "tests" / "scripts" / "test_trendline_family_saturating_quality_fresh_window_trial.py",
)
_RETIRED_PREFIXES = (
    "libs.models.trendline",
    "libs.models.trendline_family",
)


def _is_retired_prefix(module: str) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in _RETIRED_PREFIXES)


def _dynamic_import_module(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name) and node.func.id == "__import__":
        function_name = "__import__"
    elif isinstance(node.func, ast.Attribute) and node.func.attr == "import_module":
        function_name = "import_module"
    else:
        return None
    if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
        return None
    if function_name in {"import_module", "__import__"}:
        return node.args[0].value
    return None


def test_retired_research_script_and_test_paths_are_absent() -> None:
    assert all(not path.exists() for path in _RETIRED_PATHS)


def test_remaining_scripts_do_not_import_singular_models() -> None:
    violations: list[str] = []
    for path in (_ROOT / "scripts").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported_modules: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                imported_modules = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules = (node.module,)
            elif isinstance(node, ast.Call):
                dynamic_module = _dynamic_import_module(node)
                if dynamic_module is not None:
                    imported_modules = (dynamic_module,)
            violations.extend(
                f"{path}:{node.lineno}: {module}"
                for module in imported_modules
                if _is_retired_prefix(module)
            )

    assert violations == []
