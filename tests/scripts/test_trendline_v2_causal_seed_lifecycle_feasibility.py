"""Contract-freeze tests for Phase 11R.3A.

No lifecycle replay, evidence-bundle load, provider, network, holdout or
temporal execution belongs in this suite.
"""

from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import analyze_trendline_v2_causal_seed_lifecycle_feasibility as subject


EXPECTED_TOP_LEVEL = {
    "schema_version",
    "base_commit",
    "phase11r1_dependency",
    "phase11r2_dependency",
    "sources",
    "independence",
    "targets",
    "lineage_identity",
    "lifecycle_clock",
    "state_machine",
    "policies",
    "gap_recovery",
    "policy_metrics",
    "future_evaluation",
    "transition_evidence",
    "reconciliation",
    "artifacts",
    "execution_accounting",
    "decision",
    "study_controls",
}


def test_contract_triplet_is_canonical_and_self_consistent() -> None:
    triplet = subject.contract_triplet()
    assert triplet["contract_id"] == subject.CONTRACT_ID
    assert triplet["canonical_json_sha256"] == subject.CONTRACT_JSON_SHA256
    assert triplet["canonical_json_byte_length"] == subject.CONTRACT_JSON_BYTE_LENGTH
    assert len(triplet["canonical_json"].encode()) == subject.CONTRACT_JSON_BYTE_LENGTH
    assert json.loads(triplet["canonical_json"]) == triplet["payload"]


def test_contract_has_exact_revised_top_level_structure() -> None:
    payload = subject.contract_payload()
    assert set(payload) == EXPECTED_TOP_LEVEL
    assert "decision_statuses" not in payload
    assert "decision_evidence_flags" not in payload
    assert set(payload["decision"]) == {"statuses", "evidence_flags", "freeze_status", "study_result"}


@pytest.mark.parametrize("section", sorted(EXPECTED_TOP_LEVEL - {"schema_version", "base_commit"}))
def test_drift_in_every_revised_section_changes_identity(section: str) -> None:
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


def test_phase_dependency_bindings_are_exact() -> None:
    payload = subject.contract_payload()
    r1 = payload["phase11r1_dependency"]
    r2 = payload["phase11r2_dependency"]
    assert r1["commit"] == subject.PHASE11R1_COMMIT
    assert r1["script_git_blob"] == subject.PHASE11R1_SCRIPT_BLOB
    assert r1["script_sha256"] == subject.PHASE11R1_SCRIPT_SHA256
    assert r1["contract_id"] == subject.PHASE11R1_CONTRACT_ID
    assert r1["decision_id"] == subject.PHASE11R1_DECISION_ID
    assert r1["manifest_id"] == subject.PHASE11R1_MANIFEST_ID
    assert r1["inventory_sha256"] == subject.PHASE11R1_INVENTORY
    assert r2["commit"] == subject.PHASE11R2_COMMIT
    assert r2["script_git_blob"] == subject.PHASE11R2_SCRIPT_BLOB
    assert r2["script_sha256"] == subject.PHASE11R2_SCRIPT_SHA256
    assert r2["contract_id"] == subject.PHASE11R2_CONTRACT_ID
    assert r2["decision_id"] == subject.PHASE11R2_DECISION_ID
    assert r2["manifest_id"] == subject.PHASE11R2_MANIFEST_ID
    assert r2["inventory_sha256"] == subject.PHASE11R2_INVENTORY


def test_scope_and_forbidden_sources_are_frozen() -> None:
    payload = subject.contract_payload()
    targets = payload["targets"]
    sources = payload["sources"]
    independence = payload["independence"]
    assert targets["datasets"] == list(subject.DATASETS)
    assert targets["checkpoint_count"] == 88
    assert targets["phase11r2_provider_role_missing_cases"] == 52
    assert targets["phase11r2_unique_seed_gaps"] == 26
    assert sources["raw_sui_reads"] == "prohibited"
    assert sources["temporal_reads"] == "prohibited"
    assert len(sources["allowed_raw_paths"]) == 4
    assert all("sui" not in path for path in sources["allowed_raw_paths"])
    assert independence["network_requests"] == 0
    assert independence["runtime_v2_provider_executions"] == 0
    assert independence["legacy_executions"] == 0


def test_lineage_identity_uses_only_original_anchor_identity_fields() -> None:
    base = dict(
        asset="BTCUSDT",
        timeframe="1h",
        original_anchor_role="support",
        first_anchor_pivot_id="p1",
        second_anchor_pivot_id="p2",
    )
    original = subject.lineage_identity(**base)
    for excluded in subject.LINEAGE_ID_EXCLUDED_FIELDS:
        assert excluded not in subject.LINEAGE_ID_FIELDS
        assert subject.lineage_identity(**base) == original
    for field in subject.LINEAGE_ID_FIELDS:
        mutated = dict(base)
        mutated[field] = f"{mutated[field]}-changed"
        assert subject.lineage_identity(**mutated) != original


def test_lineage_universe_and_fixed_geometry_are_frozen() -> None:
    lineage = subject.contract_payload()["lineage_identity"]
    assert "anchor pair becomes lifecycle-eligible" in lineage["eligibility_rule"]
    assert lineage["geometry_immutable"] is True
    assert lineage["geometry_available_after_seed_eviction"] is True
    assert lineage["geometry_fields"] == [
        "first_anchor_timestamp",
        "first_anchor_price",
        "second_anchor_timestamp",
        "second_anchor_price",
        "exact_timestamp_space_line_geometry",
        "original_anchor_role",
    ]
    assert lineage["refitting"] == "prohibited"
    assert lineage["reanchoring"] == "prohibited"
    assert lineage["pivot_replacement"] == "prohibited"
    assert lineage["slope_adjustment"] == "prohibited"


def test_strict_active_near_is_reserved_for_exact_r1_seed() -> None:
    state = subject.contract_payload()["state_machine"]
    assert state["strict_active_near"]["source"] == "exact_current_phase11r1_strict_seed_pool"
    assert state["strict_active_near"]["historical_reentry_without_current_seed"] is False
    assert state["persisted_active_near"]["currently_absent_from_exact_phase11r1_seed"] is True
    assert state["persisted_active_near"]["actionable"] is True
    assert "PERSISTED_ACTIVE_NEAR" in state["states"]
    assert subject.lineage_is_eligible(appears_in_exact_strict_seed=True)
    assert not subject.lineage_is_eligible(appears_in_exact_strict_seed=False)


def test_state_to_semantic_role_mapping_preserves_last_active_boundary() -> None:
    mapping = subject.contract_payload()["state_machine"]["semantic_role_by_state"]
    assert mapping["NOT_YET_STRICT_ACTIVE"] is None
    assert mapping["STRICT_ACTIVE_NEAR"] == "original_anchor_role"
    assert mapping["PERSISTED_ACTIVE_NEAR"] == "original_anchor_role"
    assert mapping["PERSISTED_DISTANT"] == "original_anchor_role"
    assert mapping["REVERSAL_PENDING"] is None
    assert mapping["REVERSED_ACTIVE_NEAR"] == "opposite_of_original_anchor_role"
    assert mapping["REVERSED_PERSISTED_DISTANT"] == "opposite_of_original_anchor_role"
    assert mapping["RETIRED"] is None
    assert subject.semantic_role_for_state("REVERSAL_PENDING", "support") is None
    assert subject.semantic_role_for_state("RETIRED", "support") is None
    assert subject.semantic_role_for_state("REVERSED_ACTIVE_NEAR", "support") == "resistance"
    assert subject.semantic_role_for_state("PERSISTED_DISTANT", "resistance") == "resistance"
    assert subject.contract_payload()["state_machine"]["last_active_semantic_role_persisted_for"] == [
        "REVERSAL_PENDING",
        "RETIRED",
    ]


def test_lifecycle_clock_freezes_checkpoint_and_bar_replay() -> None:
    clock = subject.contract_payload()["lifecycle_clock"]
    assert clock["strict_seed_entry"] == "scheduled_daily_checkpoints_only"
    assert clock["bar_level_replay"] == "every_owner_timeframe_bar_between_checkpoints"
    assert clock["available_at_formula"] == "candle_timestamp + timeframe_interval"
    assert clock["transition_effective_at"] == "available_at"
    assert clock["checkpoint_state"] == "after every bar with available_at <= checkpoint"
    assert clock["interval_processing"] == "previous_checkpoint < available_at <= current_checkpoint"
    assert subject.available_at(100, "1h") == 3_700
    assert subject.checkpoint_processes_bar(
        previous_checkpoint=3_600,
        current_checkpoint=7_200,
        candle_timestamp=3_600,
        timeframe="1h",
    )
    assert not subject.checkpoint_processes_bar(
        previous_checkpoint=3_600,
        current_checkpoint=7_200,
        candle_timestamp=0,
        timeframe="1h",
    )


def test_bar_replay_precedes_checkpoint_classification_and_distance_is_checkpoint_only() -> None:
    clock = subject.contract_payload()["lifecycle_clock"]
    assert clock["checkpoint_processing_order"] == [
        "replay_bar_events_previous_checkpoint_lt_available_at_le_current_checkpoint",
        "apply_scheduled_checkpoint_strict_seed_membership",
        "classify_near_distant_using_last_completed_bar",
    ]
    assert clock["bar_event_types"] == [
        "same_role_sustained_breach",
        "post_breach_reversal_contact",
        "reversed_role_sustained_breach",
        "projection_invalidation",
    ]
    assert clock["checkpoint_only_classifications"] == [
        "exact_current_r1_strict_seed_membership",
        "persisted_active_near_vs_persisted_distant",
        "reversed_active_near_vs_reversed_persisted_distant",
    ]
    assert clock["checkpoint_state_change_effective_at"] == "checkpoint_timestamp"
    assert clock["bar_event_state_change_effective_at"] == "triggering_bar_available_at"
    assert clock["checkpoint_distance_formula"] == (
        "abs(last_completed_close - line_at_checkpoint) / "
        "ATR_of_last_completed_bar"
    )


