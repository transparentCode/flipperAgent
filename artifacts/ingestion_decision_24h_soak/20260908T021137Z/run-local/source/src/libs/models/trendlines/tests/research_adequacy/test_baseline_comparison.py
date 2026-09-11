"""Focused tests for paired deterministic naive baseline evidence."""

from __future__ import annotations

import json
import inspect
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from libs.models.trendlines.workflows.research.adequacy import (
    TrendlineAdequacyBaselineKind,
    TrendlineAdequacyBaselineSpec,
    TrendlineBaselineComparisonError,
    TrendlineBaselineSelection,
    TrendlineInteractionEvent,
    TrendlineInteractionOutcome,
    TrendlineInteractionUtilityError,
    TrendlineInteractionUtilitySpec,
    build_interaction_summaries,
    build_baseline_outcomes,
    validate_baseline_comparison_bundle,
)
from libs.models.trendlines.workflows.research.adequacy.baseline_comparison import (
    CONFIRMED_PIVOT_FINALITY,
    _approved_specs,
    _optional_delta,
    _selection_from_pivots,
    _validate_pivot_row,
)
from libs.models.trendlines.workflows.research.diagnostics import ReplayPivotRow
from scripts import analyze_trendlines_l2d4a_deterministic_baselines as d4_script
import libs.models.trendlines.workflows.research.adequacy.baseline_comparison as d4_module


HASH = "a" * 64
BASE = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _interaction_spec(horizons: tuple[int, ...] = (1, 3, 6, 12)):
    return TrendlineInteractionUtilitySpec(
        evaluation_horizons_bars=horizons,
        break_confirmation_bars=2,
    )


def _event(
    spec: TrendlineInteractionUtilitySpec,
    *,
    role: str = "support",
    selection_position: int = 10,
) -> TrendlineInteractionEvent:
    return TrendlineInteractionEvent(
        cohort_id=HASH,
        study_config_id=HASH,
        structural_stability_bundle_id=HASH,
        interaction_spec_id=spec.interaction_spec_id,
        timeframe="1h",
        episode_id=HASH,
        birth_state_id=HASH,
        anchor_key=("1h", "start", "end"),
        role=role,
        selection_position=selection_position,
        selection_event_at=(BASE + timedelta(hours=selection_position)).isoformat(),
        selection_available_at=(BASE + timedelta(hours=selection_position + 1)).isoformat(),
        selection_atr=2.0,
        frozen_slope=0.0,
        frozen_intercept=10.0,
        replay_point_id=HASH,
        content_id=HASH,
        source_id=HASH,
        checkpoint_id=HASH,
    )


def _point(event: TrendlineInteractionEvent) -> SimpleNamespace:
    return SimpleNamespace(
        prefix_source_ref=SimpleNamespace(source_id=event.source_id),
        boundary_identity=SimpleNamespace(
            snapshot_id=event.checkpoint_id,
            revision_id=event.checkpoint_id,
            checkpoint=SimpleNamespace(checkpoint_id=event.checkpoint_id),
        ),
        replay_point_id=event.replay_point_id,
        content_id=event.content_id,
    )


def _pivot(
    event: TrendlineInteractionEvent,
    role: str,
    position: int,
    price: float,
    *,
    finality: str = CONFIRMED_PIVOT_FINALITY,
) -> ReplayPivotRow:
    return ReplayPivotRow(
        timeframe=event.timeframe,
        position=event.selection_position,
        pivot_role=role,
        bar_position=position,
        event_at=(BASE + timedelta(hours=position)).isoformat(),
        price=price,
        extractor="fractal",
        extractor_finality=finality,
        source_id=event.source_id,
        checkpoint_id=event.checkpoint_id,
        boundary_snapshot_id=HASH,
        boundary_revision_id=HASH,
        replay_point_id=event.replay_point_id,
        content_id=event.content_id,
    )


