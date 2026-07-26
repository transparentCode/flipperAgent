import ast
from pathlib import Path


TRENDLINES_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = TRENDLINES_ROOT.parent

CANONICAL_BOUNDARY_SYMBOL_PATHS = {
    "INTERACTION_DIRECTION": Path("trendlines/boundary/__init__.py"),
    "interaction_direction": Path("trendlines/boundary/__init__.py"),
    "Ray": Path("trendlines/boundary/contracts.py"),
    "QualityMetrics": Path("trendlines/boundary/contracts.py"),
    "BoundaryResult": Path("trendlines/boundary/contracts.py"),
    "TouchDeclusterConfig": Path("trendlines/boundary/policy.py"),
    "TouchDiagnostics": Path("trendlines/boundary/policy.py"),
    "ConfluenceGateConfig": Path("trendlines/boundary/policy.py"),
    "ConfluenceQualitySnapshot": Path("trendlines/boundary/policy.py"),
    "RayTrackerConfig": Path("trendlines/boundary/policy.py"),
    "TrackedRayState": Path("trendlines/boundary/policy.py"),
    "decluster_touch_indices": Path("trendlines/boundary/touches.py"),
    "build_boundary_result_from_trendline_result": Path("trendlines/boundary/adapters.py"),
    "trendline_to_boundary_ray": Path("trendlines/boundary/adapters.py"),
}


def _package_files(*parts: str) -> list[Path]:
    target = TRENDLINES_ROOT.joinpath(*parts)
    return sorted(
        path
        for path in target.rglob("*.py")
        if "__pycache__" not in path.parts
        and "tests" not in path.parts
        and "scripts" not in path.parts
    )


def _non_geometry_app_python_files() -> list[Path]:
    return sorted(
        path
        for path in APP_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
        and "tests" not in path.parts
        and "geometry" not in path.parts
    )


def _app_notebook_files() -> list[Path]:
    notebook_root = APP_ROOT / "notebook"
    if not notebook_root.exists():
        return []
    return sorted(path for path in notebook_root.rglob("*.ipynb") if "__pycache__" not in path.parts)


def _absolute_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.append(node.module)
    return imports


def _top_level_definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    definitions: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            definitions.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    definitions.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            definitions.add(node.target.id)
    return definitions


def _from_import_violations(
    paths: list[Path],
    module: str,
    banned_names: set[str],
    *,
    relative_to: Path,
) -> list[str]:
    violations: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level != 0 or node.module != module:
                continue

            imported_names = {alias.name for alias in node.names}
            if "*" in imported_names:
                violations.append(f"{path.relative_to(relative_to)} -> {module}.*")
                continue

            for name in sorted(imported_names & banned_names):
                violations.append(f"{path.relative_to(relative_to)} -> {module}.{name}")

    return violations


def _violations(
    paths: list[Path],
    banned_prefixes: tuple[str, ...],
    *,
    relative_to: Path = TRENDLINES_ROOT,
    allowed_prefixes: tuple[str, ...] = (),
) -> list[str]:
    violations: list[str] = []
    for path in paths:
        for imported in _absolute_imports(path):
            if any(
                imported == prefix or imported.startswith(prefix + ".")
                for prefix in banned_prefixes
            ) and not any(
                imported == prefix or imported.startswith(prefix + ".")
                for prefix in allowed_prefixes
            ):
                violations.append(f"{path.relative_to(relative_to)} -> {imported}")
    return violations


def _text_violations(
    paths: list[Path],
    banned_snippets: tuple[str, ...],
    *,
    relative_to: Path,
) -> list[str]:
    violations: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for snippet in banned_snippets:
            if snippet in text:
                violations.append(f"{path.relative_to(relative_to)} -> {snippet}")
    return violations


def test_trendlines_package_has_no_app_namespace_dependencies():
    package_files = _package_files()

    violations = []
    for path in package_files:
        for imported in _absolute_imports(path):
            if imported == "app" or imported.startswith("app."):
                violations.append(f"{path.relative_to(TRENDLINES_ROOT)} -> {imported}")
            if "research_viewer" not in path.parts and (
                imported == "libs.models.trendlines.research_viewer"
                or imported.startswith("libs.models.trendlines.research_viewer.")
            ):
                violations.append(f"core -> viewer: {path.relative_to(TRENDLINES_ROOT)} -> {imported}")
            if "research_viewer" in path.parts and (
                imported == "apps"
                or imported.startswith("apps.")
                or imported == "app"
                or imported.startswith("app.")
                or imported.startswith("IPython")
                or imported.startswith("jupyter")
                or imported.startswith("plotly")
                or imported.startswith("matplotlib")
            ):
                violations.append(f"viewer dependency: {path.relative_to(TRENDLINES_ROOT)} -> {imported}")

    assert violations == []


def test_contracts_do_not_import_pivots_fitting_registry_or_pipeline():
    violations = _violations(
        _package_files("contracts"),
        (
            "libs.models.trendlines.boundary",
            "libs.models.trendlines.pivots",
            "libs.models.trendlines.fitting",
            "libs.models.trendlines.registry",
            "libs.models.trendlines.pipeline",
            "libs.models.trendlines.signals",
        ),
    )

    assert violations == []


