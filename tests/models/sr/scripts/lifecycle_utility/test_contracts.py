from __future__ import annotations

import pytest

from libs.models.sr.domain.contracts import ContractValidationError, ZoneSide
from libs.models.sr.scripts.lifecycle_utility.contracts import (
    GateResult,
    LifecycleUtilityDecision,
    LifecycleUtilityDisposition,
    effective_side_for_event,
)


GATE_SPECS = (
    ("readiness.completed_unique_resolutions", "readiness", 16, "integer"),
    ("readiness.comparable_folds", "readiness", 4, "integer"),
    ("readiness.minimum_completed_per_comparable_fold", "readiness", 2, "integer"),
    ("readiness.minimum_null_controls_per_compared_cell", "readiness", 4, "integer"),
    ("quality.pooled_median_excess_quality_atr", "quality", 0.10, "number"),
    ("quality.positive_comparable_fold_fraction", "quality", 0.60, "number"),
    ("quality.worst_comparable_fold_median_excess_atr", "quality", -0.10, "number"),
    ("stability.false_breakout_median_excess_quality_atr", "stability", 0.0, "number"),
    ("stability.break_confirmed_median_excess_quality_atr", "stability", 0.0, "number"),
)


def gates(*, readiness=True, quality=True, stability=True):
    result = []
    for name, category, threshold, kind in GATE_SPECS:
        should_pass = {"readiness": readiness, "quality": quality, "stability": stability}[category]
        applicable = not (category == "stability" and not should_pass)
        if not applicable:
            value = None
            passed = True
        else:
            value = threshold if should_pass else threshold - 1
            value = int(value) if kind == "integer" else value
            passed = should_pass
        result.append(
            GateResult(
                name=name,
                category=category,
                passed=passed,
                applicable=applicable,
                value=value,
                threshold=threshold,
                operator=">=",
                reason="synthetic gate",
            )
        )
    return tuple(result)


def test_effective_side_contract_is_symmetric():
    assert effective_side_for_event("FALSE_BREAKOUT", ZoneSide.SUPPORT) is ZoneSide.SUPPORT
    assert effective_side_for_event("FALSE_BREAKOUT", ZoneSide.RESISTANCE) is ZoneSide.RESISTANCE
    assert effective_side_for_event("BREAK_CONFIRMED", ZoneSide.SUPPORT) is ZoneSide.RESISTANCE
    assert effective_side_for_event("BREAK_CONFIRMED", ZoneSide.RESISTANCE) is ZoneSide.SUPPORT


@pytest.mark.parametrize(
    "mutation",
    (
        {"name": "made_up", "category": "readiness", "operator": ">=", "threshold": 16},
        {"name": "readiness.completed_unique_resolutions", "category": "quality", "operator": ">=", "threshold": 16},
        {"name": "readiness.completed_unique_resolutions", "category": "readiness", "operator": ">", "threshold": 16},
        {"name": "readiness.completed_unique_resolutions", "category": "readiness", "operator": ">=", "threshold": 999},
    ),
)
def test_gate_schema_mutations_fail_closed(mutation):
    with pytest.raises(ContractValidationError):
        GateResult(passed=True, applicable=True, value=16, reason="synthetic", **mutation)


def test_gate_passed_flag_is_derived_from_value():
    with pytest.raises(ContractValidationError):
        GateResult(
            name="quality.pooled_median_excess_quality_atr",
            category="quality",
            passed=True,
            applicable=True,
            value=0.09,
            threshold=0.10,
            operator=">=",
            reason="fabricated",
        )
    with pytest.raises(ContractValidationError):
        GateResult(
            name="quality.pooled_median_excess_quality_atr",
            category="quality",
            passed=False,
            applicable=True,
            value=0.10,
            threshold=0.10,
            operator=">=",
            reason="fabricated",
        )


def test_integer_gate_values_do_not_overflow_float_conversion():
    gate = GateResult(
        name="readiness.completed_unique_resolutions",
        category="readiness",
        passed=True,
        applicable=True,
        value=10**400,
        threshold=16,
        operator=">=",
        reason="large but valid integer",
    )
    assert gate.passed is True


@pytest.mark.parametrize(
    ("contract_valid", "gate_kind", "expected"),
    (
        (False, "all", LifecycleUtilityDisposition.INVALID_EVIDENCE),
        (True, "readiness", LifecycleUtilityDisposition.INSUFFICIENT_EVIDENCE),
        (True, "quality", LifecycleUtilityDisposition.LIFECYCLE_CONTEXT_NOT_SUPPORTED),
        (True, "all", LifecycleUtilityDisposition.LIFECYCLE_CONTEXT_SUPPORTED),
    ),
)
def test_decision_precedence(contract_valid, gate_kind, expected):
    decision = LifecycleUtilityDecision(
        contract_valid=contract_valid,
        disposition=expected,
        gates=gates(
            readiness=gate_kind not in {"readiness"},
            quality=gate_kind not in {"quality"},
            stability=gate_kind not in {"quality"},
        ),
        reason="synthetic disposition",
    )
    assert decision.disposition is expected


def test_decision_requires_exact_gate_sequence():
    valid = gates()
    with pytest.raises(ContractValidationError):
        LifecycleUtilityDecision(
            contract_valid=True,
            disposition=LifecycleUtilityDisposition.LIFECYCLE_CONTEXT_SUPPORTED,
            gates=valid[:-1],
            reason="missing gate",
        )
    with pytest.raises(ContractValidationError):
        LifecycleUtilityDecision(
            contract_valid=True,
            disposition=LifecycleUtilityDisposition.LIFECYCLE_CONTEXT_SUPPORTED,
            gates=valid + (valid[0],),
            reason="extra gate",
        )
    with pytest.raises(ContractValidationError):
        GateResult(
            name="readiness.renamed",
            category="readiness",
            passed=True,
            applicable=True,
            value=16,
            threshold=16,
            operator=">=",
            reason="renamed gate",
        )