def _selection(
    event: TrendlineInteractionEvent,
    kind: TrendlineAdequacyBaselineKind,
    *,
    available: bool = True,
) -> TrendlineBaselineSelection:
    if kind is TrendlineAdequacyBaselineKind.RECENT_EXTREMA:
        positions = (4, 8) if available else ()
        prices = (9.0, 10.0) if available else ()
        slope = 0.25 if available else None
        intercept = 8.0 if available else None
    else:
        positions = (8,) if available else ()
        prices = (10.0,) if available else ()
        slope = 0.0 if available else None
        intercept = 10.0 if available else None
    return TrendlineBaselineSelection(
        baseline_id=HASH,
        baseline_name="test-baseline",
        baseline_kind=kind,
        model_event_id=event.event_id,
        timeframe=event.timeframe,
        role=event.role,
        selection_position=event.selection_position,
        selection_event_at=event.selection_event_at,
        selection_available_at=event.selection_available_at,
        selection_atr=event.selection_atr,
        available=available,
        reason="available" if available else "insufficient_same_role_pivots",
        selected_pivot_positions=positions,
        selected_pivot_prices=prices,
        selected_pivot_finality=CONFIRMED_PIVOT_FINALITY if available else None,
        replay_point_id=event.replay_point_id,
        content_id=event.content_id,
        source_id=event.source_id,
        checkpoint_id=event.checkpoint_id,
        frozen_slope=slope,
        frozen_intercept=intercept,
    )


@pytest.fixture(scope="module")
def real_d4_context(tmp_path_factory):
    result = d4_script.run_study(
        source_root=Path.cwd() / d4_script.d3_script.SOURCE_ROOT,
        output_root=tmp_path_factory.mktemp("l2d4a") / "output",
    )
    return SimpleNamespace(**result)


def _tampered_bundle(bundle, **changes):
    changes.setdefault("baseline_comparison_bundle_id", "")
    return replace(bundle, **changes)


def _validate(bundle, context):
    validate_baseline_comparison_bundle(
        bundle,
        prepared=context.prepared,
        replay=context.replay,
        structural_stability_bundle=context.d2_bundle,
        interaction_bundle=context.d3_bundle,
        study_config=context.study_config,
    )


def test_only_frozen_deterministic_baselines_are_accepted():
    study = d4_script._study_config()
    assert tuple(spec.kind for spec in _approved_specs(study)) == (
        TrendlineAdequacyBaselineKind.RECENT_EXTREMA,
        TrendlineAdequacyBaselineKind.HORIZONTAL_SUPPORT_RESISTANCE,
    )
    random_spec = TrendlineAdequacyBaselineSpec(
        name="random",
        kind=TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR,
        repetitions=1,
        preserves=("timeframe",),
        seed=7,
    )
    with pytest.raises(TrendlineBaselineComparisonError):
        _approved_specs(replace(study, baseline_specs=(random_spec, study.baseline_specs[1])))


def test_support_selects_low_pivots():
    spec = _interaction_spec((1,))
    event = _event(spec, role="support")
    selection = _selection_from_pivots(
        d4_script._study_config().baseline_specs[0],
        event,
        _point(event),
        (_pivot(event, "high", 3, 20.0), _pivot(event, "low", 4, 9.0), _pivot(event, "low", 8, 10.0)),
    )
    assert selection.selected_pivot_positions == (4, 8)


def test_resistance_selects_high_pivots():
    spec = _interaction_spec((1,))
    event = _event(spec, role="resistance")
    selection = _selection_from_pivots(
        d4_script._study_config().baseline_specs[0],
        event,
        _point(event),
        (_pivot(event, "low", 3, 9.0), _pivot(event, "high", 4, 20.0), _pivot(event, "high", 8, 21.0)),
    )
    assert selection.selected_pivot_prices == (20.0, 21.0)


def test_recent_extrema_geometry_is_exact():
    spec = _interaction_spec((1,))
    event = _event(spec, role="support")
    selection = _selection_from_pivots(
        d4_script._study_config().baseline_specs[0],
        event,
        _point(event),
        (_pivot(event, "low", 2, 8.0), _pivot(event, "low", 6, 10.0)),
    )
    assert selection.frozen_slope == 0.5
    assert selection.frozen_intercept == 7.0


def test_horizontal_geometry_has_zero_slope():
    spec = _interaction_spec((1,))
    event = _event(spec)
    selection = _selection_from_pivots(
        d4_script._study_config().baseline_specs[1],
        event,
        _point(event),
        (_pivot(event, "low", 8, 10.0),),
    )
    assert selection.frozen_slope == 0.0
    assert selection.frozen_intercept == 10.0