def test_pivots_do_not_import_fitting_registry_or_pipeline():
    violations = _violations(
        _package_files("pivots"),
        (
            "libs.models.trendlines.boundary",
            "libs.models.trendlines.fitting",
            "libs.models.trendlines.registry",
            "libs.models.trendlines.pipeline",
            "libs.models.trendlines.signals",
        ),
    )

    assert violations == []


def test_fitting_do_not_import_registry_or_pipeline():
    violations = _violations(
        _package_files("fitting"),
        (
            "libs.models.trendlines.boundary",
            "libs.models.trendlines.registry",
            "libs.models.trendlines.pipeline",
            "libs.models.trendlines.signals",
        ),
    )

    assert violations == []


def test_data_do_not_import_pivots_fitting_registry_or_pipeline():
    violations = _violations(
        _package_files("data"),
        (
            "libs.models.trendlines.boundary",
            "libs.models.trendlines.pivots",
            "libs.models.trendlines.fitting",
            "libs.models.trendlines.registry",
            "libs.models.trendlines.pipeline",
            "libs.models.trendlines.signals",
        ),
    )

    assert violations == []


def test_registry_does_not_import_pipeline_boundary_or_signals():
    violations = _violations(
        _package_files("registry"),
        ("libs.models.trendlines.pipeline", "libs.models.trendlines.boundary", "libs.models.trendlines.signals"),
    )

    assert violations == []


def test_pipeline_does_not_import_boundary_or_signals():
    violations = _violations(
        _package_files("pipeline"),
        ("libs.models.trendlines.boundary", "libs.models.trendlines.signals"),
    )

    assert violations == []


def test_boundary_does_not_import_geometry_registry_pipeline_workflows_or_signals():
    violations = _violations(
        _package_files("boundary"),
        (
            "app.geometry",
            "libs.models.trendlines.data",
            "libs.models.trendlines.registry",
            "libs.models.trendlines.pipeline",
            "libs.models.trendlines.signals",
            "libs.models.trendlines.workflows",
        ),
    )

    assert violations == []


def test_workflows_common_do_not_import_pivots_fitting_registry_or_pipeline():
    violations = _violations(
        _package_files("workflows", "common"),
        (
            "libs.models.trendlines.pivots",
            "libs.models.trendlines.fitting",
            "libs.models.trendlines.registry",
            "libs.models.trendlines.pipeline",
            "libs.models.trendlines.signals",
        ),
    )

    assert violations == []


def test_workflows_pipeline_do_not_import_geometry():
    violations = _violations(_package_files("workflows", "pipeline"), ("app.geometry",))

    assert violations == []


def test_signals_do_not_import_data_pivots_fitting_contracts_registry_pipeline_or_workflows():
    violations = _violations(
        _package_files("signals"),
        (
            "libs.models.trendlines.data",
            "libs.models.trendlines.pivots",
            "libs.models.trendlines.fitting",
            "libs.models.trendlines.contracts",
            "libs.models.trendlines.registry",
            "libs.models.trendlines.pipeline",
            "libs.models.trendlines.workflows",
        ),
        allowed_prefixes=("libs.models.trendlines.contracts.identity",),
    )

    assert violations == []


def test_non_geometry_app_python_files_do_not_reference_geometry_module():
    import_violations = _violations(
        _non_geometry_app_python_files(),
        ("app.geometry",),
        relative_to=APP_ROOT,
    )
    text_violations = _text_violations(
        _non_geometry_app_python_files(),
        ("app.geometry",),
        relative_to=APP_ROOT,
    )

    assert import_violations + text_violations == []


def test_app_notebooks_do_not_reference_geometry_compatibility():
    violations = _text_violations(
        _app_notebook_files(),
        ("app.geometry", "GeometryOrchestrator"),
        relative_to=APP_ROOT,
    )

    assert violations == []


def test_non_geometry_app_python_files_do_not_reference_alpha_native_signal_compatibility():
    paths = _non_geometry_app_python_files()
    module_violations = _violations(
        paths,
        (
            "app.alpha.base",
            "app.alpha._runtime.structural",
            "app.alpha._runtime.temporal",
            "app.alpha._runtime.patterns",
            "app.alpha._runtime.fakeout",
            "app.alpha._runtime.constants",
            "app.alpha._runtime.quality",
            "app.alpha._runtime.temporal_utils",
            "app.alpha._runtime.context_utils",
        ),
        relative_to=APP_ROOT,
    )
    runtime_export_violations = _from_import_violations(
        paths,
        module="app.alpha._runtime",
        banned_names={
            "StructuralAlphaExtractor",
            "TemporalAlphaExtractor",
            "PatternAlphaExtractor",
            "FakeoutAlphaExtractor",
        },
        relative_to=APP_ROOT,
    )
    alpha_export_violations = _from_import_violations(
        paths,
        module="app.alpha",
        banned_names={"AlphaSignal", "BaseAlphaExtractor"},
        relative_to=APP_ROOT,
    )

    assert module_violations + runtime_export_violations + alpha_export_violations == []


def test_shared_boundary_symbols_have_single_canonical_definition():
    violations: list[str] = []

    for path in _non_geometry_app_python_files():
        relative_path = path.relative_to(APP_ROOT)
        definitions = _top_level_definitions(path)
        for symbol, canonical_path in CANONICAL_BOUNDARY_SYMBOL_PATHS.items():
            if symbol in definitions and relative_path != canonical_path:
                violations.append(f"{relative_path} -> {symbol} should live in {canonical_path}")

    assert violations == []
