"""L2-D1 causal adequacy foundation tests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from libs.models.trendlines.config import load_trendlines_config
from libs.models.trendlines.workflows.research import (
    TrendlineReplayWindow,
    TrendlineReplayIntegrityError,
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchPurpose,
    TrendlineResearchReplaySpec,
    TrendlineResearchSpec,
    prepare_trendline_research,
    run_causal_replay,
)
from libs.models.trendlines.workflows.research.adequacy import (
    KNOWN_ADEQUACY_METRIC_NAMES,
    TrendlineAdequacyAvailabilityPolicy,
    TrendlineAdequacyBaselineKind,
    TrendlineAdequacyBaselineSpec,
    TrendlineAdequacyContractError,
    TrendlineAdequacyDecisionRule,
    TrendlineAdequacyMetricValue,
    TrendlineAdequacyObservation,
    TrendlineAdequacyObservationState,
    TrendlineAdequacyOperator,
    TrendlineAdequacyStudyConfig,
    TrendlineAdequacyTimeframeSummary,
    TrendlineAdequacyWindow,
    TrendlineInvalidPointTreatment,
    TrendlineObservationUnit,
    build_adequacy_cohort,
    collect_adequacy_observations,
    default_adequacy_metric_catalog,
    summarize_adequacy_eligibility,
    validate_adequacy_point_causality,
)


def _study_config(
    *,
    start: int = 20,
    end: int = 25,
    minimum_warmup_bars: int = 1,
    minimum_prior_executed_prefixes: int = 0,
    threshold_offset: float = 0.0,
) -> TrendlineAdequacyStudyConfig:
    metric_names = (
        "eligible_point_coverage",
        "invalid_point_rate",
        "line_observation_count",
        "ray_observation_count",
    )
    return TrendlineAdequacyStudyConfig(
        study_name="l2d1-foundation-test",
        windows=(
            TrendlineAdequacyWindow(
                "1h",
                start,
                end,
                minimum_warmup_bars,
                minimum_prior_executed_prefixes,
            ),
        ),
        metric_names=metric_names,
        decision_rules=(
            TrendlineAdequacyDecisionRule(
                "eligible_point_coverage",
                TrendlineAdequacyOperator.GREATER_THAN_OR_EQUAL,
                0.5 + threshold_offset,
                1,
            ),
            TrendlineAdequacyDecisionRule(
                "invalid_point_rate",
                TrendlineAdequacyOperator.LESS_THAN_OR_EQUAL,
                0.5 + threshold_offset,
                1,
            ),
        ),
        baseline_specs=(
            TrendlineAdequacyBaselineSpec(
                "random-pairs",
                TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR,
                repetitions=2,
                preserves=("timeframe", "position", "role", "causal_prefix"),
                seed=7,
            ),
            TrendlineAdequacyBaselineSpec(
                "recent-extrema",
                TrendlineAdequacyBaselineKind.RECENT_EXTREMA,
                repetitions=1,
                preserves=("timeframe", "position", "role", "causal_prefix"),
            ),
        ),
        line_observation_unit=TrendlineObservationUnit.FITTED_LINE,
        ray_observation_unit=TrendlineObservationUnit.BOUNDARY_RAY,
        invalid_point_treatment=(
            TrendlineInvalidPointTreatment.RETAIN_AND_REPORT_EXCLUDE_FROM_GEOMETRY_METRICS
        ),
        availability_policy=TrendlineAdequacyAvailabilityPolicy.CAUSAL_PREFIX_ONLY,
    )


@pytest.fixture(scope="module")
def replay_fixture():
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
        prepare_trendline_research(
            spec,
            trendlines_config=load_trendlines_config(),
        )
    )
    replay = run_causal_replay(
        prepared,
        TrendlineResearchReplaySpec(
            windows={"1h": TrendlineReplayWindow(19, 20, 25, 1)},
            include_signals=False,
        ),
    )
    return prepared, replay


def _replay_with_stride(prepared, record_every: int):
    return run_causal_replay(
        prepared,
        TrendlineResearchReplaySpec(
            windows={"1h": TrendlineReplayWindow(19, 20, 25, record_every)},
            include_signals=False,
        ),
    )


def test_window_rejects_bool_and_invalid_bounds():
    with pytest.raises(TrendlineAdequacyContractError):
        TrendlineAdequacyWindow("1h", True, 25, 1, 0)
    with pytest.raises(TrendlineAdequacyContractError):
        TrendlineAdequacyWindow("1h", 25, 20, 1, 0)
    with pytest.raises(TrendlineAdequacyContractError):
        TrendlineAdequacyWindow("1h", 20, 25, -1, 0)
    with pytest.raises(TrendlineAdequacyContractError, match="ordered tuple"):
        replace(_study_config(), windows=list(_study_config().windows))


def test_study_windows_preserve_order_and_validate_exact_replay_scope(replay_fixture):
    prepared, replay = replay_fixture
    config = _study_config()
    config.validate_for(prepared, replay)
    assert tuple(window.timeframe for window in config.windows) == ("1h",)
    with pytest.raises(TrendlineAdequacyContractError):
        _study_config(start=20, end=26).validate_for(prepared, replay)


def test_adequacy_window_cannot_start_before_record_scope(replay_fixture):
    prepared, replay = replay_fixture
    with pytest.raises(TrendlineAdequacyContractError, match="starts before"):
        _study_config(start=19, end=22).validate_for(prepared, replay)


def test_adequacy_window_requires_recorded_stride_intersection(replay_fixture):
    prepared, _ = replay_fixture
    replay = _replay_with_stride(prepared, record_every=2)
    with pytest.raises(TrendlineAdequacyContractError, match="no recorded"):
        _study_config(start=21, end=21).validate_for(prepared, replay)


def test_adequacy_window_accepts_partial_recorded_stride_scope(replay_fixture):
    prepared, _ = replay_fixture
    replay = _replay_with_stride(prepared, record_every=2)
    config = _study_config(start=21, end=24)
    config.validate_for(prepared, replay)
    cohort = build_adequacy_cohort(prepared, replay, config)
    observations = collect_adequacy_observations(cohort, prepared, replay, config)
    assert tuple(value.position for value in observations) == (20, 22, 24)
    assert {value.position for value in observations if value.state is not TrendlineAdequacyObservationState.OUTSIDE_WINDOW} == {22, 24}


def test_study_config_rejects_unknown_metric():
    with pytest.raises(TrendlineAdequacyContractError, match="unknown adequacy metrics"):
        replace(_study_config(), metric_names=("invented_metric",))


def test_decision_threshold_requires_finite_value_and_observation_floor():
    with pytest.raises(TrendlineAdequacyContractError):
        TrendlineAdequacyDecisionRule(
            "invalid_point_rate",
            TrendlineAdequacyOperator.LESS_THAN_OR_EQUAL,
            float("nan"),
            1,
        )
    with pytest.raises(TrendlineAdequacyContractError):
        TrendlineAdequacyDecisionRule(
            "invalid_point_rate",
            TrendlineAdequacyOperator.LESS_THAN_OR_EQUAL,
            0.5,
            True,
        )


def test_study_config_identity_is_deterministic_and_changes_with_frozen_inputs():
    first = _study_config()
    second = _study_config()
    changed = _study_config(threshold_offset=0.25)
    assert first.study_config_id == second.study_config_id
    assert first.to_dict() == second.to_dict()
    assert first.study_config_id != changed.study_config_id
    assert tuple(rule.metric_name for rule in first.decision_rules) == (
        "eligible_point_coverage",
        "invalid_point_rate",
    )


def test_metric_catalog_is_frozen_and_covers_later_phases():
    catalog = default_adequacy_metric_catalog()
    assert catalog == default_adequacy_metric_catalog()
    assert tuple(value.name for value in catalog) == KNOWN_ADEQUACY_METRIC_NAMES
    assert {
        value.name: value.direction.value
        for value in catalog
        if value.name in {
            "eligible_point_coverage",
            "invalid_point_rate",
            "revision_churn_rate",
            "anchor_persistence_rate",
            "penetration_depth",
            "false_break_rate",
            "favourable_excursion",
            "adverse_excursion",
            "null_lift",
            "cohort_stability",
        }
    } == {
        "eligible_point_coverage": "higher_is_better",
        "invalid_point_rate": "lower_is_better",
        "revision_churn_rate": "lower_is_better",
        "anchor_persistence_rate": "higher_is_better",
        "penetration_depth": "lower_is_better",
        "false_break_rate": "lower_is_better",
        "favourable_excursion": "higher_is_better",
        "adverse_excursion": "lower_is_better",
        "null_lift": "higher_is_better",
        "cohort_stability": "higher_is_better",
    }
    assert {value.phase.value for value in catalog} == {
        "foundation",
        "structural_stability",
        "interaction_utility",
        "baseline_comparison",
        "robustness",
    }
    assert all(value.requires_future_rows is False for value in catalog[:4])


def test_random_baseline_requires_seed_and_deterministic_baseline_rejects_seed():
    with pytest.raises(ValueError, match="require an explicit seed"):
        TrendlineAdequacyBaselineSpec(
            "random",
            TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR,
            1,
            ("position",),
        )
    with pytest.raises(ValueError, match="must not define a seed"):
        TrendlineAdequacyBaselineSpec(
            "recent",
            TrendlineAdequacyBaselineKind.RECENT_EXTREMA,
            1,
            ("position",),
            seed=1,
        )


def test_baseline_identity_is_deterministic():
    first = TrendlineAdequacyBaselineSpec(
        "random",
        TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR,
        2,
        ("position", "causal_prefix"),
        seed=4,
    )
    second = TrendlineAdequacyBaselineSpec(
        "random",
        TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR,
        2,
        ("position", "causal_prefix"),
        seed=4,
    )
    assert first.baseline_id == second.baseline_id


def test_baseline_future_data_policy_is_fail_closed():
    with pytest.raises(ValueError, match="unknown baseline data policy"):
        TrendlineAdequacyBaselineSpec(
            "bad-policy",
            TrendlineAdequacyBaselineKind.RECENT_EXTREMA,
            1,
            ("position",),
            data_policy="future_rows_allowed",
        )


def test_cohort_binds_preparation_dataset_configuration_and_replay_ids(replay_fixture):
    prepared, replay = replay_fixture
    cohort = build_adequacy_cohort(prepared, replay, _study_config())
    assert cohort.preparation_id == prepared.preparation_id
    assert cohort.dataset_id == prepared.dataset.dataset_id
    assert cohort.research_configuration_id == prepared.configuration.research_configuration_id
    assert cohort.replay_id == replay.replay_id
    assert cohort.cohort_id
    assert cohort.cohort_id == build_adequacy_cohort(
        prepared,
        replay,
        _study_config(),
    ).cohort_id


def test_cohort_replay_identity_payload_is_immutable(replay_fixture):
    prepared, replay = replay_fixture
    cohort = build_adequacy_cohort(prepared, replay, _study_config())
    original_id = cohort.cohort_id
    serialized = cohort.to_dict()
    serialized["replay_windows"][0]["end_position"] = 999
    serialized["source_ids"]["1h"] = "changed"
    assert cohort.cohort_id == original_id
    assert cohort.replay_windows[0][3] == 25
    assert cohort.source_ids[0] == ("1h", prepared.dataset.identity.source_refs["1h"].source_id)
    with pytest.raises(TrendlineAdequacyContractError):
        replace(cohort, replay_windows=(("1h", 19, 20, 24, 1),))


def test_prepared_replay_mismatch_is_rejected(replay_fixture):
    _, replay = replay_fixture
    other_spec = TrendlineResearchSpec(
        purpose=TrendlineResearchPurpose.SMOKE,
        data=TrendlineResearchDataSpec(
            mode=TrendlineResearchDataMode.SYNTHETIC,
            seed=43,
            start_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
            bar_counts={"1h": 32},
        ),
        asset="BTCUSDT",
        timeframes=("1h",),
        primary_timeframe="1h",
    )
    other = asyncio.run(
        prepare_trendline_research(other_spec, trendlines_config=load_trendlines_config())
    )
    with pytest.raises(TrendlineAdequacyContractError):
        build_adequacy_cohort(other, replay, _study_config())


def test_valid_causal_points_are_eligible(replay_fixture):
    prepared, replay = replay_fixture
    cohort = build_adequacy_cohort(prepared, replay, _study_config())
    observations = collect_adequacy_observations(
        cohort,
        prepared,
        replay,
        _study_config(),
    )
    assert observations
    assert any(value.state is TrendlineAdequacyObservationState.ELIGIBLE for value in observations)
    assert all(value.available_at >= value.event_at for value in observations)


def test_availability_before_event_is_rejected(replay_fixture):
    _, replay = replay_fixture
    point = replay.output_at("1h", 20)
    bad = replace(point, available_at=point.event_at - timedelta(minutes=1))
    with pytest.raises(TrendlineAdequacyContractError) as exc_info:
        validate_adequacy_point_causality(bad)
    assert isinstance(exc_info.value.__cause__, TrendlineReplayIntegrityError)


def test_future_known_boundary_is_rejected(replay_fixture):
    _, replay = replay_fixture
    point = replay.output_at("1h", 20)
    bad_snapshot = replace(
        point.boundary_snapshot,
        known_at=point.available_at + timedelta(minutes=1),
    )
    bad = replace(point, boundary_snapshot=bad_snapshot)
    with pytest.raises(TrendlineAdequacyContractError) as exc_info:
        validate_adequacy_point_causality(bad)
    assert isinstance(exc_info.value.__cause__, TrendlineReplayIntegrityError)


def test_tampered_replay_point_is_rejected_during_adequacy_collection(replay_fixture):
    prepared, replay = replay_fixture
    point = replay.output_at("1h", 22)
    tampered_output = replace(
        point.output,
        metadata={**point.output.metadata, "tampered_after_identity": True},
    )
    tampered_point = replace(point, output=tampered_output)
    timeframe = replay.timeframes["1h"]
    tampered_timeframe = replace(
        timeframe,
        points=tuple(
            tampered_point if value.position == point.position else value
            for value in timeframe.points
        ),
    )
    tampered_replay = replace(
        replay,
        timeframes={"1h": tampered_timeframe},
    )
    config = _study_config()
    cohort = build_adequacy_cohort(prepared, tampered_replay, config)
    with pytest.raises(TrendlineAdequacyContractError) as exc_info:
        collect_adequacy_observations(
            cohort,
            prepared,
            tampered_replay,
            config,
        )
    assert isinstance(exc_info.value.__cause__, TrendlineReplayIntegrityError)


def test_only_recorded_points_are_observed_and_window_excludes_outside_points(replay_fixture):
    prepared, replay = replay_fixture
    config = _study_config(start=22, end=24)
    cohort = build_adequacy_cohort(prepared, replay, config)
    observations = collect_adequacy_observations(cohort, prepared, replay, config)
    assert tuple(value.position for value in observations) == replay.timeframes["1h"].recorded_positions
    assert all(value.position != 21 for value in observations if value.eligible)
    assert {value.position for value in observations if not value.eligible} >= {20, 21, 25}


def test_minimum_prior_prefixes_exclude_early_recorded_points(replay_fixture):
    prepared, replay = replay_fixture
    config = _study_config(minimum_prior_executed_prefixes=5)
    cohort = build_adequacy_cohort(prepared, replay, config)
    observations = collect_adequacy_observations(cohort, prepared, replay, config)
    early = next(value for value in observations if value.position == 20)
    assert early.state is TrendlineAdequacyObservationState.INSUFFICIENT_HISTORY


def test_invalid_output_is_retained_and_excluded_from_geometry_metrics(replay_fixture):
    prepared, replay = replay_fixture
    config = _study_config()
    cohort = build_adequacy_cohort(prepared, replay, config)
    point = replay.output_at("1h", 20)
    fit = point.output.fit_result
    boundary = point.boundary_snapshot.boundary
    observations = (
        TrendlineAdequacyObservation(
            cohort_id=cohort.cohort_id,
            timeframe="1h",
            position=point.position,
            event_at=point.event_at,
            available_at=point.available_at,
            replay_point_id=point.replay_point_id,
            content_id=point.content_id,
            source_id=point.prefix_source_ref.source_id,
            checkpoint_id=point.boundary_identity.checkpoint.checkpoint_id,
            fit_valid=False,
            state=TrendlineAdequacyObservationState.INVALID_OUTPUT,
            reason="invalid_model_output",
            prior_executed_prefix_count=0,
            support_line_count=len(fit.support_lines),
            resistance_line_count=len(fit.resistance_lines),
            support_ray_count=len(boundary.active_support_rays),
            resistance_ray_count=len(boundary.active_resistance_rays),
        ),
    )
    summary = summarize_adequacy_eligibility(observations)
    assert len(observations) == 1
    assert observations[0].state is TrendlineAdequacyObservationState.INVALID_OUTPUT
    assert summary.invalid_point_count == 1
    assert summary.eligible_point_count == 0


def test_line_and_ray_counts_are_descriptive_point_counts(replay_fixture):
    prepared, replay = replay_fixture
    config = _study_config()
    cohort = build_adequacy_cohort(prepared, replay, config)
    observations = collect_adequacy_observations(cohort, prepared, replay, config)
    point = replay.output_at("1h", observations[0].position)
    observation = observations[0]
    assert observation.support_line_count == len(point.output.fit_result.support_lines)
    assert observation.resistance_line_count == len(point.output.fit_result.resistance_lines)
    assert observation.support_ray_count == len(point.boundary_snapshot.boundary.active_support_rays)
    assert observation.resistance_ray_count == len(point.boundary_snapshot.boundary.active_resistance_rays)


def test_eligibility_summary_is_deterministic_and_has_no_decision(replay_fixture):
    prepared, replay = replay_fixture
    config = _study_config()
    cohort = build_adequacy_cohort(prepared, replay, config)
    observations = collect_adequacy_observations(cohort, prepared, replay, config)
    first = summarize_adequacy_eligibility(observations)
    second = summarize_adequacy_eligibility(tuple(observations))
    assert first.to_dict() == second.to_dict()
    assert first.to_dict()["decision"] is None


def test_public_summary_contracts_reject_invalid_values(replay_fixture):
    with pytest.raises(TrendlineAdequacyContractError):
        TrendlineAdequacyMetricValue("invalid_point_rate", float("nan"), 1)
    with pytest.raises(TrendlineAdequacyContractError):
        TrendlineAdequacyTimeframeSummary(
            timeframe="1h",
            scoped_point_count=1,
            eligible_point_count=2,
            invalid_point_count=0,
            excluded_point_count=0,
            line_observation_count=0,
            ray_observation_count=0,
        )
    prepared, replay = replay_fixture
    config = _study_config()
    cohort = build_adequacy_cohort(prepared, replay, config)
    summary = summarize_adequacy_eligibility(
        collect_adequacy_observations(cohort, prepared, replay, config)
    )
    with pytest.raises(TrendlineAdequacyContractError):
        replace(summary, scoped_point_count=summary.scoped_point_count + 1)


def test_cohort_identity_changes_when_frozen_study_changes(replay_fixture):
    prepared, replay = replay_fixture
    first = build_adequacy_cohort(prepared, replay, _study_config())
    second = build_adequacy_cohort(
        prepared,
        replay,
        _study_config(threshold_offset=0.5),
    )
    assert first.study_config_id != second.study_config_id
    assert first.cohort_id != second.cohort_id


def test_eligibility_does_not_execute_model_or_provider(monkeypatch, replay_fixture):
    prepared, replay = replay_fixture
    config = _study_config()
    cohort = build_adequacy_cohort(prepared, replay, config)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("L2-D1 eligibility must not execute model code")

    monkeypatch.setattr(
        "libs.models.trendlines.api.fit_and_signal",
        fail_if_called,
    )
    observations = collect_adequacy_observations(cohort, prepared, replay, config)
    assert observations