def test_state_retention_is_allowed_without_transition_event() -> None:
    state = subject.contract_payload()["state_machine"]
    assert all(state["state_retention_allowed"][name] for name in subject.NONTERMINAL_STATES)
    assert state["state_retention_allowed"]["RETIRED"] is False
    assert state["retention_is_not_transition_event"] is True
    assert subject.legal_transition("PERSISTED_DISTANT", "PERSISTED_DISTANT")
    assert not subject.legal_transition("RETIRED", "RETIRED")
    assert state["retired"]["terminal_state_persists"] is True
    assert state["retired"]["terminal_retention_is_not_transition_event"] is True
    assert subject.semantic_role_for_state("RETIRED", "support") is None


def test_event_precedence_and_projection_retirement_are_frozen() -> None:
    state = subject.contract_payload()["state_machine"]
    assert state["event_precedence"]["original_role"] == [
        "same_role_sustained_breach_to_reversal_pending",
        "nonpositive_or_nonfinite_projection_to_retired",
        "exact_current_strict_seed_to_strict_active_near",
        "unbreached_distance_at_most_8_atr_to_persisted_active_near",
        "unbreached_distance_above_8_atr_to_persisted_distant",
    ]
    assert state["retired"]["retirement_reasons"] == list(subject.RETIREMENT_REASONS)
    assert "original_projection_invalid" in subject.TRANSITION_TRIGGERS
    assert "reversed_projection_invalid" in subject.TRANSITION_TRIGGERS


def test_original_support_and_resistance_breach_formulas_are_exact() -> None:
    state = subject.contract_payload()["state_machine"]
    rules = state["original_role_breach"]
    assert rules["support"] == "two_consecutive_closes_below_line_minus_0.5_ATR_at_bar"
    assert rules["resistance"] == "two_consecutive_closes_above_line_plus_0.5_ATR_at_bar"
    assert rules["line_value"] == "line_geometry_evaluated_at_each_bar_timestamp"
    assert rules["atr"] == "ATR_at_evaluated_owner_timeframe_bar"
    assert subject.original_role_breach(
        role="support", close=99.0, line=100.0, atr=1.0
    )
    assert subject.original_role_breach(
        role="resistance", close=101.0, line=100.0, atr=1.0
    )
    assert not subject.original_role_breach(
        role="support", close=99.6, line=100.0, atr=1.0
    )
    assert not subject.original_role_breach(
        role="resistance", close=100.4, line=100.0, atr=1.0
    )


def test_original_breach_counter_increments_only_after_activation_and_resets() -> None:
    rules = subject.contract_payload()["state_machine"]["original_role_breach"]
    assert rules["counter_increments_on_breaching_close"] is True
    assert rules["counter_resets_on_non_breaching_close"] is True
    assert rules["counter_starts_after_strict_lineage_activation"] is True
    assert subject.update_breach_counter(
        0, breaching_close=True, strict_lineage_active=False
    ) == 0
    assert subject.update_breach_counter(
        0, breaching_close=True, strict_lineage_active=True
    ) == 1
    assert subject.update_breach_counter(
        1, breaching_close=True, strict_lineage_active=True
    ) == 2
    assert subject.update_breach_counter(
        2, breaching_close=False, strict_lineage_active=True
    ) == 0


def test_pending_can_retain_and_reversed_distant_requires_contact() -> None:
    state = subject.contract_payload()["state_machine"]
    assert state["reversal_pending"]["can_retain_across_checkpoints"] is True
    assert state["reversal_pending"]["contact_required_for_activation"] is True
    assert state["reversal_pending"]["breach_bar_is_contact"] is False
    assert subject.legal_transition("REVERSAL_PENDING", "REVERSAL_PENDING")
    assert not subject.legal_transition(
        "REVERSAL_PENDING", "REVERSED_PERSISTED_DISTANT"
    )
    assert not subject.transition_allowed(
        "REVERSAL_PENDING",
        "REVERSED_PERSISTED_DISTANT",
        reversal_contact_confirmed=False,
    )
    assert subject.transition_allowed(
        "REVERSAL_PENDING",
        "REVERSED_PERSISTED_DISTANT",
        reversal_contact_confirmed=True,
    )
    assert state["reversed_persisted_distant"]["activation"] == "confirmed_post_breach_contact"


def test_reversal_contact_and_reversed_breach_chronology_are_frozen() -> None:
    state = subject.contract_payload()["state_machine"]
    reversed_near = state["reversed_active_near"]
    breach = state["reversed_role_breach"]
    contact = state["reversal_contact"]
    assert reversed_near["contact_strictly_after_breach"] is True
    assert reversed_near["one_role_flip_maximum"] is True
    assert reversed_near["contact_tolerance_atr"] == 0.35
    assert contact["formula"] == (
        "low <= line + 0.35 * ATR_at_contact_bar and "
        "high >= line - 0.35 * ATR_at_contact_bar"
    )
    assert contact["availability"] == (
        "contact_bar_available_at > second_breach_bar_available_at"
    )
    assert contact["activation_bar_is_reaction"] is False
    assert contact["activation_bar_is_first_reversed_role_breach"] is False
    assert subject.reversal_contact_confirmed(
        low=99.0,
        high=101.0,
        line=100.0,
        atr=1.0,
        contact_available_at=20,
        second_breach_available_at=10,
    )
    assert not subject.reversal_contact_confirmed(
        low=99.0,
        high=101.0,
        line=100.0,
        atr=1.0,
        contact_available_at=10,
        second_breach_available_at=10,
    )
    assert breach["support_to_resistance"] == "two_consecutive_closes_above_line_plus_0.5_ATR"
    assert breach["resistance_to_support"] == "two_consecutive_closes_below_line_minus_0.5_ATR"
    assert breach["counter_starts_after_first_valid_reversal_contact"] is True
    assert breach["activation_contact_cannot_be_first_breach_bar"] is True


def test_policies_are_mechanism_separated() -> None:
    policies = subject.contract_payload()["policies"]
    assert policies["strict_seed_baseline_v1"]["included_states"] == ["STRICT_ACTIVE_NEAR"]
    assert policies["persist_unbreached_lineage_v1"]["included_states"] == [
        "STRICT_ACTIVE_NEAR",
        "PERSISTED_ACTIVE_NEAR",
        "PERSISTED_DISTANT",
    ]
    assert policies["confirmed_single_role_reversal_v1"]["included_states"] == [
        "STRICT_ACTIVE_NEAR",
        "REVERSED_ACTIVE_NEAR",
        "REVERSED_PERSISTED_DISTANT",
    ]
    assert policies[subject.UNION_POLICY]["included_states"] == [
        "STRICT_ACTIVE_NEAR",
        "PERSISTED_ACTIVE_NEAR",
        "REVERSED_ACTIVE_NEAR",
        "PERSISTED_DISTANT",
        "REVERSED_PERSISTED_DISTANT",
    ]
    assert policies[subject.UNION_POLICY]["unavailable_states"] == [
        "NOT_YET_STRICT_ACTIVE",
        "REVERSAL_PENDING",
        "RETIRED",
    ]
    assert policies[subject.UNION_POLICY]["descriptive_only"] is True
    assert policies[subject.UNION_POLICY]["provider_ranking"] is False


def test_gap_key_and_current_role_binding_are_exact() -> None:
    gap = subject.contract_payload()["gap_recovery"]
    assert gap["unique_gap_key"] == list(subject.UNIQUE_GAP_KEY_FIELDS)
    assert gap["provider_role_key_maps_two_to_one"] is True
    assert gap["provider_role_cases"] == 52
    assert gap["unique_gap_keys"] == 26
    assert gap["provider_role_to_unique_gap_ratio"] == "2:1"
    assert gap["candidate_current_role_must_equal_gap_role"] is True
    assert subject.candidate_recovers_gap(
        current_semantic_role="support", gap_role="support"
    )
    assert not subject.candidate_recovers_gap(
        current_semantic_role="resistance", gap_role="support"
    )


def test_gap_aggregation_prefers_actionable_and_unions_mechanisms() -> None:
    candidates = [
        {"state": "PERSISTED_DISTANT", "mechanisms": ["DISTANCE_PERSISTENCE"]},
        {"state": "REVERSED_ACTIVE_NEAR", "mechanisms": ["ROLE_REVERSAL"]},
    ]
    result = subject.aggregate_gap_recovery(candidates, provider_role_records=2)
    assert result == {
        "recovery_status": "ACTIONABLE",
        "recovery_mechanisms": ["DISTANCE_PERSISTENCE", "ROLE_REVERSAL"],
        "unrecovered_reason": None,
    }


def test_gap_aggregation_requires_exact_two_provider_role_records() -> None:
    with pytest.raises(subject.ContractFreezeError, match="exactly two"):
        subject.aggregate_gap_recovery([], provider_role_records=1)


def test_observation_deduplication_and_zero_denominator_semantics() -> None:
    observations = [
        ("btcusdt_1h", 1, "support", "lineage-1"),
        ("btcusdt_1h", 1, "support", "lineage-1"),
        ("btcusdt_1h", 1, "support", "lineage-2"),
    ]
    assert subject.unique_observation_keys(observations) == (
        ("btcusdt_1h", 1, "support", "lineage-1"),
        ("btcusdt_1h", 1, "support", "lineage-2"),
    )
    assert subject.outcome_rate(0, 0) == {"rate": None, "evaluable_count": 0}
    assert subject.outcome_rate(2, 4) == {"rate": 0.5, "evaluable_count": 4}


def test_candidate_and_gap_outcome_rates_use_distinct_denominators() -> None:
    outcomes = [
        {"evaluable": True, "successful": False},
        {"evaluable": True, "successful": True},
        {"evaluable": False, "successful": True},
    ]
    assert subject.candidate_outcome_rate(outcomes) == {
        "rate": 0.5,
        "evaluable_count": 2,
    }
    assert subject.gap_outcome_rate(outcomes) == {
        "rate": 1.0,
        "evaluable_count": 1,
    }


