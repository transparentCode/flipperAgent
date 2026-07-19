from __future__ import annotations

import ast
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
import subprocess
import sys


_PACKAGE_PREFIX = "libs.models.sr"
_PACKAGE_DIR = Path(__file__).parents[4] / "src" / "libs" / "models" / "sr"
_CORE_AREAS = {
    "adapters",
    "association",
    "config",
    "detection",
    "domain",
    "evaluation",
    "lifecycle",
    "replay",
    "serialization",
}
_YAML_IMPORT_PATHS = {
    "config/loader.py",
    "research/config/strict_yaml.py",
}
_FORBIDDEN_RESEARCH_PREFIXES = (
    "aiohttp",
    "apps",
    "ccxt",
    "httpx",
    "libs.models.sr.scripts",
    "libs.models.sr.research.studies",
    "libs.models.sr.tools",
    "libs.sr",
    "pandas",
    "psycopg",
    "requests",
    "socket",
    "sqlalchemy",
    "sqlite3",
    "urllib",
)
_EXPECTED_SIBLING_IMPORT_STATEMENTS: Counter[tuple[str, str]] = Counter()
_CONTRACT_FACADES = {
    "domain/contracts.py",
    "evaluation/contracts.py",
}


def _runtime_files() -> list[Path]:
    return sorted(_PACKAGE_DIR.rglob("*.py"))


