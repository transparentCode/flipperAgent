from __future__ import annotations

from libs.models.sr.scripts.atr_calibration.metrics import compute_candidate_metrics


def test_metrics_have_locked_folds_and_reference_denominator(calibration_config, source_capsules, development_replays):
    development, _ = source_capsules
    metric = compute_candidate_metrics(development_replays[2], development, config=calibration_config)
    assert tuple(fold.name for fold in metric.folds) == tuple(fold.name for fold in calibration_config.development_folds)
    assert metric.pooled.name == "development_pooled"
    for fold in metric.folds:
        assert fold.completed_first_touch_outcomes + fold.right_censored_first_touch_outcomes == fold.total_first_touch_outcomes
        for outcome in fold.outcomes:
            assert outcome.reference_atr_14 > 0


def test_metrics_use_the_independent_reference_series(calibration_config, source_capsules, development_replays):
    development, _ = source_capsules
    metrics = [compute_candidate_metrics(replay, development, config=calibration_config) for replay in development_replays]
    assert all(metric.period in calibration_config.candidate_periods for metric in metrics)
    assert all(
        outcome.reference_atr_14 > 0
        for metric in metrics
        for fold in metric.folds
        for outcome in fold.outcomes
    )
    assert all(replay.reference_atr == development_replays[0].reference_atr for replay in development_replays)