def test_expanded_structural_median_includes_all_176_cells_and_zeros() -> None:
    counts = [0] * 176
    counts[0] = 4
    assert subject.expanded_structural_cell_median(counts) == 0.0
    with pytest.raises(subject.ContractFreezeError, match="176"):
        subject.expanded_structural_cell_median([1])


@pytest.mark.parametrize(
    ("state", "expected_status", "expected_mechanisms"),
    [
        ("STRICT_ACTIVE_NEAR", "ACTIONABLE", []),
        ("PERSISTED_ACTIVE_NEAR", "ACTIONABLE", ["DISTANCE_PERSISTENCE"]),
        ("PERSISTED_DISTANT", "STRUCTURAL_ONLY", ["DISTANCE_PERSISTENCE"]),
        ("REVERSED_ACTIVE_NEAR", "ACTIONABLE", ["ROLE_REVERSAL"]),
        ("REVERSED_PERSISTED_DISTANT", "STRUCTURAL_ONLY", ["ROLE_REVERSAL"]),
    ],
)
def test_recovery_truth_table(
    state: str, expected_status: str, expected_mechanisms: list[str]
) -> None:
    result = subject.classify_recovery(state=state)
    assert result == {
        "recovery_status": expected_status,
        "recovery_mechanisms": expected_mechanisms,
        "unrecovered_reason": None,
    }


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"prior_strict_lineage": False}, "NO_PRIOR_STRICT_LINEAGE"),
        ({"reversal_pending_without_contact": True}, "REVERSAL_PENDING_NO_CONTACT"),
        ({"all_relevant_lineages_retired": True}, "ALL_RELEVANT_LINEAGES_RETIRED"),
    ],
)
def test_unrecovered_reasons_are_orthogonal(
    kwargs: dict[str, bool], reason: str
) -> None:
    result = subject.classify_recovery(state="REVERSAL_PENDING", **kwargs)
    assert result["recovery_status"] == "NOT_RECOVERED"
    assert result["recovery_mechanisms"] == []
    assert result["unrecovered_reason"] == reason


@pytest.mark.parametrize(
    ("timeframe", "horizon", "bars"),
    [
        ("1h", 24, 24),
        ("1h", 48, 48),
        ("1h", 96, 96),
        ("4h", 24, 6),
        ("4h", 48, 12),
        ("4h", 96, 24),
    ],
)
def test_future_horizon_bar_counts_are_exact(
    timeframe: str, horizon: int, bars: int
) -> None:
    assert subject.future_horizon_bars(timeframe, horizon) == bars


def test_future_evaluation_formulas_are_exact_and_role_aware() -> None:
    future = subject.contract_payload()["future_evaluation"]
    assert future["horizons_hours"] == [24, 48, 96]
    assert future["future_rule"] == "checkpoint_plus_interval_through_horizon_endpoint_exactly"
    assert future["candidate_key"] == list(subject.CANDIDATE_KEY_FIELDS)
    assert future["same_contact_bar_reaction"] is False
    assert future["near_line"]["zone_contact"] == (
        "low <= line + 0.35 * ATR_at_evaluated_bar and "
        "high >= line - 0.35 * ATR_at_evaluated_bar"
    )
    assert future["near_line"]["reaction_window"] == "strictly_after_first_contact_and_before_sustained_breach"
    assert future["near_line"]["support_reaction"] == "future_high - contact_line >= 1 * contact_bar_ATR"
    assert future["near_line"]["resistance_reaction"] == "contact_line - future_low >= 1 * contact_bar_ATR"
    assert future["near_line"]["reaction_atr"] == "ATR_at_first_contact"
    assert future["structural_only"]["zone_contact_within_horizon"] == (
        "low <= line + 0.35 * ATR_at_evaluated_bar and "
        "high >= line - 0.35 * ATR_at_evaluated_bar"
    )
    assert future["structural_only"]["minimum_future_distance_atr"] == "minimum(abs(close - line_at_bar) / ATR_at_bar)"
    assert future["structural_only"]["initial_distance_atr"] == "abs(last_completed_close - line_at_checkpoint) / ATR_of_last_completed_bar"
    assert future["structural_only"]["distance_contraction_atr"] == "initial_distance_atr - minimum_future_distance_atr"
    assert future["structural_only"]["crossed_into_at_most_8_atr"] == "any future distance <= 8"


def test_policy_coverage_and_inflation_formulas_are_frozen() -> None:
    metrics = subject.contract_payload()["policy_metrics"]
    assert metrics["coverage_denominator"] == 176
    assert metrics["coverage_denominator_formula"] == "4 datasets * 22 checkpoints * 2 roles"
    assert metrics["zero_strict_denominator"] == "block"
    assert metrics["observation_key"] == list(subject.CANDIDATE_KEY_FIELDS)
    assert metrics["strict_observation_states"] == ["STRICT_ACTIVE_NEAR"]
    assert metrics["expanded_actionable_observation_states"] == [
        "STRICT_ACTIVE_NEAR",
        "PERSISTED_ACTIVE_NEAR",
        "REVERSED_ACTIVE_NEAR",
    ]
    assert metrics["expanded_structural_observation_states"] == [
        "STRICT_ACTIVE_NEAR",
        "PERSISTED_ACTIVE_NEAR",
        "REVERSED_ACTIVE_NEAR",
        "PERSISTED_DISTANT",
        "REVERSED_PERSISTED_DISTANT",
    ]
    assert metrics["observation_identity"] == "unique_observation_keys_only"
    assert metrics["candidate_inflation_ratio"] == (
        "count(unique expanded structural observations) / "
        "count(unique strict observations)"
    )
    assert metrics["cell_count_statistics_population"] == (
        "expanded_structural_counts_over_all_176_cells_including_zero"
    )
    assert metrics["additional_counts"] == [
        "added_actionable_lineage_observations",
        "added_structural_lineage_observations_structural_only_count",
        "maximum_lineages_per_checkpoint_role_cell",
        "median_lineages_per_checkpoint_role_cell",
    ]
    assert metrics["outcome_rates"]["unique_gap_level"]["aggregation"] == "any_candidate_succeeds"
    assert metrics["outcome_rates"]["unique_gap_level"]["headline_decision_level"] is True
    assert metrics["outcome_rates"]["zero_denominator"] == "null_with_zero_evaluable_count"


def test_transition_evidence_schema_is_complete() -> None:
    evidence = subject.contract_payload()["transition_evidence"]
    required = {
        "lineage_id",
        "dataset_id",
        "previous_state",
        "current_state",
        "trigger",
        "effective_at",
        "checkpoint_observed_at",
        "original_anchor_role",
        "current_semantic_role",
        "fixed_geometry",
        "projection_at_checkpoint",
        "distance_atr",
        "first_same_role_breach_bar",
        "second_same_role_breach_bar",
        "first_reversal_contact_bar",
        "reversal_count",
        "retirement_reason",
        "source_input_identity",
    }
    assert set(evidence["fields"]) == required
    assert evidence["fixed_geometry_fields"] == subject.contract_payload()["lineage_identity"]["geometry_fields"]
    assert evidence["no_op_retention_recorded_in_checkpoint_state"] is True
    assert evidence["no_op_retention_persisted_as_transition"] is False
    assert evidence["effective_at_uses_available_at"] is True


def test_artifact_inventory_and_execution_accounting_remain_frozen() -> None:
    payload = subject.contract_payload()
    artifacts = payload["artifacts"]
    assert artifacts["total_file_count"] == 23
    assert artifacts["manifest_member_count"] == 22
    assert all("sui" not in path for path in artifacts["paths"])
    assert all("temporal" not in path for path in artifacts["paths"])
    accounting = payload["execution_accounting"]
    assert accounting == {
        "validation_datasets": 4,
        "checkpoints": 88,
        "checkpoint_reconstruction_repeats": 2,
        "checkpoint_reconstructions": 176,
        "phase11r1_evidence_verifications": 1,
        "phase11r2_evidence_verifications": 1,
        "raw_sui_accesses": 0,
        "temporal_accesses": 0,
        "network_requests": 0,
        "legacy_executions": 0,
        "runtime_v2_provider_executions": 0,
    }


def test_decision_contains_statuses_and_evidence_flags() -> None:
    decision = subject.contract_payload()["decision"]
    assert decision["statuses"] == list(subject.DECISION_STATUSES)
    assert "candidate_inflation_ratio" in decision["evidence_flags"]
    assert "unrecovered_gap_count" in decision["evidence_flags"]
    assert "recovered_actionable_gap_48h_survival_rate" in decision["evidence_flags"]
    assert "recovered_actionable_gap_96h_survival_rate" in decision["evidence_flags"]
    assert "recovered_actionable_gap_96h_contact_rate" in decision["evidence_flags"]
    assert "recovered_actionable_48h_survival_rate" not in decision["evidence_flags"]
    assert decision["freeze_status"] == subject.FREEZE_STATUS
    assert decision["study_result"] == "not_evaluated"


def test_contract_payload_is_defensively_copied_and_mutation_rejected() -> None:
    first = subject.contract_payload()
    first["targets"]["datasets"].append("suiusdt_1h")
    assert "suiusdt_1h" not in subject.contract_payload()["targets"]["datasets"]
    mutated = copy.deepcopy(subject.contract_payload())
    mutated["state_machine"]["strict_active_near"]["maximum_distance_atr"] = 9.0
    with pytest.raises(subject.ContractFreezeError):
        subject.validate_contract_identity(mutated)


def test_execution_guard_and_verify_cli_remain_contract_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "guarded-study"
    monkeypatch.delenv("TRENDLINE_V2_ALLOW_PHASE11R3A_LIFECYCLE_STUDY", raising=False)
    with pytest.raises(subject.ContractFreezeError, match="guard"):
        subject._execution_guard(root)
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R3A_LIFECYCLE_STUDY", "1")
    subject._execution_guard(root)
    if not subject.OUTPUT_ROOT.exists():
        assert subject.main(["--verify"]) == 0
        output = capsys.readouterr().out
        assert subject.CONTRACT_ID in output
        assert subject.FREEZE_STATUS in output


