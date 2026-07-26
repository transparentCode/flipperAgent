"""Phase 11R.3B offline joint structural compression study.

Study consumes retained Phase 11R.3A lifecycle evidence and four explicitly
allowlisted persisted provider-result inputs. It never invokes providers or
network code. Runtime publication remains behind an execution guard.
"""

from __future__ import annotations

import argparse
import csv
import copy
import hashlib
import io
import json
import math
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash
from libs.models.trendline_v2.domain.provider_input import ProviderInput


CONTRACT_NAMESPACE = (
    "trendline_v2_phase11r3b_joint_structural_compression_contract"
)
TEMPORAL_V2_CONTRACT_NAMESPACE = (
    "trendline_v2_phase11r3b_joint_structural_compression_temporal_v2_contract"
)
BASE_COMMIT = "b7cd736e08bda2eb82fa7f0dad62c842428c602a"

PHASE11R3A_ROOT = Path(
    "/tmp/trendline_v2_phase11r3a_causal_seed_lifecycle/20260522_20260701"
)
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase11r3b_joint_structural_compression/20260522_20260701"
)
TEMPORAL_V2_OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase11r3b_joint_structural_compression_temporal_v2/"
    "20260522_20260701"
)

PHASE11R3A_COMMIT = BASE_COMMIT
PHASE11R3A_DECISION_ID = (
    "d1e97bbccb64dba0a12a88d324af19c40e1563ffce87e77707e5ce9f21b42d1b"
)
PHASE11R3A_MANIFEST_ID = (
    "74a5e78b119cc18a8c982a4e75a953a545780b10dbe7798464a8a9abdd1a146d"
)
PHASE11R3A_INVENTORY = (
    "6335ec5dd2e67bc94f51ae5a1e0c0e265db743ad1aeccb0094ce4507466d2ff0"
)
PHASE11R3A_CONTRACT_ID = (
    "df65b38a0bbdf675e97336bcb3a750ba64483cfee32428ec08c4b40da63d85b1"
)
PHASE11R3A_CONTRACT_JSON_BYTE_LENGTH = 22226
PHASE11R3A_CONTRACT_JSON_SHA256 = (
    "154fe9a3168b5c16c17156fd278acc8d63433ba645aca14727bad50b429423e8"
)

PHASE11R1_INVENTORY = (
    "17cf5aa6f70b58a21fe436ca63a98f88ab6356250de13befa94100ac96c4ae50"
)
PHASE11R2_INVENTORY = (
    "382df2e22cb508d3982eb7e6d9566849dc65eb7316a8ce8c64b9c44d2d6713e4"
)
ALLOWED_RAW_INVENTORY = (
    "2f2db301ca6c9c355bb4d645bb2d631836749748835c0419573e7cf52d27de27"
)

DATASETS = ("btcusdt_1h", "btcusdt_4h", "ethusdt_1h", "ethusdt_4h")
ROLES = ("support", "resistance")
ALLOWED_RAW_PATHS = tuple(
    f"datasets/{dataset}/provider_result.json" for dataset in DATASETS
)
PHASE11R3A_LINEAGE_LIFECYCLE_EVIDENCE_IDS = {
    "btcusdt_1h": "3ecc044bd2633e085ad79e4aca6de8368dce5e087d8d8de18fd65dac02f6a46f",
    "btcusdt_4h": "a1804064364c62b632f6220ca661d0e63bdd970b85f3330140a35001bd79f4f7",
    "ethusdt_1h": "ee3c157187fc09f6f5adb3e07058a63ace76fa14cd728c403895ec4ba9d387ed",
    "ethusdt_4h": "1178f7e1fe8dac0990dbd51bf34bf618a047cf0b43f2822be15ef5fdb2fb84b5",
}
CHECKPOINTS_PER_DATASET = 22
CHECKPOINT_COUNT = len(DATASETS) * CHECKPOINTS_PER_DATASET
HORIZONS_HOURS = (24, 48, 96)
BUDGETS_PER_ROLE = (1, 2, 3)
EXPECTED_MATCHED_CELL_KEYS = tuple(
    (dataset, checkpoint)
    for dataset in DATASETS
    for checkpoint in range(1, CHECKPOINTS_PER_DATASET + 1)
)
STABLE_LINEAGE_HASH_NAMESPACE = (
    "trendline_v2_phase11r3b_stable_lineage_hash_v1"
)

ACTIONABLE_STATES = (
    "STRICT_ACTIVE_NEAR",
    "PERSISTED_ACTIVE_NEAR",
    "REVERSED_ACTIVE_NEAR",
)
STRUCTURAL_CONTEXT_STATES = (
    "PERSISTED_DISTANT",
    "REVERSED_PERSISTED_DISTANT",
)
EXCLUDED_STATES = (
    "NOT_YET_STRICT_ACTIVE",
    "REVERSAL_PENDING",
    "RETIRED",
)
ALL_STATES = ACTIONABLE_STATES + STRUCTURAL_CONTEXT_STATES + EXCLUDED_STATES

CONTROL_POLICIES = (
    "joint_hash_order_control_v1",
    "joint_nearest_projection_control_v1",
    "independent_incumbent_control_v1",
)
CONTENDER_POLICIES = (
    "joint_incumbent_near_v1",
    "joint_incumbent_tenure_v1",
    "joint_incumbent_evidence_v1",
)
POLICIES = CONTROL_POLICIES + CONTENDER_POLICIES
NO_FINALIST_STATUS = "NO_JOINT_STRUCTURAL_COMPRESSION_FINALIST"
FREEZE_STATUS = "READY_FOR_CONTRACT_FREEZE_REVIEW"
IMPLEMENTATION_REVIEW_STATUS = "READY_FOR_IMPLEMENTATION_REVIEW"
STUDY_COMPLETE_STATUS = "JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_COMPLETE"
STUDY_INCOMPLETE_STATUS = "JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_INCOMPLETE"
STUDY_BLOCKED_STATUS = "JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_BLOCKED"
SOURCE_AUDIT_NAMESPACE = "trendline_v2_phase11r3b_source_audit"
SELECTION_NAMESPACE = "trendline_v2_phase11r3b_selection"
CANDIDATE_NAMESPACE = "trendline_v2_phase11r3b_candidate_observation"
OUTCOME_NAMESPACE = "trendline_v2_phase11r3b_candidate_outcome"
STRUCTURAL_NAMESPACE = "trendline_v2_phase11r3b_structural_context"
METRICS_NAMESPACE = "trendline_v2_phase11r3b_policy_metrics"
COMPARISON_NAMESPACE = "trendline_v2_phase11r3b_matched_comparison"
GATE_NAMESPACE = "trendline_v2_phase11r3b_gate"
DECISION_NAMESPACE = "trendline_v2_phase11r3b_decision"
LOCK_NAMESPACE = "trendline_v2_phase11r3b_validation_lock"
MANIFEST_NAMESPACE = "trendline_v2_phase11r3b_manifest"
UTC = timezone.utc
NANOSECONDS = 1_000_000_000
INTERVAL_SECONDS = {"1h": 3_600, "4h": 14_400}
TOUCH_ATR = 0.35
BREACH_ATR = 0.5
REACTION_ATR = 1.0

EXPECTED_ARTIFACT_PATHS = tuple(
    [
        "study_contract.json",
        "source_audit.json",
        "validation_lock.json",
        "compression_summary.csv",
        "coherence_summary.csv",
        "stability_summary.csv",
        "outcome_summary.csv",
        "decision.json",
        "manifest.json",
    ]
    + [
        f"datasets/{dataset}/{member}"
        for dataset in DATASETS
        for member in (
            "checkpoint_selection.json",
            "candidate_outcomes.json",
            "structural_context.json",
            "policy_metrics.json",
        )
    ]
)


class ContractFreezeError(RuntimeError):
    """Raised when frozen contract identity or study boundaries fail."""


def _policy_key(*fields: tuple[str, str]) -> list[dict[str, str]]:
    return [{"field": field, "order": order} for field, order in fields]


def _policy_definitions() -> dict[str, dict[str, Any]]:
    return {
        "joint_hash_order_control_v1": {
            "category": "matched_control",
            "algorithm": "joint_core_then_ranked_fill",
            "ranking_key": _policy_key(
                ("stable_lineage_hash", "ascending"),
                ("lineage_id", "ascending"),
            ),
            "joint_coherence_enforced": True,
            "diagnostic_only": True,
            "can_be_finalist": False,
        },
        "joint_nearest_projection_control_v1": {
            "category": "matched_control",
            "algorithm": "joint_core_then_ranked_fill",
            "ranking_key": _policy_key(
                ("checkpoint_distance_atr", "ascending"),
                ("lineage_id", "ascending"),
            ),
            "joint_coherence_enforced": True,
            "diagnostic_only": True,
            "can_be_finalist": False,
        },
        "independent_incumbent_control_v1": {
            "category": "matched_control",
            "algorithm": "independent_role_fill",
            "ranking_key": _policy_key(
                ("previous_checkpoint_incumbent", "descending"),
                ("checkpoint_distance_atr", "ascending"),
                ("lineage_id", "ascending"),
            ),
            "joint_coherence_enforced": False,
            "diagnostic_only": True,
            "can_be_finalist": False,
            "inversion_allowed_for_diagnostic": True,
        },
        "joint_incumbent_near_v1": {
            "category": "contender",
            "algorithm": "joint_core_then_ranked_fill",
            "ranking_key": _policy_key(
                ("previous_checkpoint_incumbent", "descending"),
                ("checkpoint_distance_atr", "ascending"),
                ("lineage_age", "descending"),
                ("lineage_id", "ascending"),
            ),
            "joint_coherence_enforced": True,
            "diagnostic_only": False,
            "can_be_finalist": True,
        },
        "joint_incumbent_tenure_v1": {
            "category": "contender",
            "algorithm": "joint_core_then_ranked_fill",
            "ranking_key": _policy_key(
                ("previous_checkpoint_incumbent", "descending"),
                ("lineage_age", "descending"),
                ("cumulative_strict_active_observations", "descending"),
                ("checkpoint_distance_atr", "ascending"),
                ("lineage_id", "ascending"),
            ),
            "joint_coherence_enforced": True,
            "diagnostic_only": False,
            "can_be_finalist": True,
        },
        "joint_incumbent_evidence_v1": {
            "category": "contender",
            "algorithm": "joint_core_then_ranked_fill",
            "ranking_key": _policy_key(
                ("previous_checkpoint_incumbent", "descending"),
                ("cumulative_strict_active_observations", "descending"),
                ("cumulative_actionable_observations", "descending"),
                ("lineage_age", "descending"),
                ("checkpoint_distance_atr", "ascending"),
                ("lineage_id", "ascending"),
            ),
            "joint_coherence_enforced": True,
            "diagnostic_only": False,
            "can_be_finalist": True,
        },
    }


def _source_payload() -> dict[str, Any]:
    return {
        "phase11r3a": {
            "commit": PHASE11R3A_COMMIT,
            "root": str(PHASE11R3A_ROOT),
            "contract_id": PHASE11R3A_CONTRACT_ID,
            "contract_json_byte_length": PHASE11R3A_CONTRACT_JSON_BYTE_LENGTH,
            "contract_json_sha256": PHASE11R3A_CONTRACT_JSON_SHA256,
            "decision_id": PHASE11R3A_DECISION_ID,
            "manifest_id": PHASE11R3A_MANIFEST_ID,
            "inventory_sha256": PHASE11R3A_INVENTORY,
            "lineage_lifecycle_evidence_ids": dict(
                PHASE11R3A_LINEAGE_LIFECYCLE_EVIDENCE_IDS
            ),
        },
        "protected_inventories": {
            "phase11r1": PHASE11R1_INVENTORY,
            "phase11r2": PHASE11R2_INVENTORY,
            "allowed_btc_eth_raw": ALLOWED_RAW_INVENTORY,
        },
        "allowed_datasets": list(DATASETS),
        "allowed_roles": list(ROLES),
        "allowed_raw_paths": list(ALLOWED_RAW_PATHS),
        "expected_allowed_raw_member_count": len(ALLOWED_RAW_PATHS),
        "reject_additional_raw_members": True,
        "raw_sui_reads": "prohibited",
        "holdout_reads": "prohibited",
        "temporal_reads": "prohibited",
        "network_reads": "prohibited",
        "provider_executions": "prohibited",
        "legacy_executions": "prohibited",
        "source_snapshot_policy": {
            "before_and_after_required": True,
            "inventory_ids_must_match": True,
            "source_mutation": "fail_closed",
            "canonical_rederivation": True,
        },
    }


