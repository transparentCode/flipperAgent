from __future__ import annotations

from dataclasses import replace

import pytest

from libs.models.sr.scripts.geometry_sensitivity.contracts import (
    APPROVED_ASSETS,
    GeometryDisposition,
    StudyGate,
)
from libs.models.sr.scripts.geometry_sensitivity.selection import (
    _preliminary_decision,
    select_candidates,
)


def _synthetic_candidate(
    evaluation,
    baseline,
    *,
    pooled_deltas=(0.2, 0.2, 0.2, 0.2),
    micro_delta=0.2,
    fold_deltas=None,
    invalidation_delta=0.0,
    density_ratio=1.0,
    churn_delta=0.0,
    censor_delta=0.0,
):
    baseline_metrics = baseline.micro
    if fold_deltas is None:
        fold_deltas = tuple(
            (asset, fold, 0.2)
            for asset, fold, _value in evaluation.asset_fold_deltas
        )
    return replace(
        evaluation,
        micro=replace(
            evaluation.micro,
            median_quality_reference_atr=baseline_metrics.median_quality_reference_atr + micro_delta,
            invalidation_rate=baseline_metrics.invalidation_rate + invalidation_delta,
            zone_creation_density_per_100_bars=baseline_metrics.zone_creation_density_per_100_bars * density_ratio,
            churn_rate=baseline_metrics.churn_rate + churn_delta,
            right_censoring_rate=baseline_metrics.right_censoring_rate + censor_delta,
        ),
        asset_pooled_deltas=tuple(zip(APPROVED_ASSETS, pooled_deltas, strict=True)),
        asset_fold_deltas=fold_deltas,
    )


def _force_diagnostic_failure(evaluation):
    return replace(
        evaluation,
        eligibility_gates=tuple(
            replace(gate, passed=False, value=0, reason="forced diagnostic failure")
            if gate.name.startswith("diagnostic.")
            else gate
            for gate in evaluation.eligibility_gates
        ),
    )


def _fold_deltas_for_win_count(evaluation, wins):
    rows_by_asset = {
        asset: [row for row in evaluation.asset_fold_deltas if row[0] == asset]
        for asset in APPROVED_ASSETS
    }
    result = []
    for asset_index, asset in enumerate(APPROVED_ASSETS):
        for local_index, (_asset, fold, _value) in enumerate(rows_by_asset[asset]):
            if local_index == 5:
                value = None
            else:
                value = 1.0 if asset_index * 5 + local_index < wins else 0.0
            result.append((asset, fold, value))
    return tuple(result)


def _quality_candidate(evaluation, baseline, field_name, value):
    kwargs = {}
    if field_name == "minimum_median_asset_delta":
        kwargs["pooled_deltas"] = (value, value, value, value)
    elif field_name == "minimum_micro_delta":
        kwargs["micro_delta"] = value
    elif field_name == "minimum_positive_asset_count":
        kwargs["pooled_deltas"] = (0.2, 0.2, 0.2, 0.0) if value == 3 else (0.2, 0.2, 0.0, 0.0)
    elif field_name == "minimum_worst_asset_delta":
        kwargs["pooled_deltas"] = (0.2, 0.2, 0.2, value)
    elif field_name == "minimum_asset_fold_win_fraction":
        kwargs["fold_deltas"] = _fold_deltas_for_win_count(evaluation, value)
    else:
        raise AssertionError(field_name)
    return _synthetic_candidate(evaluation, baseline, **kwargs)


def _guardrail_candidate(evaluation, baseline, kind, value):
    kwargs = {}
    if kind == "invalidation":
        kwargs["invalidation_delta"] = value
    elif kind == "density_min" or kind == "density_max":
        kwargs["density_ratio"] = value
    elif kind == "churn":
        kwargs["churn_delta"] = value
    elif kind == "censor":
        kwargs["censor_delta"] = value
    else:
        raise AssertionError(kind)
    return _synthetic_candidate(evaluation, baseline, **kwargs)


def _guardrail_baseline(baseline, kind):
    field = {
        "invalidation": "invalidation_rate",
        "density_min": "zone_creation_density_per_100_bars",
        "density_max": "zone_creation_density_per_100_bars",
        "churn": "churn_rate",
        "censor": "right_censoring_rate",
    }[kind]
    value = 1.0 if field == "zone_creation_density_per_100_bars" else 0.0
    return replace(baseline, micro=replace(baseline.micro, **{field: value}))


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


