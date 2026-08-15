"""Fresh-process guards for MI0 model import isolation and legacy bootstrap."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"

EXPECTED_MODEL_REGISTRY = (
    "DivergenceEdgeScorer",
    "KyleTFI",
    "MeanReversion",
    "Momentum",
    "PriceAction",
    "RegimeClassification",
    "RegimePullbackScorer",
    "RegimeRelativeValueScorer",
    "SqueezeBreakout",
    "SqueezeBreakoutScorer",
    "TrendFollowing",
    "VPINKyle",
)

EXPECTED_STRATEGY_REGISTRY = (
    "DivergenceEdgeV2",
    "KyleTFIV2",
    "MeanReversionV2",
    "MomentumV2",
    "PriceActionV2",
    "RegimePullbackV2",
    "SqueezeBreakoutV2",
    "VPINKyleV2",
)


def _run_fresh_process(script: str) -> None:
    environment = {**os.environ, "PYTHONPATH": str(SOURCE_ROOT)}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=SOURCE_ROOT.parent,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_plain_libs_models_import_has_no_discovery_side_effect() -> None:
    _run_fresh_process(
        """
import libs.models
from libs.models.registry import ModelRegistry
from libs.models.strategy_registry import StrategyModelRegistry

assert ModelRegistry.list_all() == []
assert StrategyModelRegistry.list_all() == []
"""
    )


def test_decision_plugin_import_isolated_from_legacy_model_graph() -> None:
    _run_fresh_process(
        """
import sys
from libs.models.momentum.adapters.decision_plugin import MomentumDecisionPlugin

assert MomentumDecisionPlugin.__name__ == "MomentumDecisionPlugin"
for forbidden in (
    "pandas",
    "libs.contracts.signal",
    "libs.models.base",
    "libs.models.registry",
    "libs.models.strategy_model_v2",
    "libs.models.strategy_registry",
    "libs.models.momentum.model",
    "libs.models.momentum.strategy_v2",
):
    assert forbidden not in sys.modules, forbidden

allowed = {
    "libs.models",
    "libs.models.momentum",
    "libs.models.momentum.adapters",
    "libs.models.momentum.adapters.decision_plugin",
    "libs.models.momentum.config",
    "libs.models.momentum.core",
}
unexpected = {
    name for name in sys.modules
    if name == "libs.models" or name.startswith("libs.models.")
} - allowed
assert unexpected == set(), unexpected
"""
    )


def test_decision_plugin_does_not_bootstrap_empty_legacy_registries() -> None:
    _run_fresh_process(
        """
from libs.models.momentum.adapters.decision_plugin import MomentumDecisionPlugin
from libs.models.registry import ModelRegistry
from libs.models.strategy_registry import StrategyModelRegistry

assert MomentumDecisionPlugin
assert ModelRegistry.list_all() == []
assert StrategyModelRegistry.list_all() == []
"""
    )


def test_legacy_bootstrap_reproduces_exact_inventories_and_is_idempotent() -> None:
    _run_fresh_process(
        f"""
from libs.models.legacy_bootstrap import bootstrap_legacy_model_registries
from libs.models.registry import ModelRegistry
from libs.models.strategy_registry import StrategyModelRegistry

expected_models = {EXPECTED_MODEL_REGISTRY!r}
expected_strategies = {EXPECTED_STRATEGY_REGISTRY!r}
bootstrap_legacy_model_registries()
first_model_order = tuple(ModelRegistry.list_all())
first_strategy_order = tuple(StrategyModelRegistry.list_all())
assert first_model_order == expected_models
assert first_strategy_order == expected_strategies
assert ModelRegistry.get("Momentum").__name__ == "MomentumModel"
assert StrategyModelRegistry.get("MomentumV2").__name__ == "MomentumV2"
first_model_classes = {{name: ModelRegistry.get(name) for name in first_model_order}}
first_strategy_classes = {{
    name: StrategyModelRegistry.get(name) for name in first_strategy_order
}}

bootstrap_legacy_model_registries()
assert tuple(ModelRegistry.list_all()) == first_model_order
assert tuple(StrategyModelRegistry.list_all()) == first_strategy_order
assert {{
    name: ModelRegistry.get(name) for name in first_model_order
}} == first_model_classes
assert {{
    name: StrategyModelRegistry.get(name) for name in first_strategy_order
}} == first_strategy_classes
"""
    )


def test_momentum_legacy_public_exports_remain_explicitly_compatible() -> None:
    _run_fresh_process(
        """
from libs.models.momentum import (
    MomentumConfig,
    MomentumModel,
    MomentumObservation,
    MomentumResult,
    MomentumV2,
    evaluate_momentum,
)

assert MomentumConfig.__name__ == "MomentumConfig"
assert MomentumModel.__name__ == "MomentumModel"
assert MomentumObservation.__name__ == "MomentumObservation"
assert MomentumResult.__name__ == "MomentumResult"
assert MomentumV2.__name__ == "MomentumV2"
assert callable(evaluate_momentum)
"""
    )


def test_models_package_init_contains_no_implicit_discovery_call() -> None:
    package_init = SOURCE_ROOT / "libs/models/__init__.py"
    assert "auto_discover" not in package_init.read_text(encoding="utf-8")


def test_config_alignment_bootstraps_only_at_validation_boundary() -> None:
    _run_fresh_process(
        """
from libs.common.config import ConfigManager
from libs.models.registry import ModelRegistry

assert ModelRegistry.list_all() == []
cm = object.__new__(ConfigManager)
cm._state = {
    "features": {"assets": {"BTCUSDT": {"timeframes": {"1h": {"RSI": {}}}}}},
    "models": {
        "assets": {
            "BTCUSDT": {
                "timeframes": {
                    "1h": {"Momentum": {"enabled": True, "params": {}}}
                }
            }
        }
    },
}

warnings = cm.validate_feature_model_alignment()
assert "Momentum" in ModelRegistry.list_all()
assert any("Momentum" in warning and "MACD" in warning for warning in warnings)
"""
    )


def test_registration_intent_has_no_plain_libs_models_import() -> None:
    roots = (SOURCE_ROOT, SOURCE_ROOT.parent / "scripts")
    violations: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if any(
                isinstance(node, ast.Import)
                and any(alias.name == "libs.models" for alias in node.names)
                for node in ast.walk(tree)
            ):
                violations.append(str(path))
    assert violations == []