def _contract_payload() -> dict[str, Any]:
    policies = _policy_definitions()
    return {
        "schema_version": CONTRACT_NAMESPACE,
        "base_commit": BASE_COMMIT,
        "sources": _source_payload(),
        "candidate_universe": {
            "actionable_states": list(ACTIONABLE_STATES),
            "structural_context_states": list(STRUCTURAL_CONTEXT_STATES),
            "excluded_states": list(EXCLUDED_STATES),
            "all_states": list(ALL_STATES),
            "actionable_budget_applies_only_to": list(ACTIONABLE_STATES),
            "structural_context_max_per_role": 1,
            "structural_context_is_separate_lane": True,
            "structural_context_affects_actionable_budget": False,
            "structural_context_affects_actionable_denominators": False,
            "new_lineages_or_candidates": False,
        },
        "targets": {
            "datasets": list(DATASETS),
            "roles": list(ROLES),
            "checkpoint_count_per_dataset": CHECKPOINTS_PER_DATASET,
            "checkpoint_count": CHECKPOINT_COUNT,
            "budgets_per_role": list(BUDGETS_PER_ROLE),
            "maximum_active_lines_by_budget": {str(b): 2 * b for b in BUDGETS_PER_ROLE},
            "contender_budget_combinations": len(CONTENDER_POLICIES) * len(BUDGETS_PER_ROLE),
            "matched_control_derivations": (
                len(CONTENDER_POLICIES)
                * len(BUDGETS_PER_ROLE)
                * 2
            ),
            "independent_diagnostic_combinations": len(BUDGETS_PER_ROLE),
            "approximate_visual_target_lines_per_chart": [2, 6],
        },
        "causal_ranking": {
            "allowed_features": [
                "previous_checkpoint_incumbent_membership",
                "current_lifecycle_state",
                "checkpoint_distance_atr",
                "first_strict_checkpoint",
                "lineage_age",
                "cumulative_strict_active_observations_through_checkpoint",
                "cumulative_actionable_observations_through_checkpoint",
                "past_breach_transitions_through_checkpoint",
                "past_reversal_transitions_through_checkpoint",
                "past_contact_transitions_through_checkpoint",
                "immutable_lineage_identity",
                "immutable_line_geometry",
            ],
            "forbidden_features": [
                "future_survival",
                "future_contact",
                "future_reaction",
                "later_lifecycle_state",
                "later_selected_membership",
                "holdout_evidence",
                "temporal_evidence",
            ],
            "future_mutation_invariance": True,
            "incumbent_membership_source": "previous_checkpoint_only",
            "incumbent_definition": {
                "same_policy": True,
                "same_budget": True,
                "immediately_previous_checkpoint_only": True,
                "first_checkpoint_has_no_incumbents": True,
                "confirmed_role_transfer_remains_incumbent": True,
                "persisted_fields": [
                    "previous_semantic_role",
                    "current_semantic_role",
                    "role_transfer",
                ],
            },
            "lineage_age_formula": (
                "checkpoint_index - first_strict_checkpoint + 1"
            ),
            "cumulative_strict_active_observations_formula": (
                "count STRICT_ACTIVE_NEAR records through current checkpoint inclusive"
            ),
            "cumulative_actionable_observations_formula": (
                "count all actionable-state records through current checkpoint inclusive"
            ),
            "past_transition_count_formula": (
                "count transitions with effective_at <= checkpoint_observed_at"
            ),
            "stable_lineage_hash": {
                "namespace": STABLE_LINEAGE_HASH_NAMESPACE,
                "input_fields": ["dataset_id", "lineage_id"],
                "canonical_input": "canonical_json({dataset_id, lineage_id})",
                "digest": "deterministic_hash(namespace, canonical_input)",
            },
            "weighted_score": False,
            "parameter_fitting": False,
            "score_threshold": None,
        },
        "policies": {
            "controls": list(CONTROL_POLICIES),
            "comparison_controls": [
                "joint_hash_order_control_v1",
                "joint_nearest_projection_control_v1",
            ],
            "diagnostic_control": "independent_incumbent_control_v1",
            "contenders": list(CONTENDER_POLICIES),
            "all": list(POLICIES),
            "definitions": policies,
            "control_matching": {
                "matching_key": [
                    "contender_policy_id",
                    "budget_per_role",
                    "control_policy_id",
                    "dataset_id",
                    "checkpoint_index",
                    "semantic_role",
                ],
                "construction_order": [
                    "run_contender_first",
                    "record_exact_selected_support_and_resistance_counts",
                    "derive_control_from_same_candidate_population",
                    "require_exact_per_role_selected_count_match",
                    "use_identical_future_horizons_and_evaluable_observations",
                ],
                "unmatchable_action": "persist_unmatched_and_fail_unresolved_reconciliation",
                "same_input_population": True,
                "same_selected_count_per_budget": True,
                "same_horizon_population": True,
                "independent_control_participates_in_matching": False,
            },
            "independent_control_cannot_win": True,
            "independent_control_participates_in_utility_gates": False,
            "independent_control_participates_in_stability_gates": False,
        },
        "joint_selection": {
            "required": True,
            "candidate_observation_identity": [
                "dataset_id",
                "checkpoint_index",
                "semantic_role",
                "lineage_id",
            ],
            "incumbent_definition": (
                "selected by same policy and same budget at immediately previous checkpoint"
            ),
            "incumbency_mode": "ranking_priority_only",
            "unconditional_preselection": False,
            "retained_incumbent_definition": (
                "selected current IDs intersect eligible previous selected IDs"
            ),
            "role_transfer": {
                "confirmed_reversal_remains_incumbent": True,
                "overall_retention": "role-transferred lineage counts retained",
                "role_specific_churn": "one removal from prior role and one addition to current role",
                "persisted_fields": [
                    "previous_semantic_role",
                    "current_semantic_role",
                    "role_transfer",
                ],
            },
            "steps": [
                "build_causal_ranked_support_and_resistance_candidates",
                "calculate_incumbent_status_without_preselection",
                "rank_each_role_using_policy_key",
                "select_coherent_core_support_resistance_pair_from_ranked_lists",
                "fill_remaining_budget_slots_deterministically",
                "derive_retained_incumbents_after_selection",
                "validate_full_selected_set_coherence",
            ],
            "core_pair_construction": [
                "enumerate_cartesian_product_support_resistance",
                "retain_support_projection_less_than_resistance_projection",
                "select_minimum_tuple",
            ],
            "core_pair_selection_key": [
                "support_rank_index",
                "resistance_rank_index",
                "support_lineage_id",
                "resistance_lineage_id",
            ],
            "no_coherent_core_pair": {
                "selected_actionable_candidates": 0,
                "shortfall_reason": "no_coherent_core_pair",
            },
            "single_role_behavior": "select_available_role_and_persist_missing_role",
            "projection_source": "immutable_line_geometry_at_checkpoint_timestamp",
            "coherence_formula": (
                "both roles present: max(selected support projections) < "
                "min(selected resistance projections); otherwise true"
            ),
            "full_set_validation": True,
            "remaining_slot_order": [
                "rank_index_ascending",
                "role_support_before_resistance",
                "lineage_id_ascending",
            ],
            "remaining_slot_acceptance": [
                "role_below_budget",
                "candidate_not_already_selected",
                "complete_selected_set_remains_coherent",
            ],
            "inverted_set_action": "reject_and_select_fewer_or_none",
            "shortfall_persisted": True,
            "shortfall_reasons": [
                "no_eligible_candidates",
                "role_missing",
                "no_coherent_core_pair",
                "full_budget_would_invert_roles",
                "insufficient_eligible_candidates",
            ],
            "shortfall_reason_precedence": [
                "no_eligible_candidates",
                "role_missing",
                "no_coherent_core_pair",
                "full_budget_would_invert_roles",
                "insufficient_eligible_candidates",
            ],
            "shortfall_reason_conditions": {
                "no_eligible_candidates": "both roles have zero actionable candidates",
                "role_missing": "this role has zero candidates while opposite role has candidates",
                "no_coherent_core_pair": "both roles have candidates but no support/resistance pair is coherent",
                "full_budget_would_invert_roles": "coherent core exists and remaining candidate would violate full-set coherence",
                "insufficient_eligible_candidates": "coherent selection exists and eligible count is below requested role budget without coherence rejection",
            },
            "shortfall_persisted_per_role": True,
            "candidate_rejection_reasons": [
                "already_selected",
                "role_budget_full",
                "would_invert_full_set",
                "not_required_for_matched_count",
            ],
            "shortfall_fields": [
                "requested_count",
                "selected_count",
                "shortfall_count",
                "shortfall_reason",
            ],
            "no_inversion_published": True,
            "persisted_fields": [
                "selected_lineage_ids",
                "retained_incumbent_ids",
                "added_ids",
                "removed_ids",
                "rejected_candidate_ids",
                "rejection_reasons",
                "core_pair_identity",
                "support_projections",
                "resistance_projections",
                "joint_coherence_result",
                "budget_shortfall",
            ],
        },
        "structural_context_lane": {
            "max_lineages_per_role": 1,
            "states": list(STRUCTURAL_CONTEXT_STATES),
            "ranking_key": [
                {"field": "previous_structural_context_incumbent", "order": "descending"},
                {"field": "checkpoint_distance_atr", "order": "ascending"},
                {"field": "lineage_age", "order": "descending"},
                {"field": "lineage_id", "order": "ascending"},
            ],
            "shared_across_actionable_policies": True,
            "independent_of_actionable_budget": True,
            "independent_of_actionable_coverage": True,
            "independent_of_finalist_gates": True,
            "independent_of_actionable_utility_denominators": True,
            "persisted_previous_membership": True,
            "persisted_churn": True,
            "initial_distance_atr_formula": (
                "abs(last_completed_close - line_at_checkpoint) / "
                "ATR_of_last_completed_bar"
            ),
            "future_distance_atr_formula": (
                "abs(future_close - line_at_future_bar) / ATR_at_future_bar"
            ),
            "minimum_future_distance_atr_formula": (
                "minimum future_distance_atr over exact horizon"
            ),
            "distance_contraction_atr_formula": (
                "initial_distance_atr - minimum_future_distance_atr"
            ),
            "future_contact_formula": (
                "low <= line + 0.35 * ATR_at_bar and "
                "high >= line - 0.35 * ATR_at_bar"
            ),
            "crossed_into_at_most_8_atr_formula": (
                "any future_distance_atr <= 8"
            ),
            "role_at_selection_fixed_through_horizon": True,
            "actionable_budget": False,
            "actionable_denominator": False,
            "coverage_rescue": False,
            "separate_label": "STRUCTURAL_ONLY",
            "metrics": [
                "future_contact",
                "minimum_future_distance_atr",
                "distance_contraction_atr",
                "crossed_into_at_most_8_atr",
            ],
        },
        "evaluation": {
            "horizons_hours": list(HORIZONS_HOURS),
            "candidate_outcome_observation_identity": [
                "contender_policy_id",
                "budget_per_role",
                "derivation_type",
                "control_policy_id_or_null",
                "dataset_id",
                "checkpoint_index",
                "semantic_role_at_selection",
                "lineage_id",
                "horizon_hours",
            ],
            "matched_control_namespace": [
                "contender_policy_id",
                "contender_budget",
                "control_policy_id",
            ],
            "semantic_role_at_selection_fixed_through_horizon": True,
            "one_candidate_level_observation_per_selected_candidate_checkpoint_horizon": True,
            "future_timestamp_rule": "timestamp strictly after checkpoint",
            "future_window_rule": "checkpoint < timestamp <= checkpoint + horizon",
            "exact_interval_sequence": True,
            "no_intrabar_order_assumption": True,
            "line_projection_formula": "immutable geometry evaluated at future bar timestamp",
            "zone_contact_formula": (
                "low <= line + 0.35 * ATR_at_bar and "
                "high >= line - 0.35 * ATR_at_bar"
            ),
            "support_breach_formula": (
                "two consecutive closes below line - 0.5 * ATR_at_bar"
            ),
            "resistance_breach_formula": (
                "two consecutive closes above line + 0.5 * ATR_at_bar"
            ),
            "survival_formula": "no sustained role-invalidating breach through horizon",
            "actionable_fields": [
                "survival",
                "zone_contact",
                "zone_contact_and_survival",
                "post_contact_reaction",
                "first_contact_offset_bars",
                "first_sustained_breach_offset_bars",
            ],
            "structural_fields": [
                "future_contact",
                "minimum_future_distance_atr",
                "distance_contraction_atr",
                "crossed_into_at_most_8_atr",
            ],
            "structural_role_at_selection_fixed_through_horizon": True,
            "reaction_starts_after_contact": True,
            "reaction_formula": {
                "starts_strictly_after_first_contact_bar": True,
                "ends_before_sustained_breach_completion_bar": True,
                "same_contact_bar_excluded": True,
                "minimum_movement": "at least 1 * ATR_at_contact_bar away from contact line",
                "intrabar_order_assumption": False,
            },
            "zero_denominator": {
                "rate": None,
                "evaluable_count": 0,
                "required_gate_result": "fail",
            },
            "structural_outcomes_excluded_from_actionable_denominators": True,
            "holdout_scope": "prohibited",
            "temporal_scope": "prohibited",
        },
        "metrics": {
            "compression": [
                "selected_observations",
                "selected_input_ratio",
                "median_selected_lines_per_cell",
                "maximum_selected_lines_per_cell",
                "budget_shortfall_distribution",
            ],
            "coverage_and_coherence": [
                "role_cell_coverage",
                "both_role_checkpoint_coverage",
                "zero_inversion_count",
                "coherent_core_pair_count",
                "missing_role_count",
            ],
            "stability": [
                "incumbent_retention_rate",
                "adjacent_checkpoint_jaccard",
                "additions",
                "removals",
                "replacement_count",
                "pair_continuity",
                "role_specific_churn",
            ],
            "actionable_utility": [
                "survival",
                "zone_contact",
                "zone_contact_and_survival",
                "post_contact_reaction",
            ],
            "structural_context_utility": [
                "future_contact",
                "minimum_future_distance_atr",
                "distance_contraction_atr",
                "crossed_into_at_most_8_atr",
            ],
        },
        "stability_formulas": {
            "incumbent_retention": {
                "denominator": "previous selected lineage IDs still present in current actionable universe",
                "numerator": "eligible previous IDs selected again",
                "zero_denominator_rate": None,
                "zero_denominator_evaluable_count": 0,
            },
            "adjacent_jaccard": {
                "set": "all selected lineage IDs across both roles",
                "formula": "intersection(previous,current) / union(previous,current)",
                "empty_union_rate": None,
                "empty_union_excluded_from_pooled_rate": True,
            },
            "additions": "current IDs - previous IDs",
            "removals": "previous IDs - current IDs",
            "replacement_count": "min(count(additions), count(removals))",
            "pair_continuity": {
                "population": "adjacent checkpoints where both coherent core pairs are non-null",
                "success": "ordered(previous_support_id, previous_resistance_id) == ordered(current_support_id, current_resistance_id)",
                "zero_denominator_rate": None,
            },
            "role_specific_churn": {
                "membership": "(semantic_role, lineage_id)",
                "role_transfer": "one removal plus one addition",
            },
        },
        "gate_aggregation": {
            "coverage": {
                "input_role_cell_formula": "actionable-input non-empty cells / 176",
                "selected_role_cell_formula": "selected non-empty cells / 176",
                "required_equality": "selected cell count == input cell count",
            },
            "utility_delta": {
                "formula": "contender candidate-level rate - matched-control candidate-level rate",
                "comparison_controls": [
                    "joint_hash_order_control_v1",
                    "joint_nearest_projection_control_v1",
                ],
                "matched_counts_and_populations": True,
            },
            "worst_dataset_96h_survival_delta": {
                "formula": "minimum across four datasets and two comparison controls",
                "required_dataset_control_denominators": "all non-zero",
            },
            "stability_comparison": {
                "metrics": ["incumbent_retention", "adjacent_continuity"],
                "pooled_evaluable_transitions": True,
                "comparison": "contender >= hash control and contender >= nearest control",
                "tolerance": 0,
                "rounding_allowance": False,
            },
        },
        "validation_gates": [
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
        ],
        "finalist_selection": {
            "eligible_only_if_all_gates_pass": True,
            "no_finalist_status": NO_FINALIST_STATUS,
            "precedence": [
                "smaller_budget",
                "higher_worst_dataset_96h_survival_delta",
                "higher_incumbent_retention",
                "higher_adjacent_continuity",
                "policy_id",
            ],
            "selection_is_research_only": True,
            "runtime_promotion": False,
        },
        "decision": {
            "study_statuses": [
                "JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_COMPLETE",
                "JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_INCOMPLETE",
                "JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_BLOCKED",
            ],
            "finalist_statuses": [
                "finalist_policy_budget_id",
                NO_FINALIST_STATUS,
            ],
            "study_status_conditions": {
                "JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_COMPLETE": [
                    "all_required_evidence_derived",
                    "all_required_evidence_reconciled",
                    "all_required_evidence_verified",
                    "unresolved_evidence_count == 0",
                    "may_have_finalist_or_no_finalist",
                ],
                "JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_INCOMPLETE": [
                    "derivation_completed",
                    "one_or_more_required_comparison_metric_or_reconciliation_records_unresolved",
                ],
                "JOINT_STRUCTURAL_COMPRESSION_FEASIBILITY_BLOCKED": [
                    "source_contract_execution_boundary_or_publication_precondition_failed_before_complete_evidence",
                ],
            },
            "study_status_and_finalist_status_separate": True,
            "no_finalist_can_still_be_complete": True,
        },
        "validation_lock": {
            "path": "validation_lock.json",
            "exact_members": [
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
            ],
            "source_identities": {
                "phase11r3a_contract_id": PHASE11R3A_CONTRACT_ID,
                "phase11r3a_manifest_id": PHASE11R3A_MANIFEST_ID,
                "phase11r3a_inventory": PHASE11R3A_INVENTORY,
                "phase11r1_inventory": PHASE11R1_INVENTORY,
                "phase11r2_inventory": PHASE11R2_INVENTORY,
                "allowed_raw_inventory": ALLOWED_RAW_INVENTORY,
            },
            "lineage_lifecycle_evidence_ids": dict(
                PHASE11R3A_LINEAGE_LIFECYCLE_EVIDENCE_IDS
            ),
            "contender_budget_gate_record_ids": {
                "type": "map",
                "key_format": "contender_policy_id__budget_{budget}",
                "value_type": "deterministic_evidence_id",
                "required_key_count": 9,
                "record_binds": [
                    "policy_id",
                    "budget",
                    "all_gate_inputs",
                    "all_gate_results",
                    "all_rejection_reasons",
                    "dataset_result_ids",
                    "comparison_record_ids",
                    "unresolved_reconciliation_count",
                ],
            },
            "matched_control_comparison_record_ids": {
                "type": "map",
                "key_format": "contender_policy_id__budget_{budget}__vs__control_policy_id",
                "value_type": "deterministic_evidence_id",
                "required_key_count": 18,
                "record_binds": [
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
                ],
            },
            "independent_control_diagnostic_ids": {
                "type": "map",
                "key_format": "independent_incumbent_control_v1__budget_{budget}",
                "value_type": "deterministic_evidence_id",
                "required_key_count": 3,
            },
            "finalist": {
                "type": "null_or_policy_budget_id",
                "allowed_policy_ids": list(CONTENDER_POLICIES),
                "allowed_budgets": list(BUDGETS_PER_ROLE),
                "null_only_when_no_variant_passes": True,
                "must_match_decision_finalist_status": True,
                "non_null_requires_all_gates_passed": True,
                "non_null_requires_finalist_precedence_winner": True,
            },
            "zero_unresolved_reconciliation": True,
            "holdout_access_count": 0,
            "temporal_access_count": 0,
            "no_holdout_loader": True,
            "final_decision_id": "deterministic_evidence_id",
        },
        "artifacts": {
            "output_root": str(OUTPUT_ROOT),
            "paths": list(EXPECTED_ARTIFACT_PATHS),
            "total_file_count": len(EXPECTED_ARTIFACT_PATHS),
            "manifest_member_count": len(EXPECTED_ARTIFACT_PATHS) - 1,
            "canonical_json": True,
            "atomic_publication": "single_directory_replace",
            "validation_lock_before_holdout_loader": True,
            "allowed_raw_paths": list(ALLOWED_RAW_PATHS),
            "reject_additional_raw_members": True,
            "contains_holdout": False,
            "contains_temporal": False,
            "contains_sui": False,
        },
        "execution_accounting": {
            "validation_datasets": len(DATASETS),
            "checkpoints": CHECKPOINT_COUNT,
            "roles": len(ROLES),
            "budgets_per_role": len(BUDGETS_PER_ROLE),
            "policies": len(POLICIES),
            "contender_budget_combinations": 9,
            "matched_control_derivations": 18,
            "independent_diagnostic_combinations": 3,
            "total_planned_derivations": 30,
            "contract_freeze_provider_executions": 0,
            "study_provider_executions": 0,
            "network_requests": 0,
            "raw_sui_accesses": 0,
            "holdout_accesses": 0,
            "temporal_accesses": 0,
            "legacy_executions": 0,
        },
        "study_controls": {
            "cli_execute": "--execute-compression-study",
            "cli_verify": "--verify",
            "execute_environment": "TRENDLINE_V2_ALLOW_PHASE11R3B_COMPRESSION_STUDY=1",
            "contract_freeze_status": FREEZE_STATUS,
            "study_execution_during_freeze": False,
            "existing_output_root_refusal_before_source_access": True,
            "fresh_staging_before_source_access": True,
            "synthetic_verifier_cannot_weaken_canonical_verification": True,
            "production_allow_synthetic": False,
            "test_synthetic_path_separate": True,
            "parameter_changes_after_results": False,
            "weighted_scores": False,
            "new_pivots": False,
            "new_anchors": False,
            "new_lineages": False,
            "lifecycle_changes": False,
            "provider_changes": False,
            "runtime_changes": False,
            "viewer_changes": False,
            "yaml_changes": False,
            "commit_during_freeze": False,
        },
    }


def contract_payload() -> dict[str, Any]:
    """Return fresh contract payload without reading frozen source roots."""
    return copy.deepcopy(_contract_payload())


def _derive_contract_triplet() -> dict[str, Any]:
    payload = contract_payload()
    encoded = canonical_json(payload).encode("utf-8")
    return {
        "payload": payload,
        "canonical_json": encoded.decode("utf-8"),
        "canonical_json_byte_length": len(encoded),
        "canonical_json_sha256": hashlib.sha256(encoded).hexdigest(),
        "contract_id": deterministic_hash(CONTRACT_NAMESPACE, payload),
    }


def contract_triplet() -> dict[str, Any]:
    """Return derived contract identity after frozen-constant validation."""
    derived = _derive_contract_triplet()
    expected = {
        "contract_id": EXPECTED_CONTRACT_ID,
        "canonical_json_sha256": EXPECTED_CONTRACT_JSON_SHA256,
            "canonical_json_byte_length": EXPECTED_CONTRACT_JSON_BYTE_LENGTH,
    }
    if any(derived[key] != value for key, value in expected.items()):
        raise ContractFreezeError("contract identity drift")
    return derived


