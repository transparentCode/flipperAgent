"""Focused contracts and causal checks for L2-D4B."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from libs.models.trendlines.workflows.research.adequacy import (
    STOCHASTIC_NULL_KINDS,
    TrendlineAdequacyBaselineKind,
    TrendlineAdequacyBaselineSpec,
    TrendlineStochasticNullComparisonError,
    build_stochastic_null_selections,
    derive_stochastic_draw_id,
    measure_frozen_geometry_outcomes,
    transport_density_matched_geometry,
    validate_stochastic_null_comparison_bundle,
)
from libs.models.trendlines.workflows.research.adequacy.stochastic_null_comparison import (
    _approved_stochastic_specs,
    _density_donors,
    _quantiles,
    _role_pivot_pairs,
    _selection_from_random_pair,
)
from libs.models.trendlines.workflows.research.diagnostics import inspect_replay_pivots
from scripts import analyze_trendlines_l2d4b_seeded_nulls as d4b_script


ROOT = Path.cwd()


def _one_rep_specs():
    return tuple(
        replace(spec, repetitions=1)
        for spec in d4b_script._stochastic_specs()
    )


@pytest.fixture(scope="module")
def study_result(tmp_path_factory):
    output_root = tmp_path_factory.mktemp("l2d4b") / "output"
    return SimpleNamespace(
        **d4b_script.run_study(output_root=output_root),
    )


@pytest.fixture(scope="module")
def one_rep_selections(study_result):
    return build_stochastic_null_selections(
        study_result.prepared,
        study_result.replay,
        study_result.d3_bundle,
        _one_rep_specs(),
    )


def _events(result):
    return {event.event_id: event for event in result.d3_bundle.events}


def _selection(result, *, kind, available=None):
    values = tuple(
        row
        for row in result.bundle.stochastic_selections
        if row.baseline_kind is kind
        and (available is None or row.available is available)
    )
    return values[0]


def _tampered_bundle(bundle, **changes):
    changes.setdefault("stochastic_null_comparison_bundle_id", "")
    return replace(bundle, **changes)


def _validate(bundle, result):
    validate_stochastic_null_comparison_bundle(
        bundle,
        prepared=result.prepared,
        replay=result.replay,
        structural_stability_bundle=result.d2_bundle,
        interaction_bundle=result.d3_bundle,
        deterministic_baseline_bundle=result.d4a_bundle,
        study_config=result.study_config,
    )


def test_only_authorised_stochastic_kinds_are_accepted():
    specs = _approved_stochastic_specs(d4b_script._stochastic_specs())
    assert tuple(spec.kind for spec in specs) == STOCHASTIC_NULL_KINDS


def test_seed_must_be_explicit_non_boolean_integer():
    with pytest.raises(ValueError):
        TrendlineAdequacyBaselineSpec(
            name="bad",
            kind=TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR,
            repetitions=1,
            seed=True,
            preserves=("timeframe",),
        )


def test_repetition_count_is_explicit(one_rep_selections):
    assert len(one_rep_selections) == 43 * 2


def test_draw_identity_is_deterministic():
    assert derive_stochastic_draw_id("a" * 64, 7, 2, "b" * 64) == derive_stochastic_draw_id(
        "a" * 64,
        7,
        2,
        "b" * 64,
    )


def test_draw_changes_with_baseline_seed_repetition_or_event():
    base = derive_stochastic_draw_id("a" * 64, 7, 2, "b" * 64)
    assert base != derive_stochastic_draw_id("c" * 64, 7, 2, "b" * 64)
    assert base != derive_stochastic_draw_id("a" * 64, 8, 2, "b" * 64)
    assert base != derive_stochastic_draw_id("a" * 64, 7, 3, "b" * 64)
    assert base != derive_stochastic_draw_id("a" * 64, 7, 2, "c" * 64)


def test_random_pair_uses_same_role_pivots(study_result):
    events = _events(study_result)
    row = next(
        row
        for row in study_result.bundle.stochastic_selections
        if row.baseline_kind is TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR
        and row.available
        and events[row.model_event_id].role == "support"
    )
    event = events[row.model_event_id]
    pivots = inspect_replay_pivots(
        study_result.prepared,
        study_result.replay,
        timeframe=event.timeframe,
        position=event.selection_position,
    )
    expected_role = "low" if event.role == "support" else "high"
    selected = set(row.selected_pivot_positions)
    assert selected
    assert all(
        pivot.pivot_role == expected_role and pivot.bar_position in selected
        for pivot in pivots
        if pivot.bar_position in selected
    )


def test_random_pair_pivots_are_prior_to_selection(study_result):
    events = _events(study_result)
    for row in study_result.bundle.stochastic_selections:
        if row.baseline_kind is TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR:
            assert all(position < events[row.model_event_id].selection_position for position in row.selected_pivot_positions)


def test_random_pair_selected_pivots_are_append_only(study_result):
    rows = tuple(
        row
        for row in study_result.bundle.stochastic_selections
        if row.baseline_kind is TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR
        and row.available
    )
    assert rows
    assert {row.selected_pivot_finality for row in rows} == {"confirmed_append_only"}


def test_random_pair_candidate_order_is_deterministic(study_result):
    row = _selection(
        study_result,
        kind=TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR,
        available=True,
    )
    event = _events(study_result)[row.model_event_id]
    point = study_result.replay.output_at(event.timeframe, event.selection_position)
    pivots = inspect_replay_pivots(
        study_result.prepared,
        study_result.replay,
        timeframe=event.timeframe,
        position=event.selection_position,
    )
    left = _role_pivot_pairs(pivots, event, row.selection_close)
    right = _role_pivot_pairs(tuple(reversed(pivots)), event, row.selection_close)
    assert left == right
    assert point.replay_point_id == row.replay_point_id


def test_random_support_geometry_is_role_consistent(study_result):
    events = _events(study_result)
    row = next(
        row
        for row in study_result.bundle.stochastic_selections
        if row.baseline_kind is TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR
        and row.available
        and events[row.model_event_id].role == "support"
    )
    event = events[row.model_event_id]
    level = row.frozen_slope * event.selection_position + row.frozen_intercept
    assert level <= row.selection_close


def test_random_resistance_geometry_is_role_consistent(study_result):
    events = _events(study_result)
    row = next(
        row
        for row in study_result.bundle.stochastic_selections
        if row.baseline_kind is TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR
        and row.available
        and events[row.model_event_id].role == "resistance"
    )
    event = events[row.model_event_id]
    level = row.frozen_slope * event.selection_position + row.frozen_intercept
    assert level >= row.selection_close


def test_empty_random_candidate_pool_abstains(study_result):
    event = study_result.d3_bundle.events[0]
    point = study_result.replay.output_at(event.timeframe, event.selection_position)
    spec = _one_rep_specs()[0]
    row = _selection_from_random_pair(
        spec,
        event,
        point,
        100.0,
        0,
        derive_stochastic_draw_id(spec.baseline_id, spec.seed, 0, event.event_id),
        (),
    )
    assert not row.available
    assert row.reason == "no_valid_same_role_pivot_pair"


def test_density_donor_preserves_role_and_timeframe(study_result):
    events = _events(study_result)
    row = _selection(
        study_result,
        kind=TrendlineAdequacyBaselineKind.DENSITY_MATCHED_NULL,
        available=True,
    )
    event = events[row.model_event_id]
    donor = events[row.donor_event_id]
    assert donor.timeframe == event.timeframe
    assert donor.role == event.role


def test_density_donor_is_strictly_prior(study_result):
    events = _events(study_result)
    for row in study_result.bundle.stochastic_selections:
        if row.baseline_kind is TrendlineAdequacyBaselineKind.DENSITY_MATCHED_NULL and row.available:
            event = events[row.model_event_id]
            donor = events[row.donor_event_id]
            assert donor.selection_position < event.selection_position
            assert donor.selection_available_at < event.selection_available_at


def test_density_donor_excludes_current_simultaneous_and_future(study_result):
    events = tuple(study_result.d3_bundle.events)
    first = min(events, key=lambda event: (event.selection_position, event.event_id))
    assert not _density_donors(first, events)
    later = max(events, key=lambda event: (event.selection_position, event.event_id))
    donors = _density_donors(later, events)
    assert all(
        donor.selection_position < later.selection_position
        and donor.selection_available_at < later.selection_available_at
        for donor in donors
    )


def test_first_same_role_event_abstains_density(study_result):
    rows = tuple(
        row
        for row in study_result.bundle.stochastic_selections
        if row.baseline_kind is TrendlineAdequacyBaselineKind.DENSITY_MATCHED_NULL
    )
    assert any(not row.available for row in rows)
    assert {row.reason for row in rows if not row.available} == {"no_prior_same_role_donor"}


def test_density_support_transport_is_exact(study_result):
    events = _events(study_result)
    row = next(
        row
        for row in study_result.bundle.stochastic_selections
        if row.baseline_kind is TrendlineAdequacyBaselineKind.DENSITY_MATCHED_NULL
        and row.available
        and events[row.model_event_id].role == "support"
    )
    event = events[row.model_event_id]
    donor = events[row.donor_event_id]
    values = transport_density_matched_geometry(
        event,
        donor,
        current_selection_close=row.selection_close,
        donor_selection_close=row.donor_selection_close,
    )
    assert values[0] == row.frozen_slope
    assert values[1] == row.frozen_intercept
    assert values[3] == row.normalised_donor_distance


def test_density_resistance_transport_is_exact(study_result):
    events = _events(study_result)
    row = next(
        row
        for row in study_result.bundle.stochastic_selections
        if row.baseline_kind is TrendlineAdequacyBaselineKind.DENSITY_MATCHED_NULL
        and row.available
        and events[row.model_event_id].role == "resistance"
    )
    event = events[row.model_event_id]
    donor = events[row.donor_event_id]
    values = transport_density_matched_geometry(
        event,
        donor,
        current_selection_close=row.selection_close,
        donor_selection_close=row.donor_selection_close,
    )
    assert values[0] == row.frozen_slope
    assert values[1] == row.frozen_intercept
    assert values[3] == row.normalised_donor_distance


def test_density_transport_normalises_slope_by_donor_atr(study_result):
    row = _selection(
        study_result,
        kind=TrendlineAdequacyBaselineKind.DENSITY_MATCHED_NULL,
        available=True,
    )
    assert row.normalised_donor_slope == row.donor_frozen_slope / row.donor_selection_atr


def test_density_transport_uses_current_close_and_atr(study_result):
    events = _events(study_result)
    row = _selection(
        study_result,
        kind=TrendlineAdequacyBaselineKind.DENSITY_MATCHED_NULL,
        available=True,
    )
    event = events[row.model_event_id]
    donor = events[row.donor_event_id]
    shifted = transport_density_matched_geometry(
        event,
        donor,
        current_selection_close=row.selection_close + 1.0,
        donor_selection_close=row.donor_selection_close,
    )
    original = transport_density_matched_geometry(
        event,
        donor,
        current_selection_close=row.selection_close,
        donor_selection_close=row.donor_selection_close,
    )
    assert shifted[6] == original[6] + 1.0


def test_selection_product_has_one_row_per_event_baseline_repetition(study_result):
    coordinates = {
        (row.baseline_id, row.repetition_index, row.model_event_id)
        for row in study_result.bundle.stochastic_selections
    }
    assert len(coordinates) == 43 * 2 * 32


def test_abstentions_create_no_outcomes(study_result):
    selection_ids = {
        row.selection_id
        for row in study_result.bundle.stochastic_selections
        if not row.available
    }
    outcome_ids = {row.interaction_event_id for row in study_result.bundle.null_outcomes}
    assert not selection_ids & outcome_ids


def test_available_selections_have_one_outcome_per_horizon(study_result):
    counts = {}
    for row in study_result.bundle.null_outcomes:
        counts[row.interaction_event_id] = counts.get(row.interaction_event_id, 0) + 1
    assert counts
    assert set(counts.values()) == {4}


def test_null_outcomes_reuse_d3_semantics(study_result):
    events = _events(study_result)
    selection = _selection(
        study_result,
        kind=TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR,
        available=True,
    )
    event = events[selection.model_event_id]
    expected = measure_frozen_geometry_outcomes(
        interaction_event_id=selection.selection_id,
        role=selection.role,
        selection_position=selection.selection_position,
        selection_available_at=selection.selection_available_at,
        selection_atr=selection.selection_atr,
        frozen_slope=selection.frozen_slope,
        frozen_intercept=selection.frozen_intercept,
        frame=study_result.prepared.dataset.frames[event.timeframe],
        interaction_spec=study_result.interaction_spec,
    )
    actual = tuple(
        row
        for row in study_result.bundle.null_outcomes
        if row.interaction_event_id == selection.selection_id
    )
    assert tuple(row.to_dict() for row in actual) == tuple(row.to_dict() for row in expected)


def test_matched_summaries_exclude_null_abstentions(study_result):
    for row in study_result.bundle.repetition_comparisons:
        assert row.model_summary.event_count == row.available_null_selection_count
        assert row.null_summary.event_count == row.available_null_selection_count


def test_support_and_resistance_summaries_remain_separate(study_result):
    assert {row.role for row in study_result.bundle.repetition_comparisons} == {"support", "resistance"}
    assert {row.role for row in study_result.bundle.distribution_summaries} == {"support", "resistance"}


def test_horizons_remain_separate(study_result):
    assert {row.horizon_bars for row in study_result.bundle.repetition_comparisons} == {1, 3, 6, 12}


def test_repetition_delta_is_model_minus_null(study_result):
    row = next(
        row
        for row in study_result.bundle.repetition_comparisons
        if row.touch_rate_delta is not None
    )
    assert row.touch_rate_delta == row.model_summary.touch_rate - row.null_summary.touch_rate


def test_undefined_statistic_produces_none_delta():
    from libs.models.trendlines.workflows.research.adequacy.stochastic_null_comparison import _optional_delta

    assert _optional_delta(None, 1.0) is None
    assert _optional_delta(1.0, None) is None


def test_quantile_interpolation_is_exact():
    assert _quantiles((0.0, 10.0)) == (0.5, 9.5)


def test_undefined_repetitions_are_counted_separately(study_result):
    for row in study_result.bundle.distribution_summaries:
        assert row.defined_repetition_count + row.undefined_repetition_count == 32


def test_distribution_sign_counts_are_exact(study_result):
    for row in study_result.bundle.distribution_summaries:
        assert (
            row.negative_delta_count
            + row.zero_delta_count
            + row.positive_delta_count
            == row.defined_repetition_count
        )


def test_changed_seed_changes_bundle_identity(study_result):
    changed = tuple(
        replace(spec, seed=spec.seed + 1)
        for spec in study_result.bundle.stochastic_baseline_specs
    )
    changed_bundle = replace(
        study_result.bundle,
        stochastic_baseline_specs=changed,
        stochastic_null_comparison_bundle_id="",
    )
    assert changed_bundle.stochastic_null_comparison_bundle_id != study_result.bundle.stochastic_null_comparison_bundle_id


def test_changed_repetition_count_changes_bundle_identity(study_result):
    changed = tuple(
        replace(spec, repetitions=spec.repetitions - 1)
        for spec in study_result.bundle.stochastic_baseline_specs
    )
    changed_bundle = replace(
        study_result.bundle,
        stochastic_baseline_specs=changed,
        stochastic_null_comparison_bundle_id="",
    )
    assert changed_bundle.stochastic_null_comparison_bundle_id != study_result.bundle.stochastic_null_comparison_bundle_id


def test_reordered_event_inputs_reproduce_identical_selection_evidence(study_result):
    reversed_bundle = replace(
        study_result.d3_bundle,
        events=tuple(reversed(study_result.d3_bundle.events)),
        interaction_utility_bundle_id="",
    )
    left = build_stochastic_null_selections(
        study_result.prepared,
        study_result.replay,
        study_result.d3_bundle,
        _one_rep_specs(),
    )
    right = build_stochastic_null_selections(
        study_result.prepared,
        study_result.replay,
        reversed_bundle,
        _one_rep_specs(),
    )
    assert tuple(row.to_dict() for row in left) == tuple(row.to_dict() for row in right)


def test_tampered_draw_index_is_rejected(study_result):
    row = next(
        row
        for row in study_result.bundle.stochastic_selections
        if row.available and row.candidate_count > 1
    )
    tampered = replace(
        row,
        selected_candidate_index=(row.selected_candidate_index + 1) % row.candidate_count,
        selection_id="",
    )
    rows = tuple(tampered if value.selection_id == row.selection_id else value for value in study_result.bundle.stochastic_selections)
    with pytest.raises(TrendlineStochasticNullComparisonError):
        _validate(_tampered_bundle(study_result.bundle, stochastic_selections=rows), study_result)


def test_tampered_pivot_selection_is_rejected(study_result):
    row = next(
        row
        for row in study_result.bundle.stochastic_selections
        if row.baseline_kind is TrendlineAdequacyBaselineKind.RANDOM_VALID_PIVOT_PAIR
        and row.available
    )
    tampered = replace(
        row,
        selected_pivot_prices=(row.selected_pivot_prices[0] + 1.0, row.selected_pivot_prices[1]),
        selection_id="",
    )
    rows = tuple(tampered if value.selection_id == row.selection_id else value for value in study_result.bundle.stochastic_selections)
    with pytest.raises(TrendlineStochasticNullComparisonError):
        _validate(_tampered_bundle(study_result.bundle, stochastic_selections=rows), study_result)


def test_tampered_donor_event_is_rejected(study_result):
    row = next(
        row
        for row in study_result.bundle.stochastic_selections
        if row.baseline_kind is TrendlineAdequacyBaselineKind.DENSITY_MATCHED_NULL
        and row.available
    )
    tampered = replace(row, donor_event_id="f" * 64, selection_id="")
    rows = tuple(tampered if value.selection_id == row.selection_id else value for value in study_result.bundle.stochastic_selections)
    with pytest.raises(TrendlineStochasticNullComparisonError):
        _validate(_tampered_bundle(study_result.bundle, stochastic_selections=rows), study_result)


def test_tampered_transported_geometry_is_rejected(study_result):
    row = _selection(
        study_result,
        kind=TrendlineAdequacyBaselineKind.DENSITY_MATCHED_NULL,
        available=True,
    )
    tampered = replace(row, frozen_intercept=row.frozen_intercept + 1.0, selection_id="")
    rows = tuple(tampered if value.selection_id == row.selection_id else value for value in study_result.bundle.stochastic_selections)
    with pytest.raises(TrendlineStochasticNullComparisonError):
        _validate(_tampered_bundle(study_result.bundle, stochastic_selections=rows), study_result)


def test_tampered_null_outcome_is_rejected(study_result):
    row = study_result.bundle.null_outcomes[0]
    tampered = replace(
        row,
        horizon_end_position=row.horizon_end_position + 1,
        outcome_id="",
    )
    outcomes = tuple(tampered if value.outcome_id == row.outcome_id else value for value in study_result.bundle.null_outcomes)
    with pytest.raises(TrendlineStochasticNullComparisonError):
        _validate(_tampered_bundle(study_result.bundle, null_outcomes=outcomes), study_result)


def test_tampered_repetition_delta_is_rejected(study_result):
    row = study_result.bundle.repetition_comparisons[0]
    value = row.touch_rate_delta or 0.0
    with pytest.raises(TrendlineStochasticNullComparisonError):
        replace(row, touch_rate_delta=value + 1.0, comparison_id="")


def test_tampered_distribution_statistic_is_rejected(study_result):
    row = next(
        row
        for row in study_result.bundle.distribution_summaries
        if row.mean_delta is not None
    )
    tampered = replace(row, mean_delta=row.mean_delta + 1.0, distribution_id="")
    distributions = tuple(tampered if item.distribution_id == row.distribution_id else item for item in study_result.bundle.distribution_summaries)
    with pytest.raises(TrendlineStochasticNullComparisonError):
        _validate(_tampered_bundle(study_result.bundle, distribution_summaries=distributions), study_result)


def test_d2_identity_mismatch_is_rejected(study_result):
    with pytest.raises(TrendlineStochasticNullComparisonError):
        _validate(_tampered_bundle(study_result.bundle, structural_stability_bundle_id="b" * 64), study_result)


def test_d3_identity_mismatch_is_rejected(study_result):
    with pytest.raises(TrendlineStochasticNullComparisonError):
        _validate(_tampered_bundle(study_result.bundle, interaction_utility_bundle_id="b" * 64), study_result)


def test_d4a_identity_mismatch_is_rejected(study_result):
    with pytest.raises(TrendlineStochasticNullComparisonError):
        _validate(_tampered_bundle(study_result.bundle, baseline_comparison_bundle_id="b" * 64), study_result)


def test_no_model_or_provider_execution_is_embedded():
    source = Path(
        "src/libs/models/trendlines/workflows/research/adequacy/"
        "stochastic_null_comparison.py"
    ).read_text(encoding="utf-8")
    assert "run_causal_replay" not in source
    assert "BinanceNativeAdapter" not in source
    assert "provider" not in source.lower()
