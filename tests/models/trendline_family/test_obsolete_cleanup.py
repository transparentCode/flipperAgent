from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

from libs.integrations.trendline_regime_v2 import ablation, shadow
from libs.models.trendline import api, config_loader, contracts, mtf, provider, repository, tracker
from libs.models.trendline.configuration import loader as configuration_loader
from libs.models.trendline.discovery import contracts as discovery_contracts
from libs.models.trendline.domain import enums, families, snapshots, validation
from libs.models.trendline.mtf import composition, contracts as mtf_contracts, features
from libs.models.trendline.storage import memory, repository as storage_repository
from libs.models.trendline.tracking import service
from libs.models import trendline_family
from libs.models.trendline_family import config_loader as family_config_loader


_ROOT = Path(__file__).parents[3]
_SRC = _ROOT / "src"
_DOMAIN = _SRC / "libs" / "models" / "trendline" / "domain"
_REMOVED_MODULE_NAMES = ("contracts", "entities")


def test_migrated_imports_preserve_runtime_object_identity() -> None:
    assert api.ContractValidationError is validation.ContractValidationError
    assert api.TrendlineFamilyOutput is snapshots.TrendlineFamilyOutput
    assert api.TrendlineFamilySnapshot is snapshots.TrendlineFamilySnapshot
    assert api.LineCandidateProvider is discovery_contracts.LineCandidateProvider
    assert api.TrendlineFamilyRepository is storage_repository.TrendlineFamilyRepository
    assert api.TrendlineFamilyTracker is service.TrendlineFamilyTracker
    assert api.MTFGeometrySnapshot is mtf_contracts.MTFGeometrySnapshot
    assert api.compose_mtf_snapshot is composition.compose_mtf_snapshot
    assert config_loader.load_trendline_family_config is configuration_loader.load_trendline_family_config
    assert family_config_loader.load_trendline_family_config is configuration_loader.load_trendline_family_config

    assert shadow.ContractValidationError is validation.ContractValidationError
    assert shadow.FamilyRole is enums.FamilyRole
    assert shadow.FamilyTransitionType is enums.FamilyTransitionType
    assert shadow.TrendlineFamilyState is families.TrendlineFamilyState
    assert shadow.TrendlineFamilyOutput is snapshots.TrendlineFamilyOutput
    assert shadow.LineCandidateProvider is discovery_contracts.LineCandidateProvider
    assert shadow.MTFGeometrySnapshot is mtf_contracts.MTFGeometrySnapshot
    assert shadow.build_mtf_shadow_features is features.build_mtf_shadow_features
    assert shadow.InMemoryTrendlineFamilyRepository is memory.InMemoryTrendlineFamilyRepository
    assert shadow.TrendlineFamilyRepository is storage_repository.TrendlineFamilyRepository
    assert ablation.ContractValidationError is validation.ContractValidationError


def test_public_compatibility_surfaces_retain_owner_identity() -> None:
    assert contracts.ContractValidationError is validation.ContractValidationError
    assert provider.LineCandidateProvider is discovery_contracts.LineCandidateProvider
    assert repository.TrendlineFamilyRepository is storage_repository.TrendlineFamilyRepository
    assert tracker.TrendlineFamilyTracker is service.TrendlineFamilyTracker
    assert mtf.MTFGeometrySnapshot is mtf_contracts.MTFGeometrySnapshot
    assert trendline_family.TrendlineFamilySnapshot is snapshots.TrendlineFamilySnapshot


def test_removed_domain_scaffolds_are_absent_and_unreferenced_by_python_code() -> None:
    removed_modules = {
        ".".join(("libs", "models", "trendline", "domain", name))
        for name in _REMOVED_MODULE_NAMES
    }
    assert all(not (_DOMAIN / f"{name}.py").exists() for name in _REMOVED_MODULE_NAMES)

    violations: list[str] = []
    python_paths = (*_SRC.rglob("*.py"), *(_ROOT / "tests").rglob("*.py"))
    for path in python_paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        package: str | None = None
        if path.is_relative_to(_SRC):
            relative = path.relative_to(_SRC).with_suffix("")
            package = ".".join(relative.parts[:-1])
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                violations.extend(
                    f"{path}: {alias.name}" for alias in node.names if alias.name in removed_modules
                )
            elif isinstance(node, ast.ImportFrom):
                imported = node.module
                if node.level and package is not None:
                    imported = resolve_name(f"{'.' * node.level}{node.module or ''}", package)
                if imported in removed_modules:
                    violations.append(f"{path}: {imported}")
        violations.extend(
            f"{path}: dynamic reference to {module}"
            for module in removed_modules
            if module in source
        )
    assert violations == []