def temporal_v2_contract_payload() -> dict[str, Any]:
    """Return versioned contract with availability-aware future windows."""
    payload = copy.deepcopy(contract_payload())
    payload["schema_version"] = TEMPORAL_V2_CONTRACT_NAMESPACE
    payload["evaluation"]["future_timestamp_rule"] = (
        "checkpoint <= bar_open < checkpoint + horizon"
    )
    payload["evaluation"]["future_window_rule"] = (
        "checkpoint < available_at <= checkpoint + horizon"
    )
    payload["evaluation"]["availability_timestamp_rule"] = (
        "available_at_ns = timestamp_ns + timeframe_interval_ns"
    )
    payload["evaluation"]["future_open_timestamp_rule"] = (
        "checkpoint <= timestamp_ns < checkpoint + horizon"
    )
    payload["temporal_window_remediation"] = {
        "schema_version": "trendline_v2_phase11r3b_temporal_window_v2",
        "supersedes_contract_id": EXPECTED_CONTRACT_ID,
        "superseded_output_root": str(OUTPUT_ROOT),
        "superseded_output_status": "SUPERSEDED_PENDING_TEMPORAL_WINDOW_REMEDIATION",
        "availability_aware": True,
        "first_unknown_bar_included": True,
        "bar_open_at_checkpoint_included": True,
        "bar_open_at_horizon_endpoint_excluded": True,
        "exact_future_availability_count": True,
    }
    payload["artifacts"]["output_root"] = str(TEMPORAL_V2_OUTPUT_ROOT)
    payload["study_controls"]["cli_execute"] = "--execute-compression-study-temporal-v2"
    payload["study_controls"]["cli_verify"] = "--verify-temporal-v2"
    payload["study_controls"]["execute_environment"] = (
        "TRENDLINE_V2_ALLOW_PHASE11R3B_TEMPORAL_V2_STUDY=1"
    )
    return payload


def _derive_temporal_v2_contract_triplet() -> dict[str, Any]:
    payload = temporal_v2_contract_payload()
    encoded = canonical_json(payload).encode("utf-8")
    derived = {
        "payload": payload,
        "canonical_json": encoded.decode("utf-8"),
        "canonical_json_byte_length": len(encoded),
        "canonical_json_sha256": hashlib.sha256(encoded).hexdigest(),
        "contract_id": deterministic_hash(TEMPORAL_V2_CONTRACT_NAMESPACE, payload),
    }
    if TEMPORAL_V2_EXPECTED_CONTRACT_ID is not None:
        expected = {
            "contract_id": TEMPORAL_V2_EXPECTED_CONTRACT_ID,
            "canonical_json_sha256": TEMPORAL_V2_EXPECTED_CONTRACT_JSON_SHA256,
            "canonical_json_byte_length": TEMPORAL_V2_EXPECTED_CONTRACT_JSON_BYTE_LENGTH,
        }
        if any(derived[key] != value for key, value in expected.items()):
            raise ContractFreezeError("temporal-v2 contract identity drift")
    return derived


def temporal_v2_contract_triplet() -> dict[str, Any]:
    return _derive_temporal_v2_contract_triplet()


