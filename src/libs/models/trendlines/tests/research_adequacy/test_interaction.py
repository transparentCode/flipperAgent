"""Focused causal interaction-utility contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from libs.models.trendlines.workflows.research.adequacy import (
    TrendlineInteractionEvent,
    TrendlineInteractionOutcome,
    TrendlineInteractionSummary,
    TrendlineInteractionUtilityBundle,
    TrendlineInteractionUtilityError,
    TrendlineInteractionUtilitySpec,
    TrendlineObservationUnit,
    build_interaction_events,
    validate_interaction_utility_bundle,
)
from libs.models.trendlines.workflows.research.adequacy.stability import (
    TrendlineStructuralStabilityBundle,
)
from scripts import analyze_trendlines_l2d3_interaction_utility as d3_script
import libs.models.trendlines.workflows.research.adequacy.interaction as interaction_module
from libs.models.trendlines.workflows.research.adequacy.interaction import (
    _build_summary,
    measure_interaction_outcomes,
)


HASH = "a" * 64
BASE = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _spec(
    horizons: tuple[int, ...] = (1, 3, 6, 12),
    confirmation: int = 2,
) -> TrendlineInteractionUtilitySpec:
    return TrendlineInteractionUtilitySpec(
        evaluation_horizons_bars=horizons,
        break_confirmation_bars=confirmation,
    )


def _event(
    spec: TrendlineInteractionUtilitySpec,
    *,
    role: str = "support",
    selection_position: int = 1,
    selection_atr: float = 2.0,
    slope: float = 0.0,
    intercept: float = 10.0,
) -> TrendlineInteractionEvent:
    return TrendlineInteractionEvent(
        cohort_id=HASH,
        study_config_id=HASH,
        structural_stability_bundle_id=HASH,
        interaction_spec_id=spec.interaction_spec_id,
        timeframe="1h",
        episode_id=HASH,
        birth_state_id=HASH,
        anchor_key=("1h", "2025-01-01T00:00:00+00:00", "2025-01-01T01:00:00+00:00"),
        role=role,
        selection_position=selection_position,
        selection_event_at=(BASE + timedelta(hours=selection_position)).isoformat(),
        selection_available_at=(BASE + timedelta(hours=selection_position + 1)).isoformat(),
        selection_atr=selection_atr,
        frozen_slope=slope,
        frozen_intercept=intercept,
        replay_point_id=HASH,
        content_id=HASH,
        source_id=HASH,
        checkpoint_id=HASH,
    )


def _frame(
    lows: list[float],
    highs: list[float],
    closes: list[float],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "low": [float(value) for value in lows],
            "high": [float(value) for value in highs],
            "close": [float(value) for value in closes],
            "bar_available_at": [BASE + timedelta(hours=index + 1) for index in range(len(lows))],
        }
    )


def _outcomes(
    event: TrendlineInteractionEvent,
    spec: TrendlineInteractionUtilitySpec,
    *,
    lows: list[float] | None = None,
    highs: list[float] | None = None,
    closes: list[float] | None = None,
    final_position: int | None = None,
) -> tuple[TrendlineInteractionOutcome, ...]:
    lows = lows or [9.0] * 14
    highs = highs or [11.0] * 14
    closes = closes or [10.0] * 14
    return measure_interaction_outcomes(
        event,
        _frame(lows, highs, closes),
        spec,
        final_position=final_position,
    )


def _bundle(
    spec: TrendlineInteractionUtilitySpec,
    event: TrendlineInteractionEvent,
    outcomes: tuple[TrendlineInteractionOutcome, ...],
) -> TrendlineInteractionUtilityBundle:
    summaries = tuple(
        _build_summary(
            event.timeframe,
            event.role,
            horizon,
            tuple(outcome for outcome in outcomes if outcome.horizon_bars == horizon),
        )
        for horizon in spec.evaluation_horizons_bars
    )
    return TrendlineInteractionUtilityBundle(
        dataset_id=HASH,
        replay_id=HASH,
        cohort_id=HASH,
        study_config_id=HASH,
        structural_stability_bundle_id=HASH,
        interaction_spec=spec,
        events=(event,),
        outcomes=outcomes,
        summaries=summaries,
    )


@pytest.fixture(scope="module")
def real_d3_context(tmp_path_factory):
    result = d3_script.run_study(
        source_root=Path.cwd() / d3_script.SOURCE_ROOT,
        output_root=tmp_path_factory.mktemp("l2d3-r1"),
    )
    return SimpleNamespace(**result)


def _tampered_bundle(bundle: TrendlineInteractionUtilityBundle, **changes):
    changes.setdefault("interaction_utility_bundle_id", "")
    return replace(bundle, **changes)


def _replace_outcome(
    bundle: TrendlineInteractionUtilityBundle,
    original: TrendlineInteractionOutcome,
    **changes,
) -> TrendlineInteractionUtilityBundle:
    replacement = replace(original, outcome_id="", **changes)
    outcomes = tuple(
        replacement if value is original else value for value in bundle.outcomes
    )
    return _tampered_bundle(bundle, outcomes=outcomes)


def _touched_outcome(bundle: TrendlineInteractionUtilityBundle):
    return next(
        value
        for value in bundle.outcomes
        if value.first_touch_position is not None and not value.right_censored
    )


def _adverse_outcome(bundle: TrendlineInteractionUtilityBundle):
    return next(
        value
        for value in bundle.outcomes
        if value.first_adverse_close_position is not None and not value.right_censored
    )


def test_horizons_reject_bool_zero_duplicates_and_unordered():
    with pytest.raises(TrendlineInteractionUtilityError):
        _spec((1, True))
    with pytest.raises(TrendlineInteractionUtilityError):
        _spec((0, 1))
    with pytest.raises(TrendlineInteractionUtilityError):
        _spec((1, 1))
    with pytest.raises(TrendlineInteractionUtilityError):
        _spec((3, 1))


def test_confirmation_bars_reject_bool_and_non_positive():
    with pytest.raises(TrendlineInteractionUtilityError):
        _spec(confirmation=True)
    with pytest.raises(TrendlineInteractionUtilityError):
        _spec(confirmation=0)


def test_interaction_spec_identity_is_deterministic():
    assert _spec().interaction_spec_id == _spec().interaction_spec_id
    assert _spec().interaction_spec_id != _spec(confirmation=3).interaction_spec_id


def test_event_contract_accepts_only_support_or_resistance_roles():
    spec = _spec((1,))
    with pytest.raises(TrendlineInteractionUtilityError):
        _event(spec, role="fitted_line")
    assert _event(spec, role="support").role == "support"
    assert _event(spec, role="resistance").role == "resistance"


def test_fitted_line_observation_unit_is_not_an_interaction_event(monkeypatch):
    spec = _spec((1,))
    prepared = SimpleNamespace(spec=SimpleNamespace(timeframes=("1h",)))
    cohort = SimpleNamespace(cohort_id=HASH)
    study_config = SimpleNamespace(study_config_id=HASH)
    point = SimpleNamespace(
        timeframe="1h",
        position=2,
        event_at=BASE + timedelta(hours=2),
        available_at=BASE + timedelta(hours=3),
        replay_point_id=HASH,
        content_id=HASH,
        prefix_source_ref=SimpleNamespace(source_id=HASH),
        boundary_identity=SimpleNamespace(
            checkpoint=SimpleNamespace(checkpoint_id=HASH),
            snapshot_id=HASH,
            revision_id=HASH,
        ),
        boundary_snapshot=SimpleNamespace(
            boundary=SimpleNamespace(boundary_context={"latest_atr": 2.0})
        ),
    )
    ray_state = SimpleNamespace(
        observation_unit=TrendlineObservationUnit.BOUNDARY_RAY,
        timeframe="1h",
        anchor_key=("1h", "start", "end"),
        position=2,
        role="support",
        shape=(1.0, 2.0, 0.0, 10.0),
        state_id=HASH,
        replay_point_id=HASH,
        content_id=HASH,
        source_id=HASH,
        checkpoint_id=HASH,
        boundary_snapshot_id=HASH,
        boundary_revision_id=HASH,
    )
    ray_episode = SimpleNamespace(
        observation_unit=TrendlineObservationUnit.BOUNDARY_RAY,
        left_censored=False,
        timeframe="1h",
        first_position=2,
        anchor_key=ray_state.anchor_key,
        role_switch_count=0,
        episode_ordinal=0,
        episode_id=HASH,
    )
    fitted_episode = SimpleNamespace(
        observation_unit=TrendlineObservationUnit.FITTED_LINE,
        left_censored=False,
        timeframe="1h",
        first_position=2,
        anchor_key=("1h", 0, 1),
        role_switch_count=0,
        episode_ordinal=0,
        episode_id=HASH,
    )
    replay = SimpleNamespace(
        prepared=prepared,
        output_at=lambda timeframe, position: point,
    )
    d2_bundle = SimpleNamespace(
        cohort_id=HASH,
        study_config_id=HASH,
        structural_stability_bundle_id=HASH,
        state_rows=(ray_state,),
        episode_rows=(ray_episode, fitted_episode),
    )
    monkeypatch.setattr(
        interaction_module,
        "build_adequacy_cohort",
        lambda prepared_value, replay_value, config_value: cohort,
    )
    monkeypatch.setattr(
        interaction_module,
        "validate_structural_stability_bundle",
        lambda bundle: None,
    )
    monkeypatch.setattr(
        interaction_module,
        "validate_replay_point_integrity",
        lambda value: None,
    )
    events = build_interaction_events(
        prepared,
        replay,
        cohort,
        study_config,
        d2_bundle,
        spec,
    )
    assert len(events) == 1
    assert events[0].episode_id == HASH
    assert events[0].role == "support"


def test_birth_geometry_is_frozen_for_projection():
    spec = _spec((1,))
    event = _event(spec, selection_position=2, slope=1.5, intercept=4.0)
    outcomes = _outcomes(event, spec, lows=[0, 0, 6.9, 8.4], highs=[0, 0, 7.1, 8.6], closes=[0, 0, 7, 8.5])
    assert outcomes[0].first_touch_position == 3
    assert outcomes[0].first_touch_projected_level == 8.5


def test_projection_uses_absolute_future_position():
    spec = _spec((2,))
    event = _event(spec, selection_position=2, slope=2.0, intercept=1.0)
    result = _outcomes(event, spec, lows=[0, 0, 0, 6.9, 8.9], highs=[0, 0, 0, 7.1, 9.1], closes=[0, 0, 0, 7, 9])
    assert result[0].first_touch_position == 3
    assert result[0].first_touch_projected_level == 7.0


def test_evaluation_starts_after_selection_position():
    spec = _spec((1,))
    event = _event(spec, selection_position=1, intercept=10.0)
    result = _outcomes(event, spec, lows=[9, 9, 9], highs=[11, 11, 11], closes=[9, 9, 10])
    assert result[0].first_touch_position == 2


def test_future_availability_must_exceed_selection_availability():
    spec = _spec((1,))
    event = _event(spec, selection_position=1)
    frame = _frame([9, 9, 9], [11, 11, 11], [10, 10, 10])
    frame.loc[2, "bar_available_at"] = BASE + timedelta(hours=2)
    with pytest.raises(TrendlineInteractionUtilityError, match="availability"):
        measure_interaction_outcomes(event, frame, spec)


def test_selection_atr_must_be_finite_and_positive():
    spec = _spec((1,))
    with pytest.raises(TrendlineInteractionUtilityError):
        _event(spec, selection_atr=0)
    with pytest.raises(TrendlineInteractionUtilityError):
        _event(spec, selection_atr=float("nan"))


def test_exact_range_crossing_counts_as_touch():
    spec = _spec((1,))
    result = _outcomes(_event(spec), spec, lows=[0, 0, 10], highs=[0, 0, 10], closes=[0, 0, 10])
    assert result[0].first_touch_position == 2


def test_near_miss_does_not_count_as_touch():
    spec = _spec((1,))
    result = _outcomes(_event(spec), spec, lows=[0, 0, 10.01], highs=[0, 0, 11], closes=[0, 0, 10.5])
    assert result[0].first_touch_position is None


def test_support_defended_touch_rule():
    spec = _spec((1,))
    result = _outcomes(_event(spec, role="support"), spec, lows=[0, 0, 9], highs=[0, 0, 11], closes=[0, 0, 10])
    assert result[0].defended_touch is True


def test_resistance_defended_touch_rule():
    spec = _spec((1,))
    result = _outcomes(_event(spec, role="resistance"), spec, lows=[0, 0, 9], highs=[0, 0, 11], closes=[0, 0, 10])
    assert result[0].defended_touch is True


def test_wick_rejection_is_strict_subset_of_defended_touch():
    spec = _spec((1,))
    result = _outcomes(_event(spec), spec, lows=[0, 0, 9], highs=[0, 0, 11], closes=[0, 0, 10])
    assert result[0].wick_rejection is True
    assert result[0].defended_touch is True


def test_first_touch_latency_is_exact():
    spec = _spec((3,))
    result = _outcomes(_event(spec), spec, lows=[0, 0, 11, 9, 11], highs=[0, 0, 11, 11, 11], closes=[0, 0, 11, 10, 11])
    assert result[0].first_touch_latency_bars == 2


def test_support_penetration_is_atr_normalised():
    spec = _spec((1,))
    result = _outcomes(_event(spec, selection_atr=2), spec, lows=[0, 0, 8], highs=[0, 0, 11], closes=[0, 0, 10])
    assert result[0].first_touch_penetration_atr == 1.0


def test_resistance_penetration_is_atr_normalised():
    spec = _spec((1,))
    result = _outcomes(_event(spec, role="resistance", selection_atr=2), spec, lows=[0, 0, 9], highs=[0, 0, 12], closes=[0, 0, 10])
    assert result[0].first_touch_penetration_atr == 1.0


def test_gap_adverse_close_can_occur_without_touch():
    spec = _spec((1,))
    result = _outcomes(_event(spec), spec, lows=[0, 0, 7], highs=[0, 0, 8], closes=[0, 0, 8])
    assert result[0].first_touch_position is None
    assert result[0].first_adverse_close_position == 2


def test_confirmed_break_requires_consecutive_adverse_closes():
    spec = _spec((3,), confirmation=2)
    result = _outcomes(_event(spec), spec, lows=[0, 0, 9, 9, 11], highs=[0, 0, 9, 9, 11], closes=[0, 0, 9, 9, 11])
    assert result[0].break_status == "confirmed"


def test_return_before_confirmation_is_false_break():
    spec = _spec((3,), confirmation=2)
    result = _outcomes(_event(spec), spec, lows=[0, 0, 9, 11, 11], highs=[0, 0, 9, 11, 11], closes=[0, 0, 9, 10, 11])
    assert result[0].break_status == "false"


def test_horizon_ending_before_confirmation_is_unresolved():
    spec = _spec((1,), confirmation=2)
    result = _outcomes(_event(spec), spec, lows=[0, 0, 9], highs=[0, 0, 9], closes=[0, 0, 9])
    assert result[0].break_status == "unresolved"


def test_support_excursions_use_birth_level_and_selection_atr():
    spec = _spec((2,))
    result = _outcomes(_event(spec, selection_atr=2), spec, lows=[0, 0, 9, 8], highs=[0, 0, 12, 13], closes=[0, 0, 10, 10])
    assert result[0].favourable_excursion_atr == 1.5
    assert result[0].adverse_excursion_atr == 1.0


def test_resistance_excursions_use_birth_level_and_selection_atr():
    spec = _spec((2,))
    result = _outcomes(_event(spec, role="resistance", selection_atr=2), spec, lows=[0, 0, 8, 7], highs=[0, 0, 11, 12], closes=[0, 0, 10, 10])
    assert result[0].favourable_excursion_atr == 1.5
    assert result[0].adverse_excursion_atr == 1.0


def test_right_censored_horizons_are_not_eligible():
    spec = _spec((1,))
    event = _event(spec)
    outcomes = _outcomes(event, spec, final_position=1)
    assert outcomes[0].right_censored is True
    summary = _build_summary("1h", "support", 1, outcomes)
    assert summary.event_count == 1
    assert summary.eligible_event_count == 0
    assert summary.touch_rate is None


def test_zero_denominators_produce_none_rates():
    summary = TrendlineInteractionSummary(
        timeframe="1h",
        role="support",
        horizon_bars=1,
        event_count=0,
        eligible_event_count=0,
        right_censored_count=0,
        touch_count=0,
        defended_touch_count=0,
        wick_rejection_count=0,
        candidate_break_count=0,
        confirmed_break_count=0,
        false_break_count=0,
        unresolved_break_count=0,
        touch_rate=None,
        rejection_rate=None,
        confirmed_break_rate=None,
        false_break_rate=None,
        mean_first_touch_latency_bars=None,
        median_first_touch_latency_bars=None,
        mean_penetration_atr=None,
        median_penetration_atr=None,
        mean_favourable_excursion_atr=None,
        median_favourable_excursion_atr=None,
        mean_adverse_excursion_atr=None,
        median_adverse_excursion_atr=None,
    )
    assert summary.touch_rate is None
    assert summary.rejection_rate is None
    assert summary.confirmed_break_rate is None
    assert summary.false_break_rate is None


def test_support_and_resistance_summaries_remain_separate():
    spec = _spec((1,))
    support = _event(spec, role="support")
    resistance = _event(spec, role="resistance")
    support_summary = _build_summary("1h", "support", 1, _outcomes(support, spec))
    resistance_summary = _build_summary("1h", "resistance", 1, _outcomes(resistance, spec))
    assert support_summary.role == "support"
    assert resistance_summary.role == "resistance"
    assert support_summary.summary_id != resistance_summary.summary_id


def test_summary_rates_use_required_denominators():
    spec = _spec((1,))
    event = _event(spec)
    summary = _build_summary("1h", "support", 1, _outcomes(event, spec))
    assert summary.touch_rate == summary.touch_count / summary.eligible_event_count
    assert summary.rejection_rate == summary.defended_touch_count / summary.touch_count


def test_event_outcome_and_bundle_identities_are_deterministic():
    spec = _spec((1,))
    event = _event(spec)
    outcomes = _outcomes(event, spec)
    first = _bundle(spec, event, outcomes)
    second = _bundle(spec, _event(spec), _outcomes(_event(spec), spec))
    assert event.event_id == _event(spec).event_id
    assert outcomes[0].outcome_id == second.outcomes[0].outcome_id
    assert first.interaction_utility_bundle_id == second.interaction_utility_bundle_id


def test_changed_horizon_or_confirmation_changes_bundle_identity():
    first_spec = _spec((1,), confirmation=2)
    first_event = _event(first_spec)
    first = _bundle(first_spec, first_event, _outcomes(first_event, first_spec))
    second_spec = _spec((2,), confirmation=3)
    second_event = _event(second_spec)
    second = _bundle(second_spec, second_event, _outcomes(second_event, second_spec))
    assert first_spec.interaction_spec_id != second_spec.interaction_spec_id
    assert first.interaction_utility_bundle_id != second.interaction_utility_bundle_id


def test_d2_bundle_tamper_is_rejected_at_explicit_validation_boundary(real_d3_context):
    bundle = real_d3_context.bundle
    mismatched_d2 = TrendlineStructuralStabilityBundle(
        "",
        HASH,
        HASH,
        HASH,
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
    )
    with pytest.raises(TrendlineInteractionUtilityError, match="D2"):
        validate_interaction_utility_bundle(
            bundle,
            structural_stability_bundle=mismatched_d2,
            replay=real_d3_context.replay,
        )


def test_replay_or_source_identity_mismatch_is_rejected(real_d3_context):
    bundle = _tampered_bundle(real_d3_context.bundle, dataset_id="b" * 64)
    with pytest.raises(TrendlineInteractionUtilityError, match="dataset"):
        validate_interaction_utility_bundle(
            bundle,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_summary_tampering_is_rejected(real_d3_context):
    bundle = real_d3_context.bundle
    summary = replace(
        bundle.summaries[0],
        mean_adverse_excursion_atr=(bundle.summaries[0].mean_adverse_excursion_atr or 0.0) + 1.0,
        summary_id="",
    )
    tampered = _tampered_bundle(
        bundle,
        summaries=(summary,) + bundle.summaries[1:],
    )
    with pytest.raises(TrendlineInteractionUtilityError, match="summar"):
        validate_interaction_utility_bundle(
            tampered,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_d3_cohort_must_match_d2(real_d3_context):
    tampered = _tampered_bundle(real_d3_context.bundle, cohort_id="b" * 64)
    with pytest.raises(TrendlineInteractionUtilityError, match="cohort"):
        validate_interaction_utility_bundle(
            tampered,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_d3_study_config_must_match_d2(real_d3_context):
    tampered = _tampered_bundle(real_d3_context.bundle, study_config_id="b" * 64)
    with pytest.raises(TrendlineInteractionUtilityError, match="study config"):
        validate_interaction_utility_bundle(
            tampered,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_arbitrary_replay_identity_is_rejected(real_d3_context):
    tampered = _tampered_bundle(real_d3_context.bundle, replay_id="b" * 64)
    with pytest.raises(TrendlineInteractionUtilityError, match="replay"):
        validate_interaction_utility_bundle(
            tampered,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_missing_qualifying_event_is_rejected(real_d3_context):
    tampered = _tampered_bundle(
        real_d3_context.bundle,
        events=real_d3_context.bundle.events[:-1],
    )
    with pytest.raises(TrendlineInteractionUtilityError, match="events"):
        validate_interaction_utility_bundle(
            tampered,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_extra_fabricated_event_is_rejected(real_d3_context):
    fabricated = replace(
        real_d3_context.bundle.events[0],
        selection_position=real_d3_context.bundle.events[0].selection_position + 1,
        event_id="",
    )
    tampered = _tampered_bundle(
        real_d3_context.bundle,
        events=real_d3_context.bundle.events + (fabricated,),
    )
    with pytest.raises(TrendlineInteractionUtilityError, match="events"):
        validate_interaction_utility_bundle(
            tampered,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_duplicate_event_horizon_with_missing_coordinate_is_rejected(real_d3_context):
    outcomes = list(real_d3_context.bundle.outcomes)
    outcomes[-1] = outcomes[0]
    tampered = _tampered_bundle(real_d3_context.bundle, outcomes=tuple(outcomes))
    with pytest.raises(TrendlineInteractionUtilityError, match="event/horizon"):
        validate_interaction_utility_bundle(
            tampered,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_incorrect_horizon_end_position_is_rejected(real_d3_context):
    original = real_d3_context.bundle.outcomes[0]
    tampered = _replace_outcome(
        real_d3_context.bundle,
        original,
        horizon_end_position=original.horizon_end_position + 1000,
    )
    with pytest.raises(TrendlineInteractionUtilityError, match="horizon_end"):
        validate_interaction_utility_bundle(
            tampered,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_preselection_first_touch_is_rejected(real_d3_context):
    original = _touched_outcome(real_d3_context.bundle)
    event = next(
        value
        for value in real_d3_context.bundle.events
        if value.event_id == original.interaction_event_id
    )
    tampered = _replace_outcome(
        real_d3_context.bundle,
        original,
        first_touch_position=event.selection_position,
        first_touch_latency_bars=1,
    )
    with pytest.raises(TrendlineInteractionUtilityError, match="first_touch"):
        validate_interaction_utility_bundle(
            tampered,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_incorrect_touch_latency_is_rejected(real_d3_context):
    original = _touched_outcome(real_d3_context.bundle)
    tampered = _replace_outcome(
        real_d3_context.bundle,
        original,
        first_touch_latency_bars=original.first_touch_latency_bars + 1,
    )
    with pytest.raises(TrendlineInteractionUtilityError, match="latency"):
        validate_interaction_utility_bundle(
            tampered,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_preselection_adverse_close_is_rejected(real_d3_context):
    original = _adverse_outcome(real_d3_context.bundle)
    event = next(
        value
        for value in real_d3_context.bundle.events
        if value.event_id == original.interaction_event_id
    )
    tampered = _replace_outcome(
        real_d3_context.bundle,
        original,
        first_adverse_close_position=event.selection_position,
    )
    with pytest.raises(TrendlineInteractionUtilityError, match="adverse_close"):
        validate_interaction_utility_bundle(
            tampered,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_tampered_touch_classification_is_rejected(real_d3_context):
    original = _touched_outcome(real_d3_context.bundle)
    tampered = _replace_outcome(
        real_d3_context.bundle,
        original,
        defended_touch=not original.defended_touch,
        wick_rejection=False,
    )
    with pytest.raises(TrendlineInteractionUtilityError, match="outcomes"):
        validate_interaction_utility_bundle(
            tampered,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_tampered_break_classification_is_rejected(real_d3_context):
    original = _adverse_outcome(real_d3_context.bundle)
    replacement = "false" if original.break_status != "false" else "confirmed"
    tampered = _replace_outcome(
        real_d3_context.bundle,
        original,
        break_status=replacement,
    )
    with pytest.raises(TrendlineInteractionUtilityError, match="outcomes"):
        validate_interaction_utility_bundle(
            tampered,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_tampered_penetration_is_rejected(real_d3_context):
    original = _touched_outcome(real_d3_context.bundle)
    tampered = _replace_outcome(
        real_d3_context.bundle,
        original,
        first_touch_penetration_atr=original.first_touch_penetration_atr + 1.0,
    )
    with pytest.raises(TrendlineInteractionUtilityError, match="outcomes"):
        validate_interaction_utility_bundle(
            tampered,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_tampered_excursion_is_rejected(real_d3_context):
    original = _touched_outcome(real_d3_context.bundle)
    tampered = _replace_outcome(
        real_d3_context.bundle,
        original,
        favourable_excursion_atr=original.favourable_excursion_atr + 1.0,
    )
    with pytest.raises(TrendlineInteractionUtilityError, match="outcomes"):
        validate_interaction_utility_bundle(
            tampered,
            structural_stability_bundle=real_d3_context.structural_stability_bundle,
            replay=real_d3_context.replay,
        )


def test_interaction_measurement_has_no_model_or_provider_execution_path():
    source = __import__(
        "libs.models.trendlines.workflows.research.adequacy.interaction",
        fromlist=["__file__"],
    )
    text = open(source.__file__, encoding="utf-8").read()
    assert "BinanceNativeAdapter" not in text
    assert "fit_and_signal(" not in text
    result = _outcomes(_event(_spec((1,))), _spec((1,)))
    assert len(result) == 1