def test_imported_engines_are_only_frozen_dependencies() -> None:
    assert subject.phase11r1.__name__.endswith(
        "analyze_trendline_v2_independent_sparse_geometry"
    )
    assert subject.phase11r2.__name__.endswith(
        "analyze_trendline_v2_sparse_geometry_failure_attribution"
    )


def test_freeze_status_is_not_study_completion() -> None:
    assert subject.FREEZE_STATUS == "READY_FOR_CONTRACT_FREEZE_REVIEW"
    assert subject.FREEZE_STATUS not in subject.DECISION_STATUSES


def test_existing_output_root_refusal_is_pure() -> None:
    with pytest.raises(subject.ContractFreezeError):
        subject.require_fresh_output_root(Path(__file__))


def _synthetic_lifecycle_inputs(*, strict_second: bool = False) -> dict[str, object]:
    utc = timezone.utc
    origin = datetime(2024, 1, 1, tzinfo=utc)
    first = origin
    second = origin + timedelta(hours=2)
    geometry = {
        "start_time": subject._iso(first),
        "end_time": subject._iso(second),
        "start_price": 100.0,
        "end_price": 100.0,
    }
    lineage_id = subject.lineage_identity(
        asset="BTCUSDT",
        timeframe="1h",
        original_anchor_role="support",
        first_anchor_pivot_id="pivot-1",
        second_anchor_pivot_id="pivot-2",
    )
    lineage = subject.LifecycleLineage(
        lineage_id=lineage_id,
        dataset_id="synthetic_1h",
        asset="BTCUSDT",
        timeframe="1h",
        original_anchor_role="support",
        first_anchor_pivot_id="pivot-1",
        second_anchor_pivot_id="pivot-2",
        first_anchor_timestamp=subject._iso(first),
        first_anchor_price=100.0,
        second_anchor_timestamp=subject._iso(second),
        second_anchor_price=100.0,
        first_strict_checkpoint=1,
        source_input_identity="synthetic-input-1",
        geometry=geometry,
    )
    closes = [100.0, 100.0, 100.0, 100.0, 99.0, 99.0, 100.0, 101.0, 101.0, 100.0]
    bars = tuple(
        subject.LifecycleBar(
            timestamp_ns=subject._datetime_to_ns(origin + timedelta(hours=index)),
            available_at_ns=subject._datetime_to_ns(origin + timedelta(hours=index + 1)),
            high=max(close, 100.0) + 0.2,
            low=min(close, 100.0) - 0.2,
            close=close,
            atr=1.0,
        )
        for index, close in enumerate(closes)
    )
    checkpoints = (
        subject.LifecycleCheckpoint(
            dataset_id="synthetic_1h",
            checkpoint_index=1,
            observed_at=subject._iso(origin + timedelta(hours=4)),
            source_input_identity="synthetic-input-1",
            strict_lineage_ids=(lineage_id,),
            last_completed_timestamp_ns=bars[3].timestamp_ns,
        ),
        subject.LifecycleCheckpoint(
            dataset_id="synthetic_1h",
            checkpoint_index=2,
            observed_at=subject._iso(origin + timedelta(hours=8)),
            source_input_identity="synthetic-input-2",
            strict_lineage_ids=() if not strict_second else (lineage_id,),
            last_completed_timestamp_ns=bars[7].timestamp_ns,
        ),
        subject.LifecycleCheckpoint(
            dataset_id="synthetic_1h",
            checkpoint_index=3,
            observed_at=subject._iso(origin + timedelta(hours=10)),
            source_input_identity="synthetic-input-3",
            strict_lineage_ids=(),
            last_completed_timestamp_ns=bars[9].timestamp_ns,
        ),
    )
    return {
        "lineages": (lineage,),
        "checkpoints": {"synthetic_1h": checkpoints},
        "bars": {"synthetic_1h": bars},
    }


def test_lineage_geometry_is_frozen_and_entry_requires_strict_seed() -> None:
    inputs = _synthetic_lifecycle_inputs()
    lineage = inputs["lineages"][0]
    with pytest.raises(TypeError):
        lineage.geometry["start_price"] = 101.0
    lifecycle = subject.derive_lifecycle_evidence(**inputs)
    states = lifecycle["checkpoint_states"]["synthetic_1h"]
    assert states[0]["state"] == "STRICT_ACTIVE_NEAR"
    assert states[0]["current_semantic_role"] == "support"


def test_r2_seed_pairs_derive_independent_strict_lineage_ids() -> None:
    payload = {
        "roles": {
            "support": {
                "final_seed_ids": ["seed-support"],
                "pairs": [
                    {
                        "seed_id": "seed-support",
                        "first_pivot_id": "support-first",
                        "second_pivot_id": "support-second",
                    }
                ],
            },
            "resistance": {
                "final_seed_ids": ["seed-resistance"],
                "pairs": [
                    {
                        "seed_id": "seed-resistance",
                        "first_pivot_id": "resistance-first",
                        "second_pivot_id": "resistance-second",
                    }
                ],
            },
        }
    }
    expected = subject._strict_lineage_ids_from_r2_checkpoint(
        payload, asset="BTCUSDT", timeframe="1h"
    )
    assert expected == tuple(
        sorted(
            (
                subject.lineage_identity(
                    asset="BTCUSDT",
                    timeframe="1h",
                    original_anchor_role=role,
                    first_anchor_pivot_id=f"{role}-first",
                    second_anchor_pivot_id=f"{role}-second",
                )
                for role in ("support", "resistance")
            )
        )
    )


def test_forged_strict_seed_audit_is_rejected_against_source_expectation() -> None:
    evidence = _synthetic_bundle_evidence()
    dataset = "btcusdt_1h"
    payloads = {
        name: copy.deepcopy(payload)
        for name, payload in evidence["datasets"][dataset].items()
    }
    lifecycle = payloads["lineage_lifecycle"]
    lifecycle["strict_seed_reconciliation"][0]["expected_strict_lineage_ids"] = [
        "forged"
    ]
    lifecycle["evidence_id"] = subject._dataset_evidence_id(lifecycle)
    with pytest.raises(subject.LifecycleStudyError, match="source reconciliation"):
        subject._validate_dataset_payload(
            dataset,
            payloads,
            expected_strict_lineage_ids={1: [evidence["lineages"][0]["lineage_id"]]},
        )


def test_forged_actual_strict_seed_ids_are_rejected_against_source() -> None:
    evidence = _synthetic_bundle_evidence()
    dataset = "btcusdt_1h"
    payloads = {
        name: copy.deepcopy(payload)
        for name, payload in evidence["datasets"][dataset].items()
    }
    lifecycle = payloads["lineage_lifecycle"]
    lifecycle["strict_seed_reconciliation"][0]["strict_lineage_ids"] = [
        "forged"
    ]
    lifecycle["evidence_id"] = subject._dataset_evidence_id(lifecycle)
    expected_lineage_id = lifecycle["strict_seed_reconciliation"][0][
        "expected_strict_lineage_ids"
    ][0]
    with pytest.raises(subject.LifecycleStudyError, match="source reconciliation"):
        subject._validate_dataset_payload(
            dataset,
            payloads,
            expected_strict_lineage_ids={1: [expected_lineage_id]},
        )


def test_bar_replay_precedes_checkpoint_and_uses_available_at() -> None:
    lifecycle = subject.derive_lifecycle_evidence(**_synthetic_lifecycle_inputs())
    transitions = lifecycle["transitions"]["synthetic_1h"]
    assert [event["trigger"] for event in transitions] == [
        "strict_seed_confirmed",
        "same_role_sustained_breach_confirmed",
        "reversal_contact_confirmed_after_breach",
        "reversed_role_sustained_breach_confirmed",
    ]
    assert transitions[1]["effective_at"] == subject._iso(
        datetime(2024, 1, 1, 6, tzinfo=timezone.utc)
    )
    assert transitions[2]["effective_at"] == subject._iso(
        datetime(2024, 1, 1, 7, tzinfo=timezone.utc)
    )


def test_reversed_role_breach_retires_lineage_once() -> None:
    lifecycle = subject.derive_lifecycle_evidence(**_synthetic_lifecycle_inputs())
    transitions = lifecycle["transitions"]["synthetic_1h"]
    assert transitions[-1]["trigger"] == "reversed_role_sustained_breach_confirmed"
    assert transitions[-1]["current_state"] == "RETIRED"
    states = lifecycle["checkpoint_states"]["synthetic_1h"]
    assert states[-1]["state"] == "RETIRED"
    assert states[-1]["current_semantic_role"] is None
    assert states[-1]["last_active_semantic_role"] == "resistance"


def test_persisted_near_and_distant_states_follow_checkpoint_distance() -> None:
    inputs = _synthetic_lifecycle_inputs()
    bars = list(inputs["bars"]["synthetic_1h"])
    for index in range(4, 8):
        original = bars[index]
        bars[index] = subject.LifecycleBar(
            timestamp_ns=original.timestamp_ns,
            available_at_ns=original.available_at_ns,
            high=110.2,
            low=109.8,
            close=110.0,
            atr=1.0,
        )
    inputs["bars"] = {"synthetic_1h": tuple(bars)}
    lifecycle = subject.derive_lifecycle_evidence(**inputs)
    states = lifecycle["checkpoint_states"]["synthetic_1h"]
    assert states[0]["state"] == "STRICT_ACTIVE_NEAR"
    assert states[1]["state"] == "PERSISTED_DISTANT"