def test_pivot_positions_must_precede_selection():
    spec = _interaction_spec((1,))
    event = _event(spec)
    with pytest.raises(TrendlineBaselineComparisonError):
        _validate_pivot_row(_pivot(event, "low", event.selection_position, 10.0), event, _point(event))


def test_pivot_finality_must_be_confirmed_append_only():
    spec = _interaction_spec((1,))
    event = _event(spec)
    with pytest.raises(TrendlineBaselineComparisonError):
        _validate_pivot_row(
            _pivot(event, "low", 4, 10.0, finality="retrospective_revising"),
            event,
            _point(event),
        )


def test_pivot_rows_bind_selection_replay_point():
    spec = _interaction_spec((1,))
    event = _event(spec)
    tampered = replace(_pivot(event, "low", 4, 10.0), content_id="b" * 64)
    with pytest.raises(TrendlineBaselineComparisonError):
        _validate_pivot_row(tampered, event, _point(event))


def test_insufficient_recent_extrema_is_typed_abstention():
    spec = _interaction_spec((1,))
    event = _event(spec)
    selection = _selection_from_pivots(
        d4_script._study_config().baseline_specs[0],
        event,
        _point(event),
        (_pivot(event, "low", 8, 10.0),),
    )
    assert not selection.available
    assert selection.reason == "insufficient_same_role_pivots"


def test_missing_horizontal_pivot_is_typed_abstention():
    spec = _interaction_spec((1,))
    event = _event(spec)
    selection = _selection_from_pivots(
        d4_script._study_config().baseline_specs[1],
        event,
        _point(event),
        (_pivot(event, "high", 8, 20.0),),
    )
    assert not selection.available
    assert selection.selected_pivot_positions == ()


def test_abstention_creates_no_baseline_outcome():
    spec = _interaction_spec((1,))
    event = _event(spec)
    selection = _selection(event, TrendlineAdequacyBaselineKind.RECENT_EXTREMA, available=False)
    assert build_baseline_outcomes((selection,), SimpleNamespace(), spec) == ()


def test_one_selection_attempt_exists_per_model_event_and_baseline(real_d4_context):
    assert len(real_d4_context.comparison_bundle.baseline_selections) == 43 * 2
    assert len({(value.baseline_id, value.model_event_id) for value in real_d4_context.comparison_bundle.baseline_selections}) == 86


def test_baseline_selection_preserves_model_coordinate_and_provenance(real_d4_context):
    event = real_d4_context.d3_bundle.events[0]
    selection = next(
        value
        for value in real_d4_context.comparison_bundle.baseline_selections
        if value.model_event_id == event.event_id
    )
    assert selection.timeframe == event.timeframe
    assert selection.role == event.role
    assert selection.selection_position == event.selection_position
    assert selection.selection_available_at == event.selection_available_at
    assert selection.selection_atr == event.selection_atr
    assert selection.replay_point_id == event.replay_point_id


def test_baseline_geometry_is_frozen_after_selection():
    spec = _interaction_spec((1,))
    event = _event(spec)
    selection = _selection(event, TrendlineAdequacyBaselineKind.HORIZONTAL_SUPPORT_RESISTANCE)
    assert selection.frozen_slope == 0.0
    assert selection.frozen_intercept == 10.0


def test_baseline_outcomes_reuse_d3_semantics(real_d4_context):
    selection = next(
        value
        for value in real_d4_context.comparison_bundle.baseline_selections
        if value.available
    )
    outcome = next(
        value
        for value in real_d4_context.comparison_bundle.baseline_outcomes
        if value.interaction_event_id == selection.baseline_selection_id
    )
    assert outcome.horizon_bars in real_d4_context.interaction_spec.evaluation_horizons_bars
    assert outcome.horizon_end_position == selection.selection_position + outcome.horizon_bars


def test_d3_bundle_identity_remains_unchanged_after_helper_extraction(real_d4_context):
    assert real_d4_context.d3_bundle.interaction_utility_bundle_id == d4_script.EXPECTED_D3_BUNDLE_ID


