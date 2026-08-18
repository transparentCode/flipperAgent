"""R4B source-boundary tests for the legacy SR regression-band kernel."""

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SR_ROOT = _REPO_ROOT / "src" / "libs" / "sr"
_KERNEL_PATH = _SR_ROOT / "kernels" / "regression_band.py"
_PIPELINE_PATH = _SR_ROOT / "pipeline.py"
_MODERN_SR_ROOT = _REPO_ROOT / "src" / "libs" / "models" / "sr"


def _read_tree(path: Path) -> tuple[str, ast.Module]:
    source = path.read_text()
    return source, ast.parse(source, filename=str(path))


def _dotted_import(node: ast.Import | ast.ImportFrom) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    prefix = "." * node.level
    module = node.module or ""
    return [prefix + module]


def _function_names(tree: ast.AST) -> set[str]:
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_legacy_sr_python_has_no_regression_imports() -> None:
    forbidden = ("libs.regression", "app.regression")
    imports: list[tuple[Path, str]] = []

    for path in _SR_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.extend((path, name) for name in _dotted_import(node))

    assert [item for item in imports if item[1].startswith(forbidden)] == []


def test_modern_sr_python_has_no_legacy_sr_imports() -> None:
    forbidden = ("libs.sr", "app.sr")
    imports: list[tuple[Path, str]] = []

    for path in _MODERN_SR_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.extend((path, name) for name in _dotted_import(node))

    assert [item for item in imports if item[1].startswith(forbidden)] == []


def test_kernel_retains_injected_result_and_local_ols_contract() -> None:
    source, tree = _read_tree(_KERNEL_PATH)
    names = _function_names(tree)

    assert "_compute_inline_regression_result" not in names
    assert "_get_regression_resolver" not in names
    assert "_simple_regression_bands" in names
    assert "_extract_regression_values" in names
    assert "compute_single_tf" not in source
    assert "libs.regression" not in source
    assert "app.regression" not in source

    compute = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "compute"
    )
    compute_source = ast.get_source_segment(source, compute)
    assert compute_source is not None
    assert '"regression_result"' in compute_source
    assert "_extract_regression_values" in compute_source
    assert "_simple_regression_bands" in compute_source


def test_pipeline_has_no_regression_band_asset_bridge() -> None:
    source, tree = _read_tree(_PIPELINE_PATH)

    assert 'name == "regression_band"' not in source
    assert '"asset": self._asset' not in source
    assert "regression_band" not in source

    kernel_configs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "KernelConfig"
    ]
    assert len(kernel_configs) == 1
    extra_keyword = next(
        keyword for keyword in kernel_configs[0].keywords if keyword.arg == "extra"
    )
    assert isinstance(extra_keyword.value, ast.Dict)
    assert extra_keyword.value.keys == []
