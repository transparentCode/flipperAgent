from __future__ import annotations

from dataclasses import replace

import pytest

from libs.models.sr.domain.contracts import ContractValidationError, ZoneSide, ZoneStatus
from libs.models.sr.scripts.candidate_reinforcement_audit.contracts import (
    AuditDecision,
    AuditDisposition,
    GateResult,
)

from .conftest import make_created, make_match


@pytest.mark.parametrize(
    ("name", "category", "threshold"),
    (
        ("readiness.unknown", "readiness", 16),
        ("readiness.unique_reinforced_zones", "quality", 16),
        ("readiness.unique_reinforced_zones", "readiness", 999),
    ),
)
def test_unknown_or_mutated_gate_schema_fails_closed(name, category, threshold):
    with pytest.raises(ContractValidationError):
        GateResult(name, category, 16, threshold, ">=", True, "synthetic")


def test_gate_passed_is_derived_from_value():
    assert GateResult("readiness.comparable_folds", "readiness", 5, 4, ">=", True, "pass").passed
    with pytest.raises(ContractValidationError):
        GateResult("readiness.comparable_folds", "readiness", 3, 4, ">=", True, "fabricated")


def test_all_gate_categories_are_readiness_only():
    decision = AuditDecision(
        contract_valid=True,
        disposition=AuditDisposition.INSUFFICIENT_REINFORCEMENT_EVIDENCE,
        gates=(
            GateResult("readiness.unique_reinforced_zones", "readiness", 15, 16, ">=", False, "below"),
            GateResult("readiness.comparable_folds", "readiness", 4, 4, ">=", True, "pass"),
            GateResult("readiness.minimum_reinforced_zones_per_comparable_fold", "readiness", 2, 2, ">=", True, "pass"),
        ),
        reason="readiness only",
    )
    assert all(gate.category == "readiness" for gate in decision.gates)
    assert "quality" not in decision.to_payload()


def test_lineage_and_side_state_contracts_reject_mismatch(synthetic_audit):
    candidate = synthetic_audit.candidates[1]
    bad = replace(candidate, side=ZoneSide.RESISTANCE)
    with pytest.raises(ContractValidationError):
        replace(synthetic_audit, candidates=(synthetic_audit.candidates[0], bad))


@pytest.mark.parametrize("status", (ZoneStatus.BROKEN, ZoneStatus.EXPIRED))
def test_terminal_post_advance_match_cannot_be_eligible(synthetic_audit, status):
    candidate = synthetic_audit.candidates[1]
    with pytest.raises(ContractValidationError):
        replace(candidate, target_post_advance_status=status, eligible_reinforcement=True)


def test_duplicate_seed_lineage_is_rejected(synthetic_audit):
    with pytest.raises(ContractValidationError, match="lineage"):
        replace(synthetic_audit, lineage=synthetic_audit.lineage + synthetic_audit.lineage)


def test_missing_target_lineage_is_rejected(synthetic_audit):
    candidate = replace(synthetic_audit.candidates[1], target_zone_id="b" * 64)
    with pytest.raises(ContractValidationError, match="unknown lineage"):
        replace(synthetic_audit, candidates=(synthetic_audit.candidates[0], candidate))


def test_same_candidate_as_seed_is_not_independent(synthetic_audit):
    candidate = synthetic_audit.candidates[1]
    with pytest.raises(ContractValidationError, match="seed lineage mismatch"):
        replace(
            synthetic_audit,
            candidates=(
                synthetic_audit.candidates[0],
                replace(candidate, target_seed_candidate_id=candidate.candidate_id),
            ),
        )


def test_out_of_fold_eligible_reinforcement_is_rejected():
    seed = make_created()
    with pytest.raises(ContractValidationError, match="evaluation fold"):
        make_match(seed, fold=None, eligible=True)


def test_same_batch_match_is_never_eligible():
    seed = make_created()
    match = make_match(seed, same_batch=True)
    assert not match.eligible_reinforcement
