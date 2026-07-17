from __future__ import annotations

from libs.models.sr.research.studies.atr_calibration import cli as canonical_atr_cli
from libs.models.sr.research.studies.atr_calibration import contracts as canonical_atr_contracts
from libs.models.sr.research.studies.atr_calibration import runner as canonical_atr_runner
from libs.models.sr.research.studies.baseline_trial import cli as canonical_baseline_cli
from libs.models.sr.research.studies.baseline_trial import contracts as canonical_baseline_contracts
from libs.models.sr.research.studies.baseline_trial import runner as canonical_baseline_runner
from libs.models.sr.scripts.atr_calibration import cli as legacy_atr_cli
from libs.models.sr.scripts.atr_calibration import contracts as legacy_atr_contracts
from libs.models.sr.scripts.atr_calibration import runner as legacy_atr_runner
from libs.models.sr.scripts.baseline_trial import cli as legacy_baseline_cli
from libs.models.sr.scripts.baseline_trial import contracts as legacy_baseline_contracts
from libs.models.sr.scripts.baseline_trial import runner as legacy_baseline_runner


def test_r3a_contract_and_runner_exports_keep_exact_identity() -> None:
    assert legacy_baseline_contracts.TrialSpec is canonical_baseline_contracts.TrialSpec
    assert legacy_baseline_contracts.SourceBar is canonical_baseline_contracts.SourceBar
    assert legacy_baseline_runner.run_trial is canonical_baseline_runner.run_trial
    assert legacy_atr_contracts.SourceCapsule is canonical_atr_contracts.SourceCapsule
    assert legacy_atr_contracts.CandidateReplay is canonical_atr_contracts.CandidateReplay
    assert legacy_atr_runner.select_development_stage is canonical_atr_runner.select_development_stage


def test_r3a_cli_facades_forward_exact_entrypoints_and_parsers() -> None:
    assert legacy_baseline_cli.main is canonical_baseline_cli.main
    assert legacy_baseline_cli._parser is canonical_baseline_cli._parser
    assert legacy_atr_cli.main is canonical_atr_cli.main
    assert legacy_atr_cli._parser is canonical_atr_cli._parser