def test_future_lineage_is_absent_before_first_strict_checkpoint() -> None:
    inputs = _synthetic_lifecycle_inputs()
    base = inputs["lineages"][0]
    future_lineage_id = subject.lineage_identity(
        asset=base.asset,
        timeframe=base.timeframe,
        original_anchor_role=base.original_anchor_role,
        first_anchor_pivot_id="pivot-3",
        second_anchor_pivot_id="pivot-4",
    )
    future_lineage = subject.replace(
        base,
        lineage_id=future_lineage_id,
        first_anchor_pivot_id="pivot-3",
        second_anchor_pivot_id="pivot-4",
        first_strict_checkpoint=2,
        first_anchor_price=110.0,
        second_anchor_price=110.0,
        first_anchor_timestamp=subject._iso(datetime(2024, 1, 1, 1, tzinfo=timezone.utc)),
        second_anchor_timestamp=subject._iso(datetime(2024, 1, 1, 3, tzinfo=timezone.utc)),
        geometry={
            "start_time": subject._iso(datetime(2024, 1, 1, 1, tzinfo=timezone.utc)),
            "end_time": subject._iso(datetime(2024, 1, 1, 3, tzinfo=timezone.utc)),
            "start_price": 110.0,
            "end_price": 110.0,
        },
    )
    checkpoints = list(inputs["checkpoints"]["synthetic_1h"])
    checkpoints[1] = subject.replace(
        checkpoints[1], strict_lineage_ids=(future_lineage_id,)
    )
    inputs["lineages"] = (base, future_lineage)
    inputs["checkpoints"] = {"synthetic_1h": tuple(checkpoints)}
    lifecycle = subject.derive_lifecycle_evidence(**inputs)
    states = lifecycle["checkpoint_states"]["synthetic_1h"]
    first_states = [state for state in states if state["checkpoint_index"] == 1]
    second_states = [state for state in states if state["checkpoint_index"] == 2]
    assert future_lineage_id not in {state["lineage_id"] for state in first_states}
    assert future_lineage_id in {state["lineage_id"] for state in second_states}
    assert all(
        state["fixed_geometry"] != future_lineage.geometry
        for state in first_states
    )


def test_event_and_checkpoint_distance_evidence_use_separate_timestamps() -> None:
    inputs = _synthetic_lifecycle_inputs()
    base_lineage = inputs["lineages"][0]
    lineage = subject.replace(
        base_lineage,
        second_anchor_price=104.0,
        geometry={
            "start_time": base_lineage.first_anchor_timestamp,
            "end_time": base_lineage.second_anchor_timestamp,
            "start_price": 100.0,
            "end_price": 104.0,
        },
    )
    checkpoint = inputs["checkpoints"]["synthetic_1h"][0]
    event_bar = subject.LifecycleBar(
        timestamp_ns=subject._datetime_to_ns(datetime(2024, 1, 1, 5, tzinfo=timezone.utc)),
        available_at_ns=subject._datetime_to_ns(datetime(2024, 1, 1, 6, tzinfo=timezone.utc)),
        high=104.2,
        low=103.8,
        close=104.0,
        atr=2.0,
    )
    checkpoint_bar = subject.LifecycleBar(
        timestamp_ns=subject._datetime_to_ns(datetime(2024, 1, 1, 3, tzinfo=timezone.utc)),
        available_at_ns=subject._datetime_to_ns(datetime(2024, 1, 1, 4, tzinfo=timezone.utc)),
        high=101.2,
        low=100.8,
        close=101.0,
        atr=1.0,
    )
    evidence = subject._state_record(
        lineage,
        _direct_runtime("STRICT_ACTIVE_NEAR"),
        checkpoint,
        event_bar,
        checkpoint_bar=checkpoint_bar,
    )
    assert evidence["event_projection"] == 110.0
    assert evidence["event_distance_atr"] == 3.0
    assert evidence["projection_at_checkpoint"] == 108.0
    assert evidence["checkpoint_distance_atr"] == 7.0


def test_mixed_gap_allows_structural_candidate_under_actionable_gap() -> None:
    data, gap = _extended_outcome_inputs()
    gap = {
        **gap,
        "checkpoint_index": 1,
        "recovery_status": "ACTIONABLE",
        "candidate_lineage_ids": [data["lineage"].lineage_id],
        "candidate_recovery": [
            {
                "lineage_id": data["lineage"].lineage_id,
                "state": "PERSISTED_DISTANT",
                "recovery_status": "STRUCTURAL_ONLY",
                "recovery_mechanisms": ["DISTANCE_PERSISTENCE"],
            }
        ],
    }
    outcomes = subject.derive_future_outcomes(
        data["lifecycle"],
        lineages=data["lineages"],
        checkpoints=data["checkpoints"],
        bars=data["bars"],
        gap_records={"synthetic_1h": [gap]},
    )
    assert outcomes["synthetic_1h"]
    assert all(
        outcome["candidate_recovery_status"] == "STRUCTURAL_ONLY"
        and outcome["gap_recovery_status"] == "ACTIONABLE"
        and outcome["recovery_mechanisms"] == ["DISTANCE_PERSISTENCE"]
        and outcome["gap_recovery_mechanisms"] == ["DISTANCE_PERSISTENCE"]
        for outcome in outcomes["synthetic_1h"]
    )


def test_source_snapshot_mismatch_blocks_publication() -> None:
    with pytest.raises(subject.LifecycleStudyError, match="mutation"):
        subject._source_audit({"digest": "before"}, {"digest": "after"})


def test_source_snapshot_equal_is_accepted() -> None:
    audit = subject._source_audit({"digest": "same"}, {"digest": "same"})
    assert audit["source_audit_id"]
    assert audit["source_before"] == audit["source_after"]


def test_runner_creates_parent_and_staging_before_source_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "not-created" / "study"
    observed: dict[str, bool] = {}
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R3A_LIFECYCLE_STUDY", "1")

    def fail_after_probe() -> None:
        observed["parent"] = root.parent.is_dir()
        observed["staging"] = any(
            item.name.startswith(f".{root.name}.") for item in root.parent.iterdir()
        )
        raise subject.LifecycleStudyError("synthetic stop")

    monkeypatch.setattr(subject, "verify_retained_sources", fail_after_probe)
    with pytest.raises(subject.LifecycleStudyError, match="synthetic stop"):
        subject.run_lifecycle_study(output_root=root)
    assert observed == {"parent": True, "staging": True}
    assert not root.exists()
    assert not any(item.name.startswith(f".{root.name}.") for item in root.parent.iterdir())


def test_runner_staging_failure_makes_zero_source_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "missing-parent" / "study"
    calls = 0
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R3A_LIFECYCLE_STUDY", "1")

    def source_call() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {}

    def staging_failure(*args: object, **kwargs: object) -> str:
        raise OSError("staging unavailable")

    monkeypatch.setattr(subject, "verify_retained_sources", source_call)
    monkeypatch.setattr(subject.tempfile, "mkdtemp", staging_failure)
    with pytest.raises(OSError, match="staging unavailable"):
        subject.run_lifecycle_study(output_root=root)
    assert calls == 0


def test_canonical_runner_rejects_synthetic_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "uncreated" / "study"
    evidence = _synthetic_bundle_evidence()
    monkeypatch.setenv("TRENDLINE_V2_ALLOW_PHASE11R3A_LIFECYCLE_STUDY", "1")
    monkeypatch.setattr(subject, "verify_retained_sources", lambda: {"synthetic": True})
    monkeypatch.setattr(
        subject,
        "_derive_lifecycle_study_evidence",
        lambda **_: evidence,
    )
    with pytest.raises(subject.LifecycleStudyError, match="synthetic source marker"):
        subject.run_lifecycle_study(output_root=root)
    assert not root.exists()
    assert not any(item.name.startswith(f".{root.name}.") for item in root.parent.iterdir())


def _synthetic_bundle_evidence() -> dict[str, object]:
    base_inputs = _synthetic_lifecycle_inputs()
    lineage = base_inputs["lineages"][0].to_dict()
    checkpoint = {
        "lineage_id": lineage["lineage_id"],
        "dataset_id": "synthetic_1h",
        "checkpoint_index": 1,
        "checkpoint_observed_at": "2024-01-01T04:00:00Z",
        "state": "STRICT_ACTIVE_NEAR",
        "current_semantic_role": "support",
        "last_active_semantic_role": "support",
        "original_anchor_role": "support",
        "fixed_geometry": lineage["geometry"],
        "projection_at_checkpoint": 100.0,
        "checkpoint_distance_atr": 0.0,
        "event_projection": None,
        "event_distance_atr": None,
        "source_input_identity": "synthetic-input-1",
        "reversal_count": 0,
        "first_same_role_breach_bar": None,
        "second_same_role_breach_bar": None,
        "first_reversal_contact_bar": None,
        "retirement_reason": None,
    }
    source_audit = subject._source_audit({"synthetic": True}, {"synthetic": True})
    datasets = {}
    for dataset in subject.DATASETS:
        dataset_lineage = dict(lineage)
        dataset_lineage["dataset_id"] = dataset
        dataset_lineage["asset"] = dataset.split("_")[0].upper()
        dataset_lineage["timeframe"] = dataset.split("_")[1]
        dataset_lineage["lineage_id"] = subject.lineage_identity(
            asset=dataset_lineage["asset"],
            timeframe=dataset_lineage["timeframe"],
            original_anchor_role=dataset_lineage["original_anchor_role"],
            first_anchor_pivot_id=dataset_lineage["first_anchor_pivot_id"],
            second_anchor_pivot_id=dataset_lineage["second_anchor_pivot_id"],
        )
        state = dict(checkpoint)
        state["dataset_id"] = dataset
        state["lineage_id"] = dataset_lineage["lineage_id"]
        lifecycle = {
            "schema_version": "trendline_v2_phase11r3a_lineage_lifecycle_v1",
            "dataset_id": dataset,
            "lineages": [dataset_lineage],
            "checkpoint_states": [state],
            "transitions": [],
            "strict_seed_reconciliation": [
                {
                    "checkpoint_index": 1,
                    "strict_lineage_ids": [dataset_lineage["lineage_id"]],
                    "expected_strict_lineage_ids": [dataset_lineage["lineage_id"]],
                    "strict_identity_match": True,
                    "strict_count_match": True,
                }
            ],
        }
        gap = {
            "schema_version": "trendline_v2_phase11r3a_gap_recovery_v1",
            "dataset_id": dataset,
            "records": [],
        }
        outcomes = {
            "schema_version": "trendline_v2_phase11r3a_recovered_outcomes_v1",
            "dataset_id": dataset,
            "outcomes": [],
        }
        metrics = subject._policy_metrics(dataset, {"checkpoint_states": {dataset: [state]}}, [])
        payloads = {
            "lineage_lifecycle": lifecycle,
            "gap_recovery": gap,
            "recovered_outcomes": outcomes,
            "policy_metrics": {
                "schema_version": "trendline_v2_phase11r3a_policy_metrics_v1",
                **metrics,
            },
        }
        datasets[dataset] = {
            name: {**payload, "evidence_id": subject._dataset_evidence_id(payload)}
            for name, payload in payloads.items()
        }
    return {
        "lineages": [
            dataset["lineage_lifecycle"]["lineages"][0]
            for dataset in datasets.values()
        ],
        "datasets": datasets,
        "source_audit": source_audit,
    }


