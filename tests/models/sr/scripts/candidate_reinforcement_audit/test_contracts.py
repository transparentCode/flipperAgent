from __future__ import annotations

from dataclasses import replace

import pytest

from libs.models.sr.domain.contracts import ContractValidationError, ZoneSide, ZoneStatus
from libs.models.sr.scripts.candidate_reinforcement_audit.contracts import (
    AuditDecision,
    AuditDisposition,
    GateResult,
)


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


def test_terminal_post_advance_match_cannot_be_eligible(synthetic_audit):
    candidate = synthetic_audit.candidates[1]
    with pytest.raises(ContractValidationError):
        replace(candidate, target_post_advance_status=ZoneStatus.BROKEN, eligible_reinforcement=True)
