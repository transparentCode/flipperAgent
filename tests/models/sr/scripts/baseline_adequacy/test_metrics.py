from __future__ import annotations

from libs.models.sr.scripts.baseline_adequacy.metrics import evaluate_adequacy


def test_real_study_metrics_use_same_fold_side_nulls(adequacy_study):
    assert adequacy_study.aggregate.total_real_outcomes == 36
    assert adequacy_study.aggregate.comparable_fold_count == 5
    assert adequacy_study.aggregate.completed_real_count == 31
    assert adequacy_study.decision.disposition.value == "BASELINE_NOT_BETTER_THAN_NAIVE_NULL"
    assert len(adequacy_study.fold_side_nulls) == 12
    assert len(adequacy_study.comparisons) == adequacy_study.aggregate.completed_real_count


def test_undefined_comparability_fails_to_insufficient(adequacy_config, adequacy_study):
    from libs.models.sr.scripts.baseline_adequacy.contracts import ControlAccounting, ControlBuildResult, ControlEligibilityReason

    empty = ControlAccounting(
        total_considered=0,
        total_eligible=0,
        rejected=tuple((reason, 0) for reason in ControlEligibilityReason if reason is not ControlEligibilityReason.ELIGIBLE),
        folds=(),
    )
    controls = ControlBuildResult(anchors=(), outcomes=(), accounting=empty)
    result = evaluate_adequacy((), controls, config=adequacy_config)
    assert result.decision.disposition.value == "INSUFFICIENT_EVIDENCE"