def test_synthetic_bundle_publishes_atomically_and_reloads(tmp_path: Path) -> None:
    root = tmp_path / "missing-parent" / "study"
    result = subject._publish_lifecycle_evidence(
        _synthetic_bundle_evidence(), output_root=root
    )
    assert root.is_dir()
    assert result["file_count"] == 23
    with pytest.raises(subject.LifecycleStudyError, match="synthetic source marker"):
        subject._verify_lifecycle_bundle(root)
    assert subject._verify_synthetic_lifecycle_bundle_for_tests(root)["manifest_id"] == result["manifest_id"]
    assert not any(path.name.startswith(f".{root.name}.") for path in root.parent.iterdir())
    audit = subject._load_json(root / "source_audit.json")
    assert "staging" not in json.dumps(audit)


def test_cli_verify_rejects_synthetic_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cli-synthetic"
    monkeypatch.setattr(subject, "OUTPUT_ROOT", root)
    derived = subject._derive_contract_triplet()
    monkeypatch.setattr(subject, "EXPECTED_CONTRACT_ID", derived["contract_id"])
    monkeypatch.setattr(
        subject,
        "EXPECTED_CONTRACT_JSON_SHA256",
        derived["canonical_json_sha256"],
    )
    monkeypatch.setattr(
        subject,
        "EXPECTED_CONTRACT_JSON_BYTE_LENGTH",
        derived["canonical_json_byte_length"],
    )
    monkeypatch.setattr(subject, "CONTRACT_ID", derived["contract_id"])
    monkeypatch.setattr(
        subject,
        "CONTRACT_JSON_SHA256",
        derived["canonical_json_sha256"],
    )
    monkeypatch.setattr(
        subject,
        "CONTRACT_JSON_BYTE_LENGTH",
        derived["canonical_json_byte_length"],
    )
    subject._publish_lifecycle_evidence(_synthetic_bundle_evidence(), output_root=root)
    try:
        with pytest.raises(subject.LifecycleStudyError, match="synthetic source marker"):
            subject.main(["--verify"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_synthetic_source_snapshot_rejects_unknown_fields(tmp_path: Path) -> None:
    root = tmp_path / "unknown-source-field"
    subject._publish_lifecycle_evidence(_synthetic_bundle_evidence(), output_root=root)
    source_audit = subject._load_json(root / "source_audit.json")
    source_audit["source_before"]["unexpected"] = True
    source_audit["source_after"]["unexpected"] = True
    source_audit["source_audit_id"] = subject.deterministic_hash(
        "trendline_v2_phase11r3a_source_audit",
        {key: value for key, value in source_audit.items() if key != "source_audit_id"},
    )
    (root / "source_audit.json").write_bytes(subject._canonical_bytes(source_audit))
    _rebind_manifest_for_test(root)
    with pytest.raises(subject.LifecycleStudyError, match="source snapshot fields"):
        subject._verify_synthetic_lifecycle_bundle_for_tests(root)


def test_semantic_verifier_rejects_rebound_state_and_manifest(tmp_path: Path) -> None:
    root = tmp_path / "study"
    subject._publish_lifecycle_evidence(_synthetic_bundle_evidence(), output_root=root)
    path = root / "datasets" / "btcusdt_1h" / "lineage_lifecycle.json"
    payload = json.loads(path.read_text())
    payload["checkpoint_states"][0]["state"] = "PERSISTED_DISTANT"
    payload["evidence_id"] = subject._dataset_evidence_id(payload)
    path.write_bytes(subject._canonical_bytes(payload))
    manifest = subject._load_json(root / "manifest.json")
    members = list(subject._inventory(root))
    members = [item for item in members if item["path"] != "manifest.json"]
    manifest_payload = {key: value for key, value in manifest.items() if key != "manifest_id"}
    manifest_payload["members"] = members
    manifest_payload["output_inventory_sha256"] = subject._inventory_sha256(members)
    manifest = {
        **manifest_payload,
        "manifest_id": subject.deterministic_hash(
            "trendline_v2_phase11r3a_manifest", manifest_payload
        ),
    }
    (root / "manifest.json").write_bytes(subject._canonical_bytes(manifest))
    with pytest.raises(subject.LifecycleStudyError, match="CSV semantic|decision semantic|policy metrics"):
        subject._verify_synthetic_lifecycle_bundle_for_tests(root)


def _rebind_manifest_for_test(root: Path) -> None:
    manifest = subject._load_json(root / "manifest.json")
    members = [item for item in subject._inventory(root) if item["path"] != "manifest.json"]
    payload = {key: value for key, value in manifest.items() if key != "manifest_id"}
    payload["members"] = members
    payload["output_inventory_sha256"] = subject._inventory_sha256(members)
    rebound = {
        **payload,
        "manifest_id": subject.deterministic_hash(
            "trendline_v2_phase11r3a_manifest", payload
        ),
    }
    (root / "manifest.json").write_bytes(subject._canonical_bytes(rebound))


def test_semantic_verifier_rejects_forged_trigger_and_role(tmp_path: Path) -> None:
    root = tmp_path / "trigger-role"
    subject._publish_lifecycle_evidence(_synthetic_bundle_evidence(), output_root=root)
    path = root / "datasets" / "btcusdt_1h" / "lineage_lifecycle.json"
    payload = subject._load_json(path)
    payload["checkpoint_states"][0]["current_semantic_role"] = "resistance"
    payload["evidence_id"] = subject._dataset_evidence_id(payload)
    path.write_bytes(subject._canonical_bytes(payload))
    _rebind_manifest_for_test(root)
    with pytest.raises(subject.LifecycleStudyError, match="semantic role|CSV semantic"):
        subject._verify_synthetic_lifecycle_bundle_for_tests(root)

    root2 = tmp_path / "trigger"
    subject._publish_lifecycle_evidence(_synthetic_bundle_evidence(), output_root=root2)
    transition_path = root2 / "datasets" / "btcusdt_1h" / "lineage_lifecycle.json"
    lifecycle = subject._load_json(transition_path)
    lineage = lifecycle["lineages"][0]
    lifecycle["transitions"] = [
        {
            "lineage_id": lineage["lineage_id"],
            "dataset_id": "btcusdt_1h",
            "previous_state": "NOT_YET_STRICT_ACTIVE",
            "current_state": "STRICT_ACTIVE_NEAR",
            "trigger": "distance_exceeded_8_atr",
            "effective_at": "2024-01-01T04:00:00Z",
            "checkpoint_observed_at": "2024-01-01T04:00:00Z",
            "original_anchor_role": "support",
            "current_semantic_role": "support",
            "fixed_geometry": lineage["geometry"],
            "projection_at_checkpoint": 100.0,
            "checkpoint_distance_atr": 0.0,
            "event_projection": None,
            "event_distance_atr": None,
            "first_same_role_breach_bar": None,
            "second_same_role_breach_bar": None,
            "first_reversal_contact_bar": None,
            "reversal_count": 0,
            "retirement_reason": None,
            "source_input_identity": "synthetic-input-1",
        }
    ]
    lifecycle["evidence_id"] = subject._dataset_evidence_id(lifecycle)
    transition_path.write_bytes(subject._canonical_bytes(lifecycle))
    _rebind_manifest_for_test(root2)
    with pytest.raises(subject.LifecycleStudyError, match="transition trigger does not match"):
        subject._verify_synthetic_lifecycle_bundle_for_tests(root2)


def test_semantic_verifier_rejects_forged_recovery_and_outcome(tmp_path: Path) -> None:
    root = tmp_path / "recovery-outcome"
    subject._publish_lifecycle_evidence(_synthetic_bundle_evidence(), output_root=root)
    gap_path = root / "datasets" / "btcusdt_1h" / "gap_recovery.json"
    gap = subject._load_json(gap_path)
    gap["records"] = [
        {
            "gap_id": "forged",
            "dataset_id": "btcusdt_1h",
            "checkpoint_index": 1,
            "semantic_role": "support",
            "provider_role_record_count": 2,
            "candidate_lineage_ids": [],
            "recovery_status": "FORGED",
            "recovery_mechanisms": ["DISTANCE_PERSISTENCE"],
            "unrecovered_reason": None,
        }
    ]
    gap["evidence_id"] = subject._dataset_evidence_id(gap)
    gap_path.write_bytes(subject._canonical_bytes(gap))
    _rebind_manifest_for_test(root)
    with pytest.raises(subject.LifecycleStudyError, match="gap identity|recovery status|policy metrics"):
        subject._verify_synthetic_lifecycle_bundle_for_tests(root)

    root2 = tmp_path / "outcome"
    subject._publish_lifecycle_evidence(_synthetic_bundle_evidence(), output_root=root2)
    outcome_path = root2 / "datasets" / "btcusdt_1h" / "recovered_outcomes.json"
    outcome = subject._load_json(outcome_path)
    outcome["outcomes"] = [
        {
            "dataset_id": "btcusdt_1h",
            "checkpoint_index": 1,
            "semantic_role": "forged",
            "lineage_id": "none",
            "state": "STRICT_ACTIVE_NEAR",
            "horizon_hours": 24,
            "evaluable": True,
            "survival": True,
            "zone_contact": False,
            "zone_contact_and_survival": False,
            "post_contact_reaction": False,
            "first_contact_offset_bars": None,
            "first_sustained_breach_offset_bars": None,
            "contact_bar": None,
            "reaction_bar": None,
        }
    ]
    outcome["evidence_id"] = subject._dataset_evidence_id(outcome)
    outcome_path.write_bytes(subject._canonical_bytes(outcome))
    _rebind_manifest_for_test(root2)
    with pytest.raises(subject.LifecycleStudyError, match="future outcome"):
        subject._verify_synthetic_lifecycle_bundle_for_tests(root2)


def test_semantic_verifier_rejects_rebound_decision_and_manifest(tmp_path: Path) -> None:
    root = tmp_path / "decision"
    subject._publish_lifecycle_evidence(_synthetic_bundle_evidence(), output_root=root)
    decision_path = root / "decision.json"
    decision = subject._load_json(decision_path)
    decision["study_status"] = "CAUSAL_SEED_LIFECYCLE_FEASIBILITY_BLOCKED"
    body = {key: value for key, value in decision.items() if key != "decision_id"}
    decision["decision_id"] = subject.deterministic_hash(
        "trendline_v2_phase11r3a_decision", body
    )
    decision_path.write_bytes(subject._canonical_bytes(decision))
    _rebind_manifest_for_test(root)
    with pytest.raises(subject.LifecycleStudyError, match="decision semantic"):
        subject._verify_synthetic_lifecycle_bundle_for_tests(root)


def test_future_outcomes_exclude_contact_bar_from_reaction() -> None:
    inputs = _synthetic_lifecycle_inputs()
    lifecycle = subject.derive_lifecycle_evidence(**inputs)
    bars = list(inputs["bars"]["synthetic_1h"])
    origin = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for index in range(10, 110):
        timestamp = origin + timedelta(hours=index)
        bars.append(
            subject.LifecycleBar(
                timestamp_ns=subject._datetime_to_ns(timestamp),
                available_at_ns=subject._datetime_to_ns(timestamp + timedelta(hours=1)),
                high=100.2,
                low=99.8,
                close=100.0,
                atr=1.0,
            )
        )
    inputs["bars"] = {"synthetic_1h": tuple(bars)}
    outcomes = subject.derive_future_outcomes(
        lifecycle,
        lineages=inputs["lineages"],
        checkpoints=inputs["checkpoints"],
        bars={"synthetic_1h": tuple(bars)},
    )
    assert all(
        outcome["first_contact_offset_bars"] is None
        or outcome["post_contact_reaction"] is False
        or outcome["first_sustained_breach_offset_bars"] is None
        or outcome["first_contact_offset_bars"] < outcome["first_sustained_breach_offset_bars"]
        for outcome in outcomes.get("synthetic_1h", [])
    )


def _negative_line_runtime_inputs() -> tuple[subject.LifecycleLineage, subject.LifecycleCheckpoint, list[subject.LifecycleBar]]:
    inputs = _synthetic_lifecycle_inputs()
    base = inputs["lineages"][0]
    negative_geometry = {
        "start_time": base.first_anchor_timestamp,
        "end_time": base.second_anchor_timestamp,
        "start_price": -1.0,
        "end_price": -1.0,
    }
    lineage = subject.replace(
        base,
        first_anchor_price=-1.0,
        second_anchor_price=-1.0,
        geometry=negative_geometry,
    )
    checkpoint = inputs["checkpoints"]["synthetic_1h"][0]
    bars = [
        subject.LifecycleBar(
            timestamp_ns=subject._datetime_to_ns(datetime(2024, 1, 1, hour=hour, tzinfo=timezone.utc)),
            available_at_ns=subject._datetime_to_ns(datetime(2024, 1, 1, hour=hour + 1, tzinfo=timezone.utc)),
            high=-1.8,
            low=-2.2,
            close=-2.0,
            atr=1.0,
        )
        for hour in (4, 5)
    ]
    return lineage, checkpoint, bars


def _direct_runtime(state: str) -> dict[str, object]:
    return {
        "state": state,
        "last_active_semantic_role": "resistance" if state.startswith("REVERSED") else "support",
        "same_role_breach_count": 0,
        "reversed_breach_count": 0,
        "reversal_count": 0,
        "retirement_reason": None,
    }


def test_original_breach_precedes_projection_invalidation() -> None:
    lineage, checkpoint, bars = _negative_line_runtime_inputs()
    runtime = _direct_runtime("STRICT_ACTIVE_NEAR")
    runtime["same_role_breach_count"] = 1
    transitions: list[dict[str, object]] = []
    for bar in bars:
        subject._process_lineage_bar(lineage, runtime, bar, checkpoint, transitions)
    assert runtime["state"] == "REVERSAL_PENDING"
    assert transitions[-1]["trigger"] == "same_role_sustained_breach_confirmed"


def test_reversed_breach_precedes_projection_invalidation() -> None:
    lineage, checkpoint, bars = _negative_line_runtime_inputs()
    runtime = _direct_runtime("REVERSED_ACTIVE_NEAR")
    runtime["reversed_breach_count"] = 1
    bars[1] = subject.replace(bars[1], high=0.2, low=-0.2, close=0.0)
    transitions: list[dict[str, object]] = []
    subject._process_lineage_bar(lineage, runtime, bars[1], checkpoint, transitions)
    assert runtime["state"] == "RETIRED"
    assert transitions[-1]["trigger"] == "reversed_role_sustained_breach_confirmed"
    assert transitions[-1]["retirement_reason"] == "reversed_role_sustained_breach"


def test_pending_state_ignores_projection_invalidation() -> None:
    lineage, checkpoint, bars = _negative_line_runtime_inputs()
    runtime = _direct_runtime("REVERSAL_PENDING")
    runtime["second_same_role_breach_available_ns"] = bars[0].available_at_ns
    transitions: list[dict[str, object]] = []
    subject._process_lineage_bar(lineage, runtime, bars[1], checkpoint, transitions)
    assert runtime["state"] == "REVERSAL_PENDING"
    assert transitions == []


def test_sloped_checkpoint_projection_and_distance_use_checkpoint_time() -> None:
    inputs = _synthetic_lifecycle_inputs()
    base = inputs["lineages"][0]
    geometry = {
        "start_time": base.first_anchor_timestamp,
        "end_time": base.second_anchor_timestamp,
        "start_price": 100.0,
        "end_price": 102.0,
    }
    inputs["lineages"] = (
        subject.replace(
            base,
            first_anchor_price=100.0,
            second_anchor_price=102.0,
            geometry=geometry,
        ),
    )
    lifecycle = subject.derive_lifecycle_evidence(**inputs)
    first_state = lifecycle["checkpoint_states"]["synthetic_1h"][0]
    assert first_state["projection_at_checkpoint"] == 104.0
    assert first_state["checkpoint_distance_atr"] == 4.0


def _extended_outcome_inputs(state: str = "PERSISTED_DISTANT") -> tuple[dict[str, object], dict[str, object]]:
    inputs = _synthetic_lifecycle_inputs()
    base = inputs["lineages"][0]
    geometry = {
        "start_time": base.first_anchor_timestamp,
        "end_time": base.second_anchor_timestamp,
        "start_price": 100.0,
        "end_price": 102.0,
    }
    lineage = subject.replace(
        base,
        first_anchor_price=100.0,
        second_anchor_price=102.0,
        geometry=geometry,
    )
    bars = list(inputs["bars"]["synthetic_1h"])
    origin = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for hour in range(10, 110):
        bars.append(
            subject.LifecycleBar(
                timestamp_ns=subject._datetime_to_ns(origin + timedelta(hours=hour)),
                available_at_ns=subject._datetime_to_ns(origin + timedelta(hours=hour + 1)),
                high=100.2,
                low=99.8,
                close=100.0,
                atr=1.0,
            )
        )
    inputs["lineages"] = (lineage,)
    inputs["bars"] = {"synthetic_1h": tuple(bars)}
    lifecycle = subject.derive_lifecycle_evidence(**inputs)
    record = dict(lifecycle["checkpoint_states"]["synthetic_1h"][0])
    record["state"] = state
    record["current_semantic_role"] = "support"
    gap = {
        "gap_id": "gap-test",
        "recovery_status": "STRUCTURAL_ONLY" if "DISTANT" in state else "ACTIONABLE",
        "recovery_mechanisms": ["DISTANCE_PERSISTENCE"] if "DISTANT" in state else [],
        "candidate_lineage_ids": [lineage.lineage_id],
        "semantic_role": "support",
    }
    return {**inputs, "lifecycle": {"checkpoint_states": {"synthetic_1h": [record]}}, "lineage": lineage}, gap


def test_structural_initial_distance_uses_checkpoint_line() -> None:
    data, gap = _extended_outcome_inputs()
    outcome = subject._evaluate_candidate_outcome(
        data["lifecycle"]["checkpoint_states"]["synthetic_1h"][0],
        data["lineage"],
        data["checkpoints"]["synthetic_1h"][0],
        data["bars"]["synthetic_1h"],
        24,
        gap=gap,
    )
    assert outcome["initial_distance_atr"] == 4.0


def test_gap_filter_excludes_strict_baseline_and_binds_recovered_candidate() -> None:
    inputs = _synthetic_lifecycle_inputs()
    lifecycle = subject.derive_lifecycle_evidence(**inputs)
    assert subject.derive_future_outcomes(
        lifecycle,
        lineages=inputs["lineages"],
        checkpoints=inputs["checkpoints"],
        bars=inputs["bars"],
        gap_records={"synthetic_1h": []},
    )["synthetic_1h"] == []
    lineage = inputs["lineages"][0]
    bars = list(inputs["bars"]["synthetic_1h"])
    origin = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for hour in range(10, 110):
        bars.append(
            subject.LifecycleBar(
                timestamp_ns=subject._datetime_to_ns(origin + timedelta(hours=hour)),
                available_at_ns=subject._datetime_to_ns(origin + timedelta(hours=hour + 1)),
                high=100.2,
                low=99.8,
                close=100.0,
                atr=1.0,
            )
        )
    gap = {
        "gap_id": "gap-test",
        "checkpoint_index": 1,
        "semantic_role": "support",
        "recovery_status": "ACTIONABLE",
        "recovery_mechanisms": [],
        "candidate_lineage_ids": [lineage.lineage_id],
    }
    outcomes = subject.derive_future_outcomes(
        lifecycle,
        lineages=inputs["lineages"],
        checkpoints=inputs["checkpoints"],
        bars={"synthetic_1h": tuple(bars)},
        gap_records={"synthetic_1h": [gap]},
    )["synthetic_1h"]
    assert len(outcomes) == 3
    assert {outcome["gap_id"] for outcome in outcomes} == {"gap-test"}


def test_structural_outcome_contains_no_actionable_fields() -> None:
    data, gap = _extended_outcome_inputs()
    outcome = subject._evaluate_candidate_outcome(
        data["lifecycle"]["checkpoint_states"]["synthetic_1h"][0],
        data["lineage"],
        data["checkpoints"]["synthetic_1h"][0],
        data["bars"]["synthetic_1h"],
        24,
        gap=gap,
    )
    assert outcome["structural_only"] is True
    assert not {"survival", "zone_contact", "post_contact_reaction"} & outcome.keys()


def test_unrecovered_gap_does_not_make_complete_status_incomplete() -> None:
    evidence = _synthetic_bundle_evidence()
    dataset = evidence["datasets"]["btcusdt_1h"]
    gap = {
        "gap_id": subject.deterministic_hash(
            "trendline_v2_phase11r3a_unique_gap",
            {"dataset_id": "btcusdt_1h", "checkpoint_index": 1, "semantic_role": "support"},
        ),
        "dataset_id": "btcusdt_1h",
        "checkpoint_index": 1,
        "semantic_role": "support",
        "provider_role_record_count": 2,
        "candidate_lineage_ids": [],
        "recovery_status": "NOT_RECOVERED",
        "recovery_mechanisms": [],
        "unrecovered_reason": "NO_PRIOR_STRICT_LINEAGE",
    }
    dataset["gap_recovery"]["records"] = [gap]
    dataset["gap_recovery"]["evidence_id"] = subject._dataset_evidence_id(dataset["gap_recovery"])
    csv_members = subject._csv_members(evidence)
    decision = subject._decision_from_evidence(
        evidence,
        source_audit_id=evidence["source_audit"]["source_audit_id"],
        csv_members=csv_members,
    )
    assert decision["study_status"] == "CAUSAL_SEED_LIFECYCLE_FEASIBILITY_COMPLETE"
    assert decision["unrecovered_gap_count"] == 1


def test_unresolved_evidence_prevents_complete() -> None:
    evidence = _synthetic_bundle_evidence()
    evidence["unresolved_evidence_count"] = 1
    decision = subject._decision_from_evidence(
        evidence,
        source_audit_id=evidence["source_audit"]["source_audit_id"],
        csv_members=subject._csv_members(evidence),
    )
    assert decision["study_status"] == "CAUSAL_SEED_LIFECYCLE_FEASIBILITY_INCOMPLETE"


def test_inactive_lineage_reason_attribution_preserves_opposite_role_history() -> None:
    lineage = {"original_anchor_role": "support"}
    pending = {"state": "REVERSAL_PENDING", "last_active_semantic_role": "support"}
    retired = {"state": "RETIRED", "last_active_semantic_role": "resistance"}
    assert subject._is_relevant_inactive_lineage(lineage, pending, gap_role="resistance")
    assert subject._is_relevant_inactive_lineage(lineage, retired, gap_role="resistance")
    assert subject.aggregate_gap_recovery(
        [{"state": "REVERSAL_PENDING", "pending_without_contact": True, "prior_strict_lineage": True}],
        provider_role_records=2,
    )["unrecovered_reason"] == "REVERSAL_PENDING_NO_CONTACT"
    assert subject.aggregate_gap_recovery(
        [{"state": "RETIRED", "pending_without_contact": False, "prior_strict_lineage": True}],
        provider_role_records=2,
    )["unrecovered_reason"] == "ALL_RELEVANT_LINEAGES_RETIRED"


def test_retirement_reason_and_transition_trigger_matrix_are_exact() -> None:
    assert subject._retirement_reason_for_trigger(
        "reversed_role_sustained_breach_confirmed"
    ) == "reversed_role_sustained_breach"
    assert "strict_seed_confirmed" in subject._transition_triggers(
        "NOT_YET_STRICT_ACTIVE", "STRICT_ACTIVE_NEAR"
    )
    assert "strict_seed_confirmed" not in subject._transition_triggers(
        "STRICT_ACTIVE_NEAR", "PERSISTED_DISTANT"
    )


def test_policy_metrics_include_full_coverage_inflation_and_rates() -> None:
    inputs = _synthetic_lifecycle_inputs()
    lifecycle = subject.derive_lifecycle_evidence(**inputs)
    metrics = subject._policy_metrics(
        "synthetic_1h",
        lifecycle,
        [],
        [],
    )
    assert metrics["checkpoint_role_cell_count"] == 44
    assert metrics["candidate_inflation_ratio"] == (
        metrics["expanded_structural_observation_count"]
        / metrics["strict_observation_count"]
    )
    assert metrics["strict_actionable_coverage"]["evaluable_count"] == 44
    assert metrics["outcome_rates"]["unique_gap_level"]["48h_survival"] == {
        "rate": None,
        "evaluable_count": 0,
    }


def test_candidate_outcome_rates_are_separate_by_horizon() -> None:
    inputs = _synthetic_lifecycle_inputs()
    lifecycle = subject.derive_lifecycle_evidence(**inputs)
    state = lifecycle["checkpoint_states"]["synthetic_1h"][0]
    outcomes = [
        {
            "horizon_hours": horizon,
            "gap_id": f"gap-{horizon}",
            "structural_only": False,
            "evaluable": True,
            "survival": horizon != 48,
            "zone_contact": horizon == 96,
            "post_contact_reaction": horizon == 24,
        }
        for horizon in subject.HORIZONS_HOURS
    ]
    metrics = subject._policy_metrics(
        "synthetic_1h",
        {"checkpoint_states": {"synthetic_1h": [state]}},
        [],
        outcomes,
    )
    candidate_rates = metrics["outcome_rates"]["candidate_level"]
    assert set(candidate_rates) == {"24", "48", "96"}
    assert candidate_rates["24"]["survival"] == {"rate": 1.0, "evaluable_count": 1}
    assert candidate_rates["48"]["survival"] == {"rate": 0.0, "evaluable_count": 1}


def test_zero_pooled_strict_observations_block_inflation() -> None:
    evidence = _synthetic_bundle_evidence()
    for dataset in subject.DATASETS:
        metrics = subject._policy_metrics(
            dataset,
            {"checkpoint_states": {dataset: []}},
            [],
            [],
        )
        evidence["datasets"][dataset]["policy_metrics"] = {
            "schema_version": "trendline_v2_phase11r3a_policy_metrics_v1",
            **metrics,
        }
    with pytest.raises(subject.LifecycleStudyError, match="zero pooled strict"):
        subject._aggregate_policy_metrics(evidence)


def test_retired_lineage_count_is_unique_across_checkpoint_rows() -> None:
    evidence = _synthetic_bundle_evidence()
    for dataset in subject.DATASETS:
        records = evidence["datasets"][dataset]["lineage_lifecycle"][
            "checkpoint_states"
        ]
        retired = dict(records[0])
        retired["state"] = "RETIRED"
        retired["current_semantic_role"] = None
        retired["last_active_semantic_role"] = "support"
        retired["retirement_reason"] = "original_projection_invalid"
        records.extend([dict(retired), dict(retired)])
    decision = subject._decision_from_evidence(
        evidence,
        source_audit_id=evidence["source_audit"]["source_audit_id"],
        csv_members=subject._csv_members(evidence),
    )
    assert decision["counts"]["retired_lineage_count"] == len(subject.DATASETS)


def test_direct_study_execution_requires_environment_guard(tmp_path: Path) -> None:
    with pytest.raises(subject.ContractFreezeError, match="execution guard"):
        subject.run_lifecycle_study(output_root=tmp_path / "guarded" / "study")
    assert not (tmp_path / "guarded").exists()


def test_coordinated_rehashed_lifecycle_forgery_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "coordinated"
    expected = _synthetic_bundle_evidence()
    subject._publish_lifecycle_evidence(expected, output_root=root)
    path = root / "datasets" / "btcusdt_1h" / "lineage_lifecycle.json"
    payload = subject._load_json(path)
    payload["checkpoint_states"][0]["state"] = "PERSISTED_DISTANT"
    payload["evidence_id"] = subject._dataset_evidence_id(payload)
    path.write_bytes(subject._canonical_bytes(payload))
    _rebind_manifest_for_test(root)
    source_audit = subject._load_json(root / "source_audit.json")
    canonical_source = subject._source_snapshot()
    source_audit["source_before"] = canonical_source
    source_audit["source_after"] = copy.deepcopy(canonical_source)
    source_audit["source_audit_id"] = subject.deterministic_hash(
        "trendline_v2_phase11r3a_source_audit",
        {key: value for key, value in source_audit.items() if key != "source_audit_id"},
    )
    (root / "source_audit.json").write_bytes(subject._canonical_bytes(source_audit))
    _rebind_manifest_for_test(root)
    monkeypatch.setattr(subject, "_source_snapshot", lambda: canonical_source)
    monkeypatch.setattr(subject, "_derive_lifecycle_study_evidence", lambda **_: expected)
    with pytest.raises(subject.LifecycleStudyError, match="source-backed lifecycle"):
        subject._verify_lifecycle_bundle(root)
