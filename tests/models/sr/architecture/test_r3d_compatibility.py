from __future__ import annotations

from libs.models.sr.research.evidence.context_audit import artifacts as shared_context_artifacts
from libs.models.sr.research.evidence.context_audit import config as shared_context_config
from libs.models.sr.research.evidence.context_audit import contracts as shared_context_contracts
from libs.models.sr.research.evidence.context_audit import runner as shared_context_runner
from libs.models.sr.research.evidence.lifecycle_utility import artifacts as shared_lifecycle_artifacts
from libs.models.sr.research.evidence.lifecycle_utility import config as shared_lifecycle_config
from libs.models.sr.research.evidence.lifecycle_utility import contracts as shared_lifecycle_contracts
from libs.models.sr.research.evidence.lifecycle_utility import extraction as shared_lifecycle_extraction
from libs.models.sr.research.evidence.lifecycle_utility import runner as shared_lifecycle_runner
from libs.models.sr.research.studies.candidate_reinforcement_audit import artifacts as canonical_candidate_artifacts
from libs.models.sr.research.studies.candidate_reinforcement_audit import audit as canonical_candidate_audit
from libs.models.sr.research.studies.candidate_reinforcement_audit import cli as canonical_candidate_cli
from libs.models.sr.research.studies.candidate_reinforcement_audit import config as canonical_candidate_config
from libs.models.sr.research.studies.candidate_reinforcement_audit import contracts as canonical_candidate_contracts
from libs.models.sr.research.studies.candidate_reinforcement_audit import runner as canonical_candidate_runner
from libs.models.sr.research.studies.context_audit import artifacts as canonical_context_artifacts
from libs.models.sr.research.studies.context_audit import config as canonical_context_config
from libs.models.sr.research.studies.context_audit import contracts as canonical_context_contracts
from libs.models.sr.research.studies.context_audit import runner as canonical_context_runner
from libs.models.sr.research.studies.lifecycle_utility import artifacts as canonical_lifecycle_artifacts
from libs.models.sr.research.studies.lifecycle_utility import cli as canonical_lifecycle_cli
from libs.models.sr.research.studies.lifecycle_utility import config as canonical_lifecycle_config
from libs.models.sr.research.studies.lifecycle_utility import contracts as canonical_lifecycle_contracts
from libs.models.sr.research.studies.lifecycle_utility import extraction as canonical_lifecycle_extraction
from libs.models.sr.research.studies.lifecycle_utility import runner as canonical_lifecycle_runner
from libs.models.sr.scripts.candidate_reinforcement_audit import artifacts as legacy_candidate_artifacts
from libs.models.sr.scripts.candidate_reinforcement_audit import audit as legacy_candidate_audit
from libs.models.sr.scripts.candidate_reinforcement_audit import cli as legacy_candidate_cli
from libs.models.sr.scripts.candidate_reinforcement_audit import config as legacy_candidate_config
from libs.models.sr.scripts.candidate_reinforcement_audit import contracts as legacy_candidate_contracts
from libs.models.sr.scripts.candidate_reinforcement_audit import runner as legacy_candidate_runner
from libs.models.sr.scripts.context_audit import artifacts as legacy_context_artifacts
from libs.models.sr.scripts.context_audit import config as legacy_context_config
from libs.models.sr.scripts.context_audit import contracts as legacy_context_contracts
from libs.models.sr.scripts.context_audit import runner as legacy_context_runner
from libs.models.sr.scripts.lifecycle_utility import artifacts as legacy_lifecycle_artifacts
from libs.models.sr.scripts.lifecycle_utility import cli as legacy_lifecycle_cli
from libs.models.sr.scripts.lifecycle_utility import config as legacy_lifecycle_config
from libs.models.sr.scripts.lifecycle_utility import contracts as legacy_lifecycle_contracts
from libs.models.sr.scripts.lifecycle_utility import extraction as legacy_lifecycle_extraction
from libs.models.sr.scripts.lifecycle_utility import runner as legacy_lifecycle_runner


def test_r3d_context_evidence_exports_keep_exact_identity() -> None:
    assert legacy_context_config.ContextAuditConfig is canonical_context_config.ContextAuditConfig is shared_context_config.ContextAuditConfig
    assert legacy_context_contracts.AuditResult is canonical_context_contracts.AuditResult is shared_context_contracts.AuditResult
    assert legacy_context_runner.load_frozen_context is canonical_context_runner.load_frozen_context is shared_context_runner.load_frozen_context
    assert legacy_context_artifacts.validate_audit_bundle is canonical_context_artifacts.validate_audit_bundle is shared_context_artifacts.validate_audit_bundle


def test_r3d_lifecycle_utility_exports_keep_exact_identity() -> None:
    assert legacy_lifecycle_config.LifecycleUtilityConfig is canonical_lifecycle_config.LifecycleUtilityConfig is shared_lifecycle_config.LifecycleUtilityConfig
    assert legacy_lifecycle_contracts.LifecycleUtilityStudy is canonical_lifecycle_contracts.LifecycleUtilityStudy is shared_lifecycle_contracts.LifecycleUtilityStudy
    assert legacy_lifecycle_extraction.load_validated_inputs is canonical_lifecycle_extraction.load_validated_inputs is shared_lifecycle_extraction.load_validated_inputs
    assert legacy_lifecycle_runner.compute_study is canonical_lifecycle_runner.compute_study is shared_lifecycle_runner.compute_study
    assert legacy_lifecycle_artifacts.validate_lifecycle_bundle is canonical_lifecycle_artifacts.validate_lifecycle_bundle is shared_lifecycle_artifacts.validate_lifecycle_bundle
    assert legacy_lifecycle_cli.main is canonical_lifecycle_cli.main
    assert legacy_lifecycle_cli._parser is canonical_lifecycle_cli._parser


def test_r3d_candidate_audit_exports_keep_exact_identity() -> None:
    assert legacy_candidate_config.CandidateAuditConfig is canonical_candidate_config.CandidateAuditConfig
    assert legacy_candidate_config.FrozenSource is canonical_candidate_config.FrozenSource
    assert legacy_candidate_config.UpstreamV11 is canonical_candidate_config.UpstreamV11
    assert legacy_candidate_config.UpstreamV19 is canonical_candidate_config.UpstreamV19
    assert legacy_candidate_config.UpstreamV10 is canonical_candidate_config.UpstreamV10
    assert legacy_candidate_contracts.CandidateReinforcementAudit is canonical_candidate_contracts.CandidateReinforcementAudit
    assert legacy_candidate_audit.build_audit is canonical_candidate_audit.build_audit
    assert legacy_candidate_runner.compute_audit is canonical_candidate_runner.compute_audit
    assert legacy_candidate_artifacts.validate_audit_bundle is canonical_candidate_artifacts.validate_audit_bundle
    assert legacy_candidate_cli.main is canonical_candidate_cli.main
    assert legacy_candidate_cli._parser is canonical_candidate_cli._parser
