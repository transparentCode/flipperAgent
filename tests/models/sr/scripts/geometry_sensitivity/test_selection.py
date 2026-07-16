from __future__ import annotations

from dataclasses import replace

from libs.models.sr.scripts.geometry_sensitivity.contracts import GeometryDisposition
from libs.models.sr.scripts.geometry_sensitivity.selection import select_candidates


def _force_sample_failure(evaluation):
    gates = tuple(
        replace(gate, passed=False, value=0, reason="forced aggregate sample failure")
        if gate.name == "sample.eligible_development_folds"
        else gate
        for gate in evaluation.eligibility_gates
    )
    return replace(evaluation, eligibility_gates=gates)


def test_fold_failures_are_diagnostics_only(study):
    baseline = study.evaluations[4]
    assert baseline.fully_evaluable
    assert any(
        gate.name.startswith("diagnostic.") and not gate.passed
        for gate in baseline.eligibility_gates
    )


def test_aggregate_sample_failure_drives_insufficient_disposition(study, geometry_config):
    evaluations = tuple(
        _force_sample_failure(evaluation) if not evaluation.candidate.baseline else evaluation
        for evaluation in study.evaluations
    )
    decisions, selected, disposition = select_candidates(evaluations, config=geometry_config)
    assert selected is None
    assert disposition is GeometryDisposition.INSUFFICIENT_EVIDENCE
    assert all(not decision.fully_evaluable for decision in decisions if not decision.is_baseline)


def test_current_frozen_result_is_retain_or_select_but_not_insufficient(study):
    assert study.disposition in {
        GeometryDisposition.RETAIN_BASELINE_GEOMETRY,
        GeometryDisposition.SELECT_GLOBAL_CHALLENGER,
    }
    assert study.disposition is not GeometryDisposition.INSUFFICIENT_EVIDENCE


def test_decisions_are_canonical_and_neighbor_support_is_not_diagonal(study):
    assert tuple(item.candidate_id for item in study.decisions) == tuple(item.candidate.candidate_id for item in study.evaluations)
    for decision in study.decisions:
        assert tuple(sorted(decision.neighbor_support_ids)) == decision.neighbor_support_ids
        assert decision.candidate_id not in decision.neighbor_support_ids