def test_successful_challenger_selection_ignores_failed_diagnostic(study, geometry_config):
    baseline = study.evaluations[4]
    target = _force_diagnostic_failure(study.evaluations[3])
    evaluations = list(study.evaluations)
    evaluations[0] = _synthetic_candidate(evaluations[0], baseline, micro_delta=0.2)
    evaluations[3] = _synthetic_candidate(target, baseline, micro_delta=0.3)
    decisions, selected, disposition = select_candidates(tuple(evaluations), config=geometry_config)
    target_decision = next(item for item in decisions if item.candidate_id == evaluations[3].candidate.candidate_id)
    assert any(not gate.passed for gate in target.eligibility_gates if gate.name.startswith("diagnostic."))
    assert target_decision.passes_all_gates
    assert selected == target.candidate.candidate_id
    assert disposition is GeometryDisposition.SELECT_GLOBAL_CHALLENGER
    unknown_gate = replace(
        target_decision,
        gates=target_decision.gates + (StudyGate("future.unknown", True, 1, 1, "unknown"),),
    )
    assert not unknown_gate.passes_all_gates


@pytest.mark.parametrize(
    ("field_name", "boundary", "below"),
    (
        ("minimum_median_asset_delta", 0.10, 0.10 - 1e-9),
        ("minimum_micro_delta", 0.10, 0.10 - 1e-9),
        ("minimum_positive_asset_count", 3, 2),
        ("minimum_worst_asset_delta", -0.10, -0.10 - 1e-9),
        ("minimum_asset_fold_win_fraction", 12, 11),
    ),
)
def test_quality_thresholds_are_inclusive_and_fail_below(study, geometry_config, field_name, boundary, below):
    baseline = study.evaluations[4]
    candidate = study.evaluations[3]
    passing, _ = _preliminary_decision(_quality_candidate(candidate, baseline, field_name, boundary), baseline, geometry_config)
    failing, _ = _preliminary_decision(_quality_candidate(candidate, baseline, field_name, below), baseline, geometry_config)
    gate_name = {
        "minimum_median_asset_delta": "quality.median_asset_delta",
        "minimum_micro_delta": "quality.micro_delta",
        "minimum_positive_asset_count": "quality.positive_asset_count",
        "minimum_worst_asset_delta": "quality.worst_asset_delta",
        "minimum_asset_fold_win_fraction": "quality.asset_fold_win_fraction",
    }[field_name]
    assert next(gate for gate in passing.gates if gate.name == gate_name).passed
    assert not next(gate for gate in failing.gates if gate.name == gate_name).passed


@pytest.mark.parametrize(
    ("kind", "boundary", "outside", "gate_name"),
    (
        ("invalidation", 0.05, 0.05 + 1e-9, "guardrail.invalidation_rate_delta"),
        ("density_min", 0.50, 0.50 - 1e-9, "guardrail.zone_creation_density_ratio"),
        ("density_max", 2.00, 2.00 + 1e-9, "guardrail.zone_creation_density_ratio"),
        ("churn", 0.10, 0.10 + 1e-9, "guardrail.churn_rate_delta"),
        ("censor", 0.10, 0.10 + 1e-9, "guardrail.right_censoring_rate_delta"),
    ),
)
def test_guardrail_boundaries_are_inclusive_and_outside_fails(study, geometry_config, kind, boundary, outside, gate_name):
    baseline = _guardrail_baseline(study.evaluations[4], kind)
    candidate = study.evaluations[3]
    passing, _ = _preliminary_decision(_guardrail_candidate(candidate, baseline, kind, boundary), baseline, geometry_config)
    failing, _ = _preliminary_decision(_guardrail_candidate(candidate, baseline, kind, outside), baseline, geometry_config)
    assert next(gate for gate in passing.gates if gate.name == gate_name).passed
    assert not next(gate for gate in failing.gates if gate.name == gate_name).passed


