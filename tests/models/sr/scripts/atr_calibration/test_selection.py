from __future__ import annotations

from libs.models.sr.scripts.atr_calibration.selection import (
    DevelopmentDisposition,
    Recommendation,
    evaluate_holdout_metrics,
    select_development,
)


def test_selection_contains_development_only_and_freezes_before_holdout(calibration_config, source_capsules, development_metrics):
    development, _ = source_capsules
    selection = select_development(
        development_metrics,
        config=calibration_config,
        development_source_id=development.capsule_id,
        implementation_commit=calibration_config.source_implementation_commit,
    )
    assert selection.candidate_periods == (7, 10, 14, 20, 28)
    assert all("holdout" not in key.lower() for key in selection.to_payload())
    evaluation = evaluate_holdout_metrics(selection, {}, config=calibration_config)
    if selection.disposition is DevelopmentDisposition.INSUFFICIENT_EVIDENCE:
        assert evaluation.recommendation is Recommendation.INSUFFICIENT_EVIDENCE
    else:
        assert evaluation.recommendation is Recommendation.RETAIN_GLOBAL_14
