"""Focused frozen-contract tests for final D5D disposition."""

from dataclasses import replace
import hashlib

import pytest

from libs.models.trendlines.workflows.research.adequacy.final_disposition import (
    FINAL_HORIZONS_BARS,
    FINAL_DECISIVE_NULL,
    FINAL_MEMBER_NAMES,
    TrendlineAdequacyOutcome,
    TrendlineFinalDispositionError,
    TrendlineFinalRecommendedAction,
    build_decision_matrix,
    build_final_cohort_evidence,
    build_final_disposition_bundle,
    build_final_disposition_protocol,
    classify_null_cell,
    classify_null_cells,
    validate_final_disposition_bundle,
)


def _id(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _protocol():
    return build_final_disposition_protocol(
        d5a_source_matrix_bundle_id=_id("d5a"),
        d5b_replication_protocol_id=_id("d5b-protocol"),
        d5b_replication_bundle_id=_id("d5b"),
        d5c_sensitivity_protocol_id=_id("d5c-protocol"),
        d5c_sensitivity_bundle_id=_id("d5c"),
    )


def _cells(*, robust: bool, baseline_id: str):
    rows = []
    for role in ("support", "resistance"):
        for horizon in FINAL_HORIZONS_BARS:
            if robust:
                mean, q05, q95 = 0.2, 0.1, 0.3
                classification = "ROBUST_POSITIVE"
            else:
                mean, q05, q95 = 0.0, -0.1, 0.1
                classification = "WEAK_OR_MIXED"
            rows.append(
                {
                    "baseline_id": baseline_id,
                    "baseline_name": "test-null",
                    "role": role,
                    "horizon_bars": horizon,
                    "mean_delta": mean,
                    "q05_delta": q05,
                    "q95_delta": q95,
                    "classification": classification,
                }
            )
    return rows


def _cohort(name: str, *, robust_random: bool, robust_density: bool, parameter_robust: bool, structural="OBSERVED_NONTRIVIAL_STRUCTURE"):
    random_id = _id(f"{name}-random")
    density_id = _id(f"{name}-density")
    variant_density_rows = [
        {
            "baseline_kind": "density_matched_null",
            "metric": "touch_rate",
            "role": role,
            "horizon_bars": horizon,
            "mean_delta": 0.2 if robust_density else 0.0,
            "q05_delta": 0.1 if robust_density else -0.1,
            "q95_delta": 0.3 if robust_density else 0.1,
        }
        for role in ("support", "resistance")
        for horizon in FINAL_HORIZONS_BARS
    ]
    variant_overlap = {
        "coarse_event_jaccard": 0.5 if parameter_robust else 0.0,
        "exact_event_jaccard": 0.5 if parameter_robust else 0.0,
    }
    return build_final_cohort_evidence(
        canonical={
            "member_name": name,
            "relation": "reference",
            "asset": "BTCUSDT",
            "timeframe": "1h",
            "canonical_d2_bundle_id": _id(f"{name}-d2"),
            "canonical_d3_bundle_id": _id(f"{name}-d3"),
            "canonical_d4a_bundle_id": _id(f"{name}-d4a"),
            "canonical_d4b_bundle_id": _id(f"{name}-d4b"),
            "d5a_member_spec_id": _id(f"{name}-spec"),
            "d5a_member_evidence_id": _id(f"{name}-evidence"),
            "baseline_member_result_id": _id(f"{name}-result"),
            "d2": {
                "summaries": [
                    {
                        "observation_unit": "boundary_ray",
                        "timeframe": "1h",
                        "mean_active_anchor_count": 2.0,
                        "birth_rate": 0.1,
                        "anchor_persistence_rate": 0.9,
                        "revision_churn_rate": 0.0,
                        "episode_count": 2,
                        "observed_birth_episode_count": 2,
                        "survival": [
                            {"horizon_bars": 1, "eligible_target_count": 2, "survived_count": 2, "survival_rate": 1.0},
                            {"horizon_bars": 3, "eligible_target_count": 2, "survived_count": 1, "survival_rate": 0.5},
                        ],
                    }
                ]
            },
            "d3": {
                "events": [{"event_id": _id(f"{name}-event")}],
                "summaries": [
                    {"role": role, "horizon_bars": horizon, "touch_rate": 0.5}
                    for role in ("support", "resistance")
                    for horizon in FINAL_HORIZONS_BARS
                ],
            },
            "d4a": {
                "comparison_summaries": [
                    {
                        "baseline_id": _id(f"{name}-deterministic"),
                        "baseline_name": "recent-extrema",
                        "role": role,
                        "horizon_bars": horizon,
                        "baseline_coverage_rate": 1.0,
                        "touch_rate_delta": 0.1,
                        "rejection_rate_delta": 0.0,
                    }
                    for role in ("support", "resistance")
                    for horizon in FINAL_HORIZONS_BARS
                    for _ in range(2)
                ]
            },
            "d4b": {
                "distribution_summaries": [
                    {
                        "baseline_id": baseline_id,
                        "baseline_name": baseline_name,
                        "baseline_kind": baseline_kind,
                        "metric": "touch_rate",
                        "role": role,
                        "horizon_bars": horizon,
                        "mean_delta": mean_delta,
                        "q05_delta": q05_delta,
                        "q95_delta": q95_delta,
                    }
                    for baseline_id, baseline_name, baseline_kind, mean_delta, q05_delta, q95_delta in (
                        (random_id, "random-valid-pivot-pair-v1", "random_valid_pivot_pair", 0.2 if robust_random else 0.0, 0.1 if robust_random else -0.1, 0.3 if robust_random else 0.1),
                        (density_id, "causal-density-matched-null-v1", "density_matched_null", 0.2 if robust_density else 0.0, 0.1 if robust_density else -0.1, 0.3 if robust_density else 0.1),
                    )
                    for role in ("support", "resistance")
                    for horizon in FINAL_HORIZONS_BARS
                ]
            },
        },
        dense_capsule={
            "geometry_sensitivity_capsule_id": _id(f"{name}-dense"),
            "member_name": name,
            "variant_id": _id(f"{name}-dense-variant"),
            "event_overlap": variant_overlap,
            "delta_rows": [
                {"stage": "d3", "metric_name": "touch_rate", "role": role, "horizon_bars": horizon, "baseline_value": 0.5, "variant_value": 0.5, "delta": 0.0}
                for role in ("support", "resistance")
                for horizon in FINAL_HORIZONS_BARS
            ],
            "d4b_summaries": variant_density_rows,
        },
        sparse_capsule={
            "geometry_sensitivity_capsule_id": _id(f"{name}-sparse"),
            "member_name": name,
            "variant_id": _id(f"{name}-sparse-variant"),
            "event_overlap": variant_overlap,
            "delta_rows": [
                {"stage": "d3", "metric_name": "touch_rate", "role": role, "horizon_bars": horizon, "baseline_value": 0.5, "variant_value": 0.5, "delta": 0.0}
                for role in ("support", "resistance")
                for horizon in FINAL_HORIZONS_BARS
            ],
            "d4b_summaries": variant_density_rows,
        },
        protocol=_protocol(),
    )


def _cohorts(*, random=True, density=True, robust=True):
    # Build helper rows against protocol created inside _cohort; protocol IDs are fixed.
    return [
        _cohort(name, robust_random=random, robust_density=density, parameter_robust=robust)
        for name in FINAL_MEMBER_NAMES
    ]


def test_null_classification_boundaries_are_exact():
    assert classify_null_cell(0.1, 0.0, 0.2) == "WEAK_OR_MIXED"
    assert classify_null_cell(0.1, 0.01, 0.2) == "ROBUST_POSITIVE"
    assert classify_null_cell(-0.1, -0.2, 0.0) == "WEAK_OR_MIXED"
    assert classify_null_cell(-0.1, -0.2, -0.01) == "ROBUST_NEGATIVE"


def test_null_cells_require_exact_role_horizon_scope():
    rows = _cells(robust=True, baseline_id=_id("x"))[:-1]
    with pytest.raises(TrendlineFinalDispositionError):
        classify_null_cells(rows, protocol=_protocol())


def test_random_and_density_nulls_remain_separate():
    row = _cohort(FINAL_MEMBER_NAMES[0], robust_random=True, robust_density=False, parameter_robust=False)
    assert row.random_member_support is True
    assert row.density_member_support is False


def test_member_support_requires_six_of_eight_cells():
    rows = _cells(robust=True, baseline_id=_id("x"))
    rows[0]["classification"] = "WEAK_OR_MIXED"
    rows[1]["classification"] = "WEAK_OR_MIXED"
    from libs.models.trendlines.workflows.research.adequacy.final_disposition import member_support

    assert member_support(rows, protocol=_protocol()) is True
    rows[2]["classification"] = "WEAK_OR_MIXED"
    assert member_support(rows, protocol=_protocol()) is False


def test_coverage_failure_selects_insufficient_coverage():
    bundle = build_final_disposition_bundle(_protocol(), _cohorts(), evidence_complete=False)
    assert bundle.selected_outcome is TrendlineAdequacyOutcome.INSUFFICIENT_COVERAGE
    assert bundle.recommended_action is TrendlineFinalRecommendedAction.RESTRICT_TO_SUPPORTED_SCOPE


def test_strong_utility_and_sensitivity_selects_adequate():
    bundle = build_final_disposition_bundle(_protocol(), _cohorts())
    assert bundle.selected_outcome is TrendlineAdequacyOutcome.ADEQUATE_FOR_FURTHER_RESEARCH
    assert bundle.recommended_action is TrendlineFinalRecommendedAction.CONTINUE_UNCHANGED_RESEARCH


def test_random_material_density_failure_fragility_selects_null_outcome():
    cohorts = _cohorts(random=True, density=False, robust=False)
    bundle = build_final_disposition_bundle(_protocol(), cohorts)
    assert bundle.selected_outcome is TrendlineAdequacyOutcome.UTILITY_NOT_BETTER_THAN_NAIVE_NULL
    assert bundle.recommended_action is TrendlineFinalRecommendedAction.REDESIGN_GEOMETRY_SELECTION


def test_no_null_support_selects_structural_context_only():
    cohorts = [
        _cohort(name, robust_random=False, robust_density=False, parameter_robust=False)
        for name in FINAL_MEMBER_NAMES
    ]
    bundle = build_final_disposition_bundle(_protocol(), cohorts)
    assert bundle.selected_outcome is TrendlineAdequacyOutcome.STRUCTURALLY_STABLE_BUT_NO_UTILITY


def test_residual_ambiguity_is_last_rule():
    cohorts = [
        _cohort(name, robust_random=False, robust_density=False, parameter_robust=True)
        for name in FINAL_MEMBER_NAMES
    ]
    bundle = build_final_disposition_bundle(_protocol(), cohorts)
    assert bundle.selected_outcome is TrendlineAdequacyOutcome.INCONCLUSIVE_INSUFFICIENT_EVIDENCE
    matrix = build_decision_matrix(_protocol(), cohorts, bundle)
    assert matrix["first_selected_rule"] == "RULE_6_RESIDUAL_AMBIGUITY"


def test_manual_outcome_override_rejected():
    protocol = _protocol()
    cohorts = _cohorts(random=True, density=False, robust=False)
    bundle = build_final_disposition_bundle(protocol, cohorts)
    forged = replace(
        bundle,
        selected_outcome=TrendlineAdequacyOutcome.ADEQUATE_FOR_FURTHER_RESEARCH,
        recommended_action=TrendlineFinalRecommendedAction.CONTINUE_UNCHANGED_RESEARCH,
        final_disposition_bundle_id="",
    )
    with pytest.raises(TrendlineFinalDispositionError):
        validate_final_disposition_bundle(forged, protocol=protocol, cohorts=cohorts)


def test_wrong_cohort_id_and_duplicate_scope_rejected():
    protocol = _protocol()
    cohorts = _cohorts()
    with pytest.raises(TrendlineFinalDispositionError):
        build_final_disposition_bundle(protocol, [cohorts[0], cohorts[0]])
    forged = replace(
        cohorts[0],
        canonical_event_count=cohorts[0].canonical_event_count + 1,
        cohort_evidence_id="",
    )
    assert forged.cohort_evidence_id != cohorts[0].cohort_evidence_id


def test_final_bundle_identity_excludes_paths_and_tests():
    bundle = build_final_disposition_bundle(_protocol(), _cohorts())
    payload = bundle.to_dict()
    assert "path" not in str(payload)
    assert "test" not in str(payload).lower()


def test_protocol_freezes_five_members_roles_horizons_and_hierarchy():
    protocol = _protocol()
    assert protocol.member_names == FINAL_MEMBER_NAMES
    assert protocol.roles == ("support", "resistance")
    assert protocol.horizons_bars == FINAL_HORIZONS_BARS
    assert protocol.outcome_hierarchy[0] == "insufficient_coverage"
    with pytest.raises(TrendlineFinalDispositionError):
        replace(protocol, member_names=FINAL_MEMBER_NAMES[:-1])


def test_sensitivity_classification_requires_coarse_overlap():
    fragile = _cohort(
        FINAL_MEMBER_NAMES[0],
        robust_random=False,
        robust_density=False,
        parameter_robust=False,
    )
    payload = fragile.to_dict()
    assert payload["dense_sensitivity"]["classification"] == "PARAMETER_FRAGILE"
    assert payload["sparse_sensitivity"]["classification"] == "PARAMETER_FRAGILE"


def test_cross_member_support_requires_four_members():
    cohorts = [
        _cohort(name, robust_random=True, robust_density=True, parameter_robust=True)
        for name in FINAL_MEMBER_NAMES[:3]
    ]
    cohorts.extend(
        _cohort(name, robust_random=False, robust_density=False, parameter_robust=False)
        for name in FINAL_MEMBER_NAMES[3:]
    )
    bundle = build_final_disposition_bundle(_protocol(), cohorts)
    assert bundle.selected_outcome is TrendlineAdequacyOutcome.UTILITY_NOT_BETTER_THAN_NAIVE_NULL


def test_recommended_action_is_derived_from_outcome():
    cohorts = [_cohort(name, robust_random=False, robust_density=False, parameter_robust=False) for name in FINAL_MEMBER_NAMES]
    bundle = build_final_disposition_bundle(_protocol(), cohorts)
    assert bundle.recommended_action is TrendlineFinalRecommendedAction.RETAIN_AS_CONTEXT_ONLY


def test_axis_scope_is_exactly_four():
    bundle = build_final_disposition_bundle(_protocol(), _cohorts())
    assert tuple(name for name, _ in bundle.axis_classifications) == (
        "evidence_completeness",
        "structural_non_triviality",
        "null_relative_interaction_utility",
        "geometry_sensitivity",
    )


def test_expected_prior_bindings_reject_forged_cohort_identity():
    from libs.models.trendlines.workflows.research.adequacy.final_disposition import (
        validate_final_disposition_bundle,
    )

    protocol = _protocol()
    cohorts = _cohorts()
    expected = {
        row.member_name: {
            "d5a_member_spec_id": row.d5a_member_spec_id,
            "d5a_member_evidence_id": row.d5a_member_evidence_id,
            "canonical_d2_bundle_id": row.canonical_d2_bundle_id,
            "canonical_d3_bundle_id": row.canonical_d3_bundle_id,
            "canonical_d4a_bundle_id": row.canonical_d4a_bundle_id,
            "canonical_d4b_bundle_id": row.canonical_d4b_bundle_id,
            "baseline_member_result_id": row.baseline_member_result_id,
            "dense_capsule_id": row.dense_capsule_id,
            "sparse_capsule_id": row.sparse_capsule_id,
        }
        for row in cohorts
    }
    forged = replace(cohorts[0], dense_capsule_id=_id("forged"), cohort_evidence_id="")
    forged_cohorts = [forged, *cohorts[1:]]
    forged_bundle = build_final_disposition_bundle(protocol, forged_cohorts)
    with pytest.raises(TrendlineFinalDispositionError):
        validate_final_disposition_bundle(
            forged_bundle,
            protocol=protocol,
            cohorts=forged_cohorts,
            expected_cohort_bindings=expected,
        )


def test_duplicate_null_coordinate_rejected():
    rows = _cells(robust=True, baseline_id=_id("x"))
    rows[-1] = dict(rows[0])
    with pytest.raises(TrendlineFinalDispositionError):
        classify_null_cells(rows, protocol=_protocol())


def test_final_bundle_identity_changes_with_cohort_evidence():
    protocol = _protocol()
    cohorts = _cohorts()
    first = build_final_disposition_bundle(protocol, cohorts)
    changed = replace(cohorts[0], canonical_event_count=99, cohort_evidence_id="")
    second = build_final_disposition_bundle(protocol, [changed, *cohorts[1:]])
    assert first.final_disposition_bundle_id != second.final_disposition_bundle_id


def test_decision_matrix_reports_independent_rule_pass_and_selection():
    protocol = _protocol()
    cohorts = _cohorts(random=True, density=False, robust=False)
    bundle = build_final_disposition_bundle(protocol, cohorts)
    matrix = build_decision_matrix(protocol, cohorts, bundle)
    results = {row["rule_code"]: (row["passed"], row["selected"]) for row in matrix["rules"]}
    assert results["RULE_1_COVERAGE_FAILURE"] == (False, False)
    assert results["RULE_2_ADEQUATE_FOR_FURTHER_RESEARCH"] == (False, False)
    assert results["RULE_3_UTILITY_NOT_BETTER_THAN_NAIVE_NULL"] == (True, True)
    assert results["RULE_4_STRUCTURALLY_STABLE_BUT_NO_UTILITY"] == (False, False)
    assert results["RULE_5_EXCESSIVE_GEOMETRY_CHURN"] == (False, False)
    assert results["RULE_6_RESIDUAL_AMBIGUITY"] == (False, False)


def test_incomplete_evidence_passes_and_selects_coverage_rule():
    protocol = _protocol()
    cohorts = _cohorts()
    bundle = build_final_disposition_bundle(protocol, cohorts, evidence_complete=False)
    matrix = build_decision_matrix(protocol, cohorts, bundle, evidence_complete=False)
    row = matrix["rules"][0]
    assert row["passed"] is True
    assert row["selected"] is True


def test_later_passed_rule_cannot_override_first_hierarchy_rule():
    protocol = _protocol()
    cohorts = [
        replace(
            _cohort(name, robust_random=False, robust_density=False, parameter_robust=False),
            structural_classification="NO_MEANINGFUL_STRUCTURE",
            cohort_evidence_id="",
        )
        for name in FINAL_MEMBER_NAMES
    ]
    bundle = build_final_disposition_bundle(protocol, cohorts, evidence_complete=False)
    matrix = build_decision_matrix(protocol, cohorts, bundle, evidence_complete=False)
    results = {row["rule_code"]: row for row in matrix["rules"]}
    assert results["RULE_1_COVERAGE_FAILURE"]["passed"] is True
    assert results["RULE_5_EXCESSIVE_GEOMETRY_CHURN"]["passed"] is True
    assert results["RULE_1_COVERAGE_FAILURE"]["selected"] is True
    assert results["RULE_5_EXCESSIVE_GEOMETRY_CHURN"]["selected"] is False


def test_decisive_null_object_is_frozen_and_explicit():
    matrix = build_decision_matrix(_protocol(), _cohorts(), build_final_disposition_bundle(_protocol(), _cohorts()))
    assert matrix["decisive_null"] == FINAL_DECISIVE_NULL
    assert "legacy outcome vocabulary" in matrix["decisive_null"]["legacy_outcome_note"]
    assert "causal density-matched null" in matrix["decisive_null"]["legacy_outcome_note"]
