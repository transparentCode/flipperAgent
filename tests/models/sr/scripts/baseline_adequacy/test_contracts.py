from __future__ import annotations

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.baseline_adequacy.contracts import (
    AdequacyGateResult,
    BaselineAdequacyDecision,
    BaselineAdequacyDisposition,
)


def _gates(*, diagnostic_passed: bool = True):
    authoritative = (
        AdequacyGateResult("sample.completed_real_outcomes", "sample", True, 24, 24, ">=", "sample"),
        AdequacyGateResult("comparability.comparable_folds", "comparability", True, 4, 4, ">=", "folds"),
        AdequacyGateResult("comparability.minimum_real_outcomes_per_comparable_fold", "comparability", True, 4, 4, ">=", "real"),
        AdequacyGateResult("comparability.minimum_controls_per_side_per_comparable_fold", "comparability", True, 4, 4, ">=", "controls"),
        AdequacyGateResult("quality.pooled_median_excess_quality_atr", "quality", True, 0.1, 0.1, ">=", "quality"),
        AdequacyGateResult("quality.positive_comparable_fold_fraction", "quality", True, 0.6, 0.6, ">=", "fraction"),
        AdequacyGateResult("quality.worst_comparable_fold_excess_atr", "quality", True, -0.1, -0.1, ">=", "worst"),
    )
    diagnostics = tuple(
        AdequacyGateResult(
            f"diagnostic.fold.{fold}.comparable",
            "diagnostic",
            diagnostic_passed if fold == "2025_q3" else True,
            0 if fold == "2025_q3" and not diagnostic_passed else 1,
            1,
            "==",
            "diagnostic",
            fold,
        )
        for fold in ("2024_q3", "2024_q4", "2025_q1", "2025_q2", "2025_q3", "2025_q4")
    )
    return authoritative + diagnostics


def test_failed_diagnostic_does_not_block_baseline_disposition():
    decision = BaselineAdequacyDecision(BaselineAdequacyDisposition.BASELINE_BEATS_NAIVE_NULL, _gates(diagnostic_passed=False), "quality gates passed")
    assert decision.disposition is BaselineAdequacyDisposition.BASELINE_BEATS_NAIVE_NULL


def test_unknown_gate_category_fails_closed():
    with pytest.raises(ContractValidationError):
        AdequacyGateResult("mystery", "unknown", True, 1, 1, ">=", "bad")


def test_unknown_gate_name_fails_closed():
    with pytest.raises(ContractValidationError):
        AdequacyGateResult("sample.fabricated", "sample", True, 24, 24, ">=", "bad")


def test_gate_passed_flag_must_match_value():
    with pytest.raises(ContractValidationError):
        AdequacyGateResult("sample.completed_real_outcomes", "sample", True, 23, 24, ">=", "inconsistent")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda gates: gates[:-1],
        lambda gates: gates + (gates[-1],),
    ],
)
def test_decision_requires_exact_gate_set(mutation):
    with pytest.raises(ContractValidationError):
        BaselineAdequacyDecision(BaselineAdequacyDisposition.BASELINE_BEATS_NAIVE_NULL, mutation(_gates()), "invalid gate set")


def test_gate_category_operator_and_threshold_are_frozen():
    with pytest.raises(ContractValidationError):
        AdequacyGateResult("quality.pooled_median_excess_quality_atr", "sample", True, 0.1, 0.1, ">=", "wrong category")
    with pytest.raises(ContractValidationError):
        AdequacyGateResult("quality.pooled_median_excess_quality_atr", "quality", True, 0.1, 0.1, ">", "wrong operator")
    with pytest.raises(ContractValidationError):
        AdequacyGateResult("quality.pooled_median_excess_quality_atr", "quality", True, 0.1, 999.0, ">=", "wrong threshold")


def test_sample_failure_has_precedence_over_quality():
    gates = list(_gates())
    gates[0] = AdequacyGateResult(gates[0].name, gates[0].category, False, 23, 24, ">=", "sample")
    with pytest.raises(ContractValidationError):
        BaselineAdequacyDecision(BaselineAdequacyDisposition.BASELINE_BEATS_NAIVE_NULL, tuple(gates), "wrong")
    decision = BaselineAdequacyDecision(BaselineAdequacyDisposition.INSUFFICIENT_EVIDENCE, tuple(gates), "sample failed")
    assert decision.disposition is BaselineAdequacyDisposition.INSUFFICIENT_EVIDENCE
