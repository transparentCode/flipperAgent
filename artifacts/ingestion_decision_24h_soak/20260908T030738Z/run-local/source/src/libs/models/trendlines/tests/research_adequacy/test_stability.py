"""Offline tests for L2-D2 structural stability measurements."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from libs.models.trendlines.config import load_trendlines_config
from libs.models.trendlines.contracts.identity import canonical_hash
from libs.models.trendlines.workflows.research import (
    TrendlineReplayIntegrityError,
    TrendlineReplayWindow,
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchPurpose,
    TrendlineResearchReplaySpec,
    TrendlineResearchSpec,
    prepare_trendline_research,
    run_causal_replay,
)
from libs.models.trendlines.workflows.research.adequacy import (
    ADEQUACY_COHORT_SEMANTICS_VERSION,
    TrendlineAdequacyAvailabilityPolicy,
    TrendlineAdequacyBaselineKind,
    TrendlineAdequacyBaselineSpec,
    TrendlineAdequacyCohort,
    TrendlineAdequacyObservation,
    TrendlineAdequacyObservationState,
    TrendlineAdequacyStudyConfig,
    TrendlineAdequacyWindow,
    TrendlineInvalidPointTreatment,
    TrendlineObservationUnit,
    build_adequacy_cohort,
    collect_adequacy_observations,
    build_structural_episodes,
    build_structural_states,
    build_structural_stability_bundle,
    measure_structural_survival,
    measure_structural_drift,
    measure_structural_transitions,
    TrendlineStructuralStabilityError,
    TrendlineStructuralStabilitySpec,
    TrendlineStructuralState,
    TrendlineStructuralEpisode,
    TrendlineStructuralSurvival,
    TrendlineStructuralTransition,
    validate_structural_stability_bundle,
)
from libs.models.trendlines.workflows.research.adequacy.stability import _summary_for
from libs.models.trendlines.workflows.research.diagnostics import (
    LineEvidenceRow,
    RayEvidenceRow,
)


HASH = "a" * 64


def _cohort(timeframes: tuple[str, ...] = ("1h",)) -> TrendlineAdequacyCohort:
    windows = tuple((timeframe, 0, 0, 8, 1) for timeframe in timeframes)
    source_ids = tuple((timeframe, HASH) for timeframe in timeframes)
    availability_ids = tuple((timeframe, HASH) for timeframe in timeframes)
    availability_sources = tuple((timeframe, "exchange_close_time") for timeframe in timeframes)
    payload = {
        "study_config_id": HASH,
        "asset": "BTCUSDT",
        "timeframes": list(timeframes),
        "preparation_id": HASH,
        "dataset_id": HASH,
        "research_configuration_id": HASH,
        "replay_id": HASH,
        "replay_windows": list(windows),
        "include_signals": False,
        "source_ids": dict(source_ids),
        "availability_ids": dict(availability_ids),
        "timestamp_semantics": "open_time",
        "availability_sources": dict(availability_sources),
        "semantics_version": ADEQUACY_COHORT_SEMANTICS_VERSION,
    }
    return TrendlineAdequacyCohort(
        cohort_id=canonical_hash(payload, semantics_version=ADEQUACY_COHORT_SEMANTICS_VERSION),
        study_config_id=HASH,
        asset="BTCUSDT",
        timeframes=timeframes,
        preparation_id=HASH,
        dataset_id=HASH,
        research_configuration_id=HASH,
        replay_id=HASH,
        replay_windows=windows,
        include_signals=False,
        source_ids=source_ids,
        availability_ids=availability_ids,
        timestamp_semantics="open_time",
        availability_sources=availability_sources,
    )


def _observation(
    cohort: TrendlineAdequacyCohort,
    position: int,
    *,
    state: TrendlineAdequacyObservationState = TrendlineAdequacyObservationState.ELIGIBLE,
) -> TrendlineAdequacyObservation:
    event = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(hours=position)
    return TrendlineAdequacyObservation(
        cohort_id=cohort.cohort_id,
        timeframe="1h",
        position=position,
        event_at=event,
        available_at=event + timedelta(hours=1),
        replay_point_id=HASH,
        content_id=HASH,
        source_id=HASH,
        checkpoint_id=HASH,
        fit_valid=state is not TrendlineAdequacyObservationState.INVALID_OUTPUT,
        state=state,
        reason="test",
        prior_executed_prefix_count=position,
        support_line_count=1,
        resistance_line_count=0,
        support_ray_count=1,
        resistance_ray_count=0,
    )


def _line(
    position: int,
    *,
    role: str = "support",
    ordinal: int = 0,
    start: int = 0,
    end: int = 2,
    method: str = "pathfinding",
    start_value: float = 1.0,
    end_value: float = 2.0,
    slope: float = 0.5,
    intercept: float = 0.5,
    touch_count: int = 2,
    score: float = 0.9,
) -> LineEvidenceRow:
    return LineEvidenceRow(
        evidence_id=HASH,
        timeframe="1h",
        position=position,
        role=role,
        ordinal=ordinal,
        method=method,
        start_position=start,
        end_position=end,
        start_value=start_value,
        end_value=end_value,
        slope=slope,
        intercept=intercept,
        touch_count=touch_count,
        score=score,
        replay_point_id=HASH,
        content_id=HASH,
        source_id=HASH,
        checkpoint_id=HASH,
        boundary_snapshot_id=HASH,
        boundary_revision_id=HASH,
    )


def _ray(position: int, *, start_hour: int = 0, end_hour: int = 1, role: str = "support") -> RayEvidenceRow:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(hours=start_hour)
    end = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(hours=end_hour)
    return RayEvidenceRow(
        evidence_id=HASH,
        timeframe="1h",
        position=position,
        role=role,
        ordinal=0,
        start_time=start.isoformat(),
        end_time=end.isoformat(),
        start_price=1.0,
        end_price=2.0,
        slope=0.5,
        intercept=0.5,
        quality=0.8,
        touch_count=2,
        r_squared=0.7,
        replay_point_id=HASH,
        content_id=HASH,
        source_id=HASH,
        checkpoint_id=HASH,
        boundary_snapshot_id=HASH,
        boundary_revision_id=HASH,
    )


def _states(
    positions: tuple[int, ...],
    *,
    lines_by_position: dict[int, tuple[LineEvidenceRow, ...]] | None = None,
    rays_by_position: dict[int, tuple[RayEvidenceRow, ...]] | None = None,
    observations: tuple[TrendlineAdequacyObservation, ...] | None = None,
    spec: TrendlineStructuralStabilitySpec | None = None,
) -> tuple[TrendlineStructuralState, ...]:
    cohort = _cohort()
    observations = observations or tuple(_observation(cohort, position) for position in positions)
    line_rows = tuple(
        row
        for position in positions
        for row in (lines_by_position or {}).get(position, (_line(position),))
    )
    ray_rows = tuple(
        row
        for position in positions
        for row in (rays_by_position or {}).get(position, (_ray(position),))
    )
    return build_structural_states(
        cohort,
        observations,
        line_rows,
        ray_rows,
        spec or TrendlineStructuralStabilitySpec((1, 3, 6, 12)),
    )


def _study_config() -> TrendlineAdequacyStudyConfig:
    return TrendlineAdequacyStudyConfig(
        study_name="l2d2-test",
        windows=(TrendlineAdequacyWindow("1h", 20, 25, 1, 0),),
        metric_names=("eligible_point_coverage", "invalid_point_rate"),
        decision_rules=(),
        baseline_specs=(
            TrendlineAdequacyBaselineSpec(
                "recent-extrema",
                TrendlineAdequacyBaselineKind.RECENT_EXTREMA,
                1,
                ("timeframe", "position", "causal_prefix"),
            ),
        ),
        line_observation_unit=TrendlineObservationUnit.FITTED_LINE,
        ray_observation_unit=TrendlineObservationUnit.BOUNDARY_RAY,
        invalid_point_treatment=TrendlineInvalidPointTreatment.RETAIN_AND_REPORT_EXCLUDE_FROM_GEOMETRY_METRICS,
        availability_policy=TrendlineAdequacyAvailabilityPolicy.CAUSAL_PREFIX_ONLY,
    )


def _small_replay():
    spec = TrendlineResearchSpec(
        purpose=TrendlineResearchPurpose.SMOKE,
        data=TrendlineResearchDataSpec(
            mode=TrendlineResearchDataMode.SYNTHETIC,
            seed=42,
            start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            bar_counts={"1h": 32},
        ),
        asset="BTCUSDT",
        timeframes=("1h",),
        primary_timeframe="1h",
    )
    prepared = asyncio.run(
        prepare_trendline_research(spec, trendlines_config=load_trendlines_config())
    )
    replay = run_causal_replay(
        prepared,
        TrendlineResearchReplaySpec(
            windows={"1h": TrendlineReplayWindow(19, 20, 25, 1)},
            include_signals=False,
        ),
    )
    return prepared, replay


def _bundle_for_test(horizons: tuple[int, ...] = (1, 3)):
    prepared, replay = _small_replay()
    config = TrendlineAdequacyStudyConfig(
        study_name="l2d2-bundle",
        windows=(TrendlineAdequacyWindow("1h", 20, 25, 1, 0),),
        metric_names=("eligible_point_coverage",),
        decision_rules=(),
        baseline_specs=(
            TrendlineAdequacyBaselineSpec(
                "recent",
                TrendlineAdequacyBaselineKind.RECENT_EXTREMA,
                1,
                ("position",),
            ),
        ),
        line_observation_unit=TrendlineObservationUnit.FITTED_LINE,
        ray_observation_unit=TrendlineObservationUnit.BOUNDARY_RAY,
        invalid_point_treatment=TrendlineInvalidPointTreatment.RETAIN_AND_REPORT_EXCLUDE_FROM_GEOMETRY_METRICS,
        availability_policy=TrendlineAdequacyAvailabilityPolicy.CAUSAL_PREFIX_ONLY,
    )
    cohort = build_adequacy_cohort(prepared, replay, config)
    observations = collect_adequacy_observations(cohort, prepared, replay, config)
    return build_structural_stability_bundle(
        cohort,
        config,
        observations,
        replay,
        TrendlineStructuralStabilitySpec(horizons),
    )


def _transition(**overrides) -> TrendlineStructuralTransition:
    values = {
        "observation_unit": TrendlineObservationUnit.FITTED_LINE,
        "timeframe": "1h",
        "left_position": 1,
        "right_position": 2,
        "position_gap_bars": 1,
        "previous_active_count": 2,
        "current_active_count": 2,
        "persistent_anchor_count": 1,
        "birth_count": 1,
        "disappearance_count": 1,
        "shape_revision_count": 0,
        "role_switch_count": 0,
        "anchor_persistence_rate": 0.5,
        "birth_rate": 0.5,
        "disappearance_rate": 0.5,
        "revision_churn_rate": 0.0,
        "left_state_ids": (HASH, HASH),
        "right_state_ids": (HASH, HASH),
    }
    values.update(overrides)
    return TrendlineStructuralTransition(**values)


def test_stability_horizons_reject_bool_zero_duplicates_and_unordered():
    with pytest.raises(TrendlineStructuralStabilityError):
        TrendlineStructuralStabilitySpec((1, True))
    with pytest.raises(TrendlineStructuralStabilityError):
        TrendlineStructuralStabilitySpec((0, 1))
    with pytest.raises(TrendlineStructuralStabilityError):
        TrendlineStructuralStabilitySpec((1, 1))
    with pytest.raises(TrendlineStructuralStabilityError):
        TrendlineStructuralStabilitySpec((3, 1))


def test_stability_spec_identity_is_deterministic():
    assert TrendlineStructuralStabilitySpec((1, 3)).stability_spec_id == TrendlineStructuralStabilitySpec((1, 3)).stability_spec_id
    assert TrendlineStructuralStabilitySpec((1, 3)).stability_spec_id != TrendlineStructuralStabilitySpec((1, 6)).stability_spec_id


def test_line_structural_key_ignores_ordinal_and_role():
    cohort = _cohort()
    observations = (_observation(cohort, 1), _observation(cohort, 2))
    states = _states(
        (1, 2),
        lines_by_position={
            1: (_line(1, ordinal=4, role="support"),),
            2: (_line(2, ordinal=9, role="resistance"),),
        },
        rays_by_position={1: (), 2: ()},
        observations=observations,
    )
    assert states[0].anchor_key == states[1].anchor_key
    transition = measure_structural_transitions(states, eligible_positions={"1h": (1, 2)})[0]
    assert transition.role_switch_count == 1
    assert transition.birth_count == 0
    assert transition.disappearance_count == 0


def test_ray_structural_key_uses_exact_anchor_timestamps():
    states = _states(
        (1, 2),
        lines_by_position={1: (), 2: ()},
        rays_by_position={
            1: (_ray(1, start_hour=0, end_hour=1),),
            2: (_ray(2, start_hour=0, end_hour=1),),
        },
    )
    assert states[0].anchor_key == states[1].anchor_key
    changed = _states(
        (1, 2),
        lines_by_position={1: (), 2: ()},
        rays_by_position={
            1: (_ray(1, start_hour=0, end_hour=1),),
            2: (_ray(2, start_hour=0, end_hour=2),),
        },
    )
    assert changed[0].anchor_key != changed[1].anchor_key


def test_duplicate_roleless_anchor_fails_closed():
    cohort = _cohort()
    with pytest.raises(TrendlineStructuralStabilityError, match="duplicate"):
        build_structural_states(
            cohort,
            (_observation(cohort, 1),),
            (_line(1, role="support"), _line(1, role="resistance", ordinal=1)),
            (),
            TrendlineStructuralStabilitySpec((1,)),
        )


def test_ineligible_and_invalid_observations_contribute_no_geometry_state():
    cohort = _cohort()
    observations = (
        _observation(cohort, 1),
        _observation(cohort, 2, state=TrendlineAdequacyObservationState.INVALID_OUTPUT),
        _observation(cohort, 3, state=TrendlineAdequacyObservationState.OUTSIDE_WINDOW),
    )
    states = build_structural_states(
        cohort,
        observations,
        (_line(1), _line(2), _line(3)),
        (_ray(1), _ray(2), _ray(3)),
        TrendlineStructuralStabilitySpec((1,)),
    )
    assert {(state.position, state.observation_unit) for state in states} == {
        (1, TrendlineObservationUnit.FITTED_LINE),
        (1, TrendlineObservationUnit.BOUNDARY_RAY),
    }


def test_adjacent_transition_counts_birth_persistence_and_disappearance():
    states = _states(
        (1, 2, 3),
        lines_by_position={
            1: (_line(1),),
            2: (_line(2), _line(2, start=1, end=3, ordinal=1)),
            3: (_line(3, start=1, end=3),),
        },
        rays_by_position={1: (), 2: (), 3: ()},
    )
    transitions = measure_structural_transitions(states, eligible_positions={"1h": (1, 2, 3)})
    line_transitions = [value for value in transitions if value.observation_unit is TrendlineObservationUnit.FITTED_LINE]
    assert (line_transitions[0].persistent_anchor_count, line_transitions[0].birth_count, line_transitions[0].disappearance_count) == (1, 1, 0)
    assert (line_transitions[1].persistent_anchor_count, line_transitions[1].birth_count, line_transitions[1].disappearance_count) == (1, 0, 1)


def test_role_switch_does_not_count_as_birth_or_disappearance():
    states = _states(
        (1, 2),
        lines_by_position={1: (_line(1, role="support"),), 2: (_line(2, role="resistance"),)},
        rays_by_position={1: (), 2: ()},
    )
    transition = next(value for value in measure_structural_transitions(states, eligible_positions={"1h": (1, 2)}) if value.observation_unit is TrendlineObservationUnit.FITTED_LINE)
    assert transition.role_switch_count == 1
    assert transition.birth_count == transition.disappearance_count == 0


def test_transition_rejects_impossible_count_identities():
    with pytest.raises(TrendlineStructuralStabilityError, match="births"):
        _transition(birth_count=0)


def test_transition_rejects_inconsistent_derived_rates():
    with pytest.raises(TrendlineStructuralStabilityError, match="birth_rate"):
        _transition(birth_rate=0.123)


def test_per_unit_summary_counts_only_its_own_states():
    states = _states((1, 2))
    eligible_positions = {"1h": (1, 2)}
    transitions = measure_structural_transitions(
        states,
        eligible_positions=eligible_positions,
    )
    episodes = build_structural_episodes(
        states,
        eligible_positions=eligible_positions,
    )
    survival = measure_structural_survival(
        episodes,
        eligible_positions,
        TrendlineStructuralStabilitySpec((1,)),
    )
    summaries = tuple(
        _summary_for(
            unit,
            "1h",
            states,
            transitions,
            episodes,
            survival,
            eligible_positions,
        )
        for unit in (
            TrendlineObservationUnit.FITTED_LINE,
            TrendlineObservationUnit.BOUNDARY_RAY,
        )
    )
    assert all(
        (
            summary.mean_active_anchor_count,
            summary.minimum_active_anchor_count,
            summary.maximum_active_anchor_count,
        )
        == (1.0, 1, 1)
        for summary in summaries
    )


def test_exact_shape_change_increments_revision_count():
    states = _states(
        (1, 2),
        lines_by_position={1: (_line(1),), 2: (_line(2, slope=0.6),)},
        rays_by_position={1: (), 2: ()},
    )
    transition = next(value for value in measure_structural_transitions(states, eligible_positions={"1h": (1, 2)}) if value.observation_unit is TrendlineObservationUnit.FITTED_LINE)
    assert transition.shape_revision_count == 1


def test_quality_only_change_does_not_increment_shape_revision():
    states = _states(
        (1, 2),
        lines_by_position={1: (_line(1, score=0.7),), 2: (_line(2, score=0.8),)},
        rays_by_position={1: (), 2: ()},
    )
    transition = next(value for value in measure_structural_transitions(states, eligible_positions={"1h": (1, 2)}) if value.observation_unit is TrendlineObservationUnit.FITTED_LINE)
    assert transition.shape_revision_count == 0


def test_persistent_anchor_drift_reports_shape_and_quality_deltas():
    states = _states(
        (1, 2),
        lines_by_position={
            1: (_line(1, start_value=1.0, score=0.7, touch_count=2),),
            2: (_line(2, start_value=1.5, score=0.9, touch_count=3),),
        },
        rays_by_position={1: (), 2: ()},
    )
    drift = measure_structural_drift(states, eligible_positions={"1h": (1, 2)})
    line_drift = next(value for value in drift if value.observation_unit is TrendlineObservationUnit.FITTED_LINE)
    assert line_drift.start_value_delta == 0.5
    assert line_drift.touch_count_delta == 1.0
    assert line_drift.score_delta == pytest.approx(0.2)
    assert line_drift.start_price_delta is None


def test_zero_denominators_produce_none():
    transitions = measure_structural_transitions((), eligible_positions={"1h": (1, 2)})
    assert transitions
    assert all(value.anchor_persistence_rate is None for value in transitions)
    assert all(value.birth_rate is None for value in transitions)
    assert all(value.disappearance_rate is None for value in transitions)
    assert all(value.revision_churn_rate is None for value in transitions)


def test_recorded_position_gap_is_preserved():
    states = _states((1, 3), lines_by_position={1: (_line(1),), 3: (_line(3),)}, rays_by_position={1: (), 3: ()})
    transition = next(value for value in measure_structural_transitions(states, eligible_positions={"1h": (1, 3)}) if value.observation_unit is TrendlineObservationUnit.FITTED_LINE)
    assert transition.position_gap_bars == 2


def test_episode_continues_across_consecutive_eligible_observations():
    states = _states((1, 2, 3), lines_by_position={1: (_line(1),), 2: (_line(2),), 3: (_line(3),)}, rays_by_position={1: (), 2: (), 3: ()})
    episodes = build_structural_episodes(states, eligible_positions={"1h": (1, 2, 3)})
    line_episode = next(value for value in episodes if value.observation_unit is TrendlineObservationUnit.FITTED_LINE)
    assert line_episode.observed_positions == (1, 2, 3)
    assert line_episode.observed_position_count == 3


def test_disappearance_and_reappearance_create_separate_episodes():
    states = _states((1, 2, 3), lines_by_position={1: (_line(1),), 2: (), 3: (_line(3),)}, rays_by_position={1: (), 2: (), 3: ()})
    episodes = build_structural_episodes(states, eligible_positions={"1h": (1, 2, 3)})
    line_episodes = [value for value in episodes if value.observation_unit is TrendlineObservationUnit.FITTED_LINE]
    assert len(line_episodes) == 2
    assert all(value.observed_position_count == 1 for value in line_episodes)


def test_episode_left_and_right_censoring_are_correct():
    states = _states((1, 2), lines_by_position={1: (_line(1),), 2: (_line(2),)}, rays_by_position={1: (), 2: ()})
    episode = next(value for value in build_structural_episodes(states, eligible_positions={"1h": (1, 2)}) if value.observation_unit is TrendlineObservationUnit.FITTED_LINE)
    assert episode.left_censored is True
    assert episode.right_censored is True


def test_horizon_survival_uses_exact_recorded_targets():
    states = _states((0, 1, 2, 3), lines_by_position={0: (), 1: (_line(1),), 2: (_line(2),), 3: ()}, rays_by_position={0: (), 1: (), 2: (), 3: ()})
    episodes = build_structural_episodes(states, eligible_positions={"1h": (0, 1, 2, 3)})
    rows = measure_structural_survival(episodes, {"1h": (0, 1, 2, 3)}, TrendlineStructuralStabilitySpec((1, 3)))
    horizon_one = next(value for value in rows if value.horizon_bars == 1)
    horizon_three = next(value for value in rows if value.horizon_bars == 3)
    assert (horizon_one.survived_count, horizon_one.failed_count) == (1, 0)
    assert horizon_three.right_censored_count == 1


def test_survival_rejects_inconsistent_survival_rate():
    with pytest.raises(TrendlineStructuralStabilityError, match="survival_rate"):
        TrendlineStructuralSurvival(
            observation_unit=TrendlineObservationUnit.FITTED_LINE,
            timeframe="1h",
            horizon_bars=1,
            observed_birth_count=2,
            eligible_target_count=2,
            survived_count=1,
            failed_count=1,
            right_censored_count=0,
            target_unavailable_count=0,
            survival_rate=0.99,
        )


def test_missing_stride_targets_are_unavailable_not_interpolated():
    states = _states((0, 1, 3), lines_by_position={0: (), 1: (_line(1),), 3: ()}, rays_by_position={0: (), 1: (), 3: ()})
    episodes = build_structural_episodes(states, eligible_positions={"1h": (0, 1, 3)})
    rows = measure_structural_survival(episodes, {"1h": (0, 1, 3)}, TrendlineStructuralStabilitySpec((1,)))
    result = next(value for value in rows if value.observation_unit is TrendlineObservationUnit.FITTED_LINE)
    assert result.target_unavailable_count == 1
    assert result.eligible_target_count == 0
    assert result.survival_rate is None


def test_right_censored_targets_are_excluded():
    states = _states((0, 1), lines_by_position={0: (), 1: (_line(1),)}, rays_by_position={0: (), 1: ()})
    episodes = build_structural_episodes(states, eligible_positions={"1h": (0, 1)})
    rows = measure_structural_survival(episodes, {"1h": (0, 1)}, TrendlineStructuralStabilitySpec((1,)))
    result = next(value for value in rows if value.observation_unit is TrendlineObservationUnit.FITTED_LINE)
    assert result.right_censored_count == 1
    assert result.eligible_target_count == 0


def test_episode_positions_preserve_recording_stride_without_inference():
    states = _states(
        (1, 3),
        lines_by_position={1: (_line(1),), 3: (_line(3),)},
        rays_by_position={1: (), 3: ()},
    )
    episodes = build_structural_episodes(states, eligible_positions={"1h": (1, 3)})
    episode = next(
        value
        for value in episodes
        if value.observation_unit is TrendlineObservationUnit.FITTED_LINE
    )
    assert episode.observed_positions == (1, 3)
    assert episode.observed_position_count == 2
    assert episode.position_span_bars == 2
    with pytest.raises(TypeError):
        TrendlineStructuralEpisode(
            observation_unit=TrendlineObservationUnit.FITTED_LINE,
            timeframe="1h",
            anchor_key=("1h", "pathfinding", 0, 2),
            episode_ordinal=0,
            first_position=1,
            last_position=3,
            observed_position_count=2,
            position_span_bars=2,
            initial_role="support",
            final_role="support",
            role_switch_count=0,
            shape_revision_count=0,
            left_censored=False,
            right_censored=False,
        )


def test_survival_returns_zero_rows_for_unit_without_episodes():
    episodes = build_structural_episodes(
        (),
        eligible_positions={"1h": (0, 1)},
    )
    rows = measure_structural_survival(
        episodes,
        {"1h": (0, 1)},
        TrendlineStructuralStabilitySpec((1,)),
    )
    assert {(row.observation_unit, row.timeframe) for row in rows} == {
        (TrendlineObservationUnit.FITTED_LINE, "1h"),
        (TrendlineObservationUnit.BOUNDARY_RAY, "1h"),
    }
    assert all(row.observed_birth_count == 0 for row in rows)
    assert all(row.survival_rate is None for row in rows)


def test_bundle_summary_tampering_is_rejected_after_recomputed_bundle_id():
    bundle = _bundle_for_test()
    tampered_summary = replace(
        bundle.summaries[0],
        mean_active_anchor_count=999.0,
        summary_id="",
    )
    tampered_bundle = replace(
        bundle,
        summaries=(tampered_summary, *bundle.summaries[1:]),
        structural_stability_bundle_id="",
    )
    with pytest.raises(TrendlineStructuralStabilityError, match="summary"):
        validate_structural_stability_bundle(tampered_bundle)


def test_aggregate_rates_use_summed_denominators():
    states = _states(
        (1, 2, 3),
        lines_by_position={1: (_line(1),), 2: (_line(2), _line(2, start=1, end=3, ordinal=1)), 3: (_line(3),)},
        rays_by_position={1: (), 2: (), 3: ()},
    )
    transitions = measure_structural_transitions(states, eligible_positions={"1h": (1, 2, 3)})
    line_transitions = tuple(value for value in transitions if value.observation_unit is TrendlineObservationUnit.FITTED_LINE)
    assert sum(value.persistent_anchor_count for value in line_transitions) == 2
    assert sum(value.previous_active_count for value in line_transitions) == 3


def test_bundle_identity_is_deterministic_and_changes_with_horizons():
    prepared, replay = _small_replay()
    config = TrendlineAdequacyStudyConfig(
        study_name="l2d2-bundle",
        windows=(TrendlineAdequacyWindow("1h", 20, 25, 1, 0),),
        metric_names=("eligible_point_coverage",),
        decision_rules=(),
        baseline_specs=(TrendlineAdequacyBaselineSpec("recent", TrendlineAdequacyBaselineKind.RECENT_EXTREMA, 1, ("position",)),),
        line_observation_unit=TrendlineObservationUnit.FITTED_LINE,
        ray_observation_unit=TrendlineObservationUnit.BOUNDARY_RAY,
        invalid_point_treatment=TrendlineInvalidPointTreatment.RETAIN_AND_REPORT_EXCLUDE_FROM_GEOMETRY_METRICS,
        availability_policy=TrendlineAdequacyAvailabilityPolicy.CAUSAL_PREFIX_ONLY,
    )
    cohort = build_adequacy_cohort(prepared, replay, config)
    observations = collect_adequacy_observations(cohort, prepared, replay, config)
    first = build_structural_stability_bundle(cohort, config, observations, replay, TrendlineStructuralStabilitySpec((1, 3)))
    second = build_structural_stability_bundle(cohort, config, observations, replay, TrendlineStructuralStabilitySpec((1, 3)))
    changed = build_structural_stability_bundle(cohort, config, observations, replay, TrendlineStructuralStabilitySpec((1, 6)))
    assert first.structural_stability_bundle_id == second.structural_stability_bundle_id
    assert first.structural_stability_bundle_id != changed.structural_stability_bundle_id


def test_tampered_replay_evidence_fails_through_canonical_integrity():
    prepared, replay = _small_replay()
    config = _study_config()
    cohort = build_adequacy_cohort(prepared, replay, config)
    observations = collect_adequacy_observations(cohort, prepared, replay, config)
    point = replay.output_at("1h", 22)
    tampered = replace(
        point,
        output=replace(point.output, metadata={**point.output.metadata, "tampered": True}),
    )
    timeframe = replay.timeframes["1h"]
    tampered_replay = replace(
        replay,
        timeframes={"1h": replace(timeframe, points=tuple(tampered if value.position == 22 else value for value in timeframe.points))},
    )
    with pytest.raises(TrendlineReplayIntegrityError):
        build_structural_stability_bundle(cohort, config, observations, tampered_replay, TrendlineStructuralStabilitySpec((1,)))


def test_structural_measurement_executes_no_model_or_provider(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("structural measurement must not execute model/provider code")

    monkeypatch.setattr("libs.models.trendlines.api.fit_and_signal", fail)
    states = _states((1, 2), lines_by_position={1: (_line(1),), 2: (_line(2),)}, rays_by_position={1: (), 2: ()})
    assert measure_structural_transitions(states, eligible_positions={"1h": (1, 2)})