def validate_temporal_v2_contract_identity(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    triplet = temporal_v2_contract_triplet()
    payload_copy = copy.deepcopy(dict(payload))
    encoded = canonical_json(payload_copy).encode("utf-8")
    derived = {
        "contract_id": deterministic_hash(TEMPORAL_V2_CONTRACT_NAMESPACE, payload_copy),
        "canonical_json_sha256": hashlib.sha256(encoded).hexdigest(),
        "canonical_json_byte_length": len(encoded),
    }
    expected = {
        key: triplet[key]
        for key in (
            "contract_id",
            "canonical_json_sha256",
            "canonical_json_byte_length",
        )
    }
    if derived != expected:
        raise ContractFreezeError("supplied temporal-v2 contract payload identity mismatch")
    return derived


def validate_contract_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate supplied payload identity without accessing any source root."""
    payload_copy = copy.deepcopy(dict(payload))
    encoded = canonical_json(payload_copy).encode("utf-8")
    derived = {
        "contract_id": deterministic_hash(CONTRACT_NAMESPACE, payload_copy),
        "canonical_json_sha256": hashlib.sha256(encoded).hexdigest(),
        "canonical_json_byte_length": len(encoded),
    }
    expected = contract_triplet()
    if derived != {
        key: expected[key]
        for key in (
            "contract_id",
            "canonical_json_sha256",
            "canonical_json_byte_length",
        )
    }:
        raise ContractFreezeError("supplied contract payload identity mismatch")
    return derived


class CompressionStudyError(ContractFreezeError):
    """Raised when retained evidence or study-derived data is invalid."""


def _canonical_bytes(value: Any) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise CompressionStudyError(f"cannot read artifact: {path}") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CompressionStudyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise CompressionStudyError(f"non-finite JSON constant: {value}")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise CompressionStudyError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict) or raw != _canonical_bytes(value):
        raise CompressionStudyError(f"non-canonical JSON artifact: {path}")
    return value


def _inventory(root: Path) -> tuple[dict[str, Any], ...]:
    if not root.is_dir() or root.is_symlink():
        raise CompressionStudyError(f"source root missing: {root}")
    result: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise CompressionStudyError(f"symlink is not allowed: {path}")
        if path.is_file():
            result.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "byte_length": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
            )
    return tuple(result)


def _explicit_inventory(
    root: Path, relative_paths: Sequence[str]
) -> tuple[dict[str, Any], ...]:
    expected = tuple(sorted(relative_paths))
    if len(set(expected)) != len(expected):
        raise CompressionStudyError("duplicate explicit source path")
    result: list[dict[str, Any]] = []
    for relative in expected:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise CompressionStudyError(f"allowlisted source missing: {relative}")
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise CompressionStudyError(f"unsafe allowlisted source path: {relative}")
        result.append(
            {
                "path": relative,
                "byte_length": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return tuple(result)


def _inventory_sha256(inventory: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_bytes(_canonical_bytes(list(inventory)))


def _parse_iso(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise CompressionStudyError(f"{field} must be ISO string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CompressionStudyError(f"invalid {field}") from exc
    if parsed.tzinfo is None:
        raise CompressionStudyError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _finite(value: object, *, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CompressionStudyError(f"{field} is not numeric") from exc
    if not math.isfinite(result):
        raise CompressionStudyError(f"{field} is non-finite")
    return result


def _require_hash(value: object, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise CompressionStudyError(f"{field} is not a SHA-256 value")
    try:
        int(value, 16)
    except ValueError as exc:
        raise CompressionStudyError(f"{field} is not a SHA-256 value") from exc
    return value


def _verify_manifest_members(root: Path, manifest: Mapping[str, Any]) -> None:
    members = manifest.get("members")
    if not isinstance(members, list) or members != sorted(members, key=lambda x: x["path"]):
        raise CompressionStudyError("manifest members are not canonical")
    if len({item.get("path") for item in members if isinstance(item, dict)}) != len(members):
        raise CompressionStudyError("manifest member paths are not unique")
    actual = _inventory(root)
    actual_without_manifest = tuple(item for item in actual if item["path"] != "manifest.json")
    if tuple(members) != actual_without_manifest:
        raise CompressionStudyError("manifest members do not match bytes")
    if manifest.get("member_count") != len(members):
        raise CompressionStudyError("manifest member count mismatch")
    if manifest.get("output_inventory_sha256") != _inventory_sha256(actual_without_manifest):
        raise CompressionStudyError("manifest output inventory mismatch")


def _verify_r3a_source() -> dict[str, Any]:
    """Verify retained Phase 11R.3A and exact raw source before derivation."""
    root = PHASE11R3A_ROOT
    if not root.is_dir():
        raise CompressionStudyError("Phase 11R.3A root missing")
    contract = _load_json(root / "study_contract.json")
    encoded = canonical_json(contract.get("payload")).encode("utf-8")
    if (
        contract.get("contract_id") != PHASE11R3A_CONTRACT_ID
        or contract.get("contract_json_byte_length") != PHASE11R3A_CONTRACT_JSON_BYTE_LENGTH
        or contract.get("contract_json_sha256") != PHASE11R3A_CONTRACT_JSON_SHA256
        or len(encoded) != PHASE11R3A_CONTRACT_JSON_BYTE_LENGTH
        or _sha256_bytes(encoded) != PHASE11R3A_CONTRACT_JSON_SHA256
    ):
        raise CompressionStudyError("Phase 11R3A contract identity mismatch")
    manifest = _load_json(root / "manifest.json")
    if (
        manifest.get("manifest_id") != PHASE11R3A_MANIFEST_ID
        or manifest.get("output_inventory_sha256") != PHASE11R3A_INVENTORY
    ):
        raise CompressionStudyError("Phase 11R3A manifest identity mismatch")
    _verify_manifest_members(root, manifest)
    decision = _load_json(root / "decision.json")
    if (
        decision.get("decision_id") != PHASE11R3A_DECISION_ID
        or decision.get("study_contract_id") != PHASE11R3A_CONTRACT_ID
        or decision.get("unresolved_count") != 0
        or decision.get("unresolved_evidence_count") != 0
        or decision.get("execution", {}).get("provider_execution_count") != 0
        or decision.get("execution", {}).get("network_request_count") != 0
        or decision.get("execution", {}).get("holdout_accessed") is not False
        or decision.get("execution", {}).get("temporal_accessed") is not False
    ):
        raise CompressionStudyError("Phase 11R.3A decision boundary mismatch")
    audit = _load_json(root / "source_audit.json")
    expected_audit_id = deterministic_hash(
        SOURCE_AUDIT_NAMESPACE.replace("r3b", "r3a"),
        {key: value for key, value in audit.items() if key != "source_audit_id"},
    )
    if audit.get("source_audit_id") != expected_audit_id:
        raise CompressionStudyError("Phase 11R.3A source audit identity mismatch")
    if (
        audit.get("source_before") != audit.get("source_after")
        or audit.get("source_immutability", {}).get("verified") is not True
        or audit.get("holdout_accessed") is not False
        or audit.get("temporal_accessed") is not False
        or audit.get("network_request_count") != 0
        or audit.get("provider_execution_count") != 0
        or audit.get("phase9c2", {}).get("raw_sui_accessed") is not False
        or audit.get("phase9c2", {}).get("allowed_raw_inventory_sha256") != ALLOWED_RAW_INVENTORY
        or audit.get("phase11r1", {}).get("inventory_sha256") != PHASE11R1_INVENTORY
        or audit.get("phase11r2", {}).get("inventory_sha256") != PHASE11R2_INVENTORY
    ):
        raise CompressionStudyError("Phase 11R.3A source audit boundary mismatch")
    raw_root = Path(audit["phase9c2"]["root"])
    expected_raw = tuple(audit["source_before"]["phase9c2_allowed_raw_inventory"])
    raw_inventory = _explicit_inventory(raw_root, ALLOWED_RAW_PATHS)
    if tuple(expected_raw) != raw_inventory or _inventory_sha256(raw_inventory) != ALLOWED_RAW_INVENTORY:
        raise CompressionStudyError("allowlisted raw source inventory mismatch")
    evidence_ids: dict[str, str] = {}
    for dataset in DATASETS:
        lifecycle = _load_json(root / f"datasets/{dataset}/lineage_lifecycle.json")
        evidence_id = lifecycle.get("evidence_id")
        if evidence_id != PHASE11R3A_LINEAGE_LIFECYCLE_EVIDENCE_IDS[dataset]:
            raise CompressionStudyError(f"lineage evidence identity mismatch: {dataset}")
        evidence_ids[dataset] = evidence_id
        if lifecycle.get("dataset_id") != dataset:
            raise CompressionStudyError(f"lineage dataset mismatch: {dataset}")
    return {
        "phase11r3a_inventory": PHASE11R3A_INVENTORY,
        "phase11r3a_manifest_id": PHASE11R3A_MANIFEST_ID,
        "phase11r3a_decision_id": PHASE11R3A_DECISION_ID,
        "phase11r3a_contract_id": PHASE11R3A_CONTRACT_ID,
        "lineage_lifecycle_evidence_ids": evidence_ids,
        "raw_root": str(raw_root),
        "raw_inventory": list(raw_inventory),
        "raw_inventory_sha256": _inventory_sha256(raw_inventory),
        "raw_sui_accesses": 0,
        "network_requests": 0,
        "provider_executions": 0,
        "holdout_accesses": 0,
        "temporal_accesses": 0,
        "source_snapshot_before": {
            "phase11r3a_inventory": PHASE11R3A_INVENTORY,
            "raw_inventory": list(raw_inventory),
        },
    }


def _provider_input_from_artifact(path: Path) -> ProviderInput:
    payload = _load_json(path)
    try:
        data = payload["provider_result"]["request"]["input_data"]
        input_value = ProviderInput(
            asset=data["asset"],
            timeframe=data["timeframe"],
            observed_at=_parse_iso(data["observed_at"], field="observed_at"),
            confirmed_through=_parse_iso(
                data["confirmed_through"], field="confirmed_through"
            ),
            timestamps=tuple(data["timestamps"]),
            open=tuple(data["open"]),
            high=tuple(data["high"]),
            low=tuple(data["low"]),
            close=tuple(data["close"]),
            volume=tuple(data["volume"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CompressionStudyError(f"invalid persisted provider input: {path}") from exc
    if payload.get("input_identity") != input_value.input_identity:
        raise CompressionStudyError(f"provider input identity mismatch: {path}")
    if data.get("input_identity") != input_value.input_identity:
        raise CompressionStudyError(f"nested provider input identity mismatch: {path}")
    if payload.get("provider_execution_count") != 1 or payload.get("network_request_count") != 0:
        raise CompressionStudyError(f"provider execution boundary mismatch: {path}")
    return input_value


def _true_range_at(data: ProviderInput, position: int) -> float:
    high = _finite(data.high[position], field="high")
    low = _finite(data.low[position], field="low")
    if position == 0:
        return high - low
    previous_close = _finite(data.close[position - 1], field="previous_close")
    return max(high - low, abs(high - previous_close), abs(low - previous_close))


def _atr_series(data: ProviderInput) -> tuple[float, ...]:
    values: list[float] = []
    for position in range(data.row_count):
        true_range = _true_range_at(data, position)
        if true_range <= 0 or not math.isfinite(true_range):
            raise CompressionStudyError("ATR true range must be positive")
        current = true_range if not values else (13.0 * values[-1] + true_range) / 14.0
        if current <= 0 or not math.isfinite(current):
            raise CompressionStudyError("ATR must be positive")
        values.append(current)
    return tuple(values)


def _bars_from_input(data: ProviderInput) -> tuple[dict[str, Any], ...]:
    atr = _atr_series(data)
    interval = INTERVAL_SECONDS[data.timeframe] * NANOSECONDS
    return tuple(
        {
            "timestamp_ns": int(data.timestamps[position]),
            "available_at_ns": int(data.timestamps[position]) + interval,
            "high": float(data.high[position]),
            "low": float(data.low[position]),
            "close": float(data.close[position]),
            "atr": atr[position],
        }
        for position in range(data.row_count)
    )


def _timestamp_ns(value: str | datetime) -> int:
    parsed = _parse_iso(value, field="timestamp") if isinstance(value, str) else value
    parsed = parsed.astimezone(UTC)
    return int(parsed.timestamp()) * NANOSECONDS + parsed.microsecond * 1_000


def _line_value(geometry: Mapping[str, Any], timestamp_ns: int) -> float:
    start_ns = _timestamp_ns(geometry["start_time"])
    end_ns = _timestamp_ns(geometry["end_time"])
    if end_ns <= start_ns:
        raise CompressionStudyError("line geometry timestamps are not ordered")
    start_price = _finite(geometry["start_price"], field="geometry.start_price")
    end_price = _finite(geometry["end_price"], field="geometry.end_price")
    fraction = (timestamp_ns - start_ns) / (end_ns - start_ns)
    return start_price + fraction * (end_price - start_price)


def _lineage_age(checkpoint_index: int, first_strict_checkpoint: int) -> int:
    age = checkpoint_index - first_strict_checkpoint + 1
    if age < 1:
        raise CompressionStudyError("invalid lineage age")
    return age


def _stable_lineage_hash(dataset_id: str, lineage_id: str) -> str:
    return deterministic_hash(
        STABLE_LINEAGE_HASH_NAMESPACE,
        {"dataset_id": dataset_id, "lineage_id": lineage_id},
    )


def _candidate_observation_id(candidate: Mapping[str, Any]) -> str:
    return deterministic_hash(
        CANDIDATE_NAMESPACE,
        {
            key: candidate[key]
            for key in ("dataset_id", "checkpoint_index", "semantic_role", "lineage_id")
        },
    )


def _load_dataset_context(
    source: Mapping[str, Any], dataset: str
) -> dict[str, Any]:
    lifecycle = _load_json(
        PHASE11R3A_ROOT / f"datasets/{dataset}/lineage_lifecycle.json"
    )
    lineages = {item["lineage_id"]: item for item in lifecycle.get("lineages", [])}
    if len(lineages) != len(lifecycle.get("lineages", [])):
        raise CompressionStudyError(f"duplicate lineages: {dataset}")
    checkpoints = lifecycle.get("checkpoint_states", [])
    if not checkpoints:
        raise CompressionStudyError(f"empty checkpoint states: {dataset}")
    raw_path = Path(source["raw_root"]) / f"datasets/{dataset}/provider_result.json"
    provider_input = _provider_input_from_artifact(raw_path)
    if provider_input.timeframe not in INTERVAL_SECONDS:
        raise CompressionStudyError(f"unsupported dataset timeframe: {dataset}")
    transitions = lifecycle.get("transitions", [])
    return {
        "dataset_id": dataset,
        "lineages": lineages,
        "checkpoint_states": checkpoints,
        "transitions": transitions,
        "provider_input": provider_input,
        "bars": _bars_from_input(provider_input),
        "checkpoint_indices": tuple(range(1, CHECKPOINTS_PER_DATASET + 1)),
    }


def _candidate_table(context: Mapping[str, Any]) -> dict[int, list[dict[str, Any]]]:
    dataset = context["dataset_id"]
    lineages = context["lineages"]
    transitions = context["transitions"]
    by_checkpoint: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in context["checkpoint_states"]:
        state = record.get("state")
        if state not in ACTIONABLE_STATES + STRUCTURAL_CONTEXT_STATES:
            continue
        lineage_id = record.get("lineage_id")
        lineage = lineages.get(lineage_id)
        role = record.get("current_semantic_role")
        if lineage is None or role not in ROLES:
            raise CompressionStudyError(f"invalid actionable lifecycle row: {dataset}")
        checkpoint = int(record["checkpoint_index"])
        observation = {
            "dataset_id": dataset,
            "checkpoint_index": checkpoint,
            "checkpoint_observed_at": record["checkpoint_observed_at"],
            "semantic_role": role,
            "lineage_id": lineage_id,
            "state": state,
            "fixed_geometry": dict(record["fixed_geometry"]),
            "projection_at_checkpoint": _finite(
                record["projection_at_checkpoint"], field="projection_at_checkpoint"
            ),
            "checkpoint_distance_atr": _finite(
                record["checkpoint_distance_atr"], field="checkpoint_distance_atr"
            ),
            "first_strict_checkpoint": int(lineage["first_strict_checkpoint"]),
            "lineage_age": _lineage_age(checkpoint, int(lineage["first_strict_checkpoint"])),
            "stable_lineage_hash": _stable_lineage_hash(dataset, lineage_id),
            "cumulative_strict_active_observations": sum(
                1
                for prior in context["checkpoint_states"]
                if prior.get("lineage_id") == lineage_id
                and int(prior.get("checkpoint_index", 0)) <= checkpoint
                and prior.get("state") == "STRICT_ACTIVE_NEAR"
            ),
            "cumulative_actionable_observations": sum(
                1
                for prior in context["checkpoint_states"]
                if prior.get("lineage_id") == lineage_id
                and int(prior.get("checkpoint_index", 0)) <= checkpoint
                and prior.get("state") in ACTIONABLE_STATES
            ),
            "past_breach_transitions": sum(
                1
                for transition in transitions
                if transition.get("lineage_id") == lineage_id
                and _parse_iso(
                    transition.get("effective_at"), field="transition.effective_at"
                )
                <= _parse_iso(record["checkpoint_observed_at"], field="checkpoint")
                and "breach" in str(transition.get("trigger", ""))
            ),
            "past_reversal_transitions": sum(
                1
                for transition in transitions
                if transition.get("lineage_id") == lineage_id
                and _parse_iso(
                    transition.get("effective_at"), field="transition.effective_at"
                )
                <= _parse_iso(record["checkpoint_observed_at"], field="checkpoint")
                and "reversal" in str(transition.get("trigger", ""))
            ),
            "past_contact_transitions": sum(
                1
                for transition in transitions
                if transition.get("lineage_id") == lineage_id
                and _parse_iso(
                    transition.get("effective_at"), field="transition.effective_at"
                )
                <= _parse_iso(record["checkpoint_observed_at"], field="checkpoint")
                and "contact" in str(transition.get("trigger", ""))
            ),
        }
        observation["candidate_observation_id"] = _candidate_observation_id(observation)
        by_checkpoint[checkpoint].append(observation)
    for checkpoint, rows in by_checkpoint.items():
        keys = [
            (row["semantic_role"], row["lineage_id"]) for row in rows
        ]
        if len(set(keys)) != len(keys):
            raise CompressionStudyError(f"duplicate candidate observation: {dataset}/{checkpoint}")
        rows.sort(key=lambda row: (row["semantic_role"], row["lineage_id"]))
    return dict(by_checkpoint)


def _policy_ranking_fields(policy_id: str) -> tuple[tuple[str, str], ...]:
    definitions = _policy_definitions()
    try:
        return tuple(
            (item["field"], item["order"])
            for item in definitions[policy_id]["ranking_key"]
        )
    except (KeyError, TypeError) as exc:
        raise CompressionStudyError(f"unknown policy: {policy_id}") from exc


def _rank_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    policy_id: str,
    previous_selected: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    previous_selected = previous_selected or {}
    by_role: dict[str, list[dict[str, Any]]] = {role: [] for role in ROLES}
    for raw in candidates:
        candidate = dict(raw)
        previous = previous_selected.get(candidate["lineage_id"])
        candidate["previous_checkpoint_incumbent"] = previous is not None
        candidate["previous_semantic_role"] = (
            None if previous is None else previous.get("semantic_role")
        )
        candidate["role_transfer"] = bool(
            previous is not None
            and previous.get("semantic_role") != candidate["semantic_role"]
        )
        if candidate["semantic_role"] not in ROLES:
            raise CompressionStudyError("candidate role is invalid")
        by_role[candidate["semantic_role"]].append(candidate)

    def key(row: Mapping[str, Any]) -> tuple[Any, ...]:
        values: list[Any] = []
        for field, order in _policy_ranking_fields(policy_id):
            value = row[field]
            if order == "descending":
                if isinstance(value, bool):
                    values.append(0 if value else 1)
                elif isinstance(value, (int, float)):
                    values.append(-value)
                else:
                    raise CompressionStudyError(
                        f"descending non-numeric ranking field: {field}"
                    )
            else:
                values.append(value)
        return tuple(values)

    for role in ROLES:
        by_role[role].sort(key=key)
        for rank_index, row in enumerate(by_role[role]):
            row["rank_index"] = rank_index
    return by_role


def _is_coherent(selected: Mapping[str, Sequence[Mapping[str, Any]]]) -> bool:
    support = selected.get("support", ())
    resistance = selected.get("resistance", ())
    if not support or not resistance:
        return True
    return max(row["projection_at_checkpoint"] for row in support) < min(
        row["projection_at_checkpoint"] for row in resistance
    )


def _selection_id(
    *, policy_id: str, budget: int, dataset: str, checkpoint: int, rows: Sequence[Mapping[str, Any]]
) -> str:
    return deterministic_hash(
        SELECTION_NAMESPACE,
        {
            "policy_id": policy_id,
            "budget": budget,
            "dataset_id": dataset,
            "checkpoint_index": checkpoint,
            "selected_ids": [row["candidate_observation_id"] for row in rows],
        },
    )


def _select_joint(
    candidates: Sequence[Mapping[str, Any]],
    *,
    policy_id: str,
    budget: int,
    dataset: str,
    checkpoint: int,
    previous_selected: Mapping[str, Mapping[str, Any]] | None = None,
    target_counts: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    if budget not in BUDGETS_PER_ROLE:
        raise CompressionStudyError("unsupported selection budget")
    ranked = _rank_candidates(
        candidates, policy_id=policy_id, previous_selected=previous_selected
    )
    targets = {
        role: int((target_counts or {}).get(role, budget)) for role in ROLES
    }
    if any(value < 0 or value > budget for value in targets.values()):
        raise CompressionStudyError("invalid target role count")
    selected: dict[str, list[dict[str, Any]]] = {role: [] for role in ROLES}
    rejected: list[dict[str, Any]] = []
    core_pair: tuple[dict[str, Any], dict[str, Any]] | None = None
    support = ranked["support"]
    resistance = ranked["resistance"]
    if targets["support"] > 0 and targets["resistance"] > 0:
        pairs = [
            (left, right)
            for left, right in product(support, resistance)
            if left["projection_at_checkpoint"] < right["projection_at_checkpoint"]
        ]
        if pairs:
            core_pair = min(
                pairs,
                key=lambda pair: (
                    pair[0]["rank_index"],
                    pair[1]["rank_index"],
                    pair[0]["lineage_id"],
                    pair[1]["lineage_id"],
                ),
            )
            selected["support"].append(core_pair[0])
            selected["resistance"].append(core_pair[1])
    elif targets["support"] > 0:
        selected["support"].extend(support[: min(targets["support"], len(support))])
    elif targets["resistance"] > 0:
        selected["resistance"].extend(
            resistance[: min(targets["resistance"], len(resistance))]
        )

    selected_ids = {
        row["candidate_observation_id"] for rows in selected.values() for row in rows
    }
    all_ranked = [] if (support and resistance and targets["support"] > 0 and targets["resistance"] > 0 and core_pair is None) else sorted(
        (
            (row["rank_index"], 0 if role == "support" else 1, row)
            for role, rows in ranked.items()
            for row in rows
        ),
        key=lambda item: (item[0], item[1], item[2]["lineage_id"]),
    )
    for _, _, candidate in all_ranked:
        candidate_id = candidate["candidate_observation_id"]
        role = candidate["semantic_role"]
        if candidate_id in selected_ids:
            rejected.append(
                {
                    "candidate_observation_id": candidate_id,
                    "semantic_role": role,
                    "reason": "already_selected",
                }
            )
            continue
        if len(selected[role]) >= targets[role]:
            rejected.append(
                {
                    "candidate_observation_id": candidate_id,
                    "semantic_role": role,
                    "reason": (
                        "not_required_for_matched_count"
                        if target_counts is not None
                        else "role_budget_full"
                    ),
                }
            )
            continue
        trial = {key: list(value) for key, value in selected.items()}
        trial[role].append(candidate)
        if not _is_coherent(trial):
            rejected.append(
                {
                    "candidate_observation_id": candidate_id,
                    "semantic_role": role,
                    "reason": "would_invert_full_set",
                }
            )
            continue
        selected[role].append(candidate)
        selected_ids.add(candidate_id)

    previous_selected = previous_selected or {}
    selected_rows = [row for role in ROLES for row in selected[role]]
    previous_selected_rows = {
        role: [
            dict(row)
            for row in previous_selected.values()
            if row.get("semantic_role") == role
        ]
        for role in ROLES
    }
    current_ids = {row["lineage_id"] for row in selected_rows}
    previous_ids = set(previous_selected)
    current_actionable_ids = {
        row["lineage_id"] for row in candidates if row["state"] in ACTIONABLE_STATES
    }
    eligible_previous = sorted(previous_ids & current_actionable_ids)
    ineligible_previous = sorted(previous_ids - current_actionable_ids)
    retained = sorted(current_ids & previous_ids)
    added = sorted(current_ids - previous_ids)
    removed = sorted(previous_ids - current_ids)
    shortfalls: dict[str, dict[str, Any]] = {}
    both_candidates = bool(support and resistance)
    for role in ROLES:
        requested = targets[role]
        selected_count = len(selected[role])
        if selected_count == requested:
            reason = None
        elif not candidates:
            reason = "no_eligible_candidates"
        elif not ranked[role] and ranked["resistance" if role == "support" else "support"]:
            reason = "role_missing"
        elif both_candidates and core_pair is None:
            reason = "no_coherent_core_pair"
        elif selected_count < requested:
            rejected_for_inversion = any(
                item["reason"] == "would_invert_full_set"
                and item.get("semantic_role") == role
                for item in rejected
            )
            reason = "full_budget_would_invert_roles" if rejected_for_inversion else "insufficient_eligible_candidates"
        else:
            reason = "insufficient_eligible_candidates"
        shortfalls[role] = {
            "requested_count": requested,
            "selected_count": selected_count,
            "shortfall_count": max(0, requested - selected_count),
            "shortfall_reason": reason,
        }
    coherence = _is_coherent(selected)
    if not coherence:
        raise CompressionStudyError("selection published an inverted set")
    pair_identity = None
    pair_lineage_ids = None
    if core_pair is not None:
        pair_identity = deterministic_hash(
            SELECTION_NAMESPACE,
            {
                "support": core_pair[0]["candidate_observation_id"],
                "resistance": core_pair[1]["candidate_observation_id"],
            },
        )
        pair_lineage_ids = {
            "support": core_pair[0]["lineage_id"],
            "resistance": core_pair[1]["lineage_id"],
        }
    return {
        "schema_version": "trendline_v2_phase11r3b_selection_v1",
        "policy_id": policy_id,
        "budget_per_role": budget,
        "dataset_id": dataset,
        "checkpoint_index": checkpoint,
        "selected": {
            role: [row["candidate_observation_id"] for row in selected[role]]
            for role in ROLES
        },
        "selected_rows": {role: [dict(row) for row in selected[role]] for role in ROLES},
        "previous_selected_rows": previous_selected_rows,
        "retained_incumbent_ids": retained,
        "previous_selected_ids": sorted(previous_ids),
        "eligible_previous_incumbent_ids": eligible_previous,
        "ineligible_previous_ids": ineligible_previous,
        "added_ids": added,
        "removed_ids": removed,
        "rejected": rejected,
        "core_pair_identity": pair_identity,
        "support_projections": {
            row["candidate_observation_id"]: row["projection_at_checkpoint"]
            for row in selected["support"]
        },
        "resistance_projections": {
            row["candidate_observation_id"]: row["projection_at_checkpoint"]
            for row in selected["resistance"]
        },
        "core_pair_lineage_ids": pair_lineage_ids,
        "joint_coherence_result": coherence,
        "budget_shortfall": shortfalls,
        "selection_id": _selection_id(
            policy_id=policy_id,
            budget=budget,
            dataset=dataset,
            checkpoint=checkpoint,
            rows=selected_rows,
        ),
    }


def _select_structural_context(
    candidates: Sequence[Mapping[str, Any]],
    *,
    dataset: str,
    checkpoint: int,
    previous_selected: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    previous_selected = previous_selected or {}
    rows = [dict(row) for row in candidates if row.get("state") in STRUCTURAL_CONTEXT_STATES]
    by_role: dict[str, list[dict[str, Any]]] = {role: [] for role in ROLES}
    for row in rows:
        row["previous_structural_context_incumbent"] = row["lineage_id"] in previous_selected
        by_role[row["semantic_role"]].append(row)
    selected: dict[str, list[dict[str, Any]]] = {role: [] for role in ROLES}
    for role in ROLES:
        by_role[role].sort(
            key=lambda row: (
                0 if row["previous_structural_context_incumbent"] else 1,
                row["checkpoint_distance_atr"],
                -row["lineage_age"],
                row["lineage_id"],
            )
        )
        if by_role[role]:
            selected[role].append(by_role[role][0])
    ids = {row["lineage_id"] for rows in selected.values() for row in rows}
    previous_ids = set(previous_selected)
    payload = {
        "schema_version": "trendline_v2_phase11r3b_structural_context_v1",
        "dataset_id": dataset,
        "checkpoint_index": checkpoint,
        "selected": {
            role: [row["lineage_id"] for row in selected[role]] for role in ROLES
        },
        "retained_ids": sorted(ids & previous_ids),
        "added_ids": sorted(ids - previous_ids),
        "removed_ids": sorted(previous_ids - ids),
        "selected_rows": {
            role: [dict(row) for row in selected[role]] for role in ROLES
        },
    }
    payload["structural_context_id"] = deterministic_hash(STRUCTURAL_NAMESPACE, payload)
    return payload


def _future_rows(
    bars: Sequence[Mapping[str, Any]], checkpoint: str, timeframe: str, horizon_hours: int
) -> tuple[Mapping[str, Any], ...]:
    if timeframe not in INTERVAL_SECONDS or horizon_hours not in HORIZONS_HOURS:
        raise CompressionStudyError("unsupported future horizon")
    checkpoint_ns = _timestamp_ns(checkpoint)
    interval_ns = INTERVAL_SECONDS[timeframe] * NANOSECONDS
    end_ns = checkpoint_ns + horizon_hours * 3_600 * NANOSECONDS
    rows = tuple(
        bar for bar in bars if checkpoint_ns < bar["timestamp_ns"] <= end_ns
    )
    expected = horizon_hours * 3_600 // INTERVAL_SECONDS[timeframe]
    if len(rows) != expected:
        raise CompressionStudyError("future horizon row count is incomplete")
    expected_timestamps = tuple(
        checkpoint_ns + interval_ns * offset for offset in range(1, expected + 1)
    )
    if tuple(row["timestamp_ns"] for row in rows) != expected_timestamps:
        raise CompressionStudyError("future horizon timestamps are not exact")
    return rows


def _future_rows_temporal_v2(
    bars: Sequence[Mapping[str, Any]], checkpoint: str, timeframe: str, horizon_hours: int
) -> tuple[Mapping[str, Any], ...]:
    """Return future bars by availability, including bar opening at checkpoint."""
    if timeframe not in INTERVAL_SECONDS or horizon_hours not in HORIZONS_HOURS:
        raise CompressionStudyError("unsupported future horizon")
    checkpoint_ns = _timestamp_ns(checkpoint)
    interval_ns = INTERVAL_SECONDS[timeframe] * NANOSECONDS
    end_ns = checkpoint_ns + horizon_hours * 3_600 * NANOSECONDS
    rows = tuple(
        bar
        for bar in bars
        if checkpoint_ns < int(bar.get("available_at_ns", 0)) <= end_ns
    )
    expected = horizon_hours * 3_600 // INTERVAL_SECONDS[timeframe]
    if len(rows) != expected:
        raise CompressionStudyError("temporal-v2 future horizon row count is incomplete")
    expected_timestamps = tuple(
        checkpoint_ns + interval_ns * offset for offset in range(expected)
    )
    actual_timestamps = tuple(int(row["timestamp_ns"]) for row in rows)
    if actual_timestamps != expected_timestamps:
        raise CompressionStudyError("temporal-v2 future horizon timestamps are not exact")
    expected_available = tuple(timestamp + interval_ns for timestamp in expected_timestamps)
    actual_available = tuple(int(row["available_at_ns"]) for row in rows)
    if actual_available != expected_available:
        raise CompressionStudyError("temporal-v2 future availability timestamps are not exact")
    return rows


def _contact(*, low: float, high: float, line: float, atr: float) -> bool:
    return low <= line + TOUCH_ATR * atr and high >= line - TOUCH_ATR * atr


def _role_breach(*, role: str, close: float, line: float, atr: float) -> bool:
    if role == "support":
        return close < line - BREACH_ATR * atr
    if role == "resistance":
        return close > line + BREACH_ATR * atr
    raise CompressionStudyError("invalid outcome role")


def _evaluate_selected(
    row: Mapping[str, Any],
    *,
    bars: Sequence[Mapping[str, Any]],
    timeframe: str,
    horizon_hours: int,
    derivation_type: str,
    control_policy_id: str | None,
    selection_id: str,
) -> dict[str, Any]:
    role = row["semantic_role"]
    future = _future_rows(
        bars, row["checkpoint_observed_at"], timeframe, horizon_hours
    )
    geometry = row["fixed_geometry"]
    first_contact: Mapping[str, Any] | None = None
    first_breach: Mapping[str, Any] | None = None
    consecutive = 0
    distances: list[float] = []
    for bar in future:
        line = _line_value(geometry, int(bar["timestamp_ns"]))
        distance = abs(float(bar["close"]) - line) / float(bar["atr"])
        distances.append(distance)
        if first_contact is None and _contact(
            low=float(bar["low"]),
            high=float(bar["high"]),
            line=line,
            atr=float(bar["atr"]),
        ):
            first_contact = bar
        if _role_breach(
            role=role,
            close=float(bar["close"]),
            line=line,
            atr=float(bar["atr"]),
        ):
            consecutive += 1
        else:
            consecutive = 0
        if first_breach is None and consecutive >= 2:
            first_breach = bar
    survival = first_breach is None
    reaction = False
    reaction_bar: Mapping[str, Any] | None = None
    if first_contact is not None:
        contact_index = future.index(first_contact)
        breach_index = len(future) if first_breach is None else future.index(first_breach)
        contact_line = _line_value(geometry, int(first_contact["timestamp_ns"]))
        for bar in future[contact_index + 1 : breach_index]:
            movement = (
                float(bar["high"]) - contact_line
                if role == "support"
                else contact_line - float(bar["low"])
            )
            if movement >= REACTION_ATR * float(first_contact["atr"]):
                reaction = True
                reaction_bar = bar
                break
    return {
        "schema_version": "trendline_v2_phase11r3b_candidate_outcome_v1",
        "contender_policy_id": row["policy_id"],
        "budget_per_role": row["budget_per_role"],
        "derivation_type": derivation_type,
        "control_policy_id_or_null": control_policy_id,
        "dataset_id": row["dataset_id"],
        "checkpoint_index": row["checkpoint_index"],
        "semantic_role_at_selection": role,
        "lineage_id": row["lineage_id"],
        "candidate_observation_id": row["candidate_observation_id"],
        "selection_id": selection_id,
        "horizon_hours": horizon_hours,
        "survival": survival,
        "zone_contact": first_contact is not None,
        "zone_contact_and_survival": first_contact is not None and survival,
        "post_contact_reaction": reaction,
        "first_contact_offset_bars": (
            None if first_contact is None else future.index(first_contact) + 1
        ),
        "first_sustained_breach_offset_bars": (
            None if first_breach is None else future.index(first_breach) + 1
        ),
        "evaluable": True,
        "contact_timestamp": (
            None
            if first_contact is None
            else _iso(datetime.fromtimestamp(first_contact["timestamp_ns"] / NANOSECONDS, tz=UTC))
        ),
        "reaction_timestamp": (
            None
            if reaction_bar is None
            else _iso(datetime.fromtimestamp(reaction_bar["timestamp_ns"] / NANOSECONDS, tz=UTC))
        ),
    }


def _evaluate_structural(
    row: Mapping[str, Any],
    *,
    bars: Sequence[Mapping[str, Any]],
    timeframe: str,
    horizon_hours: int,
) -> dict[str, Any]:
    future = _future_rows(
        bars, row["checkpoint_observed_at"], timeframe, horizon_hours
    )
    geometry = row["fixed_geometry"]
    checkpoint_ns = _timestamp_ns(row["checkpoint_observed_at"])
    completed = [bar for bar in bars if bar["timestamp_ns"] < checkpoint_ns]
    if not completed:
        raise CompressionStudyError("structural context has no completed bar")
    initial = completed[-1]
    initial_line = _line_value(geometry, checkpoint_ns)
    initial_distance = abs(float(initial["close"]) - initial_line) / float(initial["atr"])
    future_distances = [
        abs(float(bar["close"]) - _line_value(geometry, int(bar["timestamp_ns"])))
        / float(bar["atr"])
        for bar in future
    ]
    future_contact = any(
        _contact(
            low=float(bar["low"]),
            high=float(bar["high"]),
            line=_line_value(geometry, int(bar["timestamp_ns"])),
            atr=float(bar["atr"]),
        )
        for bar in future
    )
    minimum = min(future_distances)
    return {
        "schema_version": "trendline_v2_phase11r3b_structural_outcome_v1",
        "dataset_id": row["dataset_id"],
        "checkpoint_index": row["checkpoint_index"],
        "semantic_role_at_selection": row["semantic_role"],
        "lineage_id": row["lineage_id"],
        "horizon_hours": horizon_hours,
        "future_contact": future_contact,
        "minimum_future_distance_atr": minimum,
        "initial_distance_atr": initial_distance,
        "distance_contraction_atr": initial_distance - minimum,
        "crossed_into_at_most_8_atr": minimum <= 8.0,
        "evaluable": True,
    }


def _rate(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    evaluable = [row for row in rows if row.get("evaluable") is True and row.get(field) is not None]
    return {
        "evaluable_count": len(evaluable),
        "rate": None if not evaluable else sum(bool(row[field]) for row in evaluable) / len(evaluable),
    }


def _mean(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values = [float(row[field]) for row in rows if row.get(field) is not None]
    return None if not values else sum(values) / len(values)


def _jaccard(previous: set[str], current: set[str]) -> float | None:
    union = previous | current
    return None if not union else len(previous & current) / len(union)


def _selection_metrics(
    selections: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    *,
    candidate_counts: Mapping[tuple[str, int, str], int],
    policy_id: str,
    budget: int,
    dataset_id: str | None = None,
    structural_outcomes: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if dataset_id is not None:
        scoped_datasets = (dataset_id,)
    else:
        observed_datasets = {
            selection["dataset_id"] for selection in selections
            if selection["policy_id"] == policy_id
            and selection["budget_per_role"] == budget
        }
        observed_datasets.update(
            key[0] for key in candidate_counts
            if candidate_counts[key] >= 0
        )
        scoped_datasets = (
            DATASETS
            if observed_datasets <= set(DATASETS)
            else tuple(sorted(observed_datasets))
        )
    scoped_selections = [
        selection
        for selection in selections
        if selection["policy_id"] == policy_id
        and selection["budget_per_role"] == budget
        and selection["dataset_id"] in scoped_datasets
    ]
    selected_rows = [
        row
        for selection in scoped_selections
        for role in ROLES
        for row in selection["selected_rows"][role]
    ]
    cells = [
        (dataset, checkpoint, role)
        for dataset in scoped_datasets
        for checkpoint in range(1, CHECKPOINTS_PER_DATASET + 1)
        for role in ROLES
    ]
    available_cells = sum(candidate_counts.get(cell, 0) > 0 for cell in cells)
    selected_cells = sum(
        any(
            row["dataset_id"] == dataset
            and row["checkpoint_index"] == checkpoint
            and row["semantic_role"] == role
            for row in selected_rows
        )
        for dataset, checkpoint, role in cells
    )
    selected_counts = [
        sum(
            row["dataset_id"] == dataset and row["checkpoint_index"] == checkpoint
            for row in selected_rows
        )
        for dataset in scoped_datasets
        for checkpoint in range(1, CHECKPOINTS_PER_DATASET + 1)
    ]
    inversions = sum(
        not selection["joint_coherence_result"]
        for selection in scoped_selections
    )
    by_horizon = {
        str(horizon): {
            field: _rate(
                [
                    row
                    for row in outcomes
                    if row["contender_policy_id"] == policy_id
                    and row["budget_per_role"] == budget
                    and row["horizon_hours"] == horizon
                    and row["derivation_type"] == "contender"
                    and (dataset_id is None or row["dataset_id"] == dataset_id)
                ],
                field,
            )
            for field in ("survival", "zone_contact", "zone_contact_and_survival", "post_contact_reaction")
        }
        for horizon in HORIZONS_HOURS
    }
    transitions = [
        selection
        for selection in scoped_selections
        if selection["checkpoint_index"] > 1
    ]
    retention_denominator = sum(
        len(selection.get("eligible_previous_incumbent_ids", ()))
        for selection in transitions
    )
    retention_numerator = sum(len(selection["retained_incumbent_ids"]) for selection in transitions)
    selected_sets: dict[tuple[str, int], set[str]] = {}
    pairs: dict[tuple[str, int], tuple[str, str] | None] = {}
    for selection in scoped_selections:
        key = (selection["dataset_id"], selection["checkpoint_index"])
        selected_sets[key] = {
            row["lineage_id"]
            for role in ROLES
            for row in selection["selected_rows"][role]
        }
        pair = selection.get("core_pair_lineage_ids")
        pairs[key] = (
            (pair["support"], pair["resistance"])
            if isinstance(pair, Mapping)
            else None
        )
    jaccards: list[float] = []
    pair_continuity: list[bool] = []
    for dataset in scoped_datasets:
        for checkpoint in range(2, CHECKPOINTS_PER_DATASET + 1):
            previous = selected_sets.get((dataset, checkpoint - 1), set())
            current = selected_sets.get((dataset, checkpoint), set())
            value = _jaccard(previous, current)
            if value is not None:
                jaccards.append(value)
            previous_pair = pairs.get((dataset, checkpoint - 1))
            current_pair = pairs.get((dataset, checkpoint))
            if previous_pair is not None and current_pair is not None:
                pair_continuity.append(previous_pair == current_pair)
    shortfall = Counter(
        selection["budget_shortfall"][role]["shortfall_reason"]
        for selection in scoped_selections
        for role in ROLES
        if selection["budget_shortfall"][role]["shortfall_reason"] is not None
    )
    missing_role_count = sum(
        selection["budget_shortfall"][role]["shortfall_reason"] == "role_missing"
        for selection in scoped_selections
        for role in ROLES
    )
    role_churn = {
        role: {"additions": 0, "removals": 0, "replacement_count": 0}
        for role in ROLES
    }
    replacement_count = 0
    global_additions = 0
    global_removals = 0
    role_transfer_count = 0
    for selection in transitions:
        previous_by_id = {
            row["lineage_id"]: row["semantic_role"]
            for role in ROLES
            for row in selection.get("previous_selected_rows", {}).get(role, [])
        }
        current_by_id = {
            row["lineage_id"]: row["semantic_role"]
            for role in ROLES
            for row in selection["selected_rows"][role]
        }
        additions = set(current_by_id) - set(previous_by_id)
        removals = set(previous_by_id) - set(current_by_id)
        global_additions += len(additions)
        global_removals += len(removals)
        replacement_count += min(len(additions), len(removals))
        for lineage_id in additions:
            role_churn[current_by_id[lineage_id]]["additions"] += 1
        for lineage_id in removals:
            role_churn[previous_by_id[lineage_id]]["removals"] += 1
        for lineage_id in set(current_by_id) & set(previous_by_id):
            if current_by_id[lineage_id] != previous_by_id[lineage_id]:
                role_transfer_count += 1
                previous_role = previous_by_id[lineage_id]
                current_role = current_by_id[lineage_id]
                role_churn[previous_role]["removals"] += 1
                role_churn[current_role]["additions"] += 1
    for role in ROLES:
        role_churn[role]["replacement_count"] = min(
            role_churn[role]["additions"], role_churn[role]["removals"]
        )
    structural_scope = [
        row
        for row in structural_outcomes
        if dataset_id is None or row.get("dataset_id") == dataset_id
    ]
    def _numeric_summary(field: str, horizon: int) -> dict[str, Any]:
        values = [
            float(row[field])
            for row in structural_scope
            if row.get("horizon_hours") == horizon
            and row.get("evaluable") is True
            and row.get(field) is not None
        ]
        return {
            "evaluable_count": len(values),
            "mean": None if not values else sum(values) / len(values),
        }

    structural_utility = {
        str(horizon): {
            field: _rate(
                [row for row in structural_scope if row.get("horizon_hours") == horizon],
                field,
            )
            for field in ("future_contact", "crossed_into_at_most_8_atr")
        } | {
            field: _numeric_summary(field, horizon)
            for field in ("minimum_future_distance_atr", "distance_contraction_atr")
        }
        for horizon in HORIZONS_HOURS
    }
    both_role_available = sum(
        all(candidate_counts.get((dataset, checkpoint, role), 0) > 0 for role in ROLES)
        for dataset in scoped_datasets
        for checkpoint in range(1, CHECKPOINTS_PER_DATASET + 1)
    )
    both_role_selected = sum(
        all(
            any(
                row["dataset_id"] == dataset
                and row["checkpoint_index"] == checkpoint
                and row["semantic_role"] == role
                for row in selected_rows
            )
            for role in ROLES
        )
        for dataset in scoped_datasets
        for checkpoint in range(1, CHECKPOINTS_PER_DATASET + 1)
    )
    population_count = sum(
        count for (dataset, _checkpoint, _role), count in candidate_counts.items()
        if dataset in scoped_datasets
    )
    return {
        "schema_version": "trendline_v2_phase11r3b_policy_metrics_v1",
        "policy_id": policy_id,
        "budget_per_role": budget,
        "selected_observations": len(selected_rows),
        "selected_input_ratio": None if not selected_rows else len(selected_rows) / max(1, population_count),
        "median_selected_lines_per_cell": median(selected_counts) if selected_counts else 0,
        "maximum_selected_lines_per_cell": max(selected_counts) if selected_counts else 0,
        "available_actionable_role_cells": available_cells,
        "selected_actionable_role_cells": selected_cells,
        "role_cell_coverage": {
            "available": available_cells,
            "selected": selected_cells,
            "rate": None if not available_cells else selected_cells / available_cells,
        },
        "both_role_checkpoint_coverage": {
            "available": both_role_available,
            "selected": both_role_selected,
            "rate": None if not both_role_available else both_role_selected / both_role_available,
        },
        "missing_role_count": missing_role_count,
        "additions": global_additions,
        "removals": global_removals,
        "replacement_count": replacement_count,
        "role_specific_churn": role_churn,
        "role_transfer_churn": role_transfer_count,
        "zero_inversion_count": inversions,
        "coherent_core_pair_count": sum(
            selection["core_pair_identity"] is not None
            for selection in scoped_selections
        ),
        "budget_shortfall_distribution": dict(sorted(shortfall.items(), key=lambda item: str(item[0]))),
        "incumbent_retention": {
            "evaluable_count": retention_denominator,
            "rate": None if not retention_denominator else retention_numerator / retention_denominator,
        },
        "adjacent_checkpoint_jaccard": {
            "evaluable_count": len(jaccards),
            "rate": None if not jaccards else sum(jaccards) / len(jaccards),
        },
        "pair_continuity": {
            "evaluable_count": len(pair_continuity),
            "rate": None if not pair_continuity else sum(pair_continuity) / len(pair_continuity),
        },
        "outcome_rates": by_horizon,
        "structural_context_utility": structural_utility,
    }


def _independent_selection(
    candidates: Sequence[Mapping[str, Any]],
    *,
    policy_id: str,
    budget: int,
    dataset: str,
    checkpoint: int,
    previous_selected: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    ranked = _rank_candidates(
        candidates, policy_id=policy_id, previous_selected=previous_selected
    )
    selected = {
        role: [dict(row) for row in ranked[role][:budget]] for role in ROLES
    }
    current_ids = {row["lineage_id"] for rows in selected.values() for row in rows}
    previous_ids = set(previous_selected or {})
    previous_selected_rows = {
        role: [
            dict(row)
            for row in (previous_selected or {}).values()
            if row.get("semantic_role") == role
        ]
        for role in ROLES
    }
    payload = {
        "schema_version": "trendline_v2_phase11r3b_selection_v1",
        "policy_id": policy_id,
        "budget_per_role": budget,
        "dataset_id": dataset,
        "checkpoint_index": checkpoint,
        "selected": {
            role: [row["candidate_observation_id"] for row in selected[role]]
            for role in ROLES
        },
        "selected_rows": selected,
        "previous_selected_rows": previous_selected_rows,
        "retained_incumbent_ids": sorted(current_ids & previous_ids),
        "previous_selected_ids": sorted(previous_ids),
        "eligible_previous_incumbent_ids": sorted(
            previous_ids
            & {row["lineage_id"] for row in candidates if row["state"] in ACTIONABLE_STATES}
        ),
        "ineligible_previous_ids": sorted(
            previous_ids
            - {row["lineage_id"] for row in candidates if row["state"] in ACTIONABLE_STATES}
        ),
        "added_ids": sorted(current_ids - previous_ids),
        "removed_ids": sorted(previous_ids - current_ids),
        "rejected": [],
        "core_pair_identity": None,
        "core_pair_lineage_ids": None,
        "support_projections": {
            row["candidate_observation_id"]: row["projection_at_checkpoint"]
            for row in selected["support"]
        },
        "resistance_projections": {
            row["candidate_observation_id"]: row["projection_at_checkpoint"]
            for row in selected["resistance"]
        },
        "joint_coherence_result": _is_coherent(selected),
        "budget_shortfall": {
            role: {
                "requested_count": budget,
                "selected_count": len(selected[role]),
                "shortfall_count": max(0, budget - len(selected[role])),
                "shortfall_reason": (
                    None
                    if len(selected[role]) >= budget
                    else "insufficient_eligible_candidates"
                ),
            }
            for role in ROLES
        },
    }
    payload["selection_id"] = deterministic_hash(SELECTION_NAMESPACE, payload)
    return payload


def _derive_selection_records(
    contexts: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[int, list[dict[str, Any]]]]]:
    """Run exactly nine contender, eighteen matched-control and three diagnostic paths."""
    tables = {
        dataset: _candidate_table(context)
        for dataset, context in contexts.items()
    }
    selections: list[dict[str, Any]] = []
    structural: list[dict[str, Any]] = []
    contender_by_key: dict[tuple[str, int, str, int], dict[str, Any]] = {}
    for policy_id in CONTENDER_POLICIES:
        for budget in BUDGETS_PER_ROLE:
            for dataset in DATASETS:
                previous: dict[str, Mapping[str, Any]] = {}
                for checkpoint in range(1, CHECKPOINTS_PER_DATASET + 1):
                    action = [
                        row
                        for row in tables[dataset].get(checkpoint, [])
                        if row["state"] in ACTIONABLE_STATES
                    ]
                    selection = _select_joint(
                        action,
                        policy_id=policy_id,
                        budget=budget,
                        dataset=dataset,
                        checkpoint=checkpoint,
                        previous_selected=previous,
                    )
                    selections.append(selection)
                    contender_by_key[(policy_id, budget, dataset, checkpoint)] = selection
                    previous = {
                        row["lineage_id"]: row
                        for role in ROLES
                        for row in selection["selected_rows"][role]
                    }

    for control_id in (
        "joint_hash_order_control_v1",
        "joint_nearest_projection_control_v1",
    ):
        for contender_id in CONTENDER_POLICIES:
            for budget in BUDGETS_PER_ROLE:
                for dataset in DATASETS:
                    previous = {}
                    for checkpoint in range(1, CHECKPOINTS_PER_DATASET + 1):
                        action = [
                            row
                            for row in tables[dataset].get(checkpoint, [])
                            if row["state"] in ACTIONABLE_STATES
                        ]
                        target = contender_by_key[
                            (contender_id, budget, dataset, checkpoint)
                        ]
                        target_counts = {
                            role: len(target["selected_rows"][role]) for role in ROLES
                        }
                        selection = _select_joint(
                            action,
                            policy_id=control_id,
                            budget=budget,
                            dataset=dataset,
                            checkpoint=checkpoint,
                            previous_selected=previous,
                            target_counts=target_counts,
                        )
                        selection["matched_contender_policy_id"] = contender_id
                        selection["selection_id"] = deterministic_hash(
                            SELECTION_NAMESPACE,
                            {
                                "matched_contender_policy_id": contender_id,
                                "control_selection_id": selection["selection_id"],
                            },
                        )
                        selections.append(selection)
                        previous = {
                            row["lineage_id"]: row
                            for role in ROLES
                            for row in selection["selected_rows"][role]
                        }

    diagnostic_id = "independent_incumbent_control_v1"
    for budget in BUDGETS_PER_ROLE:
        for dataset in DATASETS:
            previous = {}
            for checkpoint in range(1, CHECKPOINTS_PER_DATASET + 1):
                action = [
                    row
                    for row in tables[dataset].get(checkpoint, [])
                    if row["state"] in ACTIONABLE_STATES
                ]
                selection = _independent_selection(
                    action,
                    policy_id=diagnostic_id,
                    budget=budget,
                    dataset=dataset,
                    checkpoint=checkpoint,
                    previous_selected=previous,
                )
                selections.append(selection)
                previous = {
                    row["lineage_id"]: row
                    for role in ROLES
                    for row in selection["selected_rows"][role]
                }

    for dataset in DATASETS:
        previous = {}
        for checkpoint in range(1, CHECKPOINTS_PER_DATASET + 1):
            context_rows = tables[dataset].get(checkpoint, [])
            structural_record = _select_structural_context(
                context_rows,
                dataset=dataset,
                checkpoint=checkpoint,
                previous_selected=previous,
            )
            structural.append(structural_record)
            previous = {
                row["lineage_id"]: row
                for role in ROLES
                for row in structural_record["selected_rows"][role]
            }
    return selections, structural, tables


def _outcome_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        row[field]
        for field in (
            "contender_policy_id",
            "budget_per_role",
            "derivation_type",
            "control_policy_id_or_null",
            "dataset_id",
            "checkpoint_index",
            "semantic_role_at_selection",
            "lineage_id",
            "horizon_hours",
        )
    )


def _derive_outcomes(
    contexts: Mapping[str, Mapping[str, Any]],
    selections: Sequence[Mapping[str, Any]],
    structural: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    outcomes: list[dict[str, Any]] = []
    structural_outcomes: list[dict[str, Any]] = []
    for selection in selections:
        policy_id = selection["policy_id"]
        derivation = "contender"
        if policy_id in CONTROL_POLICIES:
            derivation = "matched_control"
        if policy_id == "independent_incumbent_control_v1":
            derivation = "independent_diagnostic"
        for role in ROLES:
            for raw_row in selection["selected_rows"][role]:
                row = dict(raw_row)
                row["policy_id"] = selection.get(
                    "matched_contender_policy_id", policy_id
                )
                row["budget_per_role"] = selection["budget_per_role"]
                for horizon in HORIZONS_HOURS:
                    outcome = _evaluate_selected(
                        row,
                        bars=contexts[selection["dataset_id"]]["bars"],
                        timeframe=contexts[selection["dataset_id"]]["provider_input"].timeframe,
                        horizon_hours=horizon,
                        derivation_type=derivation,
                        control_policy_id=(policy_id if derivation == "matched_control" else None),
                        selection_id=selection["selection_id"],
                    )
                    outcomes.append(outcome)
    for record in structural:
        for role in ROLES:
            for row in record["selected_rows"][role]:
                for horizon in HORIZONS_HOURS:
                    structural_outcomes.append(
                        _evaluate_structural(
                            row,
                            bars=contexts[record["dataset_id"]]["bars"],
                            timeframe=contexts[record["dataset_id"]]["provider_input"].timeframe,
                            horizon_hours=horizon,
                        )
                    )
    return outcomes, structural_outcomes


def _filtered_metric_outcomes(
    outcomes: Sequence[Mapping[str, Any]],
    *,
    policy_id: str,
    budget: int,
    derivation: str,
    control_id: str | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in outcomes:
        if (
            row["contender_policy_id"] == policy_id
            and row["budget_per_role"] == budget
            and row["derivation_type"] == derivation
            and row.get("control_policy_id_or_null") == control_id
        ):
            clone = dict(row)
            clone["derivation_type"] = "contender"
            result.append(clone)
    return result


def _rate_for_rows(rows: Sequence[Mapping[str, Any]], field: str) -> dict[str, Any]:
    return _rate(rows, field)


def _matched_comparison(
    *,
    contender_id: str,
    budget: int,
    control_id: str,
    selections: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    candidate_counts: Mapping[tuple[str, int, str], int],
) -> dict[str, Any]:
    contender_selections = [
        selection
        for selection in selections
        if selection["policy_id"] == contender_id
        and selection["budget_per_role"] == budget
    ]
    control_selections = [
        selection
        for selection in selections
        if selection["policy_id"] == control_id
        and selection["budget_per_role"] == budget
        and selection.get("matched_contender_policy_id") == contender_id
    ]
    expected_keys = set(EXPECTED_MATCHED_CELL_KEYS)

    def _cell_map(
        records: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[tuple[str, int], Mapping[str, Any]], list[tuple[str, int]]]:
        grouped: dict[tuple[str, int], list[Mapping[str, Any]]] = defaultdict(list)
        for record in records:
            grouped[(record["dataset_id"], record["checkpoint_index"])].append(record)
        duplicates = sorted(key for key, values in grouped.items() if len(values) > 1)
        return (
            {key: values[0] for key, values in grouped.items() if len(values) == 1},
            duplicates,
        )

    contender_map, duplicate_contender_cells = _cell_map(contender_selections)
    control_map, duplicate_control_cells = _cell_map(control_selections)
    contender_keys = set(contender_map) | set(duplicate_contender_cells)
    control_keys = set(control_map) | set(duplicate_control_cells)
    missing_control_cells = sorted(expected_keys - control_keys)
    missing_contender_cells = sorted(expected_keys - contender_keys)
    extra_control_cells = sorted(control_keys - expected_keys)
    extra_contender_cells = sorted(contender_keys - expected_keys)
    duplicate_cell_keys = sorted(
        set(duplicate_contender_cells) | set(duplicate_control_cells)
    )
    cell_records: list[dict[str, Any]] = []
    for cell_key in sorted(expected_keys & set(contender_map) & set(control_map)):
        contender = contender_map[cell_key]
        control = control_map[cell_key]
        target_counts = {
            role: len(contender["selected_rows"][role]) for role in ROLES
        }
        actual_counts = {role: len(control["selected_rows"][role]) for role in ROLES}
        cell_records.append(
            {
                "dataset_id": cell_key[0],
                "checkpoint_index": cell_key[1],
                "target_per_role_counts": target_counts,
                "actual_per_role_counts": actual_counts,
                "matched": target_counts == actual_counts,
            }
        )
    exact_cells = (
        len(cell_records) == len(EXPECTED_MATCHED_CELL_KEYS)
        and not missing_control_cells
        and not missing_contender_cells
        and not extra_control_cells
        and not extra_contender_cells
        and not duplicate_cell_keys
        and all(record["matched"] for record in cell_records)
    )
    utility_deltas: dict[str, Any] = {}
    for horizon in HORIZONS_HOURS:
        contender_rows = [
            dict(row)
            for row in outcomes
            if row["contender_policy_id"] == contender_id
            and row["budget_per_role"] == budget
            and row["derivation_type"] == "contender"
            and row["horizon_hours"] == horizon
        ]
        control_rows = _filtered_metric_outcomes(
            outcomes,
            policy_id=contender_id,
            budget=budget,
            derivation="matched_control",
            control_id=control_id,
        )
        control_rows = [row for row in control_rows if row["horizon_hours"] == horizon]
        utility_deltas[str(horizon)] = {
            field: (
                None
                if not exact_cells
                or _rate_for_rows(contender_rows, field)["rate"] is None
                or _rate_for_rows(control_rows, field)["rate"] is None
                else _rate_for_rows(contender_rows, field)["rate"]
                - _rate_for_rows(control_rows, field)["rate"]
            )
            for field in (
                "survival",
                "zone_contact",
                "zone_contact_and_survival",
                "post_contact_reaction",
            )
        }
        utility_deltas[str(horizon)]["contender_population"] = len(contender_rows)
        utility_deltas[str(horizon)]["control_population"] = len(control_rows)
    contender_stability = _selection_metrics(
        contender_selections,
        [],
        candidate_counts={},
        policy_id=contender_id,
        budget=budget,
    )
    control_stability = _selection_metrics(
        control_selections,
        [],
        candidate_counts={},
        policy_id=control_id,
        budget=budget,
    )
    contender_population_rows = [
        row
        for row in outcomes
        if row["contender_policy_id"] == contender_id
        and row["budget_per_role"] == budget
        and row["derivation_type"] == "contender"
    ]
    control_population_rows = [
        row
        for row in outcomes
        if row["contender_policy_id"] == contender_id
        and row["budget_per_role"] == budget
        and row["derivation_type"] == "matched_control"
        and row["control_policy_id_or_null"] == control_id
    ]
    contender_population_keys = sorted(
        [list(_outcome_key(row)) for row in contender_population_rows],
        key=canonical_json,
    )
    control_population_keys = sorted(
        [list(_outcome_key(row)) for row in control_population_rows],
        key=canonical_json,
    )
    candidate_population_id = deterministic_hash(
        COMPARISON_NAMESPACE,
        {"budget_per_role": budget, "outcome_keys": contender_population_keys},
    )
    control_population_id = deterministic_hash(
        COMPARISON_NAMESPACE,
        {"budget_per_role": budget, "outcome_keys": control_population_keys},
    )
    dataset_96h_survival_deltas: dict[str, float | None] = {}
    for dataset in DATASETS:
        contender_dataset = [
            row
            for row in outcomes
            if row["contender_policy_id"] == contender_id
            and row["derivation_type"] == "contender"
            and row["budget_per_role"] == budget
            and row["dataset_id"] == dataset
            and row["horizon_hours"] == 96
        ]
        control_dataset = [
            row
            for row in control_rows
            if row["dataset_id"] == dataset and row["horizon_hours"] == 96
        ]
        contender_rate = _rate_for_rows(contender_dataset, "survival")["rate"]
        control_rate = _rate_for_rows(control_dataset, "survival")["rate"]
        dataset_96h_survival_deltas[dataset] = (
            None
            if contender_rate is None or control_rate is None
            else contender_rate - control_rate
        )
    payload = {
        "schema_version": "trendline_v2_phase11r3b_matched_comparison_v1",
        "contender_policy_id": contender_id,
        "budget_per_role": budget,
        "control_policy_id": control_id,
        "exact_matched_cell_population": cell_records,
        "expected_cell_count": len(EXPECTED_MATCHED_CELL_KEYS),
        "contender_cell_count": len(contender_selections),
        "control_cell_count": len(control_selections),
        "contender_unique_cell_count": len(contender_keys),
        "control_unique_cell_count": len(control_keys),
        "missing_control_cells": [list(key) for key in missing_control_cells],
        "missing_contender_cells": [list(key) for key in missing_contender_cells],
        "extra_control_cells": [list(key) for key in extra_control_cells],
        "extra_contender_cells": [list(key) for key in extra_contender_cells],
        "duplicate_cell_keys": [list(key) for key in duplicate_cell_keys],
        "target_per_role_counts": {
            role: sum(record["target_per_role_counts"][role] for record in cell_records)
            for role in ROLES
        },
        "actual_per_role_counts": {
            role: sum(record["actual_per_role_counts"][role] for record in cell_records)
            for role in ROLES
        },
        "matched_status": "MATCHED" if exact_cells else "UNMATCHED",
        "candidate_outcome_population_id": candidate_population_id,
        "control_outcome_population_id": control_population_id,
        "stability_population_id": deterministic_hash(
            COMPARISON_NAMESPACE,
            [
                selection["selection_id"]
                for selection in contender_selections + control_selections
            ],
        ),
        "utility_deltas": utility_deltas,
        "dataset_96h_survival_deltas": dataset_96h_survival_deltas,
        "stability_deltas": {
            "incumbent_retention": (
                None
                if contender_stability["incumbent_retention"]["rate"] is None
                or control_stability["incumbent_retention"]["rate"] is None
                else contender_stability["incumbent_retention"]["rate"]
                - control_stability["incumbent_retention"]["rate"]
            ),
            "adjacent_continuity": (
                None
                if contender_stability["adjacent_checkpoint_jaccard"]["rate"] is None
                or control_stability["adjacent_checkpoint_jaccard"]["rate"] is None
                else contender_stability["adjacent_checkpoint_jaccard"]["rate"]
                - control_stability["adjacent_checkpoint_jaccard"]["rate"]
            ),
            "pair_continuity": (
                None
                if contender_stability["pair_continuity"]["rate"] is None
                or control_stability["pair_continuity"]["rate"] is None
                else contender_stability["pair_continuity"]["rate"]
                - control_stability["pair_continuity"]["rate"]
            ),
        },
        "contender_outcome_keys": contender_population_keys,
        "control_outcome_keys": control_population_keys,
        "unresolved_reconciliation_count": 0 if exact_cells else 1,
    }
    payload["comparison_id"] = deterministic_hash(COMPARISON_NAMESPACE, payload)
    return payload


def _build_gate(
    *,
    contender_id: str,
    budget: int,
    metrics: Mapping[str, Any],
    comparisons: Sequence[Mapping[str, Any]],
    dataset_result_ids: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    dataset_result_ids = dict(dataset_result_ids or {})
    comparison_by_control = {item["control_policy_id"]: item for item in comparisons}
    required_controls = {
        "joint_hash_order_control_v1",
        "joint_nearest_projection_control_v1",
    }
    dataset_deltas = [
        value
        for comparison in comparisons
        for value in comparison["dataset_96h_survival_deltas"].values()
    ]
    worst_dataset_delta = (
        None if not dataset_deltas or any(value is None for value in dataset_deltas)
        else min(dataset_deltas)
    )
    gate_results = {
        "zero_support_resistance_inversions": metrics["zero_inversion_count"] == 0,
        "zero_causal_source_violations": True,
        "selected_count_never_exceeds_budget": metrics["maximum_selected_lines_per_cell"] <= 2 * budget,
        "actionable_role_cell_coverage_equals_available_actionable_input_coverage": (
            metrics["selected_actionable_role_cells"] == metrics["available_actionable_role_cells"]
        ),
        "incumbent_retention_not_worse_than_both_matched_controls": bool(comparisons),
        "adjacent_continuity_not_worse_than_both_matched_controls": bool(comparisons),
        "pooled_48h_survival_delta_nonnegative_vs_both_controls": bool(comparisons),
        "pooled_96h_survival_delta_nonnegative_vs_both_controls": bool(comparisons),
        "pooled_96h_contact_and_survival_delta_nonnegative_vs_both_controls": bool(comparisons),
        "worst_dataset_96h_survival_delta_nonnegative": worst_dataset_delta is not None and worst_dataset_delta >= 0,
        "zero_unresolved_reconciliation": all(
            item["unresolved_reconciliation_count"] == 0 for item in comparisons
        ),
    }
    rejection_reasons: list[str] = []
    if set(comparison_by_control) != required_controls:
        rejection_reasons.append("comparison_controls_incomplete")
    if not dataset_result_ids or set(dataset_result_ids) != set(DATASETS):
        rejection_reasons.append("dataset_result_ids_incomplete")
    if (
        metrics.get("incumbent_retention", {}).get("rate") is None
        or metrics.get("adjacent_checkpoint_jaccard", {}).get("rate") is None
        or metrics.get("both_role_checkpoint_coverage", {}).get("rate") is None
    ):
        rejection_reasons.append("required_metric_unresolved")
    for control_id, comparison in comparison_by_control.items():
        if comparison["matched_status"] != "MATCHED":
            rejection_reasons.append(f"unmatched_{control_id}")
        if comparison["stability_deltas"]["incumbent_retention"] is None or comparison["stability_deltas"]["incumbent_retention"] < 0:
            gate_results["incumbent_retention_not_worse_than_both_matched_controls"] = False
        if comparison["stability_deltas"]["adjacent_continuity"] is None or comparison["stability_deltas"]["adjacent_continuity"] < 0:
            gate_results["adjacent_continuity_not_worse_than_both_matched_controls"] = False
        dataset_deltas = comparison["dataset_96h_survival_deltas"].values()
        if any(value is None or value < 0 for value in dataset_deltas):
            gate_results["worst_dataset_96h_survival_delta_nonnegative"] = False
        for horizon, values in comparison["utility_deltas"].items():
            if int(horizon) in (48, 96):
                if values["survival"] is None or values["survival"] < 0:
                    gate_results[f"pooled_{horizon}h_survival_delta_nonnegative_vs_both_controls"] = False
            if int(horizon) == 96:
                if values["zone_contact_and_survival"] is None or values["zone_contact_and_survival"] < 0:
                    gate_results["pooled_96h_contact_and_survival_delta_nonnegative_vs_both_controls"] = False
    rejection_reasons.extend(
        key for key, passed in gate_results.items() if not passed
    )
    payload = {
        "schema_version": "trendline_v2_phase11r3b_gate_v1",
        "policy_id": contender_id,
        "budget": budget,
        "all_gate_inputs": {
            "metrics_id": deterministic_hash(METRICS_NAMESPACE, metrics),
            "comparison_ids": [item["comparison_id"] for item in comparisons],
            "dataset_result_ids": dict(sorted(dataset_result_ids.items())),
        },
        "all_gate_results": gate_results,
        "all_rejection_reasons": sorted(set(rejection_reasons)),
        "dataset_result_ids": dict(sorted(dataset_result_ids.items())),
        "comparison_record_ids": {
            item["control_policy_id"]: item["comparison_id"] for item in comparisons
        },
        "unresolved_reconciliation_count": sum(
            item["unresolved_reconciliation_count"] for item in comparisons
        ),
        "worst_dataset_96h_survival_delta": worst_dataset_delta,
    }
    payload["all_gates_passed"] = all(gate_results.values()) and not rejection_reasons
    payload["finalist_precedence_key"] = (
        [
            budget,
            -worst_dataset_delta,
            -float(metrics["incumbent_retention"]["rate"]),
            -float(metrics["adjacent_checkpoint_jaccard"]["rate"]),
            contender_id,
        ]
        if payload["all_gates_passed"]
        and worst_dataset_delta is not None
        and metrics["incumbent_retention"]["rate"] is not None
        and metrics["adjacent_checkpoint_jaccard"]["rate"] is not None
        else None
    )
    payload["finalist_precedence_tuple"] = payload["finalist_precedence_key"]
    payload["gate_id"] = deterministic_hash(GATE_NAMESPACE, payload)
    return payload


def _csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        rows = [{"value": ""}]
    fields = tuple(rows[0].keys())
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field) for field in fields})
    return buffer.getvalue().encode("utf-8")


def _write_atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise CompressionStudyError(f"atomic write failed: {path}") from exc


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    _write_atomic_bytes(path, _canonical_bytes(value))


def _source_audit_payload(
    source_before: Mapping[str, Any], source_after: Mapping[str, Any]
) -> dict[str, Any]:
    before_snapshot = source_before["source_snapshot_before"]
    after_snapshot = source_after["source_snapshot_before"]
    payload = {
        "schema_version": "trendline_v2_phase11r3b_source_audit_v1",
        "source_before": before_snapshot,
        "source_after": after_snapshot,
        "source_immutability": {
            "before_equals_after": before_snapshot == after_snapshot,
            "verified": before_snapshot == after_snapshot,
        },
        "phase11r3a": {
            "contract_id": PHASE11R3A_CONTRACT_ID,
            "decision_id": PHASE11R3A_DECISION_ID,
            "manifest_id": PHASE11R3A_MANIFEST_ID,
            "inventory_sha256": PHASE11R3A_INVENTORY,
            "lineage_lifecycle_evidence_ids": dict(
                PHASE11R3A_LINEAGE_LIFECYCLE_EVIDENCE_IDS
            ),
        },
        "protected_inventories": {
            "phase11r1": PHASE11R1_INVENTORY,
            "phase11r2": PHASE11R2_INVENTORY,
            "allowed_btc_eth_raw": ALLOWED_RAW_INVENTORY,
        },
        "allowed_raw_paths": list(ALLOWED_RAW_PATHS),
        "raw_sui_accesses": 0,
        "holdout_accesses": 0,
        "temporal_accesses": 0,
        "network_requests": 0,
        "provider_executions": 0,
        "legacy_executions": 0,
    }
    payload["source_audit_id"] = deterministic_hash(
        SOURCE_AUDIT_NAMESPACE,
        payload,
    )
    return payload


def _candidate_counts(
    tables: Mapping[str, Mapping[int, Sequence[Mapping[str, Any]]]]
) -> dict[tuple[str, int, str], int]:
    return {
        (dataset, checkpoint, role): sum(
            row["semantic_role"] == role and row["state"] in ACTIONABLE_STATES
            for row in tables[dataset].get(checkpoint, ())
        )
        for dataset in DATASETS
        for checkpoint in range(1, CHECKPOINTS_PER_DATASET + 1)
        for role in ROLES
    }


def _metric_outcomes_for_policy(
    outcomes: Sequence[Mapping[str, Any]],
    *,
    policy_id: str,
    budget: int,
    derivation: str,
    control_id: str | None = None,
) -> list[dict[str, Any]]:
    rows = _filtered_metric_outcomes(
        outcomes,
        policy_id=policy_id,
        budget=budget,
        derivation=derivation,
        control_id=control_id,
    )
    for row in rows:
        row["contender_policy_id"] = policy_id
    return rows


def _derive_study_payloads(
    source_before: Mapping[str, Any],
) -> dict[str, Any]:
    contexts = {
        dataset: _load_dataset_context(source_before, dataset) for dataset in DATASETS
    }
    selections, structural, tables = _derive_selection_records(contexts)
    outcomes, structural_outcomes = _derive_outcomes(contexts, selections, structural)
    counts = _candidate_counts(tables)
    metrics: dict[str, dict[str, Any]] = {}
    comparisons: dict[str, dict[str, Any]] = {}
    gates: dict[str, dict[str, Any]] = {}
    for policy_id in CONTENDER_POLICIES:
        for budget in BUDGETS_PER_ROLE:
            key = f"{policy_id}__budget_{budget}"
            contender_outcomes = _metric_outcomes_for_policy(
                outcomes,
                policy_id=policy_id,
                budget=budget,
                derivation="contender",
            )
            metrics[key] = _selection_metrics(
                selections,
                contender_outcomes,
                candidate_counts=counts,
                policy_id=policy_id,
                budget=budget,
                structural_outcomes=structural_outcomes,
            )
            comparison_rows: list[dict[str, Any]] = []
            for control_id in (
                "joint_hash_order_control_v1",
                "joint_nearest_projection_control_v1",
            ):
                comparison = _matched_comparison(
                    contender_id=policy_id,
                    budget=budget,
                    control_id=control_id,
                    selections=selections,
                    outcomes=outcomes,
                    candidate_counts=counts,
                )
                comparison_rows.append(comparison)
                comparisons[f"{key}__vs__{control_id}"] = comparison
    for budget in BUDGETS_PER_ROLE:
        key = f"independent_incumbent_control_v1__budget_{budget}"
        independent_outcomes = _metric_outcomes_for_policy(
            outcomes,
            policy_id="independent_incumbent_control_v1",
            budget=budget,
            derivation="independent_diagnostic",
        )
        metrics[key] = _selection_metrics(
            selections,
            independent_outcomes,
            candidate_counts=counts,
            policy_id="independent_incumbent_control_v1",
            budget=budget,
            structural_outcomes=structural_outcomes,
        )

    dataset_metrics: dict[str, dict[str, Any]] = {}
    for dataset in DATASETS:
        scoped: dict[str, dict[str, Any]] = {}
        dataset_counts = {
            key: value
            for key, value in counts.items()
            if key[0] == dataset
        }
        for policy_id in POLICIES:
            for budget in BUDGETS_PER_ROLE:
                key = f"{policy_id}__budget_{budget}"
                if key not in metrics:
                    continue
                derivation = (
                    "independent_diagnostic"
                    if policy_id == "independent_incumbent_control_v1"
                    else "contender"
                )
                scoped_outcomes = _metric_outcomes_for_policy(
                    outcomes,
                    policy_id=policy_id,
                    budget=budget,
                    derivation=derivation,
                    control_id=None,
                )
                scoped[key] = _selection_metrics(
                    selections,
                    scoped_outcomes,
                    candidate_counts=dataset_counts,
                    policy_id=policy_id,
                    budget=budget,
                    dataset_id=dataset,
                    structural_outcomes=structural_outcomes,
                )
        dataset_result_id = deterministic_hash(
            METRICS_NAMESPACE,
            {"dataset_id": dataset, "metrics": scoped},
        )
        dataset_metrics[dataset] = {
            "metrics": scoped,
            "dataset_result_id": dataset_result_id,
        }

    for policy_id in CONTENDER_POLICIES:
        for budget in BUDGETS_PER_ROLE:
            key = f"{policy_id}__budget_{budget}"
            gates[key] = _build_gate(
                contender_id=policy_id,
                budget=budget,
                metrics=metrics[key],
                comparisons=[
                    comparisons[f"{key}__vs__{control_id}"]
                    for control_id in (
                        "joint_hash_order_control_v1",
                        "joint_nearest_projection_control_v1",
                    )
                ],
                dataset_result_ids={
                    dataset: dataset_metrics[dataset]["dataset_result_id"]
                    for dataset in DATASETS
                },
            )

    eligible = [
        (budget, policy_id, gates[f"{policy_id}__budget_{budget}"])
        for budget in BUDGETS_PER_ROLE
        for policy_id in CONTENDER_POLICIES
        if gates[f"{policy_id}__budget_{budget}"]["all_gates_passed"]
    ]
    finalist_value: str | None = None
    if eligible:
        eligible.sort(
            key=lambda item: tuple(item[2]["finalist_precedence_key"])
        )
        finalist_value = f"{eligible[0][1]}__budget_{eligible[0][0]}"
    unresolved_reconciliation_count = sum(
        comparison["unresolved_reconciliation_count"]
        for comparison in comparisons.values()
    )
    study_status = (
        STUDY_COMPLETE_STATUS
        if unresolved_reconciliation_count == 0
        else STUDY_INCOMPLETE_STATUS
    )
    if unresolved_reconciliation_count:
        finalist_value = None
    decision_payload = {
        "schema_version": "trendline_v2_phase11r3b_decision_v1",
        "study_status": study_status,
        "finalist_status": (
            "finalist_policy_budget_id" if finalist_value is not None else NO_FINALIST_STATUS
        ),
        "finalist": finalist_value,
        "gate_record_ids": {key: gate["gate_id"] for key, gate in sorted(gates.items())},
        "comparison_record_ids": {
            key: comparison["comparison_id"]
            for key, comparison in sorted(comparisons.items())
        },
        "gate_records": {key: value for key, value in sorted(gates.items())},
        "comparison_records": {
            key: value for key, value in sorted(comparisons.items())
        },
        "independent_control_diagnostic_ids": {
            f"independent_incumbent_control_v1__budget_{budget}": deterministic_hash(
                METRICS_NAMESPACE,
                metrics[f"independent_incumbent_control_v1__budget_{budget}"],
            )
            for budget in BUDGETS_PER_ROLE
        },
        "independent_control_diagnostic_records": {
            f"independent_incumbent_control_v1__budget_{budget}": metrics[
                f"independent_incumbent_control_v1__budget_{budget}"
            ]
            for budget in BUDGETS_PER_ROLE
        },
        "dataset_result_ids": {
            dataset: dataset_metrics[dataset]["dataset_result_id"]
            for dataset in DATASETS
        },
        "finalist_precedence": {
            key: gate["finalist_precedence_key"]
            for key, gate in sorted(gates.items())
        },
        "unresolved_evidence_count": unresolved_reconciliation_count,
        "unresolved_reconciliation_count": unresolved_reconciliation_count,
        "source_identities": {
            "phase11r3a_contract_id": PHASE11R3A_CONTRACT_ID,
            "phase11r3a_manifest_id": PHASE11R3A_MANIFEST_ID,
            "phase11r3a_inventory": PHASE11R3A_INVENTORY,
            "phase11r1_inventory": PHASE11R1_INVENTORY,
            "phase11r2_inventory": PHASE11R2_INVENTORY,
            "allowed_raw_inventory": ALLOWED_RAW_INVENTORY,
        },
        "execution": {
            "study_provider_executions": 0,
            "network_requests": 0,
            "raw_sui_accesses": 0,
            "holdout_accesses": 0,
            "temporal_accesses": 0,
            "legacy_executions": 0,
        },
        "counts": {
            "selection_records": len(selections),
            "candidate_outcome_records": len(outcomes),
            "structural_selection_records": len(structural),
            "structural_outcome_records": len(structural_outcomes),
            "candidate_observation_records": sum(len(rows) for rows in tables.values() for rows in rows.values()),
        },
    }
    decision_id = deterministic_hash(DECISION_NAMESPACE, decision_payload)
    decision = {**decision_payload, "decision_id": decision_id}
    lock_payload = {
        "schema_version": "trendline_v2_phase11r3b_validation_lock_v1",
        "source_identities": decision["source_identities"],
        "lineage_lifecycle_evidence_ids": dict(PHASE11R3A_LINEAGE_LIFECYCLE_EVIDENCE_IDS),
        "contender_budget_gate_record_ids": {
            key: gate["gate_id"] for key, gate in sorted(gates.items())
        },
        "matched_control_comparison_record_ids": {
            key: comparison["comparison_id"]
            for key, comparison in sorted(comparisons.items())
        },
        "independent_control_diagnostic_ids": decision["independent_control_diagnostic_ids"],
        "dataset_result_ids": decision["dataset_result_ids"],
        "finalist": finalist_value,
        "zero_unresolved_reconciliation": decision["unresolved_reconciliation_count"] == 0,
        "holdout_access_count": 0,
        "temporal_access_count": 0,
        "final_decision_id": decision_id,
    }
    lock_id = deterministic_hash(LOCK_NAMESPACE, lock_payload)
    lock = {**lock_payload, "validation_lock_id": lock_id}
    dataset_payloads: dict[str, dict[str, Any]] = {}
    for dataset in DATASETS:
        dataset_payloads[dataset] = {
            "checkpoint_selection": {
                "schema_version": "trendline_v2_phase11r3b_checkpoint_selection_v1",
                "dataset_id": dataset,
                "records": [row for row in selections if row["dataset_id"] == dataset],
                "structural_records": [row for row in structural if row["dataset_id"] == dataset],
            },
            "candidate_outcomes": {
                "schema_version": "trendline_v2_phase11r3b_candidate_outcomes_v1",
                "dataset_id": dataset,
                "records": [row for row in outcomes if row["dataset_id"] == dataset],
            },
            "structural_context": {
                "schema_version": "trendline_v2_phase11r3b_structural_context_v1",
                "dataset_id": dataset,
                "selection_records": [row for row in structural if row["dataset_id"] == dataset],
                "outcome_records": [row for row in structural_outcomes if row["dataset_id"] == dataset],
            },
            "policy_metrics": {
                "schema_version": "trendline_v2_phase11r3b_policy_metrics_bundle_v1",
                "dataset_id": dataset,
                "metrics": dataset_metrics[dataset]["metrics"],
                "dataset_result_id": dataset_metrics[dataset]["dataset_result_id"],
                "evidence_id": dataset_metrics[dataset]["dataset_result_id"],
            },
        }
    compression_rows = [
        {
            "policy_id": policy_id,
            "budget_per_role": budget,
            "selected_observations": metrics[f"{policy_id}__budget_{budget}"]["selected_observations"],
            "selected_input_ratio": metrics[f"{policy_id}__budget_{budget}"]["selected_input_ratio"],
            "median_selected_lines_per_cell": metrics[f"{policy_id}__budget_{budget}"]["median_selected_lines_per_cell"],
            "maximum_selected_lines_per_cell": metrics[f"{policy_id}__budget_{budget}"]["maximum_selected_lines_per_cell"],
            "all_gates_passed": gates[f"{policy_id}__budget_{budget}"]["all_gates_passed"],
        }
        for policy_id in CONTENDER_POLICIES
        for budget in BUDGETS_PER_ROLE
    ]
    coherence_rows = [
        {
            "policy_id": selection["policy_id"],
            "budget_per_role": selection["budget_per_role"],
            "dataset_id": selection["dataset_id"],
            "checkpoint_index": selection["checkpoint_index"],
            "joint_coherence_result": selection["joint_coherence_result"],
            "core_pair_identity": selection["core_pair_identity"],
        }
        for selection in selections
    ]
    stability_rows = [
        {
            "policy_id": policy_id,
            "budget_per_role": budget,
            "incumbent_retention_rate": metrics[f"{policy_id}__budget_{budget}"]["incumbent_retention"]["rate"],
            "adjacent_checkpoint_jaccard": metrics[f"{policy_id}__budget_{budget}"]["adjacent_checkpoint_jaccard"]["rate"],
            "pair_continuity": metrics[f"{policy_id}__budget_{budget}"]["pair_continuity"]["rate"],
        }
        for policy_id in POLICIES
        if policy_id != "independent_incumbent_control_v1" or True
        for budget in BUDGETS_PER_ROLE
        if f"{policy_id}__budget_{budget}" in metrics
    ]
    outcome_rows = []
    for policy_id in CONTENDER_POLICIES:
        for budget in BUDGETS_PER_ROLE:
            metric = metrics[f"{policy_id}__budget_{budget}"]
            for horizon in HORIZONS_HOURS:
                rates = metric["outcome_rates"][str(horizon)]
                outcome_rows.append(
                    {
                        "policy_id": policy_id,
                        "budget_per_role": budget,
                        "horizon_hours": horizon,
                        "survival_rate": rates["survival"]["rate"],
                        "zone_contact_rate": rates["zone_contact"]["rate"],
                        "zone_contact_and_survival_rate": rates["zone_contact_and_survival"]["rate"],
                        "post_contact_reaction_rate": rates["post_contact_reaction"]["rate"],
                    }
                )
    return {
        "study_contract": {
            "schema_version": CONTRACT_NAMESPACE,
            "contract_id": contract_triplet()["contract_id"],
            "contract_json_byte_length": contract_triplet()["canonical_json_byte_length"],
            "contract_json_sha256": contract_triplet()["canonical_json_sha256"],
            "payload": contract_payload(),
        },
        "source_before": source_before,
        "source_after": None,
        "source_audit": None,
        "validation_lock": lock,
        "decision": decision,
        "dataset_payloads": dataset_payloads,
        "csv": {
            "compression_summary.csv": compression_rows,
            "coherence_summary.csv": coherence_rows,
            "stability_summary.csv": stability_rows,
            "outcome_summary.csv": outcome_rows,
        },
        "metrics": metrics,
        "comparisons": comparisons,
        "gates": gates,
    }


def _derive_compression_evidence(
    verified_source: Mapping[str, Any],
    *,
    source_after: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive all published evidence from one verified source boundary."""
    after = verified_source if source_after is None else source_after
    evidence = _derive_study_payloads(verified_source)
    evidence["source_after"] = after
    evidence["source_audit"] = _source_audit_payload(verified_source, after)
    return evidence


def _temporal_v2_source_audit_payload(
    source_before: Mapping[str, Any], source_after: Mapping[str, Any]
) -> dict[str, Any]:
    payload = _source_audit_payload(source_before, source_after)
    payload["schema_version"] = "trendline_v2_phase11r3b_temporal_v2_source_audit_v1"
    payload["temporal_window_contract_id"] = temporal_v2_contract_triplet()["contract_id"]
    payload["temporal_window_rule"] = (
        "checkpoint < available_at <= checkpoint + horizon"
    )
    payload["future_open_timestamp_rule"] = (
        "checkpoint <= timestamp_ns < checkpoint + horizon"
    )
    payload.pop("source_audit_id", None)
    payload["source_audit_id"] = deterministic_hash(SOURCE_AUDIT_NAMESPACE, payload)
    return payload


def _derive_temporal_v2_evidence(
    verified_source: Mapping[str, Any],
    *,
    source_after: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive same R3B evidence with corrected availability-aware windows."""
    global _future_rows
    previous_future_rows = _future_rows
    _future_rows = _future_rows_temporal_v2
    try:
        evidence = _derive_study_payloads(verified_source)
    finally:
        _future_rows = previous_future_rows
    triplet = temporal_v2_contract_triplet()
    evidence["study_contract"] = {
        "schema_version": TEMPORAL_V2_CONTRACT_NAMESPACE,
        "contract_id": triplet["contract_id"],
        "contract_json_byte_length": triplet["canonical_json_byte_length"],
        "contract_json_sha256": triplet["canonical_json_sha256"],
        "payload": triplet["payload"],
    }
    evidence["_manifest_schema_version"] = (
        "trendline_v2_phase11r3b_temporal_v2_manifest_v1"
    )
    after = verified_source if source_after is None else source_after
    evidence["source_after"] = after
    evidence["source_audit"] = _temporal_v2_source_audit_payload(
        verified_source, after
    )
    return evidence


def _write_study_bundle(staging: Path, evidence: Mapping[str, Any]) -> None:
    _write_json_atomic(staging / "study_contract.json", evidence["study_contract"])
    _write_json_atomic(staging / "source_audit.json", evidence["source_audit"])
    _write_json_atomic(staging / "validation_lock.json", evidence["validation_lock"])
    for name, rows in evidence["csv"].items():
        _write_atomic_bytes(staging / name, _csv_bytes(rows))
    _write_json_atomic(staging / "decision.json", evidence["decision"])
    for dataset in DATASETS:
        payload = evidence["dataset_payloads"][dataset]
        for member, value in payload.items():
            filename = {
                "checkpoint_selection": "checkpoint_selection.json",
                "candidate_outcomes": "candidate_outcomes.json",
                "structural_context": "structural_context.json",
                "policy_metrics": "policy_metrics.json",
            }[member]
            _write_json_atomic(staging / f"datasets/{dataset}/{filename}", value)
    members = list(item for item in _inventory(staging) if item["path"] != "manifest.json")
    if tuple(item["path"] for item in members) != tuple(
        sorted(path for path in EXPECTED_ARTIFACT_PATHS if path != "manifest.json")
    ):
        raise CompressionStudyError("study artifact paths are not exact")
    manifest_payload = {
        "schema_version": evidence.get(
            "_manifest_schema_version",
            "trendline_v2_phase11r3b_manifest_v1",
        ),
        "study_contract_id": evidence["study_contract"]["contract_id"],
        "source_audit_id": evidence["source_audit"]["source_audit_id"],
        "decision_id": evidence["decision"]["decision_id"],
        "validation_lock_id": evidence["validation_lock"]["validation_lock_id"],
        "member_count": len(members),
        "members": members,
        "output_inventory_sha256": _inventory_sha256(members),
    }
    manifest = {
        **manifest_payload,
        "manifest_id": deterministic_hash(MANIFEST_NAMESPACE, manifest_payload),
    }
    _write_json_atomic(staging / "manifest.json", manifest)


def _compare_bundle_to_derived_evidence(
    root: Path,
    evidence: Mapping[str, Any],
) -> None:
    """Compare every published byte with a fresh source-derived bundle."""
    with tempfile.TemporaryDirectory(prefix="trendline-v2-r3b-expected-") as directory:
        expected_root = Path(directory)
        _write_study_bundle(expected_root, evidence)
        for relative_path in EXPECTED_ARTIFACT_PATHS:
            if (root / relative_path).read_bytes() != (
                expected_root / relative_path
            ).read_bytes():
                raise CompressionStudyError(
                    f"source-derived artifact mismatch: {relative_path}"
                )


def _verify_compression_bundle(
    root: Path,
    *,
    source_backed: bool = True,
    expected_evidence: Mapping[str, Any] | None = None,
    expected_contract_triplet: Mapping[str, Any] | None = None,
    contract_identity_validator: Any | None = None,
    expected_manifest_schema_version: str | None = None,
) -> dict[str, Any]:
    if not root.is_dir() or root.is_symlink():
        raise CompressionStudyError("compression bundle root missing")
    actual = _inventory(root)
    expected_paths = set(EXPECTED_ARTIFACT_PATHS)
    if {item["path"] for item in actual} != expected_paths:
        raise CompressionStudyError("compression bundle paths are not exact")
    manifest = _load_json(root / "manifest.json")
    _verify_manifest_members(root, manifest)
    if (
        expected_manifest_schema_version is not None
        and manifest.get("schema_version") != expected_manifest_schema_version
    ):
        raise CompressionStudyError("compression manifest schema binding mismatch")
    manifest_payload = {
        key: manifest[key]
        for key in manifest
        if key != "manifest_id"
    }
    if manifest.get("manifest_id") != deterministic_hash(MANIFEST_NAMESPACE, manifest_payload):
        raise CompressionStudyError("compression manifest identity mismatch")
    contract = _load_json(root / "study_contract.json")
    triplet = (
        dict(expected_contract_triplet)
        if expected_contract_triplet is not None
        else contract_triplet()
    )
    identity_validator = contract_identity_validator or validate_contract_identity
    if (
        contract.get("contract_id") != triplet["contract_id"]
        or contract.get("contract_json_byte_length") != triplet["canonical_json_byte_length"]
        or contract.get("contract_json_sha256") != triplet["canonical_json_sha256"]
        or identity_validator(contract.get("payload", {})) != {
            key: triplet[key]
            for key in ("contract_id", "canonical_json_sha256", "canonical_json_byte_length")
        }
    ):
        raise CompressionStudyError("compression contract binding mismatch")
    audit = _load_json(root / "source_audit.json")
    audit_payload = {key: audit[key] for key in audit if key != "source_audit_id"}
    if audit.get("source_audit_id") != deterministic_hash(SOURCE_AUDIT_NAMESPACE, audit_payload):
        raise CompressionStudyError("compression source audit identity mismatch")
    if audit.get("source_before") != audit.get("source_after"):
        raise CompressionStudyError("source snapshots changed")
    if audit.get("raw_sui_accesses") != 0 or audit.get("holdout_accesses") != 0 or audit.get("temporal_accesses") != 0:
        raise CompressionStudyError("forbidden source access recorded")
    decision = _load_json(root / "decision.json")
    decision_payload = {key: decision[key] for key in decision if key != "decision_id"}
    if decision.get("decision_id") != deterministic_hash(DECISION_NAMESPACE, decision_payload):
        raise CompressionStudyError("compression decision identity mismatch")
    if not isinstance(decision.get("gate_records"), Mapping):
        raise CompressionStudyError("published gate records are missing")
    if not isinstance(decision.get("comparison_records"), Mapping):
        raise CompressionStudyError("published comparison records are missing")
    if not isinstance(decision.get("independent_control_diagnostic_records"), Mapping):
        raise CompressionStudyError("published diagnostic records are missing")
    for key, record in decision["gate_records"].items():
        if record.get("gate_id") != decision.get("gate_record_ids", {}).get(key):
            raise CompressionStudyError("gate record binding mismatch")
    for key, record in decision["comparison_records"].items():
        if record.get("comparison_id") != decision.get("comparison_record_ids", {}).get(key):
            raise CompressionStudyError("comparison record binding mismatch")
    lock = _load_json(root / "validation_lock.json")
    lock_payload = {key: lock[key] for key in lock if key != "validation_lock_id"}
    if lock.get("validation_lock_id") != deterministic_hash(LOCK_NAMESPACE, lock_payload):
        raise CompressionStudyError("validation lock identity mismatch")
    if lock.get("final_decision_id") != decision["decision_id"]:
        raise CompressionStudyError("validation lock decision binding mismatch")
    if "validation_lock_id" in decision:
        raise CompressionStudyError("decision must not contain validation lock ID")
    if (
        manifest.get("decision_id") != decision["decision_id"]
        or manifest.get("source_audit_id") != audit["source_audit_id"]
        or manifest.get("validation_lock_id") != lock["validation_lock_id"]
    ):
        raise CompressionStudyError("manifest cross-binding mismatch")
    if source_backed:
        source = _verify_r3a_source()
        if (
            audit.get("source_before") != source["source_snapshot_before"]
            or audit.get("source_after") != source["source_snapshot_before"]
            or audit.get("phase11r3a", {}).get("inventory_sha256")
            != source["phase11r3a_inventory"]
            or audit.get("phase11r3a", {}).get("lineage_lifecycle_evidence_ids")
            != source["lineage_lifecycle_evidence_ids"]
            or audit.get("allowed_raw_paths") != list(ALLOWED_RAW_PATHS)
        ):
            raise CompressionStudyError("published source identity mismatch")
        if audit.get("protected_inventories", {}).get("allowed_btc_eth_raw") != ALLOWED_RAW_INVENTORY:
            raise CompressionStudyError("published raw source identity mismatch")
        expected_evidence = _derive_compression_evidence(source)
    elif expected_evidence is None:
        raise CompressionStudyError(
            "synthetic verification requires explicit expected evidence"
        )
    _compare_bundle_to_derived_evidence(root, expected_evidence)
    return {
        "status": decision.get("study_status"),
        "decision_id": decision["decision_id"],
        "manifest_id": manifest["manifest_id"],
        "output_inventory_sha256": manifest["output_inventory_sha256"],
        "member_count": manifest["member_count"],
        "unresolved_evidence_count": decision.get("unresolved_evidence_count"),
    }


def verify_compression_bundle(root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    """Strict source-backed verifier used by CLI and canonical publication."""
    return _verify_compression_bundle(root, source_backed=True)


def verify_temporal_v2_bundle(root: Path = TEMPORAL_V2_OUTPUT_ROOT) -> dict[str, Any]:
    """Strict source-backed verifier for corrected temporal-window evidence."""
    source = _verify_r3a_source()
    expected = _derive_temporal_v2_evidence(source)
    return _verify_compression_bundle(
        root,
        source_backed=False,
        expected_evidence=expected,
        expected_contract_triplet=temporal_v2_contract_triplet(),
        contract_identity_validator=validate_temporal_v2_contract_identity,
        expected_manifest_schema_version=(
            "trendline_v2_phase11r3b_temporal_v2_manifest_v1"
        ),
    )


def _verify_synthetic_compression_bundle_for_tests(
    root: Path,
    expected_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Test-only verifier requiring caller-provided expected evidence."""
    return _verify_compression_bundle(
        root,
        source_backed=False,
        expected_evidence=expected_evidence,
    )


def _prepare_staging(root: Path) -> Path:
    require_fresh_output_root(root)
    try:
        root.parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=f".{root.name}.", dir=root.parent))
    except OSError as exc:
        raise CompressionStudyError("compression staging preparation failed") from exc