def test_summary_helper_rejects_duplicate_missing_event_horizon_coordinate():
    spec = _interaction_spec((1,))
    event_a = _event(spec, selection_position=10)
    event_b = _event(spec, selection_position=11)

    def right_censored(event):
        return TrendlineInteractionOutcome(
            interaction_event_id=event.event_id,
            horizon_bars=1,
            horizon_end_position=event.selection_position + 1,
            right_censored=True,
            first_touch_position=None,
            first_touch_latency_bars=None,
            first_touch_projected_level=None,
            first_touch_penetration_atr=None,
            defended_touch=None,
            wick_rejection=None,
            first_adverse_close_position=None,
            break_status="none",
            favourable_excursion_atr=None,
            adverse_excursion_atr=None,
        )

    with pytest.raises(TrendlineInteractionUtilityError):
        build_interaction_summaries(
            {
                event_a.event_id: (event_a.timeframe, event_a.role),
                event_b.event_id: (event_b.timeframe, event_b.role),
            },
            (right_censored(event_a), right_censored(event_a)),
            ("1h",),
            spec,
        )


def test_d4_bundle_exposes_explicit_interaction_spec_id(real_d4_context):
    bundle = real_d4_context.comparison_bundle
    payload = json.loads(
        real_d4_context.paths["baseline_comparison_bundle"].read_text()
    )
    assert bundle.interaction_spec_id == bundle.interaction_spec.interaction_spec_id
    assert payload["interaction_spec_id"] == bundle.interaction_spec_id


def test_d4_interaction_spec_id_matches_d3(real_d4_context):
    assert (
        real_d4_context.comparison_bundle.interaction_spec_id
        == real_d4_context.d3_bundle.interaction_spec_id
    )


def test_manifest_comparison_summaries_match_bundle(real_d4_context):
    manifest = json.loads(real_d4_context.paths["run_manifest"].read_text())
    bundle = json.loads(
        real_d4_context.paths["baseline_comparison_bundle"].read_text()
    )
    expected = [
        summary.to_dict()
        for summary in real_d4_context.comparison_bundle.comparison_summaries
    ]
    assert manifest["comparison_summary_count"] == 16
    assert manifest["comparison_summaries"] == expected
    assert manifest["comparison_summaries"] == bundle["comparison_summaries"]


def test_matched_model_summaries_exclude_baseline_abstentions(real_d4_context):
    for summary in real_d4_context.comparison_bundle.comparison_summaries:
        assert summary.model_summary.event_count == summary.baseline_available_count
        assert summary.baseline_summary.event_count == summary.baseline_available_count


def test_support_and_resistance_summaries_remain_separate(real_d4_context):
    coordinates = {
        (value.role, value.horizon_bars)
        for value in real_d4_context.comparison_bundle.comparison_summaries
    }
    assert ("support", 1) in coordinates
    assert ("resistance", 1) in coordinates


def test_horizons_remain_separate(real_d4_context):
    assert {value.horizon_bars for value in real_d4_context.comparison_bundle.comparison_summaries} == {1, 3, 6, 12}


def test_baseline_coverage_rate_uses_event_denominator(real_d4_context):
    for value in real_d4_context.comparison_bundle.comparison_summaries:
        expected = value.baseline_available_count / value.model_event_count
        assert value.baseline_coverage_rate == expected


def test_undefined_statistic_delta_is_none():
    assert _optional_delta(None, 0.5) is None
    assert _optional_delta(0.5, None) is None


def test_model_minus_baseline_delta_sign_is_correct():
    assert _optional_delta(0.75, 0.25) == 0.5
    assert _optional_delta(0.25, 0.75) == -0.5


def test_no_composite_winner_metric_exists(real_d4_context):
    assert all(not hasattr(value, "winner") for value in real_d4_context.comparison_bundle.comparison_summaries)
    assert all("winner" not in value.to_dict() for value in real_d4_context.comparison_bundle.comparison_summaries)


def test_tampered_selected_pivot_is_rejected(real_d4_context):
    original = next(value for value in real_d4_context.comparison_bundle.baseline_selections if value.available)
    tampered = replace(
        original,
        selected_pivot_prices=(original.selected_pivot_prices[0] + 1.0, *original.selected_pivot_prices[1:]),
        baseline_selection_id="",
    )
    selections = tuple(tampered if value is original else value for value in real_d4_context.comparison_bundle.baseline_selections)
    with pytest.raises(TrendlineBaselineComparisonError):
        _validate(_tampered_bundle(real_d4_context.comparison_bundle, baseline_selections=selections), real_d4_context)


