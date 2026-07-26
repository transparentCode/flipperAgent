"""Contract-freeze tests for Phase 11R.3B.

These tests must remain source-free: no lifecycle bundle, provider, network,
holdout, temporal or compression execution is allowed during contract freeze.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import analyze_trendline_v2_joint_structural_compression as subject


EXPECTED_TOP_LEVEL = {
    "schema_version",
    "base_commit",
    "sources",
    "candidate_universe",
    "targets",
    "causal_ranking",
    "policies",
    "joint_selection",
    "structural_context_lane",
    "evaluation",
    "metrics",
    "stability_formulas",
    "gate_aggregation",
    "validation_gates",
    "finalist_selection",
    "decision",
    "validation_lock",
    "artifacts",
    "execution_accounting",
    "study_controls",
}


def test_contract_triplet_is_canonical_and_self_consistent() -> None:
    triplet = subject.contract_triplet()
    assert triplet["contract_id"] == subject.EXPECTED_CONTRACT_ID
    assert triplet["canonical_json_sha256"] == subject.EXPECTED_CONTRACT_JSON_SHA256
    assert triplet["canonical_json_byte_length"] == subject.EXPECTED_CONTRACT_JSON_BYTE_LENGTH
    assert len(triplet["canonical_json"].encode("utf-8")) == subject.EXPECTED_CONTRACT_JSON_BYTE_LENGTH
    assert json.loads(triplet["canonical_json"]) == triplet["payload"]


def test_temporal_v2_contract_is_distinct_and_availability_aware() -> None:
    triplet = subject.temporal_v2_contract_triplet()
    payload = triplet["payload"]
    assert triplet["contract_id"] == subject.TEMPORAL_V2_EXPECTED_CONTRACT_ID
    assert triplet["contract_id"] != subject.EXPECTED_CONTRACT_ID
    assert payload["evaluation"]["future_window_rule"] == (
        "checkpoint < available_at <= checkpoint + horizon"
    )
    assert payload["evaluation"]["future_open_timestamp_rule"] == (
        "checkpoint <= timestamp_ns < checkpoint + horizon"
    )
    assert payload["temporal_window_remediation"]["supersedes_contract_id"] == (
        subject.EXPECTED_CONTRACT_ID
    )


def test_contract_has_exact_top_level_structure() -> None:
    assert set(subject.contract_payload()) == EXPECTED_TOP_LEVEL


@pytest.mark.parametrize("section", sorted(EXPECTED_TOP_LEVEL - {"schema_version", "base_commit"}))
def test_mutating_every_contract_section_changes_identity(section: str) -> None:
    payload = subject.contract_payload()
    value = payload[section]
    if isinstance(value, dict):
        value["__drift__"] = True
    elif isinstance(value, list):
        value.append("__drift__")
    else:
        payload[section] = "__drift__"
    with pytest.raises(subject.ContractFreezeError):
        subject.validate_contract_identity(payload)


def test_exact_base_and_source_identity_bindings() -> None:
    payload = subject.contract_payload()
    assert payload["base_commit"] == "b7cd736e08bda2eb82fa7f0dad62c842428c602a"
    source = payload["sources"]
    assert source["phase11r3a"]["root"] == str(subject.PHASE11R3A_ROOT)
    assert source["phase11r3a"]["commit"] == subject.PHASE11R3A_COMMIT
    assert source["phase11r3a"]["contract_id"] == subject.PHASE11R3A_CONTRACT_ID
    assert source["phase11r3a"]["contract_json_byte_length"] == 22226
    assert source["phase11r3a"]["contract_json_sha256"] == subject.PHASE11R3A_CONTRACT_JSON_SHA256
    assert source["phase11r3a"]["decision_id"] == subject.PHASE11R3A_DECISION_ID
    assert source["phase11r3a"]["manifest_id"] == subject.PHASE11R3A_MANIFEST_ID
    assert source["phase11r3a"]["inventory_sha256"] == subject.PHASE11R3A_INVENTORY
    assert source["protected_inventories"] == {
        "phase11r1": subject.PHASE11R1_INVENTORY,
        "phase11r2": subject.PHASE11R2_INVENTORY,
        "allowed_btc_eth_raw": subject.ALLOWED_RAW_INVENTORY,
    }
    assert source["allowed_raw_paths"] == list(subject.ALLOWED_RAW_PATHS)
    assert source["expected_allowed_raw_member_count"] == 4
    assert source["reject_additional_raw_members"] is True


def test_only_four_validation_datasets_and_forbidden_sources() -> None:
    source = subject.contract_payload()["sources"]
    assert source["allowed_datasets"] == list(subject.DATASETS)
    assert source["allowed_datasets"] == [
        "btcusdt_1h",
        "btcusdt_4h",
        "ethusdt_1h",
        "ethusdt_4h",
    ]
    assert source["raw_sui_reads"] == "prohibited"
    assert source["holdout_reads"] == "prohibited"
    assert source["temporal_reads"] == "prohibited"
    assert source["network_reads"] == "prohibited"
    assert source["provider_executions"] == "prohibited"


def test_candidate_state_partition_is_exact() -> None:
    universe = subject.contract_payload()["candidate_universe"]
    assert universe["actionable_states"] == list(subject.ACTIONABLE_STATES)
    assert universe["structural_context_states"] == list(subject.STRUCTURAL_CONTEXT_STATES)
    assert universe["excluded_states"] == list(subject.EXCLUDED_STATES)
    assert set(universe["all_states"]) == set(subject.ALL_STATES)
    assert set(universe["actionable_states"]).isdisjoint(universe["structural_context_states"])
    assert set(universe["all_states"]) == set(universe["excluded_states"]) | set(universe["actionable_states"]) | set(universe["structural_context_states"])


def test_budgets_are_exact_and_structural_context_is_outside_budget() -> None:
    payload = subject.contract_payload()
    assert payload["targets"]["budgets_per_role"] == [1, 2, 3]
    assert payload["targets"]["maximum_active_lines_by_budget"] == {"1": 2, "2": 4, "3": 6}
    context = payload["structural_context_lane"]
    assert context["max_lineages_per_role"] == 1
    assert context["actionable_budget"] is False
    assert context["actionable_denominator"] is False
    assert context["coverage_rescue"] is False


def test_ranking_is_causal_and_has_no_weighted_score() -> None:
    ranking = subject.contract_payload()["causal_ranking"]
    assert ranking["weighted_score"] is False
    assert ranking["parameter_fitting"] is False
    assert ranking["score_threshold"] is None
    assert ranking["incumbent_membership_source"] == "previous_checkpoint_only"
    assert "future_survival" in ranking["forbidden_features"]
    assert "future_contact" in ranking["forbidden_features"]
    assert "later_selected_membership" in ranking["forbidden_features"]
    assert ranking["future_mutation_invariance"] is True


def test_policy_set_and_exact_lexicographic_keys_are_frozen() -> None:
    policies = subject.contract_payload()["policies"]
    assert policies["controls"] == list(subject.CONTROL_POLICIES)
    assert policies["comparison_controls"] == [
        "joint_hash_order_control_v1",
        "joint_nearest_projection_control_v1",
    ]
    assert policies["diagnostic_control"] == "independent_incumbent_control_v1"
    assert policies["contenders"] == list(subject.CONTENDER_POLICIES)
    definitions = policies["definitions"]
    assert definitions["joint_incumbent_near_v1"]["ranking_key"] == [
        {"field": "previous_checkpoint_incumbent", "order": "descending"},
        {"field": "checkpoint_distance_atr", "order": "ascending"},
        {"field": "lineage_age", "order": "descending"},
        {"field": "lineage_id", "order": "ascending"},
    ]
    assert definitions["joint_incumbent_tenure_v1"]["ranking_key"][2] == {
        "field": "cumulative_strict_active_observations",
        "order": "descending",
    }
    assert definitions["joint_incumbent_evidence_v1"]["ranking_key"][2] == {
        "field": "cumulative_actionable_observations",
        "order": "descending",
    }
    assert policies["independent_control_cannot_win"] is True


def test_joint_selection_formula_and_full_set_check_are_frozen() -> None:
    selection = subject.contract_payload()["joint_selection"]
    assert selection["required"] is True
    assert selection["full_set_validation"] is True
    assert "max(selected support projections) <" in selection["coherence_formula"]
    assert selection["inverted_set_action"] == "reject_and_select_fewer_or_none"
    assert "selected_lineage_ids" in selection["persisted_fields"]
    assert "budget_shortfall" in selection["persisted_fields"]


def test_controls_are_matched_by_cell_count_and_horizon_population() -> None:
    matching = subject.contract_payload()["policies"]["control_matching"]
    assert matching["matching_key"] == [
        "contender_policy_id",
        "budget_per_role",
        "control_policy_id",
        "dataset_id",
        "checkpoint_index",
        "semantic_role",
    ]
    assert matching["construction_order"][0] == "run_contender_first"
    assert matching["unmatchable_action"] == (
        "persist_unmatched_and_fail_unresolved_reconciliation"
    )
    assert matching["same_input_population"] is True
    assert matching["same_selected_count_per_budget"] is True
    assert matching["same_horizon_population"] is True


def test_evaluation_horizons_and_denominator_boundaries_are_frozen() -> None:
    evaluation = subject.contract_payload()["evaluation"]
    assert evaluation["horizons_hours"] == [24, 48, 96]
    assert evaluation["future_timestamp_rule"] == "timestamp strictly after checkpoint"
    assert evaluation["future_window_rule"] == "checkpoint < timestamp <= checkpoint + horizon"
    assert evaluation["reaction_starts_after_contact"] is True
    assert evaluation["structural_outcomes_excluded_from_actionable_denominators"] is True
    assert evaluation["holdout_scope"] == "prohibited"
    assert evaluation["temporal_scope"] == "prohibited"


def test_finalist_gates_and_precedence_are_exact() -> None:
    payload = subject.contract_payload()
    gates = payload["validation_gates"]
    assert gates == [
        "zero_support_resistance_inversions",
        "zero_causal_source_violations",
        "selected_count_never_exceeds_budget",
        "actionable_role_cell_coverage_equals_available_actionable_input_coverage",
        "incumbent_retention_not_worse_than_both_matched_controls",
        "adjacent_continuity_not_worse_than_both_matched_controls",
        "pooled_48h_survival_delta_nonnegative_vs_both_controls",
        "pooled_96h_survival_delta_nonnegative_vs_both_controls",
        "pooled_96h_contact_and_survival_delta_nonnegative_vs_both_controls",
        "worst_dataset_96h_survival_delta_nonnegative",
        "zero_unresolved_reconciliation",
    ]
    finalist = payload["finalist_selection"]
    assert finalist["no_finalist_status"] == subject.NO_FINALIST_STATUS
    assert finalist["precedence"] == [
        "smaller_budget",
        "higher_worst_dataset_96h_survival_delta",
        "higher_incumbent_retention",
        "higher_adjacent_continuity",
        "policy_id",
    ]


def test_artifact_inventory_is_exact_and_safe() -> None:
    artifacts = subject.contract_payload()["artifacts"]
    assert tuple(artifacts["paths"]) == subject.EXPECTED_ARTIFACT_PATHS
    assert artifacts["total_file_count"] == len(subject.EXPECTED_ARTIFACT_PATHS)
    assert artifacts["manifest_member_count"] == len(subject.EXPECTED_ARTIFACT_PATHS) - 1
    assert artifacts["paths"][-1] == "datasets/ethusdt_4h/policy_metrics.json"
    assert artifacts["contains_holdout"] is False
    assert artifacts["contains_temporal"] is False
    assert artifacts["contains_sui"] is False


def test_execution_accounting_and_study_controls_are_research_only() -> None:
    payload = subject.contract_payload()
    accounting = payload["execution_accounting"]
    assert accounting["checkpoints"] == 88
    assert accounting["policies"] == 6
    assert accounting["contender_budget_combinations"] == 9
    assert accounting["matched_control_derivations"] == 18
    assert accounting["independent_diagnostic_combinations"] == 3
    assert accounting["total_planned_derivations"] == 30
    assert accounting["study_provider_executions"] == 0
    assert accounting["network_requests"] == 0
    controls = payload["study_controls"]
    assert controls["study_execution_during_freeze"] is False
    assert controls["production_allow_synthetic"] is False
    assert controls["test_synthetic_path_separate"] is True
    assert controls["runtime_changes"] is False
    assert controls["viewer_changes"] is False
    assert controls["yaml_changes"] is False


def test_contract_payload_is_detached_from_callers() -> None:
    first = subject.contract_payload()
    first["sources"]["allowed_datasets"].append("suiusdt_1h")
    second = subject.contract_payload()
    assert second["sources"]["allowed_datasets"] == list(subject.DATASETS)


def test_output_root_refusal_precedes_any_execution() -> None:
    with pytest.raises(subject.ContractFreezeError, match="output root refused"):
        subject.require_fresh_output_root(Path("/tmp"))


def test_execution_guard_requires_environment_after_fresh_root_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "compression"
    monkeypatch.delenv("TRENDLINE_V2_ALLOW_PHASE11R3B_COMPRESSION_STUDY", raising=False)
    with pytest.raises(subject.ContractFreezeError, match="execution guard"):
        subject._execution_guard(root)


def test_execution_guard_rejects_existing_root_before_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "compression"
    root.mkdir()
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R3B_COMPRESSION_STUDY", "1")
    with pytest.raises(subject.ContractFreezeError, match="output root refused"):
        subject._execution_guard(root)


def test_direct_runner_requires_execution_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRENDLINE_V2_ALLOW_PHASE11R3B_COMPRESSION_STUDY", raising=False)
    with pytest.raises(subject.ContractFreezeError, match="execution guard"):
        subject.run_compression_study(tmp_path / "study")


def test_canonical_execution_requires_explicit_runner_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "published"
    called: list[bool] = []

    # Importing/configuring the runner must not create publication output.
    subject.contract_triplet()
    assert not root.exists()

    def isolated_guard() -> None:
        subject.require_fresh_output_root(root)

    monkeypatch.setattr(subject, "_execution_guard", isolated_guard)
    assert not root.exists()

    def fake_run_compression_study() -> dict[str, str]:
        called.append(True)
        root.mkdir()
        (root / "publication.marker").write_text("published\n", encoding="utf-8")
        return {"status": "synthetic-test-run"}

    monkeypatch.setattr(
        subject,
        "run_compression_study",
        fake_run_compression_study,
    )
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R3B_COMPRESSION_STUDY", "1")
    assert subject.main(["--execute-compression-study"]) == 0
    assert called == [True]
    assert (root / "publication.marker").read_text(encoding="utf-8") == "published\n"


def test_no_source_or_runtime_imports_are_needed_for_contract_identity() -> None:
    source = subject.contract_payload()["sources"]
    assert source["provider_executions"] == "prohibited"
    assert source["network_reads"] == "prohibited"
    assert subject.contract_triplet()["payload"]["study_controls"]["study_execution_during_freeze"] is False


def test_no_production_synthetic_verifier_switch_exists() -> None:
    assert "allow_synthetic" not in subject.main.__code__.co_varnames
    assert subject.contract_payload()["study_controls"]["production_allow_synthetic"] is False


def test_independent_control_is_excluded_from_all_gates() -> None:
    policies = subject.contract_payload()["policies"]
    assert policies["diagnostic_control"] == "independent_incumbent_control_v1"
    assert policies["independent_control_participates_in_utility_gates"] is False
    assert policies["independent_control_participates_in_stability_gates"] is False
    assert policies["independent_control_cannot_win"] is True


def test_matched_control_counts_and_unmatched_reconciliation_are_frozen() -> None:
    matching = subject.contract_payload()["policies"]["control_matching"]
    assert matching["same_selected_count_per_budget"] is True
    assert matching["construction_order"] == [
        "run_contender_first",
        "record_exact_selected_support_and_resistance_counts",
        "derive_control_from_same_candidate_population",
        "require_exact_per_role_selected_count_match",
        "use_identical_future_horizons_and_evaluable_observations",
    ]
    assert matching["unmatchable_action"].endswith("unresolved_reconciliation")


def test_incumbent_and_role_transfer_semantics_are_exact() -> None:
    payload = subject.contract_payload()
    ranking = payload["causal_ranking"]["incumbent_definition"]
    assert ranking["same_policy"] is True
    assert ranking["same_budget"] is True
    assert ranking["immediately_previous_checkpoint_only"] is True
    assert ranking["first_checkpoint_has_no_incumbents"] is True
    assert ranking["confirmed_role_transfer_remains_incumbent"] is True
    transfer = payload["joint_selection"]["role_transfer"]
    assert transfer["overall_retention"] == "role-transferred lineage counts retained"
    assert transfer["role_specific_churn"] == (
        "one removal from prior role and one addition to current role"
    )


def test_causal_feature_formulas_and_stable_hash_input_are_frozen() -> None:
    ranking = subject.contract_payload()["causal_ranking"]
    assert ranking["lineage_age_formula"] == (
        "checkpoint_index - first_strict_checkpoint + 1"
    )
    assert "inclusive" in ranking["cumulative_strict_active_observations_formula"]
    assert "inclusive" in ranking["cumulative_actionable_observations_formula"]
    assert ranking["past_transition_count_formula"].endswith(
        "checkpoint_observed_at"
    )
    stable_hash = ranking["stable_lineage_hash"]
    assert stable_hash["namespace"] == subject.STABLE_LINEAGE_HASH_NAMESPACE
    assert stable_hash["input_fields"] == ["dataset_id", "lineage_id"]
    assert stable_hash["canonical_input"] == "canonical_json({dataset_id, lineage_id})"


def test_cartesian_core_pair_and_no_pair_behavior_are_exact() -> None:
    selection = subject.contract_payload()["joint_selection"]
    assert selection["core_pair_construction"] == [
        "enumerate_cartesian_product_support_resistance",
        "retain_support_projection_less_than_resistance_projection",
        "select_minimum_tuple",
    ]
    assert selection["core_pair_selection_key"] == [
        "support_rank_index",
        "resistance_rank_index",
        "support_lineage_id",
        "resistance_lineage_id",
    ]
    assert selection["no_coherent_core_pair"] == {
        "selected_actionable_candidates": 0,
        "shortfall_reason": "no_coherent_core_pair",
    }


def test_fill_order_full_coherence_and_shortfall_precedence_are_exact() -> None:
    selection = subject.contract_payload()["joint_selection"]
    assert selection["remaining_slot_order"] == [
        "rank_index_ascending",
        "role_support_before_resistance",
        "lineage_id_ascending",
    ]
    assert selection["remaining_slot_acceptance"] == [
        "role_below_budget",
        "candidate_not_already_selected",
        "complete_selected_set_remains_coherent",
    ]
    assert selection["shortfall_reason_precedence"] == [
        "no_eligible_candidates",
        "role_missing",
        "no_coherent_core_pair",
        "full_budget_would_invert_roles",
        "insufficient_eligible_candidates",
    ]
    assert selection["full_set_validation"] is True
    assert selection["no_inversion_published"] is True


def test_stability_metric_denominators_and_role_churn_are_frozen() -> None:
    stability = subject.contract_payload()["stability_formulas"]
    assert stability["incumbent_retention"]["denominator"].startswith(
        "previous selected lineage IDs"
    )
    assert stability["incumbent_retention"]["zero_denominator_rate"] is None
    assert stability["incumbent_retention"]["zero_denominator_evaluable_count"] == 0
    assert stability["adjacent_jaccard"]["formula"] == (
        "intersection(previous,current) / union(previous,current)"
    )
    assert stability["adjacent_jaccard"]["empty_union_excluded_from_pooled_rate"] is True
    assert stability["replacement_count"] == "min(count(additions), count(removals))"
    assert stability["pair_continuity"]["zero_denominator_rate"] is None
    assert stability["role_specific_churn"]["membership"] == (
        "(semantic_role, lineage_id)"
    )


def test_actionable_contact_breach_survival_and_reaction_formulas_are_frozen() -> None:
    evaluation = subject.contract_payload()["evaluation"]
    assert evaluation["line_projection_formula"] == (
        "immutable geometry evaluated at future bar timestamp"
    )
    assert evaluation["zone_contact_formula"] == (
        "low <= line + 0.35 * ATR_at_bar and "
        "high >= line - 0.35 * ATR_at_bar"
    )
    assert evaluation["support_breach_formula"] == (
        "two consecutive closes below line - 0.5 * ATR_at_bar"
    )
    assert evaluation["resistance_breach_formula"] == (
        "two consecutive closes above line + 0.5 * ATR_at_bar"
    )
    assert evaluation["survival_formula"] == (
        "no sustained role-invalidating breach through horizon"
    )
    reaction = evaluation["reaction_formula"]
    assert reaction["starts_strictly_after_first_contact_bar"] is True
    assert reaction["ends_before_sustained_breach_completion_bar"] is True
    assert reaction["same_contact_bar_excluded"] is True
    assert reaction["minimum_movement"] == (
        "at least 1 * ATR_at_contact_bar away from contact line"
    )


def test_null_outcome_metric_fails_required_gate() -> None:
    evaluation = subject.contract_payload()["evaluation"]
    assert evaluation["zero_denominator"] == {
        "rate": None,
        "evaluable_count": 0,
        "required_gate_result": "fail",
    }


def test_coverage_utility_worst_dataset_and_stability_gate_aggregation_are_exact() -> None:
    gates = subject.contract_payload()["gate_aggregation"]
    assert gates["coverage"] == {
        "input_role_cell_formula": "actionable-input non-empty cells / 176",
        "selected_role_cell_formula": "selected non-empty cells / 176",
        "required_equality": "selected cell count == input cell count",
    }
    assert gates["utility_delta"]["comparison_controls"] == [
        "joint_hash_order_control_v1",
        "joint_nearest_projection_control_v1",
    ]
    assert gates["utility_delta"]["matched_counts_and_populations"] is True
    assert gates["worst_dataset_96h_survival_delta"]["formula"] == (
        "minimum across four datasets and two comparison controls"
    )
    assert gates["worst_dataset_96h_survival_delta"]["required_dataset_control_denominators"] == "all non-zero"
    assert gates["stability_comparison"]["comparison"] == (
        "contender >= hash control and contender >= nearest control"
    )
    assert gates["stability_comparison"]["tolerance"] == 0
    assert gates["stability_comparison"]["rounding_allowance"] is False


def test_structural_context_ranking_and_independence_are_frozen() -> None:
    context = subject.contract_payload()["structural_context_lane"]
    assert context["ranking_key"] == [
        {"field": "previous_structural_context_incumbent", "order": "descending"},
        {"field": "checkpoint_distance_atr", "order": "ascending"},
        {"field": "lineage_age", "order": "descending"},
        {"field": "lineage_id", "order": "ascending"},
    ]
    assert context["shared_across_actionable_policies"] is True
    assert context["independent_of_actionable_budget"] is True
    assert context["independent_of_actionable_coverage"] is True
    assert context["independent_of_finalist_gates"] is True
    assert context["independent_of_actionable_utility_denominators"] is True


def test_decision_and_validation_lock_membership_are_separate_and_exact() -> None:
    payload = subject.contract_payload()
    decision = payload["decision"]
    assert decision["study_statuses"] == [
        "JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_COMPLETE",
        "JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_INCOMPLETE",
        "JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_BLOCKED",
    ]
    assert decision["finalist_statuses"] == [
        "finalist_policy_budget_id",
        subject.NO_FINALIST_STATUS,
    ]
    assert decision["study_status_and_finalist_status_separate"] is True
    assert decision["no_finalist_can_still_be_complete"] is True
    lock = payload["validation_lock"]
    assert lock["exact_members"] == [
        "source_identities",
        "lineage_lifecycle_evidence_ids",
        "contender_budget_gate_record_ids",
        "matched_control_comparison_record_ids",
        "independent_control_diagnostic_ids",
        "finalist",
        "zero_unresolved_reconciliation",
        "holdout_access_count",
        "temporal_access_count",
        "final_decision_id",
    ]
    assert lock["lineage_lifecycle_evidence_ids"] == (
        subject.PHASE11R3A_LINEAGE_LIFECYCLE_EVIDENCE_IDS
    )
    assert lock["contender_budget_gate_record_ids"]["required_key_count"] == 9
    assert lock["matched_control_comparison_record_ids"]["required_key_count"] == 18
    assert lock["independent_control_diagnostic_ids"]["required_key_count"] == 3
    assert lock["finalist"]["type"] == "null_or_policy_budget_id"
    assert lock["finalist"]["null_only_when_no_variant_passes"] is True
    assert lock["finalist"]["non_null_requires_all_gates_passed"] is True
    assert lock["final_decision_id"] == "deterministic_evidence_id"
    assert lock["holdout_access_count"] == 0
    assert lock["temporal_access_count"] == 0
    assert lock["no_holdout_loader"] is True


def test_exact_raw_allowlist_rejects_extra_members_by_contract() -> None:
    source = subject.contract_payload()["sources"]
    artifacts = subject.contract_payload()["artifacts"]
    assert tuple(source["allowed_raw_paths"]) == subject.ALLOWED_RAW_PATHS
    assert source["expected_allowed_raw_member_count"] == 4
    assert source["reject_additional_raw_members"] is True
    assert artifacts["allowed_raw_paths"] == list(subject.ALLOWED_RAW_PATHS)
    assert artifacts["reject_additional_raw_members"] is True


def test_finalist_schema_allows_null_or_valid_contender_budget_id() -> None:
    finalist = subject.contract_payload()["validation_lock"]["finalist"]
    assert finalist["type"] == "null_or_policy_budget_id"
    assert finalist["allowed_policy_ids"] == list(subject.CONTENDER_POLICIES)
    assert finalist["allowed_budgets"] == [1, 2, 3]
    assert finalist["null_only_when_no_variant_passes"] is True
    assert finalist["must_match_decision_finalist_status"] is True
    assert finalist["non_null_requires_all_gates_passed"] is True
    assert finalist["non_null_requires_finalist_precedence_winner"] is True


def test_study_status_conditions_allow_complete_no_finalist() -> None:
    decision = subject.contract_payload()["decision"]
    conditions = decision["study_status_conditions"]
    assert conditions["JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_COMPLETE"] == [
        "all_required_evidence_derived",
        "all_required_evidence_reconciled",
        "all_required_evidence_verified",
        "unresolved_evidence_count == 0",
        "may_have_finalist_or_no_finalist",
    ]
    assert conditions["JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_INCOMPLETE"] == [
        "derivation_completed",
        "one_or_more_required_comparison_metric_or_reconciliation_records_unresolved",
    ]
    assert conditions["JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_BLOCKED"] == [
        "source_contract_execution_boundary_or_publication_precondition_failed_before_complete_evidence",
    ]
    assert decision["no_finalist_can_still_be_complete"] is True


def test_incumbency_is_rank_priority_and_retention_is_post_selection() -> None:
    selection = subject.contract_payload()["joint_selection"]
    assert selection["incumbency_mode"] == "ranking_priority_only"
    assert selection["unconditional_preselection"] is False
    assert selection["retained_incumbent_definition"] == (
        "selected current IDs intersect eligible previous selected IDs"
    )
    assert selection["steps"][1] == "calculate_incumbent_status_without_preselection"
    assert selection["steps"][-2] == "derive_retained_incumbents_after_selection"


def test_outcome_identity_namespaces_matched_controls_and_freezes_role() -> None:
    evaluation = subject.contract_payload()["evaluation"]
    assert evaluation["candidate_outcome_observation_identity"] == [
        "contender_policy_id",
        "budget_per_role",
        "derivation_type",
        "control_policy_id_or_null",
        "dataset_id",
        "checkpoint_index",
        "semantic_role_at_selection",
        "lineage_id",
        "horizon_hours",
    ]
    assert evaluation["matched_control_namespace"] == [
        "contender_policy_id",
        "contender_budget",
        "control_policy_id",
    ]
    assert evaluation["semantic_role_at_selection_fixed_through_horizon"] is True
    assert evaluation["one_candidate_level_observation_per_selected_candidate_checkpoint_horizon"] is True


def test_structural_context_formulas_and_role_freeze_are_exact() -> None:
    context = subject.contract_payload()["structural_context_lane"]
    assert context["initial_distance_atr_formula"] == (
        "abs(last_completed_close - line_at_checkpoint) / "
        "ATR_of_last_completed_bar"
    )
    assert context["future_distance_atr_formula"] == (
        "abs(future_close - line_at_future_bar) / ATR_at_future_bar"
    )
    assert context["minimum_future_distance_atr_formula"] == (
        "minimum future_distance_atr over exact horizon"
    )
    assert context["distance_contraction_atr_formula"] == (
        "initial_distance_atr - minimum_future_distance_atr"
    )
    assert context["future_contact_formula"] == (
        "low <= line + 0.35 * ATR_at_bar and "
        "high >= line - 0.35 * ATR_at_bar"
    )
    assert context["crossed_into_at_most_8_atr_formula"] == (
        "any future_distance_atr <= 8"
    )
    assert context["role_at_selection_fixed_through_horizon"] is True


def test_shortfall_scarcity_reason_and_rejection_reason_set_are_exact() -> None:
    selection = subject.contract_payload()["joint_selection"]
    assert selection["shortfall_reasons"] == [
        "no_eligible_candidates",
        "role_missing",
        "no_coherent_core_pair",
        "full_budget_would_invert_roles",
        "insufficient_eligible_candidates",
    ]
    assert selection["shortfall_reason_precedence"] == selection["shortfall_reasons"]
    assert selection["shortfall_reason_conditions"]["insufficient_eligible_candidates"] == (
        "coherent selection exists and eligible count is below requested role budget without coherence rejection"
    )
    assert selection["shortfall_persisted_per_role"] is True
    assert selection["candidate_rejection_reasons"] == [
        "already_selected",
        "role_budget_full",
        "would_invert_full_set",
        "not_required_for_matched_count",
    ]


def test_validation_lock_binds_generated_evidence_ids_and_decision_id() -> None:
    lock = subject.contract_payload()["validation_lock"]
    gate = lock["contender_budget_gate_record_ids"]
    comparison = lock["matched_control_comparison_record_ids"]
    diagnostic = lock["independent_control_diagnostic_ids"]
    assert gate["type"] == "map"
    assert gate["value_type"] == "deterministic_evidence_id"
    assert gate["record_binds"] == [
        "policy_id",
        "budget",
        "all_gate_inputs",
        "all_gate_results",
        "all_rejection_reasons",
        "dataset_result_ids",
        "comparison_record_ids",
        "unresolved_reconciliation_count",
    ]
    assert comparison["value_type"] == "deterministic_evidence_id"
    assert comparison["record_binds"] == [
        "contender_policy_id",
        "budget_per_role",
        "control_policy_id",
        "exact_matched_cell_population",
        "target_per_role_counts",
        "actual_per_role_counts",
        "matched_status",
        "candidate_outcome_population_id",
        "stability_population_id",
        "utility_deltas",
    ]
    assert diagnostic["value_type"] == "deterministic_evidence_id"
    assert lock["final_decision_id"] == "deterministic_evidence_id"


def test_r3a_lineage_lifecycle_evidence_name_is_explicit() -> None:
    source = subject.contract_payload()["sources"]["phase11r3a"]
    lock = subject.contract_payload()["validation_lock"]
    assert source["lineage_lifecycle_evidence_ids"] == (
        subject.PHASE11R3A_LINEAGE_LIFECYCLE_EVIDENCE_IDS
    )
    assert lock["lineage_lifecycle_evidence_ids"] == (
        subject.PHASE11R3A_LINEAGE_LIFECYCLE_EVIDENCE_IDS
    )


def _candidate(
    role: str,
    lineage_id: str,
    projection: float,
    *,
    state: str = "STRICT_ACTIVE_NEAR",
    checkpoint: int = 1,
) -> dict[str, object]:
    row: dict[str, object] = {
        "dataset_id": "synthetic",
        "checkpoint_index": checkpoint,
        "checkpoint_observed_at": "2026-01-01T00:00:00Z",
        "semantic_role": role,
        "lineage_id": lineage_id,
        "state": state,
        "fixed_geometry": {
            "start_time": "2025-12-01T00:00:00Z",
            "end_time": "2025-12-02T00:00:00Z",
            "start_price": projection,
            "end_price": projection,
        },
        "projection_at_checkpoint": projection,
        "checkpoint_distance_atr": 1.0,
        "first_strict_checkpoint": 1,
        "lineage_age": checkpoint,
        "stable_lineage_hash": lineage_id,
        "cumulative_strict_active_observations": checkpoint,
        "cumulative_actionable_observations": checkpoint,
        "past_breach_transitions": 0,
        "past_reversal_transitions": 0,
        "past_contact_transitions": 0,
    }
    row["candidate_observation_id"] = lineage_id
    return row


def _future_bars(hours: int = 96) -> list[dict[str, float | int]]:
    start = 1_767_225_600_000_000_000  # 2026-01-01T00:00:00Z
    return [
        {
            "timestamp_ns": start + offset * 3_600 * 1_000_000_000,
            "available_at_ns": start + (offset + 1) * 3_600 * 1_000_000_000,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "atr": 1.0,
        }
        for offset in range(1, hours + 1)
    ]


@pytest.mark.parametrize(
    ("timeframe", "interval_seconds"),
    (("1h", 3_600), ("4h", 14_400)),
)
@pytest.mark.parametrize("horizon_hours", subject.HORIZONS_HOURS)
def test_temporal_v2_future_window_uses_exact_availability(
    timeframe: str,
    interval_seconds: int,
    horizon_hours: int,
) -> None:
    checkpoint_ns = 1_767_225_600_000_000_000
    interval_ns = interval_seconds * 1_000_000_000
    expected_count = horizon_hours * 3_600 // interval_seconds
    bars = [
        {
            "timestamp_ns": checkpoint_ns + offset * interval_ns,
            "available_at_ns": checkpoint_ns + (offset + 1) * interval_ns,
        }
        for offset in range(-1, expected_count + 2)
    ]
    rows = subject._future_rows_temporal_v2(
        bars,
        "2026-01-01T00:00:00Z",
        timeframe,
        horizon_hours,
    )
    assert len(rows) == expected_count
    assert rows[0]["timestamp_ns"] == checkpoint_ns
    assert rows[-1]["timestamp_ns"] == checkpoint_ns + (expected_count - 1) * interval_ns
    assert checkpoint_ns + horizon_hours * 3_600 * 1_000_000_000 not in {
        row["timestamp_ns"] for row in rows
    }
    assert all(
        checkpoint_ns < row["available_at_ns"] <= checkpoint_ns + horizon_hours * 3_600 * 1_000_000_000
        for row in rows
    )


def _minimal_synthetic_evidence() -> tuple[dict[str, object], dict[str, object]]:
    source = {
        "source_snapshot_before": {"synthetic_source": True},
        "phase11r3a_inventory": subject.PHASE11R3A_INVENTORY,
        "lineage_lifecycle_evidence_ids": dict(
            subject.PHASE11R3A_LINEAGE_LIFECYCLE_EVIDENCE_IDS
        ),
    }
    audit = subject._source_audit_payload(source, source)
    triplet = subject.contract_triplet()
    dataset_result_ids = {
        dataset: subject.deterministic_hash("test-dataset-result", dataset)
        for dataset in subject.DATASETS
    }
    decision_payload = {
        "schema_version": "trendline_v2_phase11r3b_decision_v1",
        "study_status": subject.STUDY_COMPLETE_STATUS,
        "finalist_status": subject.NO_FINALIST_STATUS,
        "finalist": None,
        "gate_record_ids": {},
        "comparison_record_ids": {},
        "gate_records": {},
        "comparison_records": {},
        "independent_control_diagnostic_ids": {},
        "independent_control_diagnostic_records": {},
        "dataset_result_ids": dataset_result_ids,
        "finalist_precedence": {},
        "unresolved_evidence_count": 0,
        "unresolved_reconciliation_count": 0,
        "source_identities": {},
        "execution": {},
        "counts": {},
    }
    decision = {
        **decision_payload,
        "decision_id": subject.deterministic_hash(
            subject.DECISION_NAMESPACE, decision_payload
        ),
    }
    lock_payload = {
        "schema_version": "trendline_v2_phase11r3b_validation_lock_v1",
        "source_identities": {},
        "lineage_lifecycle_evidence_ids": dict(
            subject.PHASE11R3A_LINEAGE_LIFECYCLE_EVIDENCE_IDS
        ),
        "contender_budget_gate_record_ids": {},
        "matched_control_comparison_record_ids": {},
        "independent_control_diagnostic_ids": {},
        "dataset_result_ids": dataset_result_ids,
        "finalist": None,
        "zero_unresolved_reconciliation": True,
        "holdout_access_count": 0,
        "temporal_access_count": 0,
        "final_decision_id": decision["decision_id"],
    }
    lock = {
        **lock_payload,
        "validation_lock_id": subject.deterministic_hash(
            subject.LOCK_NAMESPACE, lock_payload
        ),
    }
    dataset_payloads = {
        dataset: {
            "checkpoint_selection": {
                "schema_version": "checkpoint_selection",
                "dataset_id": dataset,
                "records": [],
                "structural_records": [],
            },
            "candidate_outcomes": {
                "schema_version": "candidate_outcomes",
                "dataset_id": dataset,
                "records": [],
            },
            "structural_context": {
                "schema_version": "structural_context",
                "dataset_id": dataset,
                "selection_records": [],
                "outcome_records": [],
            },
            "policy_metrics": {
                "schema_version": "policy_metrics",
                "dataset_id": dataset,
                "metrics": {},
                "dataset_result_id": dataset_result_ids[dataset],
                "evidence_id": dataset_result_ids[dataset],
            },
        }
        for dataset in subject.DATASETS
    }
    evidence = {
        "study_contract": {
            "schema_version": subject.CONTRACT_NAMESPACE,
            "contract_id": triplet["contract_id"],
            "contract_json_byte_length": triplet["canonical_json_byte_length"],
            "contract_json_sha256": triplet["canonical_json_sha256"],
            "payload": triplet["payload"],
        },
        "source_before": source,
        "source_after": source,
        "source_audit": audit,
        "validation_lock": lock,
        "decision": decision,
        "dataset_payloads": dataset_payloads,
        "csv": {
            "compression_summary.csv": [{"value": "synthetic"}],
            "coherence_summary.csv": [{"value": "synthetic"}],
            "stability_summary.csv": [{"value": "synthetic"}],
            "outcome_summary.csv": [{"value": "synthetic"}],
        },
    }
    return source, evidence


def _rebind_manifest(root: Path) -> None:
    manifest = subject._load_json(root / "manifest.json")
    members = list(item for item in subject._inventory(root) if item["path"] != "manifest.json")
    payload = {
        **manifest,
        "member_count": len(members),
        "members": members,
        "output_inventory_sha256": subject._inventory_sha256(members),
    }
    payload.pop("manifest_id", None)
    payload["manifest_id"] = subject.deterministic_hash(
        subject.MANIFEST_NAMESPACE,
        {key: value for key, value in payload.items() if key != "manifest_id"},
    )
    subject._write_json_atomic(root / "manifest.json", payload)


def test_candidate_identity_is_deterministic_and_namespaced() -> None:
    first = _candidate("support", "line-1", 100.0)
    second = _candidate("support", "line-1", 100.0)
    assert subject._candidate_observation_id(first) == subject._candidate_observation_id(second)
    assert subject._candidate_observation_id(first) != subject._candidate_observation_id(
        _candidate("resistance", "line-1", 100.0)
    )


def test_line_projection_uses_elapsed_timestamp_space() -> None:
    geometry = {
        "start_time": "2026-01-01T00:00:00Z",
        "end_time": "2026-01-01T02:00:00Z",
        "start_price": 100.0,
        "end_price": 104.0,
    }
    assert subject._line_value(geometry, subject._timestamp_ns("2026-01-01T01:00:00Z")) == 102.0


def test_joint_core_pair_is_cartesian_and_coherent() -> None:
    rows = [
        _candidate("support", "s2", 90.0),
        _candidate("support", "s1", 91.0),
        _candidate("resistance", "r2", 110.0),
        _candidate("resistance", "r1", 100.0),
    ]
    selected = subject._select_joint(
        rows,
        policy_id="joint_hash_order_control_v1",
        budget=2,
        dataset="synthetic",
        checkpoint=1,
    )
    assert selected["core_pair_identity"] is not None
    assert selected["joint_coherence_result"] is True
    assert max(selected["support_projections"].values()) < min(
        selected["resistance_projections"].values()
    )


def test_joint_selection_rejects_no_coherent_core_pair() -> None:
    selected = subject._select_joint(
        [_candidate("support", "s", 110.0), _candidate("resistance", "r", 100.0)],
        policy_id="joint_incumbent_near_v1",
        budget=1,
        dataset="synthetic",
        checkpoint=1,
    )
    assert selected["selected"] == {"support": [], "resistance": []}
    assert all(
        selected["budget_shortfall"][role]["shortfall_reason"] == "no_coherent_core_pair"
        for role in subject.ROLES
    )


def test_joint_selection_missing_role_persists_role_shortfall() -> None:
    selected = subject._select_joint(
        [_candidate("support", "s", 100.0)],
        policy_id="joint_incumbent_near_v1",
        budget=2,
        dataset="synthetic",
        checkpoint=1,
    )
    assert selected["selected"]["support"] == ["s"]
    assert selected["budget_shortfall"]["resistance"]["shortfall_reason"] == "role_missing"


def test_joint_selection_never_publishes_inversion_during_fill() -> None:
    rows = [
        _candidate("support", "s1", 90.0),
        _candidate("support", "s2", 105.0),
        _candidate("resistance", "r1", 100.0),
        _candidate("resistance", "r2", 110.0),
    ]
    selected = subject._select_joint(
        rows,
        policy_id="joint_nearest_projection_control_v1",
        budget=2,
        dataset="synthetic",
        checkpoint=1,
    )
    assert selected["joint_coherence_result"] is True
    assert any(item["reason"] == "would_invert_full_set" for item in selected["rejected"])


def test_incumbency_is_rank_priority_not_unconditional_preselection() -> None:
    previous = {"old": _candidate("support", "old", 100.0)}
    rows = [_candidate("support", "new", 90.0), _candidate("support", "old", 110.0)]
    selected = subject._select_joint(
        rows,
        policy_id="joint_incumbent_near_v1",
        budget=1,
        dataset="synthetic",
        checkpoint=2,
        previous_selected=previous,
    )
    assert selected["selected"]["support"] == ["old"]
    assert selected["retained_incumbent_ids"] == ["old"]


def test_role_transfer_is_retained_by_lineage_id() -> None:
    previous = {"line": _candidate("support", "line", 90.0)}
    selected = subject._select_joint(
        [_candidate("support", "other", 80.0), _candidate("resistance", "line", 100.0)],
        policy_id="joint_incumbent_near_v1",
        budget=1,
        dataset="synthetic",
        checkpoint=2,
        previous_selected=previous,
    )
    assert selected["retained_incumbent_ids"] == ["line"]
    assert selected["selected"]["resistance"] == ["line"]


def test_target_counts_bound_matched_control_population() -> None:
    rows = [_candidate("support", "s", 90.0), _candidate("resistance", "r", 100.0)]
    selected = subject._select_joint(
        rows,
        policy_id="joint_hash_order_control_v1",
        budget=3,
        dataset="synthetic",
        checkpoint=1,
        target_counts={"support": 1, "resistance": 1},
    )
    assert {role: len(selected["selected_rows"][role]) for role in subject.ROLES} == {
        "support": 1,
        "resistance": 1,
    }
    assert any(
        item["reason"] == "not_required_for_matched_count"
        for item in selected["rejected"]
    ) is False


def test_matched_control_excess_is_marked_not_required_for_target_count() -> None:
    rows = [
        _candidate("support", "s1", 90.0),
        _candidate("support", "s2", 91.0),
        _candidate("resistance", "r1", 100.0),
        _candidate("resistance", "r2", 101.0),
    ]
    selected = subject._select_joint(
        rows,
        policy_id="joint_hash_order_control_v1",
        budget=3,
        dataset="synthetic",
        checkpoint=1,
        target_counts={"support": 1, "resistance": 1},
    )
    assert any(
        item["reason"] == "not_required_for_matched_count"
        for item in selected["rejected"]
    )


def test_zero_shortfall_has_no_reason_even_when_role_is_absent() -> None:
    selected = subject._select_joint(
        [_candidate("support", "s", 100.0)],
        policy_id="joint_incumbent_near_v1",
        budget=1,
        dataset="synthetic",
        checkpoint=1,
        target_counts={"support": 1, "resistance": 0},
    )
    assert selected["budget_shortfall"]["resistance"] == {
        "requested_count": 0,
        "selected_count": 0,
        "shortfall_count": 0,
        "shortfall_reason": None,
    }


def test_ineligible_previous_lineages_are_excluded_from_retention_denominator() -> None:
    previous = {
        "eligible": _candidate("support", "eligible", 90.0, checkpoint=1),
        "evicted": _candidate("support", "evicted", 91.0, checkpoint=1),
    }
    first = subject._select_joint(
        list(previous.values()) + [_candidate("resistance", "r0", 110.0)],
        policy_id="joint_incumbent_near_v1",
        budget=1,
        dataset="synthetic",
        checkpoint=1,
    )
    second = subject._select_joint(
        [_candidate("support", "eligible", 90.0, checkpoint=2), _candidate("resistance", "r1", 110.0, checkpoint=2)],
        policy_id="joint_incumbent_near_v1",
        budget=1,
        dataset="synthetic",
        checkpoint=2,
        previous_selected=previous,
    )
    assert second["previous_selected_ids"] == ["eligible", "evicted"]
    assert second["eligible_previous_incumbent_ids"] == ["eligible"]
    assert second["ineligible_previous_ids"] == ["evicted"]
    metrics = subject._selection_metrics(
        [first, second],
        [],
        candidate_counts={
            ("synthetic", 1, "support"): 2,
            ("synthetic", 1, "resistance"): 1,
            ("synthetic", 2, "support"): 1,
            ("synthetic", 2, "resistance"): 1,
        },
        policy_id="joint_incumbent_near_v1",
        budget=1,
    )
    assert metrics["incumbent_retention"] == {"evaluable_count": 1, "rate": 1.0}


def test_pair_continuity_uses_stable_lineage_ids_not_observation_ids() -> None:
    first_rows = [
        _candidate("support", "s", 90.0, checkpoint=1),
        _candidate("resistance", "r", 110.0, checkpoint=1),
    ]
    first_rows[0]["candidate_observation_id"] = "s-at-1"
    first_rows[1]["candidate_observation_id"] = "r-at-1"
    second_rows = [
        _candidate("support", "s", 90.0, checkpoint=2),
        _candidate("resistance", "r", 110.0, checkpoint=2),
    ]
    second_rows[0]["candidate_observation_id"] = "s-at-2"
    second_rows[1]["candidate_observation_id"] = "r-at-2"
    first = subject._select_joint(
        first_rows,
        policy_id="joint_incumbent_near_v1",
        budget=1,
        dataset="synthetic",
        checkpoint=1,
    )
    second = subject._select_joint(
        second_rows,
        policy_id="joint_incumbent_near_v1",
        budget=1,
        dataset="synthetic",
        checkpoint=2,
        previous_selected={row["lineage_id"]: row for row in first_rows},
    )
    metrics = subject._selection_metrics(
        [first, second],
        [],
        candidate_counts={
            ("synthetic", 1, "support"): 1,
            ("synthetic", 1, "resistance"): 1,
            ("synthetic", 2, "support"): 1,
            ("synthetic", 2, "resistance"): 1,
        },
        policy_id="joint_incumbent_near_v1",
        budget=1,
    )
    assert first["core_pair_identity"] != second["core_pair_identity"]
    assert first["core_pair_lineage_ids"] == second["core_pair_lineage_ids"]
    assert metrics["pair_continuity"] == {"evaluable_count": 1, "rate": 1.0}


def test_policy_metrics_persist_required_compression_and_churn_fields() -> None:
    selection = subject._select_joint(
        [_candidate("support", "s", 90.0), _candidate("resistance", "r", 110.0)],
        policy_id="joint_incumbent_near_v1",
        budget=1,
        dataset="synthetic",
        checkpoint=1,
    )
    metrics = subject._selection_metrics(
        [selection],
        [],
        candidate_counts={
            ("synthetic", 1, "support"): 1,
            ("synthetic", 1, "resistance"): 1,
        },
        policy_id="joint_incumbent_near_v1",
        budget=1,
    )
    for field in (
        "both_role_checkpoint_coverage",
        "missing_role_count",
        "additions",
        "removals",
        "replacement_count",
        "role_specific_churn",
        "role_transfer_churn",
        "structural_context_utility",
    ):
        assert field in metrics


def _matched_selection(
    policy_id: str,
    dataset: str,
    checkpoint: int,
    *,
    contender_id: str | None = None,
) -> dict[str, object]:
    rows = [
        _candidate("support", f"s-{dataset}-{checkpoint}", 90.0, checkpoint=checkpoint),
        _candidate("resistance", f"r-{dataset}-{checkpoint}", 110.0, checkpoint=checkpoint),
    ]
    selection = subject._select_joint(
        rows,
        policy_id=policy_id,
        budget=1,
        dataset=dataset,
        checkpoint=checkpoint,
        target_counts={"support": 1, "resistance": 1}
        if contender_id is not None
        else None,
    )
    if contender_id is not None:
        selection["matched_contender_policy_id"] = contender_id
    return selection


def test_missing_matched_control_cell_is_unmatched() -> None:
    comparison = subject._matched_comparison(
        contender_id="joint_incumbent_near_v1",
        budget=1,
        control_id="joint_hash_order_control_v1",
        selections=[_matched_selection("joint_incumbent_near_v1", "btcusdt_1h", 1)],
        outcomes=[],
        candidate_counts={},
    )
    assert comparison["matched_status"] == "UNMATCHED"
    assert comparison["unresolved_reconciliation_count"] > 0
    assert comparison["expected_cell_count"] == 88
    assert comparison["control_cell_count"] == 0
    assert comparison["missing_control_cells"]


def test_duplicate_and_extra_matched_cells_are_unmatched() -> None:
    contender = _matched_selection("joint_incumbent_near_v1", "btcusdt_1h", 1)
    control_one = _matched_selection(
        "joint_hash_order_control_v1", "btcusdt_1h", 1,
        contender_id="joint_incumbent_near_v1",
    )
    control_two = _matched_selection(
        "joint_hash_order_control_v1", "btcusdt_1h", 1,
        contender_id="joint_incumbent_near_v1",
    )
    comparison = subject._matched_comparison(
        contender_id="joint_incumbent_near_v1",
        budget=1,
        control_id="joint_hash_order_control_v1",
        selections=[contender],
        outcomes=[],
        candidate_counts={},
    )
    assert comparison["matched_status"] == "UNMATCHED"
    comparison = subject._matched_comparison(
        contender_id="joint_incumbent_near_v1",
        budget=1,
        control_id="joint_hash_order_control_v1",
        selections=[contender, control_one, control_two],
        outcomes=[],
        candidate_counts={},
    )
    assert comparison["matched_status"] == "UNMATCHED"
    assert ["btcusdt_1h", 1] in comparison["duplicate_cell_keys"]


def test_complete_matched_population_requires_88_cells() -> None:
    contenders = [
        _matched_selection("joint_incumbent_near_v1", dataset, checkpoint)
        for dataset in subject.DATASETS
        for checkpoint in range(1, subject.CHECKPOINTS_PER_DATASET + 1)
    ]
    controls = [
        _matched_selection(
            "joint_hash_order_control_v1",
            dataset,
            checkpoint,
            contender_id="joint_incumbent_near_v1",
        )
        for dataset in subject.DATASETS
        for checkpoint in range(1, subject.CHECKPOINTS_PER_DATASET + 1)
    ]
    comparison = subject._matched_comparison(
        contender_id="joint_incumbent_near_v1",
        budget=1,
        control_id="joint_hash_order_control_v1",
        selections=contenders + controls,
        outcomes=[],
        candidate_counts={},
    )
    assert comparison["expected_cell_count"] == 88
    assert comparison["contender_cell_count"] == 88
    assert comparison["control_cell_count"] == 88
    assert len(comparison["exact_matched_cell_population"]) == 88
    assert comparison["matched_status"] == "MATCHED"


def test_role_transfer_updates_role_churn_without_global_lineage_churn() -> None:
    previous = _candidate("support", "line", 90.0, checkpoint=1)
    first = subject._select_joint(
        [previous],
        policy_id="joint_incumbent_near_v1",
        budget=1,
        dataset="synthetic",
        checkpoint=1,
        target_counts={"support": 1, "resistance": 0},
    )
    current = _candidate("resistance", "line", 110.0, checkpoint=2)
    second = subject._select_joint(
        [current],
        policy_id="joint_incumbent_near_v1",
        budget=1,
        dataset="synthetic",
        checkpoint=2,
        previous_selected={"line": previous},
        target_counts={"support": 0, "resistance": 1},
    )
    metrics = subject._selection_metrics(
        [first, second],
        [],
        candidate_counts={
            ("synthetic", 1, "support"): 1,
            ("synthetic", 2, "resistance"): 1,
        },
        policy_id="joint_incumbent_near_v1",
        budget=1,
    )
    assert metrics["additions"] == 0
    assert metrics["removals"] == 0
    assert metrics["role_transfer_churn"] == 1
    assert metrics["role_specific_churn"]["support"]["removals"] == 1
    assert metrics["role_specific_churn"]["resistance"]["additions"] == 1


def test_support_shortfall_uses_support_rejections_only() -> None:
    selected = subject._select_joint(
        [
            _candidate("support", "s", 90.0),
            _candidate("resistance", "r-good", 100.0),
            _candidate("resistance", "r-inverted", 80.0),
        ],
        policy_id="joint_nearest_projection_control_v1",
        budget=2,
        dataset="synthetic",
        checkpoint=1,
    )
    assert selected["budget_shortfall"]["support"]["shortfall_reason"] == (
        "insufficient_eligible_candidates"
    )
    assert any(
        item["semantic_role"] == "resistance"
        and item["reason"] == "would_invert_full_set"
        for item in selected["rejected"]
    )


def test_structural_summary_has_numeric_metrics_and_zero_denominators() -> None:
    selection = subject._select_joint(
        [_candidate("support", "s", 90.0)],
        policy_id="joint_incumbent_near_v1",
        budget=1,
        dataset="synthetic",
        checkpoint=1,
        target_counts={"support": 1, "resistance": 0},
    )
    metrics = subject._selection_metrics(
        [selection],
        [],
        candidate_counts={("synthetic", 1, "support"): 1},
        policy_id="joint_incumbent_near_v1",
        budget=1,
        structural_outcomes=[],
    )
    for horizon in map(str, subject.HORIZONS_HOURS):
        summary = metrics["structural_context_utility"][horizon]
        assert set(summary) == {
            "future_contact",
            "crossed_into_at_most_8_atr",
            "minimum_future_distance_atr",
            "distance_contraction_atr",
        }
        assert summary["minimum_future_distance_atr"] == {
            "evaluable_count": 0,
            "mean": None,
        }


def test_independent_control_can_expose_inversion_without_joint_gate() -> None:
    selected = subject._independent_selection(
        [_candidate("support", "s", 110.0), _candidate("resistance", "r", 100.0)],
        policy_id="independent_incumbent_control_v1",
        budget=1,
        dataset="synthetic",
        checkpoint=1,
    )
    assert selected["joint_coherence_result"] is False


def test_structural_context_caps_each_role_at_one() -> None:
    selected = subject._select_structural_context(
        [
            _candidate("support", "s1", 90.0, state="PERSISTED_DISTANT"),
            _candidate("support", "s2", 91.0, state="PERSISTED_DISTANT"),
            _candidate("resistance", "r1", 110.0, state="REVERSED_PERSISTED_DISTANT"),
            _candidate("resistance", "r2", 111.0, state="REVERSED_PERSISTED_DISTANT"),
        ],
        dataset="synthetic",
        checkpoint=1,
    )
    assert all(len(selected["selected"][role]) <= 1 for role in subject.ROLES)


def test_structural_context_is_separate_from_actionable_budget() -> None:
    payload = subject.contract_payload()["structural_context_lane"]
    assert payload["actionable_budget"] is False
    assert payload["actionable_denominator"] is False


def test_future_rows_are_strictly_after_checkpoint() -> None:
    rows = _future_bars()
    assert min(row["timestamp_ns"] for row in rows) > subject._timestamp_ns("2026-01-01T00:00:00Z")


def test_future_horizon_requires_exact_interval_population() -> None:
    with pytest.raises(subject.CompressionStudyError, match="future horizon row count"):
        subject._future_rows(_future_bars(95), "2026-01-01T00:00:00Z", "1h", 96)


def test_contact_formula_is_symmetric_zone_formula() -> None:
    assert subject._contact(low=99.7, high=100.2, line=100.0, atr=1.0)
    assert not subject._contact(low=101.0, high=102.0, line=100.0, atr=1.0)


def test_support_breach_requires_role_specific_close() -> None:
    assert subject._role_breach(role="support", close=99.0, line=100.0, atr=1.0)
    assert not subject._role_breach(role="support", close=99.5, line=100.0, atr=1.0)


def test_resistance_breach_requires_role_specific_close() -> None:
    assert subject._role_breach(role="resistance", close=101.0, line=100.0, atr=1.0)
    assert not subject._role_breach(role="resistance", close=100.5, line=100.0, atr=1.0)


def test_reaction_excludes_contact_bar() -> None:
    bars = _future_bars()
    bars[0]["low"] = 99.7
    bars[0]["high"] = 101.5
    row = _candidate("support", "line", 100.0)
    result = subject._evaluate_selected(
        {**row, "policy_id": "joint_incumbent_near_v1", "budget_per_role": 1},
        bars=bars,
        timeframe="1h",
        horizon_hours=96,
        derivation_type="contender",
        control_policy_id=None,
        selection_id="selection",
    )
    assert result["first_contact_offset_bars"] == 1
    assert result["post_contact_reaction"] is False


def test_reaction_starts_on_later_bar() -> None:
    bars = _future_bars()
    bars[0]["low"] = 99.7
    bars[1]["high"] = 101.1
    row = _candidate("support", "line", 100.0)
    result = subject._evaluate_selected(
        {**row, "policy_id": "joint_incumbent_near_v1", "budget_per_role": 1},
        bars=bars,
        timeframe="1h",
        horizon_hours=96,
        derivation_type="contender",
        control_policy_id=None,
        selection_id="selection",
    )
    assert result["post_contact_reaction"] is True


def test_sustained_breach_requires_two_consecutive_bars() -> None:
    bars = _future_bars()
    bars[0]["close"] = 99.0
    bars[1]["close"] = 100.0
    row = _candidate("support", "line", 100.0)
    result = subject._evaluate_selected(
        {**row, "policy_id": "joint_incumbent_near_v1", "budget_per_role": 1},
        bars=bars,
        timeframe="1h",
        horizon_hours=96,
        derivation_type="contender",
        control_policy_id=None,
        selection_id="selection",
    )
    assert result["survival"] is True


def test_candidate_outcome_identity_contains_fixed_role_and_horizon() -> None:
    bars = _future_bars()
    row = _candidate("resistance", "line", 100.0)
    result = subject._evaluate_selected(
        {**row, "policy_id": "joint_incumbent_near_v1", "budget_per_role": 1},
        bars=bars,
        timeframe="1h",
        horizon_hours=24,
        derivation_type="contender",
        control_policy_id=None,
        selection_id="selection",
    )
    assert result["semantic_role_at_selection"] == "resistance"
    assert result["horizon_hours"] == 24


def test_rate_returns_null_for_zero_denominator() -> None:
    assert subject._rate([], "survival") == {"evaluable_count": 0, "rate": None}


def test_jaccard_excludes_empty_union() -> None:
    assert subject._jaccard(set(), set()) is None
    assert subject._jaccard({"a"}, {"a", "b"}) == 0.5


def test_atomic_writer_creates_parent_and_exact_bytes(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "artifact.json"
    subject._write_json_atomic(target, {"b": 2, "a": 1})
    assert target.read_bytes() == b'{"a":1,"b":2}\n'


def test_prepare_staging_creates_missing_output_parent(tmp_path: Path) -> None:
    root = tmp_path / "missing" / "study"
    staging = subject._prepare_staging(root)
    try:
        assert root.parent.is_dir()
        assert staging.parent == root.parent
        assert staging.is_dir()
    finally:
        staging.rmdir()


def test_prepare_staging_refuses_existing_output(tmp_path: Path) -> None:
    root = tmp_path / "study"
    root.mkdir()
    with pytest.raises(subject.ContractFreezeError, match="output root refused"):
        subject._prepare_staging(root)


def test_source_snapshot_payload_is_immutable_copy() -> None:
    payload = subject.contract_payload()
    payload["sources"]["allowed_raw_paths"].append("forbidden")
    assert "forbidden" not in subject.contract_payload()["sources"]["allowed_raw_paths"]


def test_forbidden_states_do_not_enter_actionable_selection() -> None:
    assert set(subject.ACTIONABLE_STATES).isdisjoint(subject.EXCLUDED_STATES)
    assert set(subject.STRUCTURAL_CONTEXT_STATES).isdisjoint(subject.EXCLUDED_STATES)


def test_stable_lineage_hash_binds_dataset_and_lineage() -> None:
    assert subject._stable_lineage_hash("a", "line") != subject._stable_lineage_hash("b", "line")


def test_selection_id_changes_when_selected_order_changes() -> None:
    rows = [
        _candidate("support", "s1", 90.0),
        _candidate("support", "s2", 91.0),
        _candidate("resistance", "r1", 100.0),
        _candidate("resistance", "r2", 101.0),
    ]
    first = subject._select_joint(rows, policy_id="joint_hash_order_control_v1", budget=2, dataset="synthetic", checkpoint=1)
    reversed_rows = list(reversed(
        first["selected_rows"]["support"] + first["selected_rows"]["resistance"]
    ))
    assert first["selection_id"] != subject._selection_id(
        policy_id=first["policy_id"], budget=2, dataset="synthetic", checkpoint=1,
        rows=reversed_rows,
    )


def test_csv_bytes_are_deterministic() -> None:
    rows = [{"policy_id": "p", "budget": 1}]
    assert subject._csv_bytes(rows) == subject._csv_bytes(rows)


def test_compression_error_is_contract_error() -> None:
    assert issubclass(subject.CompressionStudyError, subject.ContractFreezeError)


def test_output_artifact_count_is_frozen() -> None:
    assert len(subject.EXPECTED_ARTIFACT_PATHS) == 25
    assert len(subject.EXPECTED_ARTIFACT_PATHS) - 1 == 24


def test_no_holdout_or_temporal_paths_are_contract_members() -> None:
    assert all("holdout" not in path and "temporal" not in path for path in subject.EXPECTED_ARTIFACT_PATHS)


def test_study_controls_keep_synthetic_path_out_of_production() -> None:
    controls = subject.contract_payload()["study_controls"]
    assert controls["production_allow_synthetic"] is False
    assert controls["test_synthetic_path_separate"] is True


def test_synthetic_verifier_requires_explicit_expected_evidence(tmp_path: Path) -> None:
    _source, evidence = _minimal_synthetic_evidence()
    subject._write_study_bundle(tmp_path, evidence)
    with pytest.raises(subject.CompressionStudyError, match="explicit expected evidence"):
        subject._verify_synthetic_compression_bundle_for_tests(tmp_path)
    result = subject._verify_synthetic_compression_bundle_for_tests(
        tmp_path, evidence
    )
    assert result["status"] == subject.STUDY_COMPLETE_STATUS


def test_source_backed_verifier_rejects_rehashed_forged_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, evidence = _minimal_synthetic_evidence()
    subject._write_study_bundle(tmp_path, evidence)
    monkeypatch.setattr(subject, "_verify_r3a_source", lambda: source)
    monkeypatch.setattr(
        subject,
        "_derive_compression_evidence",
        lambda _verified_source: evidence,
    )
    subject.verify_compression_bundle(tmp_path)

    decision = subject._load_json(tmp_path / "decision.json")
    decision["finalist"] = "forged"
    decision_body = {
        key: value for key, value in decision.items() if key != "decision_id"
    }
    decision["decision_id"] = subject.deterministic_hash(
        subject.DECISION_NAMESPACE, decision_body
    )
    subject._write_json_atomic(tmp_path / "decision.json", decision)
    lock = subject._load_json(tmp_path / "validation_lock.json")
    lock["final_decision_id"] = decision["decision_id"]
    lock_body = {
        key: value for key, value in lock.items() if key != "validation_lock_id"
    }
    lock["validation_lock_id"] = subject.deterministic_hash(
        subject.LOCK_NAMESPACE, lock_body
    )
    subject._write_json_atomic(tmp_path / "validation_lock.json", lock)
    manifest = subject._load_json(tmp_path / "manifest.json")
    manifest["decision_id"] = decision["decision_id"]
    manifest["validation_lock_id"] = lock["validation_lock_id"]
    subject._write_json_atomic(tmp_path / "manifest.json", manifest)
    _rebind_manifest(tmp_path)

    with pytest.raises(subject.CompressionStudyError, match="source-derived artifact mismatch"):
        subject.verify_compression_bundle(tmp_path)