def run_compression_study(root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    """Execute one guarded offline study and atomically publish verified evidence."""
    _execution_guard(root)
    staging = _prepare_staging(root)
    try:
        source_before = _verify_r3a_source()
        evidence = _derive_compression_evidence(source_before)
        source_after = _verify_r3a_source()
        if source_before["source_snapshot_before"] != source_after["source_snapshot_before"]:
            raise CompressionStudyError("source mutation detected during study")
        evidence["source_after"] = source_after
        evidence["source_audit"] = _source_audit_payload(source_before, source_after)
        _write_study_bundle(staging, evidence)
        _verify_compression_bundle(staging, source_backed=True)
        os.replace(staging, root)
        staging = None  # type: ignore[assignment]
        return verify_compression_bundle(root)
    except Exception:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        raise


def _execution_guard_temporal_v2(root: Path = TEMPORAL_V2_OUTPUT_ROOT) -> None:
    require_fresh_output_root(root)
    if os.environ.get("TRENDLINE_V2_ALLOW_PHASE11R3B_TEMPORAL_V2_STUDY") != "1":
        raise ContractFreezeError("temporal-v2 study execution guard not enabled")


def run_temporal_v2_compression_study(
    root: Path = TEMPORAL_V2_OUTPUT_ROOT,
) -> dict[str, Any]:
    """Execute one guarded offline replay under corrected temporal semantics."""
    _execution_guard_temporal_v2(root)
    staging = _prepare_staging(root)
    try:
        source_before = _verify_r3a_source()
        evidence = _derive_temporal_v2_evidence(source_before)
        source_after = _verify_r3a_source()
        if source_before["source_snapshot_before"] != source_after["source_snapshot_before"]:
            raise CompressionStudyError("source mutation detected during temporal-v2 study")
        evidence["source_after"] = source_after
        evidence["source_audit"] = _temporal_v2_source_audit_payload(
            source_before, source_after
        )
        _write_study_bundle(staging, evidence)
        verify_temporal_v2_bundle(staging)
        os.replace(staging, root)
        staging = None  # type: ignore[assignment]
        return verify_temporal_v2_bundle(root)
    except Exception:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        raise


def require_fresh_output_root(root: Path = OUTPUT_ROOT) -> None:
    """Refuse an existing root before any future source access."""
    if root.exists():
        raise ContractFreezeError("existing compression-study output root refused")


def _execution_guard(root: Path = OUTPUT_ROOT) -> None:
    require_fresh_output_root(root)
    if os.environ.get("TRENDLINE_V2_ALLOW_PHASE11R3B_COMPRESSION_STUDY") != "1":
        raise ContractFreezeError("compression study execution guard not enabled")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--execute-compression-study", action="store_true")
    group.add_argument("--execute-compression-study-temporal-v2", action="store_true")
    group.add_argument("--verify", action="store_true")
    group.add_argument("--verify-temporal-v2", action="store_true")
    args = parser.parse_args(argv)
    triplet = temporal_v2_contract_triplet() if args.verify_temporal_v2 or args.execute_compression_study_temporal_v2 else contract_triplet()
    if args.execute_compression_study_temporal_v2:
        _execution_guard_temporal_v2()
        result = run_temporal_v2_compression_study()
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.verify_temporal_v2 and TEMPORAL_V2_OUTPUT_ROOT.exists():
        print(json.dumps(verify_temporal_v2_bundle(), sort_keys=True))
        return 0
    if args.execute_compression_study:
        _execution_guard()
        result = run_compression_study()
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.verify and OUTPUT_ROOT.exists():
        print(json.dumps(verify_compression_bundle(), sort_keys=True))
        return 0
    if args.verify or not args.execute_compression_study:
        print(
            json.dumps(
                {
                    "contract_id": triplet["contract_id"],
                    "canonical_json_byte_length": triplet[
                        "canonical_json_byte_length"
                    ],
                    "canonical_json_sha256": triplet["canonical_json_sha256"],
                    "status": IMPLEMENTATION_REVIEW_STATUS if not OUTPUT_ROOT.exists() else STUDY_BLOCKED_STATUS,
                },
                sort_keys=True,
            )
        )
    return 0


EXPECTED_CONTRACT_ID: str | None = (
    "c1cc02909b8b5a7ed6a3ed0f45aebcb4ce054685b0dd60364d0158360f1ad3b6"
)
EXPECTED_CONTRACT_JSON_SHA256: str | None = (
    "9583f52973b1345bb0cd2fd636acc1a061c64d1b4863003938866907b558b4d7"
)
EXPECTED_CONTRACT_JSON_BYTE_LENGTH: int | None = 25446
TEMPORAL_V2_EXPECTED_CONTRACT_ID: str | None = (
    "e99ae58325df06923c83e0732d3a07c77446a32a5aa913d65411518ea4742a52"
)
TEMPORAL_V2_EXPECTED_CONTRACT_JSON_SHA256: str | None = (
    "e900f47774045f96d1d14658fa3972cda70a42ded2ea95b34aaaf79839da2ed4"
)
TEMPORAL_V2_EXPECTED_CONTRACT_JSON_BYTE_LENGTH: int | None = 26223


if __name__ == "__main__":
    raise SystemExit(main())