def test_tampered_baseline_geometry_is_rejected(real_d4_context):
    original = next(value for value in real_d4_context.comparison_bundle.baseline_selections if value.available)
    tampered = replace(original, frozen_intercept=original.frozen_intercept + 1.0, baseline_selection_id="")
    selections = tuple(tampered if value is original else value for value in real_d4_context.comparison_bundle.baseline_selections)
    with pytest.raises(TrendlineBaselineComparisonError):
        _validate(_tampered_bundle(real_d4_context.comparison_bundle, baseline_selections=selections), real_d4_context)


def test_tampered_baseline_outcome_is_rejected(real_d4_context):
    original = next(
        value
        for value in real_d4_context.comparison_bundle.baseline_outcomes
        if value.first_touch_position is not None
    )
    tampered = replace(original, first_touch_projected_level=999.0, outcome_id="")
    outcomes = tuple(tampered if value is original else value for value in real_d4_context.comparison_bundle.baseline_outcomes)
    with pytest.raises(TrendlineBaselineComparisonError):
        _validate(_tampered_bundle(real_d4_context.comparison_bundle, baseline_outcomes=outcomes), real_d4_context)


def test_tampered_comparison_delta_is_rejected(real_d4_context):
    original = real_d4_context.comparison_bundle.comparison_summaries[0]
    tampered = replace(original, touch_rate_delta=0.123, comparison_summary_id="")
    summaries = tuple(tampered if value is original else value for value in real_d4_context.comparison_bundle.comparison_summaries)
    with pytest.raises(TrendlineBaselineComparisonError):
        _validate(_tampered_bundle(real_d4_context.comparison_bundle, comparison_summaries=summaries), real_d4_context)


def test_d2_identity_mismatch_is_rejected(real_d4_context):
    with pytest.raises(TrendlineBaselineComparisonError):
        _validate(_tampered_bundle(real_d4_context.comparison_bundle, structural_stability_bundle_id="b" * 64), real_d4_context)


def test_d3_identity_mismatch_is_rejected(real_d4_context):
    with pytest.raises(TrendlineBaselineComparisonError):
        _validate(_tampered_bundle(real_d4_context.comparison_bundle, interaction_utility_bundle_id="b" * 64), real_d4_context)


def test_missing_or_duplicate_event_baseline_selection_is_rejected(real_d4_context):
    first = real_d4_context.comparison_bundle.baseline_selections[0]
    selections = (first,) + real_d4_context.comparison_bundle.baseline_selections[:-1]
    with pytest.raises(TrendlineBaselineComparisonError):
        _validate(_tampered_bundle(real_d4_context.comparison_bundle, baseline_selections=selections), real_d4_context)


def test_baseline_generation_contains_no_model_fit_signal_or_provider_execution():
    source = inspect.getsource(d4_module)
    assert "fit_trendlines" not in source
    assert "Binance" not in source
    assert "provider" not in source.lower()
    assert "signal_output" not in source


def test_bundle_identity_is_content_addressed(real_d4_context):
    bundle = real_d4_context.comparison_bundle
    assert bundle.baseline_comparison_bundle_id == bundle.__class__(
        dataset_id=bundle.dataset_id,
        replay_id=bundle.replay_id,
        cohort_id=bundle.cohort_id,
        study_config_id=bundle.study_config_id,
        structural_stability_bundle_id=bundle.structural_stability_bundle_id,
        interaction_utility_bundle_id=bundle.interaction_utility_bundle_id,
        interaction_spec=bundle.interaction_spec,
        baseline_specs=bundle.baseline_specs,
        model_event_ids=bundle.model_event_ids,
        baseline_selections=bundle.baseline_selections,
        baseline_outcomes=bundle.baseline_outcomes,
        model_summaries=bundle.model_summaries,
        baseline_summaries=bundle.baseline_summaries,
        comparison_summaries=bundle.comparison_summaries,
    ).baseline_comparison_bundle_id
