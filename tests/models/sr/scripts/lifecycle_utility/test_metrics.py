from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from libs.models.sr.scripts.lifecycle_utility.contracts import LifecycleUtilityDisposition
from libs.models.sr.scripts.lifecycle_utility.metrics import evaluate_metrics


FOLD_STARTS = {
    "2024_q3": datetime(2024, 7, 2, tzinfo=timezone.utc),
    "2024_q4": datetime(2024, 10, 2, tzinfo=timezone.utc),
    "2025_q1": datetime(2025, 1, 2, tzinfo=timezone.utc),
    "2025_q2": datetime(2025, 4, 2, tzinfo=timezone.utc),
}


def outcomes_for(make_event, make_outcome, counts=(4, 4, 4, 4), quality=0.25, null_count=4):
    outcomes = []
    for fold, count in zip(FOLD_STARTS, counts):
        for index in range(count):
            event_class = "FALSE_BREAKOUT" if len(outcomes) % 2 == 0 else "BREAK_CONFIRMED"
            event = make_event(
                seed=f"metrics-{fold}-{index}-{len(outcomes)}",
                fold=fold,
                event_class=event_class,
                event_at=FOLD_STARTS[fold] + timedelta(days=index),
            )
            outcomes.append(
                make_outcome(
                    event,
                    quality=quality,
                    null_median=0.0 if null_count else None,
                    null_count=null_count,
                )
            )
    return tuple(outcomes)


def test_supported_result_requires_all_readiness_and_quality_gates(lifecycle_config, make_event, make_outcome):
    evaluation = evaluate_metrics(outcomes_for(make_event, make_outcome), config=lifecycle_config)
    assert evaluation.decision.disposition is LifecycleUtilityDisposition.LIFECYCLE_CONTEXT_SUPPORTED
    assert evaluation.aggregate.comparable_fold_count == 4
    assert evaluation.aggregate.compared_count == 16
    assert evaluation.aggregate.pooled_median_excess_quality_atr == 0.25


@pytest.mark.parametrize(
    "counts",
    (
        (4, 4, 4, 3),
        (4, 4, 4, 0),
    ),
)
def test_readiness_failures_precede_quality_disposition(lifecycle_config, make_event, make_outcome, counts):
    evaluation = evaluate_metrics(outcomes_for(make_event, make_outcome, counts=counts), config=lifecycle_config)
    assert evaluation.decision.disposition is LifecycleUtilityDisposition.INSUFFICIENT_EVIDENCE


def test_quality_failure_is_not_insufficient_evidence(lifecycle_config, make_event, make_outcome):
    evaluation = evaluate_metrics(outcomes_for(make_event, make_outcome, quality=0.0), config=lifecycle_config)
    assert evaluation.decision.disposition is LifecycleUtilityDisposition.LIFECYCLE_CONTEXT_NOT_SUPPORTED
    assert evaluation.decision.gates[4].passed is False


def test_contract_failure_has_highest_precedence(lifecycle_config, make_event, make_outcome):
    evaluation = evaluate_metrics(outcomes_for(make_event, make_outcome), config=lifecycle_config, contract_valid=False)
    assert evaluation.decision.disposition is LifecycleUtilityDisposition.INVALID_EVIDENCE


def test_undefined_denominators_fail_closed(lifecycle_config):
    evaluation = evaluate_metrics((), config=lifecycle_config)
    assert evaluation.aggregate.pooled_median_excess_quality_atr is None
    assert evaluation.aggregate.positive_comparable_fold_fraction is None
    assert evaluation.decision.disposition is LifecycleUtilityDisposition.INSUFFICIENT_EVIDENCE
    assert all(not gate.passed for gate in evaluation.gates[:4])


def test_missing_null_control_does_not_mutate_the_null_population(lifecycle_config, make_event, make_outcome):
    outcome = outcomes_for(make_event, make_outcome, counts=(4, 4, 4, 4), null_count=0)[0]
    evaluation = evaluate_metrics((outcome,), config=lifecycle_config)
    assert outcome.null_control_count == 0
    assert outcome.null_median_quality_atr is None
    assert evaluation.decision.disposition is LifecycleUtilityDisposition.INSUFFICIENT_EVIDENCE
