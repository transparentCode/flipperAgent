from __future__ import annotations

from dataclasses import replace

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.research.source.capsules import SourceCapsule as SharedSourceCapsule
from libs.models.sr.research.studies.atr_calibration.contracts import SourceCapsule as CanonicalATRSourceCapsule
from libs.models.sr.scripts.atr_calibration.contracts import CapsuleStage, SourceCapsule


def test_source_capsule_is_immutable_and_split_is_strict(source_capsules):
    development, sealed = source_capsules
    assert development.stage is CapsuleStage.DEVELOPMENT
    assert sealed is None
    assert development.bars[-1].closed_at < development.split_boundary
    with pytest.raises((AttributeError, TypeError)):
        development.bars = ()


def test_development_capsule_rejects_holdout_bar(source_capsules):
    development, _ = source_capsules
    with pytest.raises(ContractValidationError):
        replace(development, bars=development.bars + (development.bars[-1],))


def test_invalid_capsule_stage_fails_with_public_contract_error(source_capsules):
    development, _ = source_capsules
    with pytest.raises(ContractValidationError):
        SourceCapsule(
            stage="unknown",
            source_bundle_id=development.source_bundle_id,
            source_bars_sha256=development.source_bars_sha256,
            source_row_count=development.source_row_count,
            split_boundary=development.split_boundary,
            implementation_commit=development.implementation_commit,
            bars=development.bars,
        )


def test_legacy_atr_and_shared_source_capsule_exports_are_identical():
    assert SourceCapsule is CanonicalATRSourceCapsule is SharedSourceCapsule


@pytest.mark.parametrize("commit_length", [40, 41, 63, 64])
def test_source_capsule_preserves_historical_git_identity_range(source_capsules, commit_length):
    development, _ = source_capsules
    capsule = replace(development, implementation_commit="a" * commit_length)
    assert capsule.implementation_commit == "a" * commit_length


@pytest.mark.parametrize("commit_length", [39, 65])
def test_source_capsule_rejects_outside_historical_git_identity_range(source_capsules, commit_length):
    development, _ = source_capsules
    with pytest.raises(ContractValidationError, match="implementation_commit must be a git SHA"):
        replace(development, implementation_commit="a" * commit_length)
