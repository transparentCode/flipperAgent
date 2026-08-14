"""Permanent anti-overengineering guards for the decision_app boundary."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src" / "apps" / "decision_app"
GENERIC_MODULES = {
    "data.py",
    "live_runtime.py",
    "model_runtime.py",
    "planner.py",
    "service.py",
    "startup.py",
}
LEGACY_RUNTIME_PREFIXES = (
    "apps.ingestion_app",
    "apps.signal_app",
    "apps.strategy_app",
    "apps.risk_app",
    "apps.execution_app",
)
FORBIDDEN_RUNTIME_NAMES = (
    "FeatureVector",
    "ModelManager",
    "SignalRuntimeRunner",
    "StrategyRuntimeRunner",
)
FORBIDDEN_STREAM_METHODS = ("xreadgroup", "xack", "xautoclaim", "xgroup")


def _source_files() -> tuple[Path, ...]:
    return tuple(sorted(SOURCE_ROOT.rglob("*.py")))


def _parsed_sources() -> tuple[tuple[Path, str, ast.Module], ...]:
    parsed: list[tuple[Path, str, ast.Module]] = []
    for path in _source_files():
        text = path.read_text(encoding="utf-8")
        parsed.append((path, text, ast.parse(text, filename=str(path))))
    return tuple(parsed)


def _import_names(tree: ast.Module) -> tuple[str, ...]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.append(node.module)
    return tuple(names)


def test_decision_app_does_not_import_legacy_runtime_apps() -> None:
    offenders: list[str] = []
    for path, _, tree in _parsed_sources():
        for name in _import_names(tree):
            if name == "apps" or name.startswith(LEGACY_RUNTIME_PREFIXES):
                offenders.append(f"{path}: {name}")
    assert offenders == []


def test_generic_decision_modules_do_not_import_model_implementation_packages() -> None:
    offenders: list[str] = []
    for path, _, tree in _parsed_sources():
        if path.name not in GENERIC_MODULES:
            continue
        for name in _import_names(tree):
            if name.startswith("libs.models"):
                offenders.append(f"{path}: {name}")
    assert offenders == []


def test_generic_runtime_has_no_legacy_model_or_featurevector_surface() -> None:
    offenders: list[str] = []
    for path, text, _ in _parsed_sources():
        for name in FORBIDDEN_RUNTIME_NAMES:
            if name in text:
                offenders.append(f"{path}: {name}")
    assert offenders == []


def test_market_and_lifecycle_inputs_use_direct_xread_only() -> None:
    offenders: list[str] = []
    for path, text, _ in _parsed_sources():
        lowered = text.lower()
        for method in FORBIDDEN_STREAM_METHODS:
            if f".{method}" in lowered or f'"{method}"' in lowered:
                offenders.append(f"{path}: {method}")
    assert offenders == []


def test_plugin_loading_is_explicit_not_discovered_dynamically() -> None:
    offenders: list[str] = []
    for path, text, tree in _parsed_sources():
        lowered = text.lower()
        for token in ("pkgutil", "entry_points(", "importlib.metadata"):
            if token in lowered:
                offenders.append(f"{path}: {token}")
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"walk_packages", "iter_modules"}
            ):
                offenders.append(f"{path}: {node.func.attr}")
    assert offenders == []


def test_generic_orchestration_has_no_model_specific_branches() -> None:
    offenders: list[str] = []
    for path, _, tree in _parsed_sources():
        if path.name not in GENERIC_MODULES:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            condition = ast.unparse(node.test)
            if "plugin_name" in condition:
                offenders.append(f"{path}: {condition}")
    assert offenders == []


def test_generation_and_transport_boundaries_do_not_guess_signatures() -> None:
    offenders: list[str] = []
    for path, text, _ in _parsed_sources():
        if "inspect.signature" in text or "_maybe_await" in text:
            offenders.append(str(path))
        if path.name == "service.py" and "asyncio.wait_for" in text:
            offenders.append(f"{path}: periodic wake fallback")
        if (
            path.name
            in {
                "lifecycle.py",
                "live_input.py",
                "service.py",
                "signal_transport.py",
                "startup.py",
            }
            and "except TypeError" in text
        ):
            offenders.append(f"{path}: TypeError compatibility fallback")
    assert offenders == []


def test_dead_decision_runtime_aliases_are_not_reintroduced() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in _source_files())
    for alias in (
        "LiveInputReader",
        "DecisionModelRuntime",
        "LaneModelRuntime",
        "rewarm_causally",
    ):
        assert alias not in text
