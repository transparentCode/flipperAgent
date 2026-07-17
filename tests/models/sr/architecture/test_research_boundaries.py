from __future__ import annotations

import ast
from collections import Counter, defaultdict
from collections.abc import Iterator
from pathlib import Path


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
_EXPECTED_SIBLING_IMPORT_STATEMENTS = Counter(
    {
        ("atr_calibration", "baseline_trial"): 3,
        ("baseline_adequacy", "baseline_trial"): 1,
        ("baseline_adequacy", "cohort_readiness"): 4,
        ("baseline_adequacy", "geometry_sensitivity"): 2,
        ("candidate_reinforcement_audit", "baseline_adequacy"): 1,
        ("candidate_reinforcement_audit", "baseline_trial"): 1,
        ("candidate_reinforcement_audit", "lifecycle_utility"): 3,
        ("cohort_readiness", "atr_calibration"): 7,
        ("cohort_readiness", "baseline_trial"): 1,
        ("context_audit", "baseline_adequacy"): 4,
        ("context_audit", "baseline_trial"): 1,
        ("context_audit", "cohort_readiness"): 2,
        ("geometry_sensitivity", "baseline_trial"): 1,
        ("geometry_sensitivity", "cohort_readiness"): 6,
        ("lifecycle_utility", "context_audit"): 4,
    }
)
_EXPECTED_TOP_LEVEL_CYCLES = {
    frozenset({"config", "domain"}),
    frozenset({"scripts", "tools"}),
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


def _imported_modules(path: Path) -> Iterator[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from ((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _relative_import_module(path, node)
            if module is not None:
                yield node.lineno, module


def _is_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _relative_path(path: Path) -> str:
    return path.relative_to(_PACKAGE_DIR).as_posix()


def _study_name(module: str) -> str | None:
    prefix = f"{_PACKAGE_PREFIX}.scripts."
    if not module.startswith(prefix):
        return None
    parts = module.removeprefix(prefix).split(".")
    return parts[0] if parts and parts[0] else None


def _sibling_imports() -> Counter[tuple[str, str]]:
    scripts_dir = _PACKAGE_DIR / "scripts"
    imports: Counter[tuple[str, str]] = Counter()
    for path in sorted(scripts_dir.rglob("*.py")):
        importer = path.relative_to(scripts_dir).parts[0]
        for _, module in _imported_modules(path):
            imported = _study_name(module)
            if imported is not None and imported != importer:
                imports[importer, imported] += 1
    return imports


def _research_package_graph() -> dict[str, set[str]]:
    research_dir = _PACKAGE_DIR / "research"
    graph: dict[str, set[str]] = defaultdict(set)
    prefix = f"{_PACKAGE_PREFIX}.research."
    for path in sorted(research_dir.rglob("*.py")):
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
        for _, module in _imported_modules(path):
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


def test_shared_research_modules_do_not_import_studies_or_runtime_services() -> None:
    research_dir = _PACKAGE_DIR / "research"
    violations = [
        f"{_relative_path(path)}:{line} imports {module}"
        for path in sorted(research_dir.rglob("*.py"))
        for line, module in _imported_modules(path)
        if any(_is_prefix(module, forbidden) for forbidden in _FORBIDDEN_RESEARCH_PREFIXES)
    ]
    assert violations == []


def test_yaml_imports_stay_at_the_two_approved_locations() -> None:
    yaml_imports = [
        f"{_relative_path(path)}:{line} imports {module}"
        for path in _runtime_files()
        for line, module in _imported_modules(path)
        if _is_prefix(module, "yaml")
        and _relative_path(path) not in _YAML_IMPORT_PATHS
    ]
    assert yaml_imports == []


def test_sibling_study_imports_match_the_recorded_r2_baseline() -> None:
    assert _sibling_imports() == _EXPECTED_SIBLING_IMPORT_STATEMENTS


def test_shared_research_package_import_graph_is_acyclic() -> None:
    assert not _has_cycle(_research_package_graph())


def test_active_top_level_import_cycles_match_the_recorded_r2_baseline() -> None:
    assert _cycle_components(_top_level_package_graph()) == _EXPECTED_TOP_LEVEL_CYCLES


def test_shared_package_facades_are_export_only() -> None:
    violations: list[str] = []
    for path in sorted((_PACKAGE_DIR / "research").rglob("__init__.py")):
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
