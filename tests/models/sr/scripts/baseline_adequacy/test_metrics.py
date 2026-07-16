from __future__ import annotations

import pytest

from libs.models.sr.scripts.baseline_adequacy.metrics import evaluate_adequacy


def test_real_study_metrics_use_same_fold_side_nulls(adequacy_study):
    assert adequacy_study.aggregate.total_real_outcomes == 36
    assert adequacy_study.aggregate.comparable_fold_count == 5
    assert adequacy_study.aggregate.completed_real_count == 31
    assert adequacy_study.aggregate.approved_pooled.total_outcomes == 36
    assert adequacy_study.aggregate.approved_pooled.completed_outcomes == 36
    assert adequacy_study.aggregate.approved_pooled.right_censored_outcomes == 0
    assert adequacy_study.aggregate.fold_local.total_outcomes == 36
    assert adequacy_study.aggregate.fold_local.completed_outcomes == 34
    assert adequacy_study.aggregate.fold_local.right_censored_outcomes == 2
    assert adequacy_study.aggregate.comparable_mapped.total_outcomes == 31
    assert adequacy_study.aggregate.comparable_mapped.completed_outcomes == 31
    assert adequacy_study.aggregate.comparable_mapped.right_censored_outcomes == 0
    assert adequacy_study.aggregate.comparable_mapped.fold_count == 5
    assert adequacy_study.aggregate.approved_pooled.median_quality_reference_atr == pytest.approx(-0.014070405071082426)
    assert adequacy_study.aggregate.fold_local.median_quality_reference_atr == pytest.approx(0.1807362526958346)
    assert adequacy_study.aggregate.approved_pooled.median_quality_reference_atr != adequacy_study.aggregate.fold_local.median_quality_reference_atr
    assert adequacy_study.aggregate.pooled_real_baseline_median_quality == adequacy_study.aggregate.approved_pooled.median_quality_reference_atr
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