def test_orthogonal_neighbor_stability_success_and_failure(study, geometry_config):
    baseline = study.evaluations[4]
    successful = list(study.evaluations)
    successful[0] = _synthetic_candidate(successful[0], baseline, micro_delta=0.2)
    successful[3] = _synthetic_candidate(successful[3], baseline, micro_delta=0.3)
    decisions, selected, _ = select_candidates(tuple(successful), config=geometry_config)
    target = next(item for item in decisions if item.candidate_id == successful[3].candidate.candidate_id)
    assert target.passes_stability
    assert selected == successful[3].candidate.candidate_id

    failed = list(study.evaluations)
    failed[3] = _synthetic_candidate(failed[3], baseline, micro_delta=0.3)
    decisions, selected, disposition = select_candidates(tuple(failed), config=geometry_config)
    target = next(item for item in decisions if item.candidate_id == failed[3].candidate.candidate_id)
    assert not target.passes_stability
    assert target.neighbor_support_ids == ()
    assert selected is None
    assert disposition is GeometryDisposition.RETAIN_BASELINE_GEOMETRY


@pytest.mark.parametrize("support_index", (2, 4))
def test_stability_ignores_diagonal_and_baseline_candidates(study, geometry_config, support_index):
    baseline = study.evaluations[4]
    evaluations = list(study.evaluations)
    evaluations[3] = _synthetic_candidate(evaluations[3], baseline, micro_delta=0.3)
    if support_index != 4:
        evaluations[support_index] = _synthetic_candidate(evaluations[support_index], baseline, micro_delta=0.2)
    decisions, selected, _ = select_candidates(tuple(evaluations), config=geometry_config)
    target = next(item for item in decisions if item.candidate_id == evaluations[3].candidate.candidate_id)
    assert not target.passes_stability
    assert target.neighbor_support_ids == ()
    assert selected is None


def test_selection_tie_breaking_is_deterministic(study, geometry_config):
    baseline = study.evaluations[4]
    evaluations = list(study.evaluations)
    for index in (0, 1, 3):
        evaluations[index] = _synthetic_candidate(evaluations[index], baseline, micro_delta=0.2)
    first = select_candidates(tuple(evaluations), config=geometry_config)
    second = select_candidates(tuple(evaluations), config=geometry_config)
    assert first == second
    assert first[1] == evaluations[1].candidate.candidate_id
    assert first[2] is GeometryDisposition.SELECT_GLOBAL_CHALLENGER


def test_all_three_dispositions_are_reachable(study, geometry_config):
    baseline = study.evaluations[4]
    selected_evaluations = list(study.evaluations)
    selected_evaluations[0] = _synthetic_candidate(selected_evaluations[0], baseline, micro_delta=0.2)
    selected_evaluations[3] = _synthetic_candidate(selected_evaluations[3], baseline, micro_delta=0.3)
    _decisions, selected, selected_disposition = select_candidates(tuple(selected_evaluations), config=geometry_config)
    assert selected is not None
    assert selected_disposition is GeometryDisposition.SELECT_GLOBAL_CHALLENGER

    _decisions, selected, retained_disposition = select_candidates(study.evaluations, config=geometry_config)
    assert selected is None
    assert retained_disposition is GeometryDisposition.RETAIN_BASELINE_GEOMETRY

    insufficient = tuple(
        _force_sample_failure(evaluation) if not evaluation.candidate.baseline else evaluation
        for evaluation in study.evaluations
    )
    _decisions, selected, insufficient_disposition = select_candidates(insufficient, config=geometry_config)
    assert selected is None
    assert insufficient_disposition is GeometryDisposition.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize(
    ("metric_field", "gate_name"),
    (
        ("median_quality_reference_atr", "quality.micro_delta"),
        ("zone_creation_density_per_100_bars", "guardrail.zone_creation_density_ratio"),
        ("invalidation_rate", "guardrail.invalidation_rate_delta"),
        ("churn_rate", "guardrail.churn_rate_delta"),
        ("right_censoring_rate", "guardrail.right_censoring_rate_delta"),
    ),
)
def test_undefined_metric_denominators_fail_closed(study, geometry_config, metric_field, gate_name):
    baseline = study.evaluations[4]
    candidate = study.evaluations[3]
    candidate = replace(candidate, micro=replace(candidate.micro, **{metric_field: None}))
    decision, _ = _preliminary_decision(candidate, baseline, geometry_config)
    assert not next(gate for gate in decision.gates if gate.name == gate_name).passed
