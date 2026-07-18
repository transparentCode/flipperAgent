from __future__ import annotations

from libs.models.sr.research.evidence.baseline_adequacy import artifacts as shared_artifacts
from libs.models.sr.research.evidence.baseline_adequacy import config as shared_config
from libs.models.sr.research.evidence.baseline_adequacy import contracts as shared_contracts
from libs.models.sr.research.evidence.baseline_adequacy import runner as shared_runner
from libs.models.sr.research.evidence.geometry_sensitivity import artifacts as shared_geometry_artifacts
from libs.models.sr.research.evidence.geometry_sensitivity import config as shared_geometry_config
from libs.models.sr.research.evidence.geometry_sensitivity import contracts as shared_geometry_contracts
from libs.models.sr.research.evidence.geometry_sensitivity import runner as shared_geometry_runner
from libs.models.sr.research.studies.baseline_adequacy import cli as canonical_adequacy_cli
from libs.models.sr.research.studies.baseline_adequacy import artifacts as canonical_adequacy_artifacts
from libs.models.sr.research.studies.baseline_adequacy import contracts as canonical_adequacy_contracts
from libs.models.sr.research.studies.baseline_adequacy import runner as canonical_adequacy_runner
from libs.models.sr.research.studies.baseline_trial import contracts as canonical_baseline_contracts
from libs.models.sr.research.studies.context_audit import cli as canonical_context_cli
from libs.models.sr.research.studies.context_audit import audit as canonical_context_audit
from libs.models.sr.research.studies.context_audit import contracts as canonical_context_contracts
from libs.models.sr.research.studies.context_audit import runner as canonical_context_runner
from libs.models.sr.research.studies.geometry_sensitivity import artifacts as canonical_geometry_artifacts
from libs.models.sr.research.studies.geometry_sensitivity import config as canonical_geometry_config
from libs.models.sr.research.studies.geometry_sensitivity import contracts as canonical_geometry_contracts
from libs.models.sr.research.studies.geometry_sensitivity import runner as canonical_geometry_runner
from libs.models.sr.research.viewer.contracts import ViewerConfig
from libs.models.sr.scripts.baseline_adequacy import cli as legacy_adequacy_cli
from libs.models.sr.scripts.baseline_adequacy import artifacts as legacy_adequacy_artifacts
from libs.models.sr.scripts.baseline_adequacy import config as legacy_adequacy_config
from libs.models.sr.scripts.baseline_adequacy import contracts as legacy_adequacy_contracts
from libs.models.sr.scripts.baseline_adequacy import runner as legacy_adequacy_runner
from libs.models.sr.scripts.context_audit import cli as legacy_context_cli
from libs.models.sr.scripts.context_audit import audit as legacy_context_audit
from libs.models.sr.scripts.context_audit import contracts as legacy_context_contracts
from libs.models.sr.scripts.context_audit import runner as legacy_context_runner
from libs.models.sr.scripts.geometry_sensitivity import artifacts as legacy_geometry_artifacts
from libs.models.sr.scripts.geometry_sensitivity import config as legacy_geometry_config
from libs.models.sr.scripts.geometry_sensitivity import contracts as legacy_geometry_contracts
from libs.models.sr.scripts.geometry_sensitivity import runner as legacy_geometry_runner


def test_r3c_baseline_adequacy_exports_keep_exact_identity() -> None:
    assert legacy_adequacy_contracts.BaselineAdequacyConfig is shared_contracts.BaselineAdequacyConfig
    assert canonical_adequacy_contracts.BaselineAdequacyStudy is shared_contracts.BaselineAdequacyStudy
    assert legacy_adequacy_config.load_baseline_adequacy_config is shared_config.load_baseline_adequacy_config
    assert canonical_adequacy_runner.compute_study is shared_runner.compute_study
    assert legacy_adequacy_runner.validate_baseline_parity is shared_runner.validate_baseline_parity
    assert canonical_adequacy_artifacts.validate_evaluation_bundle is shared_artifacts.validate_evaluation_bundle
    assert legacy_adequacy_artifacts.publish_evaluation_bundle is shared_artifacts.publish_evaluation_bundle


def test_r3c_context_audit_exports_keep_exact_identity() -> None:
    assert legacy_context_contracts.AuditResult is canonical_context_contracts.AuditResult
    assert legacy_context_audit.build_audit is canonical_context_audit.build_audit
    assert legacy_context_runner.compute_audit is canonical_context_runner.compute_audit


def test_r3c_geometry_frozen_evidence_exports_keep_exact_identity() -> None:
    assert canonical_geometry_config.GeometrySensitivityConfig is shared_geometry_config.GeometrySensitivityConfig
    assert legacy_geometry_config.load_geometry_config is shared_geometry_config.load_geometry_config
    assert canonical_geometry_contracts.GeometrySensitivityStudy is shared_geometry_contracts.GeometrySensitivityStudy
    assert legacy_geometry_contracts.GeometryCandidate is shared_geometry_contracts.GeometryCandidate
    assert canonical_geometry_runner.run_study is shared_geometry_runner.run_study
    assert legacy_geometry_runner.compute_study is shared_geometry_runner.compute_study
    assert canonical_geometry_artifacts.validate_evaluation_bundle is shared_geometry_artifacts.validate_evaluation_bundle
    assert legacy_geometry_artifacts.publish_evaluation_bundle is shared_geometry_artifacts.publish_evaluation_bundle


def test_r3c_viewer_contract_keeps_baseline_identity() -> None:
    assert canonical_baseline_contracts.ViewerConfig is ViewerConfig


def test_r3c_cli_facades_forward_exact_entrypoints_and_parsers() -> None:
    assert legacy_adequacy_cli.main is canonical_adequacy_cli.main
    assert legacy_adequacy_cli._parser is canonical_adequacy_cli._parser
    assert legacy_context_cli.main is canonical_context_cli.main
    assert legacy_context_cli._parser is canonical_context_cli._parser
