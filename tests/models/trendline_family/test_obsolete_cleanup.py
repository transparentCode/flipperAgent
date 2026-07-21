from __future__ import annotations

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