def _relative_import_module(path: Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    relative = path.relative_to(_PACKAGE_DIR).with_suffix("")
    package_parts = (*_PACKAGE_PREFIX.split("."), *relative.parts[:-1])
    if node.level > len(package_parts):
        return None
    base_parts = package_parts[: len(package_parts) - node.level + 1]
    if node.module:
        base_parts += tuple(node.module.split("."))
    return ".".join(base_parts)


def _imports_from_nodes(
    path: Path,
    nodes: Iterable[ast.AST],
) -> Iterator[tuple[int, str]]:
    for node in nodes:
        if isinstance(node, ast.Import):
            yield from ((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _relative_import_module(path, node)
            if module is not None:
                yield node.lineno, module


def _imported_modules(path: Path) -> Iterator[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    yield from _imports_from_nodes(path, ast.walk(tree))


def _module_scope_imported_modules(path: Path) -> Iterator[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    yield from _imports_from_nodes(path, tree.body)


def _is_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _relative_path(path: Path) -> str:
    return path.relative_to(_PACKAGE_DIR).as_posix()


def _study_name(module: str, *, prefix: str) -> str | None:
    if not module.startswith(prefix):
        return None
    parts = module.removeprefix(prefix).split(".")
    return parts[0] if parts and parts[0] else None


def _sibling_imports(
    *,
    studies_dir: Path,
    module_prefix: str,
) -> Counter[tuple[str, str]]:
    imports: Counter[tuple[str, str]] = Counter()
    for path in sorted(studies_dir.rglob("*.py")):
        importer = path.relative_to(studies_dir).parts[0]
        for _, module in _imported_modules(path):
            imported = _study_name(module, prefix=module_prefix)
            if imported is not None and imported != importer:
                imports[importer, imported] += 1
    return imports


def _research_package_graph() -> dict[str, set[str]]:
    research_dir = _PACKAGE_DIR / "research"
    graph: dict[str, set[str]] = defaultdict(set)
    prefix = f"{_PACKAGE_PREFIX}.research."
    for path in sorted(research_dir.rglob("*.py")):
        if path.relative_to(research_dir).parts[0] == "studies":
            continue
        source = path.relative_to(research_dir).parts[0]
        graph.setdefault(source, set())
        for _, module in _imported_modules(path):
            if not module.startswith(prefix):
                continue
            target_parts = module.removeprefix(prefix).split(".")
            if target_parts and target_parts[0] != source:
                graph[source].add(target_parts[0])
    return graph


def _has_cycle(graph: dict[str, set[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(neighbor) for neighbor in graph[node]):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _top_level_package_graph() -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for path in _runtime_files():
        source = path.relative_to(_PACKAGE_DIR).parts[0]
        graph.setdefault(source, set())
        for _, module in _module_scope_imported_modules(path):
            if not _is_prefix(module, _PACKAGE_PREFIX):
                continue
            suffix = module.removeprefix(f"{_PACKAGE_PREFIX}.")
            if not suffix:
                continue
            target = suffix.split(".", 1)[0]
            if target != source:
                graph[source].add(target)
    return graph


def _cycle_components(graph: dict[str, set[str]]) -> set[frozenset[str]]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: set[frozenset[str]] = set()

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in graph[node]:
            if neighbor not in indices:
                visit(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])
        if lowlinks[node] != indices[node]:
            return
        component: set[str] = set()
        while True:
            member = stack.pop()
            on_stack.remove(member)
            component.add(member)
            if member == node:
                break
        if len(component) > 1:
            components.add(frozenset(component))

    for node in graph:
        if node not in indices:
            visit(node)
    return components


def test_active_sr_never_imports_legacy_libs_sr() -> None:
    violations = [
        f"{_relative_path(path)}:{line} imports {module}"
        for path in _runtime_files()
        for line, module in _imported_modules(path)
        if _is_prefix(module, "libs.sr")
    ]
    assert violations == []


def test_core_modules_do_not_depend_on_research() -> None:
    violations = [
        f"{_relative_path(path)}:{line} imports {module}"
        for path in _runtime_files()
        if path.relative_to(_PACKAGE_DIR).parts[0] in _CORE_AREAS
        for line, module in _imported_modules(path)
        if _is_prefix(module, f"{_PACKAGE_PREFIX}.research")
    ]
    assert violations == []


def test_research_modules_do_not_depend_on_tools() -> None:
    research_dir = _PACKAGE_DIR / "research"
    violations = [
        f"{_relative_path(path)}:{line} imports {module}"
        for path in sorted(research_dir.rglob("*.py"))
        for line, module in _imported_modules(path)
        if _is_prefix(module, f"{_PACKAGE_PREFIX}.tools")
    ]
    assert violations == []


def test_shared_research_modules_do_not_import_studies_or_runtime_services() -> None:
    research_dir = _PACKAGE_DIR / "research"
    violations = [
        f"{_relative_path(path)}:{line} imports {module}"
        for path in sorted(research_dir.rglob("*.py"))
        if path.relative_to(research_dir).parts[0] != "studies"
        for line, module in _imported_modules(path)
        if any(
            _is_prefix(module, forbidden) for forbidden in _FORBIDDEN_RESEARCH_PREFIXES
        )
    ]
    assert violations == []


def test_yaml_imports_stay_at_the_two_approved_locations() -> None:
    yaml_imports = [
        f"{_relative_path(path)}:{line} imports {module}"
        for path in _runtime_files()
        for line, module in _imported_modules(path)
        if _is_prefix(module, "yaml") and _relative_path(path) not in _YAML_IMPORT_PATHS
    ]
    assert yaml_imports == []


def test_sibling_study_imports_are_eliminated_at_r3_completion() -> None:
    assert (
        _sibling_imports(
            studies_dir=_PACKAGE_DIR / "scripts",
            module_prefix=f"{_PACKAGE_PREFIX}.scripts.",
        )
        == _EXPECTED_SIBLING_IMPORT_STATEMENTS
    )


def test_shared_research_package_import_graph_is_acyclic() -> None:
    assert not _has_cycle(_research_package_graph())


def test_core_import_time_package_graph_is_acyclic() -> None:
    cycles = _cycle_components(_top_level_package_graph())
    assert {cycle for cycle in cycles if cycle & _CORE_AREAS} == set()


def test_active_sr_import_time_package_graph_is_acyclic() -> None:
    assert _cycle_components(_top_level_package_graph()) == set()


def test_domain_factory_config_validation_dependency_is_late_and_explicit() -> None:
    path = _PACKAGE_DIR / "domain" / "factory.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    factory = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_initial_state"
    )
    imports = {module for _, module in _imports_from_nodes(path, ast.walk(factory))}
    assert imports == {f"{_PACKAGE_PREFIX}.config.models"}


def test_importing_domain_does_not_import_config_in_a_fresh_process() -> None:
    environment = {"PYTHONPATH": str(_PACKAGE_DIR.parents[2])}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import libs.models.sr.domain; "
            "assert not any(name == 'libs.models.sr.config' or "
            "name.startswith('libs.models.sr.config.') for name in sys.modules)",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_active_modules_import_canonical_contract_owners_not_facades() -> None:
    facade_imports = (
        f"{_PACKAGE_PREFIX}.domain.contracts",
        f"{_PACKAGE_PREFIX}.evaluation.contracts",
    )
    violations = [
        f"{_relative_path(path)}:{line} imports {module}"
        for path in _runtime_files()
        if _relative_path(path) not in _CONTRACT_FACADES
        for line, module in _imported_modules(path)
        if module in facade_imports
    ]
    assert violations == []


def test_active_modules_import_contract_validation_error_from_canonical_owner() -> None:
    legacy_error_module = f"{_PACKAGE_PREFIX}.domain.identity"
    violations: list[str] = []
    for path in _runtime_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = _relative_import_module(path, node)
            if module != legacy_error_module:
                continue
            if any(alias.name == "ContractValidationError" for alias in node.names):
                violations.append(f"{_relative_path(path)}:{node.lineno}")
    assert violations == []


def test_core_contract_facades_are_export_only() -> None:
    violations: list[str] = []
    for relative_path in sorted(_CONTRACT_FACADES):
        path = _PACKAGE_DIR / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    continue
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, ast.Assign) and all(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            ):
                continue
            violations.append(f"{relative_path}:{node.lineno}")
    assert violations == []


def test_shared_package_facades_are_export_only() -> None:
    violations: list[str] = []
    for path in sorted((_PACKAGE_DIR / "research").rglob("__init__.py")):
        if path.relative_to(_PACKAGE_DIR / "research").parts[0] == "studies":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str):
                    continue
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, ast.Assign) and all(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in node.targets
            ):
                continue
            violations.append(f"{_relative_path(path)}:{node.lineno}")
    assert violations == []


def test_canonical_studies_do_not_import_script_studies() -> None:
    canonical_dir = _PACKAGE_DIR / "research" / "studies"
    violations = [
        f"{_relative_path(path)}:{line} imports {module}"
        for path in sorted(canonical_dir.rglob("*.py"))
        for line, module in _imported_modules(path)
        if _is_prefix(module, f"{_PACKAGE_PREFIX}.scripts")
    ]
    assert violations == []


def test_canonical_studies_do_not_import_sibling_studies() -> None:
    assert (
        _sibling_imports(
            studies_dir=_PACKAGE_DIR / "research" / "studies",
            module_prefix=f"{_PACKAGE_PREFIX}.research.studies.",
        )
        == Counter()
    )


def test_r3d_script_facades_only_forward_to_canonical_studies() -> None:
    facade_dirs = (
        _PACKAGE_DIR / "scripts" / "baseline_trial",
        _PACKAGE_DIR / "scripts" / "atr_calibration",
        _PACKAGE_DIR / "scripts" / "cohort_readiness",
        _PACKAGE_DIR / "scripts" / "geometry_sensitivity",
        _PACKAGE_DIR / "scripts" / "baseline_adequacy",
        _PACKAGE_DIR / "scripts" / "context_audit",
        _PACKAGE_DIR / "scripts" / "lifecycle_utility",
        _PACKAGE_DIR / "scripts" / "candidate_reinforcement_audit",
    )
    violations: list[str] = []
    for facade_dir in facade_dirs:
        for path in sorted(facade_dir.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                    if isinstance(node.value.value, str):
                        continue
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    continue
                if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
                    continue
                violations.append(f"{_relative_path(path)}:{node.lineno}")
    assert violations == []


def test_zone_viewer_payload_facade_is_export_only() -> None:
    path = _PACKAGE_DIR / "tools" / "zone_viewer" / "payload.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: list[int] = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Assign) and all(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            continue
        violations.append(node.lineno)
    assert violations == []


def test_canonical_study_set_includes_approved_v2_studies() -> None:
    canonical_dir = _PACKAGE_DIR / "research" / "studies"
    assert {
        path.name
        for path in canonical_dir.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    } == {
        "atr_calibration",
        "baseline_adequacy",
        "baseline_trial",
        "candidate_reinforcement_audit",
        "cohort_readiness",
        "context_audit",
        "displacement_origin_adequacy",
        "geometry_sensitivity",
        "lifecycle_utility",
        "pivot_rejection_adequacy",
        "swing_reversal_adequacy",
    }
