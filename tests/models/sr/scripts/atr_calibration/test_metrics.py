from __future__ import annotations

from datetime import timedelta

from libs.models.sr.domain.contracts import SREventType
from libs.models.sr.scripts.atr_calibration.metrics import compute_candidate_metrics, compute_window_metrics


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


def test_terminal_event_at_window_end_is_excluded_by_half_open_policy(calibration_config, source_capsules, development_replays):
    development, _ = source_capsules
    replay = development_replays[2]
    events_by_zone = {}
    for event in replay.trace.events:
        events_by_zone.setdefault(event.zone_id, []).append(event)
    terminal_pair = next(
        (
            (events_by_zone[zone_id], min(
                (candidate for candidate in events_by_zone[zone_id] if candidate.event_type in {SREventType.BREAK_CONFIRMED, SREventType.EXPIRED}),
                key=lambda candidate: candidate.timestamp,
            ))
            for zone_id in sorted(events_by_zone)
            if any(event.event_type in {SREventType.BREAK_CONFIRMED, SREventType.EXPIRED} for event in events_by_zone[zone_id])
            and any(created.event_type is SREventType.CREATED and created.timestamp < min(
                (candidate.timestamp for candidate in events_by_zone[zone_id] if candidate.event_type in {SREventType.BREAK_CONFIRMED, SREventType.EXPIRED}),
            ) for created in events_by_zone[zone_id])
        ),
        None,
    )
    assert terminal_pair is not None
    zone_events, terminal = terminal_pair
    created = next(event for event in zone_events if event.event_type is SREventType.CREATED and event.timestamp < terminal.timestamp)
    exact_end = compute_window_metrics(
        replay,
        development,
        config=calibration_config,
        name="half_open_exact_end",
        start=created.timestamp,
        end=terminal.timestamp,
    )
    following_end = compute_window_metrics(
        replay,
        development,
        config=calibration_config,
        name="half_open_following_end",
        start=created.timestamp,
        end=terminal.timestamp + timedelta(days=1),
    )
    assert exact_end.created_zone_count >= 1
    assert following_end.cohort_terminal_count > exact_end.cohort_terminal_count
