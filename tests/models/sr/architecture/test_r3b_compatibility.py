from __future__ import annotations

from libs.models.sr.research.cohort import artifacts as shared_cohort_artifacts
from libs.models.sr.research.cohort import config as shared_cohort_config
from libs.models.sr.research.cohort import contracts as shared_cohort_contracts
from libs.models.sr.research.cohort import metrics as shared_cohort_metrics
from libs.models.sr.research.studies.cohort_readiness import cli as canonical_cohort_cli
from libs.models.sr.research.studies.cohort_readiness import artifacts as canonical_cohort_artifacts
from libs.models.sr.research.studies.cohort_readiness import config as canonical_cohort_config
from libs.models.sr.research.studies.cohort_readiness import contracts as canonical_cohort_contracts
from libs.models.sr.research.studies.cohort_readiness import runner as canonical_cohort_runner
from libs.models.sr.research.studies.cohort_readiness import metrics as canonical_cohort_metrics
from libs.models.sr.research.studies.cohort_readiness import source as canonical_cohort_source
from libs.models.sr.research.studies.geometry_sensitivity import cli as canonical_geometry_cli
from libs.models.sr.research.studies.geometry_sensitivity import contracts as canonical_geometry_contracts
from libs.models.sr.research.studies.geometry_sensitivity import runner as canonical_geometry_runner
from libs.models.sr.scripts.cohort_readiness import cli as legacy_cohort_cli
from libs.models.sr.scripts.cohort_readiness import artifacts as legacy_cohort_artifacts
from libs.models.sr.scripts.cohort_readiness import config as legacy_cohort_config
from libs.models.sr.scripts.cohort_readiness import contracts as legacy_cohort_contracts
from libs.models.sr.scripts.cohort_readiness import runner as legacy_cohort_runner
from libs.models.sr.scripts.cohort_readiness import metrics as legacy_cohort_metrics
from libs.models.sr.scripts.geometry_sensitivity import cli as legacy_geometry_cli
from libs.models.sr.scripts.geometry_sensitivity import contracts as legacy_geometry_contracts
from libs.models.sr.scripts.geometry_sensitivity import runner as legacy_geometry_runner


def test_r3b_cohort_contracts_keep_exact_legacy_and_shared_identity() -> None:
    assert legacy_cohort_contracts.AssetSource is canonical_cohort_contracts.AssetSource
    assert legacy_cohort_contracts.AssetSource is shared_cohort_contracts.AssetSource
    assert legacy_cohort_contracts.CohortEvaluation is shared_cohort_contracts.CohortEvaluation
    assert legacy_cohort_config.CohortConfig is canonical_cohort_config.CohortConfig
    assert legacy_cohort_config.CohortConfig is shared_cohort_config.CohortConfig
    assert legacy_cohort_runner.evaluate_stage is canonical_cohort_runner.evaluate_stage
    assert legacy_cohort_runner.default_provider_adapter is canonical_cohort_source.default_provider_adapter
    assert canonical_cohort_contracts.SourceBundle is shared_cohort_contracts.SourceBundle
    assert legacy_cohort_artifacts.validate_evaluation_bundle is canonical_cohort_artifacts.validate_evaluation_bundle
    assert canonical_cohort_artifacts.validate_evaluation_bundle is shared_cohort_artifacts.validate_evaluation_bundle
    assert legacy_cohort_metrics.replay_asset is canonical_cohort_metrics.replay_asset
    assert canonical_cohort_metrics.replay_asset is shared_cohort_metrics.replay_asset


def test_r3b_geometry_contract_and_runner_exports_keep_exact_identity() -> None:
    assert legacy_geometry_contracts.GeometryCandidate is canonical_geometry_contracts.GeometryCandidate
    assert legacy_geometry_contracts.GeometrySensitivityStudy is canonical_geometry_contracts.GeometrySensitivityStudy
    assert legacy_geometry_runner.compute_study is canonical_geometry_runner.compute_study


def test_r3b_cli_facades_forward_exact_entrypoints_and_parsers() -> None:
    assert legacy_cohort_cli.main is canonical_cohort_cli.main
    assert legacy_cohort_cli._parser is canonical_cohort_cli._parser
    assert legacy_geometry_cli.main is canonical_geometry_cli.main
    assert legacy_geometry_cli._parser is canonical_geometry_cli._parser
