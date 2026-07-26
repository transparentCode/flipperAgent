"""Phase 11R.3A causal seed-lifecycle replay and feasibility evidence.

Runtime study execution stays behind an explicit environment guard and is
offline-only. Holdout, temporal, network and provider paths remain forbidden.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import math
import os
import shutil
import tempfile
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash
from scripts import analyze_trendline_v2_independent_sparse_geometry as phase11r1
from scripts import analyze_trendline_v2_sparse_geometry_failure_attribution as phase11r2


UTC = timezone.utc
NANOSECONDS = 1_000_000_000


CONTRACT_NAMESPACE = (
    "trendline_v2_phase11r3a_causal_seed_lifecycle_feasibility_contract"
)
BASE_COMMIT = "00bb28c2afd1a3195957c9d1fcb5e8d9b3e8da14"
PHASE11R1_COMMIT = "f99997c10b83082b3d3ce8de6b82f8add0996a71"
PHASE11R1_SCRIPT_BLOB = "102159f511f0a2d0598a521cf7ee42aa1cfaf64b"
PHASE11R1_SCRIPT_SHA256 = (
    "47d4b43ce556789b7992da3777356a05682ac5165b759c4b74682f89c808ee48"
)
PHASE11R2_COMMIT = BASE_COMMIT
PHASE11R2_SCRIPT_BLOB = "6d6a4bff2c439c68b1dfa51cbce34448e6e3a0d9"
PHASE11R2_SCRIPT_SHA256 = (
    "04c492dd9626fd9c4c4ac8583b69dcb5de2f66904994e451c752d335a250b626"
)

PHASE11R1_CONTRACT_ID = (
    "3bcad03fdd5df8b3af6754bdb38b0436cc93528964298607dd1169950cc312d3"
)
PHASE11R1_DECISION_ID = (
    "a06d0ca3a7a08b89db7a065133d5c30eeaa51800172187f4b75e7146e21e29fa"
)
PHASE11R1_MANIFEST_ID = (
    "6393883d533a6b56eb2abfb7b1402bee6eb75cfb366f59e942b7e44bb128ab32"
)
PHASE11R1_INVENTORY = (
    "17cf5aa6f70b58a21fe436ca63a98f88ab6356250de13befa94100ac96c4ae50"
)
PHASE11R1_LOCK_ID = (
    "ef381809b4d0155c625be28e752786099272910d7633a9c0d29101b8a2f81815"
)

PHASE11R2_CONTRACT_ID = (
    "d3a52e28ce11ffb86bb05aff826ce48ad11b9035c6796e9e938a616463686089"
)
PHASE11R2_DECISION_ID = (
    "14efee537f6882570aa6db470a4a4cab321f9346b512c512cab8150b9220ca85"
)
PHASE11R2_MANIFEST_ID = (
    "ce3bc58dedc8536035f4e1736047fd1e427c3993e9a77d9d3226864293d8de9a"
)
PHASE11R2_INVENTORY = (
    "382df2e22cb508d3982eb7e6d9566849dc65eb7316a8ce8c64b9c44d2d6713e4"
)
PHASE11R2_SOURCE_AUDIT_ID = (
    "ff95e7d3c2ec59270b60cc0943dfa73582d299c40824a918b62819cb75ebf852"
)

PHASE9C2_ROOT = Path(
    "/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/20260522_20260701"
)
PHASE11R1_ROOT = Path(
    "/tmp/trendline_v2_phase11r1_independent_sparse_geometry/"
    "20260522_20260701__20250801_20260401"
)
PHASE11R2_ROOT = Path(
    "/tmp/trendline_v2_phase11r2_failure_attribution/20260522_20260701"
)
PHASE10C2_ROOT = Path("/tmp/trendline_v2_phase10c2_lookback_eviction")
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase11r3a_causal_seed_lifecycle/20260522_20260701"
)

PHASE9C2_DECISION_ID = (
    "4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c"
)
PHASE9C2_MANIFEST_ID = (
    "beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81"
)
PHASE9C2_OUTPUT_INVENTORY = (
    "ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532"
)
PHASE9C2_SOURCE_INVENTORY = (
    "631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be"
)
PHASE9C2_RAW_INVENTORY = (
    "2f2db301ca6c9c355bb4d645bb2d631836749748835c0419573e7cf52d27de27"
)

DATASETS = ("btcusdt_1h", "btcusdt_4h", "ethusdt_1h", "ethusdt_4h")
ROLES = ("support", "resistance")
CHECKPOINTS_PER_DATASET = 22
CHECKPOINT_COUNT = len(DATASETS) * CHECKPOINTS_PER_DATASET
PROVIDER_ROLE_GAP_COUNT = 52
UNIQUE_GAP_COUNT = 26
HORIZONS_HOURS = (24, 48, 96)
INTERVAL_SECONDS = {"1h": 3_600, "4h": 14_400}

LINEAGE_NAMESPACE = "trendline_v2_phase11r3a_pair_lineage"
LINEAGE_ID_FIELDS = (
    "asset",
    "timeframe",
    "original_anchor_role",
    "first_anchor_pivot_id",
    "second_anchor_pivot_id",
)
LINEAGE_ID_EXCLUDED_FIELDS = (
    "checkpoint",
    "current_lifecycle_state",
    "current_semantic_role",
    "current_distance_atr",
)

STATES = (
    "NOT_YET_STRICT_ACTIVE",
    "STRICT_ACTIVE_NEAR",
    "PERSISTED_ACTIVE_NEAR",
    "PERSISTED_DISTANT",
    "REVERSAL_PENDING",
    "REVERSED_ACTIVE_NEAR",
    "REVERSED_PERSISTED_DISTANT",
    "RETIRED",
)
NONTERMINAL_STATES = tuple(state for state in STATES if state != "RETIRED")
RETIREMENT_REASONS = (
    "original_projection_invalid",
    "reversed_projection_invalid",
    "reversed_role_sustained_breach",
)
TRANSITION_TRIGGERS = (
    "strict_seed_confirmed",
    "distance_exceeded_8_atr",
    "distance_returned_at_most_8_atr",
    "same_role_sustained_breach_confirmed",
    "reversal_contact_confirmed_after_breach",
    "reversed_distance_exceeded_8_atr",
    "reversed_distance_returned_at_most_8_atr",
    "reversed_role_sustained_breach_confirmed",
    "original_projection_invalid",
    "reversed_projection_invalid",
)
LEGAL_TRANSITIONS = {
    "NOT_YET_STRICT_ACTIVE": ("STRICT_ACTIVE_NEAR",),
    "STRICT_ACTIVE_NEAR": (
        "PERSISTED_ACTIVE_NEAR",
        "PERSISTED_DISTANT",
        "REVERSAL_PENDING",
        "RETIRED",
    ),
    "PERSISTED_ACTIVE_NEAR": (
        "STRICT_ACTIVE_NEAR",
        "PERSISTED_DISTANT",
        "REVERSAL_PENDING",
        "RETIRED",
    ),
    "PERSISTED_DISTANT": (
        "STRICT_ACTIVE_NEAR",
        "PERSISTED_ACTIVE_NEAR",
        "REVERSAL_PENDING",
        "RETIRED",
    ),
    "REVERSAL_PENDING": (
        "REVERSED_ACTIVE_NEAR",
        "REVERSED_PERSISTED_DISTANT",
        "RETIRED",
    ),
    "REVERSED_ACTIVE_NEAR": (
        "REVERSED_PERSISTED_DISTANT",
        "RETIRED",
    ),
    "REVERSED_PERSISTED_DISTANT": (
        "REVERSED_ACTIVE_NEAR",
        "RETIRED",
    ),
    "RETIRED": (),
}

# Trigger semantics are part of the persisted lifecycle contract.  Keeping the
# matrix explicit prevents a rebound artifact from pairing a legal state edge
# with an unrelated event label.
TRANSITION_TRIGGER_MATRIX = {
    ("NOT_YET_STRICT_ACTIVE", "STRICT_ACTIVE_NEAR"): frozenset(
        {"strict_seed_confirmed"}
    ),
    ("STRICT_ACTIVE_NEAR", "PERSISTED_ACTIVE_NEAR"): frozenset(
        {"distance_returned_at_most_8_atr"}
    ),
    ("PERSISTED_ACTIVE_NEAR", "STRICT_ACTIVE_NEAR"): frozenset(
        {"strict_seed_confirmed"}
    ),
    ("PERSISTED_DISTANT", "STRICT_ACTIVE_NEAR"): frozenset(
        {"strict_seed_confirmed"}
    ),
    ("PERSISTED_ACTIVE_NEAR", "PERSISTED_ACTIVE_NEAR"): frozenset(),
    ("PERSISTED_DISTANT", "PERSISTED_ACTIVE_NEAR"): frozenset(
        {"distance_returned_at_most_8_atr"}
    ),
    ("STRICT_ACTIVE_NEAR", "PERSISTED_DISTANT"): frozenset(
        {"distance_exceeded_8_atr"}
    ),
    ("PERSISTED_ACTIVE_NEAR", "PERSISTED_DISTANT"): frozenset(
        {"distance_exceeded_8_atr"}
    ),
    ("PERSISTED_DISTANT", "PERSISTED_DISTANT"): frozenset(),
    ("STRICT_ACTIVE_NEAR", "REVERSAL_PENDING"): frozenset(
        {"same_role_sustained_breach_confirmed"}
    ),
    ("PERSISTED_ACTIVE_NEAR", "REVERSAL_PENDING"): frozenset(
        {"same_role_sustained_breach_confirmed"}
    ),
    ("PERSISTED_DISTANT", "REVERSAL_PENDING"): frozenset(
        {"same_role_sustained_breach_confirmed"}
    ),
    ("REVERSAL_PENDING", "REVERSED_ACTIVE_NEAR"): frozenset(
        {"reversal_contact_confirmed_after_breach"}
    ),
    ("REVERSAL_PENDING", "REVERSED_PERSISTED_DISTANT"): frozenset(
        {"reversal_contact_confirmed_after_breach"}
    ),
    ("REVERSED_ACTIVE_NEAR", "REVERSED_PERSISTED_DISTANT"): frozenset(
        {"reversed_distance_exceeded_8_atr"}
    ),
    ("REVERSED_PERSISTED_DISTANT", "REVERSED_ACTIVE_NEAR"): frozenset(
        {"reversed_distance_returned_at_most_8_atr"}
    ),
    ("REVERSED_ACTIVE_NEAR", "RETIRED"): frozenset(
        {"reversed_projection_invalid", "reversed_role_sustained_breach_confirmed"}
    ),
    ("REVERSED_PERSISTED_DISTANT", "RETIRED"): frozenset(
        {"reversed_projection_invalid", "reversed_role_sustained_breach_confirmed"}
    ),
    ("STRICT_ACTIVE_NEAR", "RETIRED"): frozenset({"original_projection_invalid"}),
    ("PERSISTED_ACTIVE_NEAR", "RETIRED"): frozenset(
        {"original_projection_invalid"}
    ),
    ("PERSISTED_DISTANT", "RETIRED"): frozenset({"original_projection_invalid"}),
}
STATE_RETENTION_ALLOWED = {
    state: state != "RETIRED"
    for state in STATES
}

POLICIES = (
    "strict_seed_baseline_v1",
    "persist_unbreached_lineage_v1",
    "confirmed_single_role_reversal_v1",
)
UNION_POLICY = "persistent_role_aware_lineage_union_v1"
RECOVERY_STATUSES = (
    "ACTIONABLE",
    "STRUCTURAL_ONLY",
    "NOT_RECOVERED",
)
RECOVERY_MECHANISMS = (
    "DISTANCE_PERSISTENCE",
    "ROLE_REVERSAL",
)
UNRECOVERED_REASONS = (
    "NO_PRIOR_STRICT_LINEAGE",
    "REVERSAL_PENDING_NO_CONTACT",
    "ALL_RELEVANT_LINEAGES_RETIRED",
)
UNIQUE_GAP_KEY_FIELDS = ("dataset_id", "checkpoint_index", "semantic_role")
CANDIDATE_KEY_FIELDS = (
    "dataset_id",
    "checkpoint_index",
    "semantic_role",
    "lineage_id",
)
DECISION_STATUSES = (
    "CAUSAL_SEED_LIFECYCLE_FEASIBILITY_COMPLETE",
    "CAUSAL_SEED_LIFECYCLE_FEASIBILITY_INCOMPLETE",
    "CAUSAL_SEED_LIFECYCLE_FEASIBILITY_BLOCKED",
)
FREEZE_STATUS = "READY_FOR_CONTRACT_FREEZE_REVIEW"

EXPECTED_ARTIFACT_PATHS = tuple(
    [
        "study_contract.json",
        "source_audit.json",
        "lifecycle_summary.csv",
        "gap_recovery_summary.csv",
        "outcome_summary.csv",
        "decision.json",
        "manifest.json",
    ]
    + [
        f"datasets/{dataset}/{member}"
        for dataset in DATASETS
        for member in (
            "lineage_lifecycle.json",
            "gap_recovery.json",
            "recovered_outcomes.json",
            "policy_metrics.json",
        )
    ]
)


class ContractFreezeError(RuntimeError):
    """Raised when frozen contract identity or study boundaries fail."""


def _dependency_payload() -> dict[str, Any]:
    return {
        "phase11r1": {
            "module": phase11r1.__name__,
            "commit": PHASE11R1_COMMIT,
            "script_path": "scripts/analyze_trendline_v2_independent_sparse_geometry.py",
            "script_git_blob": PHASE11R1_SCRIPT_BLOB,
            "script_sha256": PHASE11R1_SCRIPT_SHA256,
            "contract_id": PHASE11R1_CONTRACT_ID,
            "decision_id": PHASE11R1_DECISION_ID,
            "manifest_id": PHASE11R1_MANIFEST_ID,
            "inventory_sha256": PHASE11R1_INVENTORY,
            "validation_lock_id": PHASE11R1_LOCK_ID,
        },
        "phase11r2": {
            "module": phase11r2.__name__,
            "commit": PHASE11R2_COMMIT,
            "script_path": "scripts/analyze_trendline_v2_sparse_geometry_failure_attribution.py",
            "script_git_blob": PHASE11R2_SCRIPT_BLOB,
            "script_sha256": PHASE11R2_SCRIPT_SHA256,
            "contract_id": PHASE11R2_CONTRACT_ID,
            "decision_id": PHASE11R2_DECISION_ID,
            "manifest_id": PHASE11R2_MANIFEST_ID,
            "inventory_sha256": PHASE11R2_INVENTORY,
            "source_audit_id": PHASE11R2_SOURCE_AUDIT_ID,
        },
    }


def _contract_payload() -> dict[str, Any]:
    """Return complete Phase 11R.3A contract preimage without source access."""
    payload = {
        "schema_version": CONTRACT_NAMESPACE,
        "base_commit": BASE_COMMIT,
        "phase11r1_dependency": _dependency_payload()["phase11r1"],
        "phase11r2_dependency": _dependency_payload()["phase11r2"],
        "sources": {
            "phase11r1_root": str(PHASE11R1_ROOT),
            "phase11r2_root": str(PHASE11R2_ROOT),
            "phase9c2_root": str(PHASE9C2_ROOT),
            "phase10c2_root": str(PHASE10C2_ROOT),
            "phase9c2_decision_id": PHASE9C2_DECISION_ID,
            "phase9c2_manifest_id": PHASE9C2_MANIFEST_ID,
            "phase9c2_output_inventory_sha256": PHASE9C2_OUTPUT_INVENTORY,
            "phase9c2_source_inventory_sha256": PHASE9C2_SOURCE_INVENTORY,
            "phase9c2_allowed_raw_inventory_sha256": PHASE9C2_RAW_INVENTORY,
            "allowed_raw_paths": [
                f"datasets/{dataset}/provider_result.json" for dataset in DATASETS
            ],
            "forbidden_raw_paths": [
                "datasets/suiusdt_1h/provider_result.json",
                "datasets/suiusdt_4h/provider_result.json",
            ],
            "forbidden_roots": [str(PHASE10C2_ROOT)],
            "persisted_sui_placeholder_reads": "allowed_for_phase11r1_verification_only",
            "raw_sui_reads": "prohibited",
            "temporal_reads": "prohibited",
        },
        "independence": {
            "mode": "offline_candidate_lifecycle_research_only",
            "network_requests": 0,
            "runtime_v2_provider_executions": 0,
            "legacy_executions": 0,
            "provider_execution": "prohibited",
            "pivot_changes": False,
            "span_requirement_changes": False,
            "touch_requirement_changes": False,
            "distance_threshold_search": False,
            "selector": "prohibited",
            "holdout_access": False,
            "temporal_access": False,
            "runtime_configuration_changes": False,
            "source_mutation_policy": "fail_closed",
        },
        "targets": {
            "datasets": list(DATASETS),
            "roles": list(ROLES),
            "checkpoint_count_per_dataset": CHECKPOINTS_PER_DATASET,
            "checkpoint_count": CHECKPOINT_COUNT,
            "phase11r2_provider_role_missing_cases": PROVIDER_ROLE_GAP_COUNT,
            "phase11r2_unique_seed_gaps": UNIQUE_GAP_COUNT,
            "strict_seed_reconciliation": "phase11r1 final strict seed identities exactly",
            "candidate_level_and_unique_gap_level": True,
        },
        "lineage_identity": {
            "namespace": LINEAGE_NAMESPACE,
            "fields": list(LINEAGE_ID_FIELDS),
            "excluded_fields": list(LINEAGE_ID_EXCLUDED_FIELDS),
            "same_anchor_pair_stable_across_checkpoints": True,
            "original_role_preserved": True,
        },
        "state_machine": {
            "states": list(STATES),
            "typed_transition_triggers": list(TRANSITION_TRIGGERS),
            "legal_transitions": {
                state: list(destinations)
                for state, destinations in LEGAL_TRANSITIONS.items()
            },
            "strict_seed_entry": "only complete Phase11R1 strict seed may enter persistence or reversal",
            "strict_active_near": {
                "minimum_span_hours": 96,
                "minimum_touches": 3,
                "touch_tolerance_atr": 0.35,
                "sustained_breach_atr": 0.5,
                "sustained_breach_bars": 2,
                "maximum_distance_atr": 8.0,
                "positive_finite_projection": True,
            },
            "persisted_distant": {
                "prior_state": "STRICT_ACTIVE_NEAR",
                "same_role_breach": "absent",
                "distance": "> 8 ATR",
                "actionable": False,
                "fixed_age_expiry": False,
            },
            "reversal_pending": {
                "trigger": "same_role_sustained_breach_confirmed",
                "availability": "second_breach_bar_timestamp_plus_timeframe_interval",
                "breach_bar_is_contact": False,
            },
            "reversed_active_near": {
                "one_role_flip_maximum": True,
                "contact_strictly_after_breach": True,
                "contact_tolerance_atr": 0.35,
                "reversed_role_breach": "invalidates",
                "positive_finite_projection": True,
                "maximum_distance_atr": 8.0,
            },
            "reversed_persisted_distant": {"actionable": False},
            "reversed_retired": {"permanent": True},
            "invalid_pair_rules": {
                "persistence_requires_prior_strict_active": True,
                "reversal_requires_prior_strict_lineage": True,
                "unconfirmed_pair_recovery": "prohibited",
                "maximum_role_reversals": 1,
            },
        },
        "policies": {
            "fixed": list(POLICIES),
            "descriptive_union": UNION_POLICY,
            "strict_seed_baseline_v1": {
                "included_states": ["STRICT_ACTIVE_NEAR"],
                "must_reproduce_phase11r1": True,
            },
            "persist_unbreached_lineage_v1": {
                "included_states": ["STRICT_ACTIVE_NEAR", "PERSISTED_DISTANT"],
                "distant_actionable": False,
            },
            "confirmed_single_role_reversal_v1": {
                "included_states": [
                    "STRICT_ACTIVE_NEAR",
                    "PERSISTED_DISTANT",
                    "REVERSED_ACTIVE_NEAR",
                    "REVERSED_PERSISTED_DISTANT",
                ],
                "ranking": "prohibited",
            },
            "persistent_role_aware_lineage_union_v1": {
                "descriptive_only": True,
                "provider_ranking": False,
                "selected_line_output": False,
            },
        },
        "gap_recovery": {
            "labels": list(RECOVERY_STATUSES),
            "provider_role_case_inherits_unique_gap": True,
            "classification_priority": [
                "RECOVERED_BY_BOTH_POLICIES",
                "RECOVERED_ACTIONABLE_BY_ROLE_REVERSAL",
                "RECOVERED_STRUCTURAL_BY_DISTANCE_PERSISTENCE",
                "NOT_RECOVERED_NO_PRIOR_STRICT_LINEAGE",
                "NOT_RECOVERED_REVERSAL_PENDING_NO_CONTACT",
                "NOT_RECOVERED_REVERSED_LINEAGE_RETIRED",
            ],
            "counts_to_reconcile": {
                "provider_role_cases": PROVIDER_ROLE_GAP_COUNT,
                "unique_seed_gaps": UNIQUE_GAP_COUNT,
            },
            "no_double_counting_provider_evidence": True,
        },
        "future_evaluation": {
            "horizons_hours": list(HORIZONS_HOURS),
            "future_rule": "timestamp strictly after checkpoint",
            "exact_interval_sequence": True,
            "near_line_fields": [
                "survival",
                "zone_contact",
                "zone_contact_and_survival",
                "post_contact_reaction",
                "first_contact_offset_bars",
                "first_sustained_breach_offset_bars",
            ],
            "distant_line_fields": [
                "zone_contact_within_horizon",
                "minimum_future_distance_atr",
                "distance_contraction_atr",
                "crossed_into_at_most_8_atr",
            ],
            "same_contact_bar_reaction": False,
            "role_aware_support_and_resistance": True,
            "distant_actionable": False,
            "no_intrabar_order_assumption": True,
            "distance_metrics": {
                "minimum_future_distance_atr": "minimum(abs(close-line)/ATR)",
                "distance_contraction_atr": "initial_distance_atr-minimum_future_distance_atr",
                "crossed_into_at_most_8_atr": "any future distance <= 8 ATR",
            },
            "temporal_policy": "not_evaluated",
        },
        "reconciliation": {
            "all_checkpoints_reconstructed_twice": True,
            "checkpoint_reconstructions": CHECKPOINT_COUNT * 2,
            "strict_seed_identities": True,
            "provider_role_gaps": PROVIDER_ROLE_GAP_COUNT,
            "unique_seed_gaps": UNIQUE_GAP_COUNT,
            "legal_state_transitions": True,
            "deterministic_lineage_ids": True,
            "exact_future_windows": True,
            "zero_unresolved": True,
            "zero_forbidden_reads": True,
            "source_snapshots_unchanged": True,
            "semantic_rederivation": {
                "json_members": True,
                "csv_members": True,
                "forged_lifecycle_state_rejected": True,
                "forged_transition_trigger_rejected": True,
                "forged_role_rejected": True,
                "forged_recovery_label_rejected": True,
                "forged_future_outcome_rejected": True,
                "forged_decision_rejected": True,
                "forged_manifest_rejected": True,
            },
        },
        "artifacts": {
            "output_root": str(OUTPUT_ROOT),
            "total_file_count": len(EXPECTED_ARTIFACT_PATHS),
            "manifest_member_count": len(EXPECTED_ARTIFACT_PATHS) - 1,
            "paths": list(EXPECTED_ARTIFACT_PATHS),
            "contains_sui": False,
            "contains_temporal": False,
            "atomic_publication": True,
        },
        "execution_accounting": {
            "validation_datasets": len(DATASETS),
            "checkpoints": CHECKPOINT_COUNT,
            "checkpoint_reconstruction_repeats": 2,
            "checkpoint_reconstructions": CHECKPOINT_COUNT * 2,
            "phase11r1_evidence_verifications": 1,
            "phase11r2_evidence_verifications": 1,
            "raw_sui_accesses": 0,
            "temporal_accesses": 0,
            "network_requests": 0,
            "legacy_executions": 0,
            "runtime_v2_provider_executions": 0,
        },
        "decision_statuses": list(DECISION_STATUSES),
        "decision_evidence_flags": [
            "unique_gap_count",
            "actionable_recovery_count",
            "structural_only_recovery_count",
            "role_reversal_recovery_count",
            "distance_persistence_recovery_count",
            "unrecovered_gap_count",
            "candidate_inflation_ratio",
            "reversal_pending_without_contact_count",
            "reversed_retirement_count",
            "recovered_actionable_48h_survival_rate",
            "recovered_actionable_96h_survival_rate",
            "recovered_actionable_96h_contact_rate",
        ],
        "study_controls": {
            "cli_execute": "--execute-lifecycle-study",
            "cli_verify": "--verify",
            "execute_environment": "TRENDLINE_V2_ALLOW_PHASE11R3A_LIFECYCLE_STUDY=1",
            "contract_freeze_status": FREEZE_STATUS,
            "study_execution_during_freeze": False,
            "existing_output_root_refusal_before_source_access": True,
            "atomic_publication": "single_directory_replace",
            "parameter_changes_after_results": False,
            "threshold_search": False,
            "provider_promotion": False,
            "selector": False,
            "holdout_access": False,
            "temporal_access": False,
        },
    }

    payload["lineage_identity"].update(
        {
            "eligibility_rule": (
                "anchor pair becomes lifecycle-eligible only when it appears "
                "in the exact Phase11R1 strict seed pool at a scheduled checkpoint"
            ),
            "geometry_fields": [
                "first_anchor_timestamp",
                "first_anchor_price",
                "second_anchor_timestamp",
                "second_anchor_price",
                "exact_timestamp_space_line_geometry",
                "original_anchor_role",
            ],
            "geometry_immutable": True,
            "refitting": "prohibited",
            "reanchoring": "prohibited",
            "pivot_replacement": "prohibited",
            "slope_adjustment": "prohibited",
            "geometry_available_after_seed_eviction": True,
        }
    )
    payload["lifecycle_clock"] = {
        "strict_seed_entry": "scheduled_daily_checkpoints_only",
        "scheduled_checkpoint_count": CHECKPOINT_COUNT,
        "bar_level_replay": "every_owner_timeframe_bar_between_checkpoints",
        "available_at_formula": "candle_timestamp + timeframe_interval",
        "transition_effective_at": "available_at",
        "checkpoint_state": "after every bar with available_at <= checkpoint",
        "interval_processing": "previous_checkpoint < available_at <= current_checkpoint",
        "checkpoint_processing_order": [
            "replay_bar_events_previous_checkpoint_lt_available_at_le_current_checkpoint",
            "apply_scheduled_checkpoint_strict_seed_membership",
            "classify_near_distant_using_last_completed_bar",
        ],
        "bar_event_types": [
            "same_role_sustained_breach",
            "post_breach_reversal_contact",
            "reversed_role_sustained_breach",
            "projection_invalidation",
        ],
        "checkpoint_only_classifications": [
            "exact_current_r1_strict_seed_membership",
            "persisted_active_near_vs_persisted_distant",
            "reversed_active_near_vs_reversed_persisted_distant",
        ],
        "checkpoint_state_change_effective_at": "checkpoint_timestamp",
        "bar_event_state_change_effective_at": "triggering_bar_available_at",
        "checkpoint_distance_formula": (
            "abs(last_completed_close - line_at_checkpoint) / "
            "ATR_of_last_completed_bar"
        ),
        "chronological_bar_processing": True,
        "strict_seed_replay_clock": "checkpoint_only",
        "event_replay_clock": "owner_timeframe_bar",
        "incomplete_bar_use": False,
    }
    payload["state_machine"] = {
        "states": list(STATES),
        "nonterminal_states": list(NONTERMINAL_STATES),
        "terminal_state": "RETIRED",
        "state_retention_allowed": dict(STATE_RETENTION_ALLOWED),
        "retention_is_not_transition_event": True,
        "typed_transition_triggers": list(TRANSITION_TRIGGERS),
        "legal_transitions": {
            state: list(destinations)
            for state, destinations in LEGAL_TRANSITIONS.items()
        },
        "strict_seed_entry": {
            "source": "exact_current_phase11r1_strict_seed_pool",
            "schedule": "scheduled_daily_checkpoints_only",
            "requires_complete_seed": True,
        },
        "strict_active_near": {
            "source": "exact_current_phase11r1_strict_seed_pool",
            "historical_reentry_without_current_seed": False,
            "minimum_span_hours": 96,
            "minimum_touches": 3,
            "touch_tolerance_atr": 0.35,
            "sustained_breach_atr": 0.5,
            "sustained_breach_bars": 2,
            "maximum_distance_atr": 8.0,
            "positive_finite_projection": True,
        },
        "original_role_breach": {
            "support": "two_consecutive_closes_below_line_minus_0.5_ATR_at_bar",
            "resistance": "two_consecutive_closes_above_line_plus_0.5_ATR_at_bar",
            "line_value": "line_geometry_evaluated_at_each_bar_timestamp",
            "atr": "ATR_at_evaluated_owner_timeframe_bar",
            "counter_increments_on_breaching_close": True,
            "counter_resets_on_non_breaching_close": True,
            "counter_starts_after_strict_lineage_activation": True,
        },
        "persisted_active_near": {
            "historically_strict_active": True,
            "currently_absent_from_exact_phase11r1_seed": True,
            "same_role_sustained_breach": False,
            "projection": "positive_and_finite",
            "distance": "<= 8 ATR",
            "actionable": True,
        },
        "persisted_distant": {
            "historically_strict_active": True,
            "currently_absent_from_exact_phase11r1_seed": True,
            "same_role_sustained_breach": False,
            "projection": "positive_and_finite",
            "distance": "> 8 ATR",
            "actionable": False,
            "fixed_age_expiry": False,
        },
        "reversal_pending": {
            "trigger": "same_role_sustained_breach_confirmed",
            "availability": "second_breach_bar_available_at",
            "breach_bar_is_contact": False,
            "can_retain_across_checkpoints": True,
            "contact_required_for_activation": True,
        },
        "reversal_contact": {
            "formula": (
                "low <= line + 0.35 * ATR_at_contact_bar and "
                "high >= line - 0.35 * ATR_at_contact_bar"
            ),
            "availability": "contact_bar_available_at > second_breach_bar_available_at",
            "activation_bar_is_reaction": False,
            "activation_bar_is_first_reversed_role_breach": False,
        },
        "reversed_active_near": {
            "activation": "confirmed_post_breach_contact",
            "one_role_flip_maximum": True,
            "contact_strictly_after_breach": True,
            "contact_tolerance_atr": 0.35,
            "reversed_role_breach": "retires",
            "positive_finite_projection": True,
            "maximum_distance_atr": 8.0,
        },
        "reversed_persisted_distant": {
            "activation": "confirmed_post_breach_contact",
            "same_activation_conditions_as": "REVERSED_ACTIVE_NEAR",
            "distance": "> 8 ATR",
            "actionable": False,
        },
        "retired": {
            "permanent": True,
            "terminal_state_persists": True,
            "terminal_retention_is_not_transition_event": True,
            "retirement_reasons": list(RETIREMENT_REASONS),
        },
        "event_precedence": {
            "original_role": [
                "same_role_sustained_breach_to_reversal_pending",
                "nonpositive_or_nonfinite_projection_to_retired",
                "exact_current_strict_seed_to_strict_active_near",
                "unbreached_distance_at_most_8_atr_to_persisted_active_near",
                "unbreached_distance_above_8_atr_to_persisted_distant",
            ],
            "reversal_pending": [
                "valid_strictly_post_breach_contact_to_reversed_state",
                "otherwise_retain_reversal_pending",
            ],
            "reversed_lineage": [
                "reversed_role_sustained_breach_to_retired",
                "nonpositive_or_nonfinite_projection_to_retired",
                "distance_at_most_8_atr_to_reversed_active_near",
                "distance_above_8_atr_to_reversed_persisted_distant",
            ],
        },
        "invalid_pair_rules": {
            "persistence_requires_prior_strict_lineage": True,
            "reversal_requires_prior_strict_lineage": True,
            "unconfirmed_pair_recovery": "prohibited",
            "maximum_role_reversals": 1,
        },
        "reversed_role_breach": {
            "support_to_resistance": "two_consecutive_closes_above_line_plus_0.5_ATR",
            "resistance_to_support": "two_consecutive_closes_below_line_minus_0.5_ATR",
            "counter_starts_after_first_valid_reversal_contact": True,
            "activation_contact_cannot_be_first_breach_bar": True,
        },
        "semantic_role_by_state": {
            "NOT_YET_STRICT_ACTIVE": None,
            "STRICT_ACTIVE_NEAR": "original_anchor_role",
            "PERSISTED_ACTIVE_NEAR": "original_anchor_role",
            "PERSISTED_DISTANT": "original_anchor_role",
            "REVERSAL_PENDING": None,
            "REVERSED_ACTIVE_NEAR": "opposite_of_original_anchor_role",
            "REVERSED_PERSISTED_DISTANT": "opposite_of_original_anchor_role",
            "RETIRED": None,
        },
        "last_active_semantic_role_persisted_for": [
            "REVERSAL_PENDING",
            "RETIRED",
        ],
    }
    payload["policies"] = {
        "fixed": list(POLICIES),
        "descriptive_union": UNION_POLICY,
        "strict_seed_baseline_v1": {
            "included_states": ["STRICT_ACTIVE_NEAR"],
            "must_reproduce_phase11r1": True,
            "mechanism": "exact_strict_seed",
        },
        "persist_unbreached_lineage_v1": {
            "included_states": [
                "STRICT_ACTIVE_NEAR",
                "PERSISTED_ACTIVE_NEAR",
                "PERSISTED_DISTANT",
            ],
            "mechanism": "DISTANCE_PERSISTENCE",
            "distant_actionable": False,
        },
        "confirmed_single_role_reversal_v1": {
            "included_states": [
                "STRICT_ACTIVE_NEAR",
                "REVERSED_ACTIVE_NEAR",
                "REVERSED_PERSISTED_DISTANT",
            ],
            "mechanism": "ROLE_REVERSAL",
            "ranking": "prohibited",
        },
        "persistent_role_aware_lineage_union_v1": {
            "included_states": [
                "STRICT_ACTIVE_NEAR",
                "PERSISTED_ACTIVE_NEAR",
                "REVERSED_ACTIVE_NEAR",
                "PERSISTED_DISTANT",
                "REVERSED_PERSISTED_DISTANT",
            ],
            "unavailable_states": [
                "NOT_YET_STRICT_ACTIVE",
                "REVERSAL_PENDING",
                "RETIRED",
            ],
            "descriptive_only": True,
            "provider_ranking": False,
            "selected_line_output": False,
        },
    }
    payload["gap_recovery"] = {
        "recovery_statuses": list(RECOVERY_STATUSES),
        "recovery_mechanisms_ordered": list(RECOVERY_MECHANISMS),
        "unrecovered_reasons": list(UNRECOVERED_REASONS),
        "unique_gap_key": list(UNIQUE_GAP_KEY_FIELDS),
        "provider_role_key_maps_two_to_one": True,
        "provider_role_cases": PROVIDER_ROLE_GAP_COUNT,
        "unique_gap_keys": UNIQUE_GAP_COUNT,
        "provider_role_to_unique_gap_ratio": "2:1",
        "candidate_current_role_must_equal_gap_role": True,
        "aggregation": {
            "collect": "every_lifecycle_candidate_with_current_role_equal_gap_role",
            "actionable_precedes_structural_only": True,
            "mechanisms": "ordered_union_across_all_recovered_candidates",
            "unrecovered_reason_precedence": [
                "NO_PRIOR_STRICT_LINEAGE",
                "REVERSAL_PENDING_NO_CONTACT",
                "ALL_RELEVANT_LINEAGES_RETIRED",
            ],
        },
        "actionable_states": [
            "STRICT_ACTIVE_NEAR",
            "PERSISTED_ACTIVE_NEAR",
            "REVERSED_ACTIVE_NEAR",
        ],
        "structural_only_states": [
            "PERSISTED_DISTANT",
            "REVERSED_PERSISTED_DISTANT",
        ],
        "not_recovered_states": ["NOT_YET_STRICT_ACTIVE", "REVERSAL_PENDING", "RETIRED"],
        "recovery_classification_once_per_unique_gap": True,
        "no_double_counting_provider_evidence": True,
        "exactly_two_provider_role_records_per_unique_gap": True,
    }
    payload["policy_metrics"] = {
        "coverage_denominator": len(DATASETS) * CHECKPOINTS_PER_DATASET * len(ROLES),
        "coverage_denominator_formula": "4 datasets * 22 checkpoints * 2 roles",
        "strict_actionable_coverage": (
            "cells_with_at_least_one_STRICT_ACTIVE_NEAR_lineage / 176"
        ),
        "expanded_actionable_coverage": (
            "cells_with_at_least_one_actionable_lineage / 176"
        ),
        "expanded_structural_coverage": (
            "cells_with_at_least_one_actionable_or_structural_lineage / 176"
        ),
        "observation_key": list(CANDIDATE_KEY_FIELDS),
        "strict_observation_states": ["STRICT_ACTIVE_NEAR"],
        "expanded_actionable_observation_states": [
            "STRICT_ACTIVE_NEAR",
            "PERSISTED_ACTIVE_NEAR",
            "REVERSED_ACTIVE_NEAR",
        ],
        "expanded_structural_observation_states": [
            "STRICT_ACTIVE_NEAR",
            "PERSISTED_ACTIVE_NEAR",
            "REVERSED_ACTIVE_NEAR",
            "PERSISTED_DISTANT",
            "REVERSED_PERSISTED_DISTANT",
        ],
        "observation_identity": "unique_observation_keys_only",
        "candidate_inflation_ratio": (
            "count(unique expanded structural observations) / "
            "count(unique strict observations)"
        ),
        "zero_strict_denominator": "block",
        "additional_counts": [
            "added_actionable_lineage_observations",
            "added_structural_lineage_observations_structural_only_count",
            "maximum_lineages_per_checkpoint_role_cell",
            "median_lineages_per_checkpoint_role_cell",
        ],
        "cell_count_statistics_population": "expanded_structural_counts_over_all_176_cells_including_zero",
        "added_actionable_definition": "expanded_actionable_set_minus_strict_set",
        "added_structural_definition": "structural_only_observation_count",
        "coverage_population": "complete_176_checkpoint_role_cells",
        "outcome_rates": {
            "candidate_level": {
                "recovered_actionable_candidate_survival_rate": "successful_recovered_actionable_candidates / evaluable_recovered_actionable_candidates",
                "recovered_actionable_candidate_contact_rate": "successful_recovered_actionable_candidates / evaluable_recovered_actionable_candidates",
            },
            "unique_gap_level": {
                "recovered_actionable_gap_survival_rate": "recovered_actionable_gaps_with_any_successful_candidate / recovered_actionable_gaps_with_evaluable_candidate",
                "recovered_actionable_gap_contact_rate": "recovered_actionable_gaps_with_any_successful_candidate / recovered_actionable_gaps_with_evaluable_candidate",
                "aggregation": "any_candidate_succeeds",
                "headline_decision_level": True,
            },
            "zero_denominator": "null_with_zero_evaluable_count",
            "candidate_rates_persisted_separately": True,
        },
    }
    payload["future_evaluation"] = {
        "horizons_hours": list(HORIZONS_HOURS),
        "future_rule": "checkpoint_plus_interval_through_horizon_endpoint_exactly",
        "candidate_key": list(CANDIDATE_KEY_FIELDS),
        "same_contact_bar_reaction": False,
        "no_intrabar_order_assumption": True,
        "line_value": "line_geometry_evaluated_at_each_bar_timestamp",
        "atr_for_zone_and_survival": "ATR_at_evaluated_bar",
        "near_line": {
            "survival": "no_two_consecutive_role_invalidating_closes_at_0.5_ATR",
            "zone_contact": (
                "low <= line + 0.35 * ATR_at_evaluated_bar and "
                "high >= line - 0.35 * ATR_at_evaluated_bar"
            ),
            "reaction_window": "strictly_after_first_contact_and_before_sustained_breach",
            "support_reaction": "future_high - contact_line >= 1 * contact_bar_ATR",
            "resistance_reaction": "contact_line - future_low >= 1 * contact_bar_ATR",
            "reaction_atr": "ATR_at_first_contact",
        },
        "structural_only": {
            "zone_contact_within_horizon": (
                "low <= line + 0.35 * ATR_at_evaluated_bar and "
                "high >= line - 0.35 * ATR_at_evaluated_bar"
            ),
            "minimum_future_distance_atr": (
                "minimum(abs(close - line_at_bar) / ATR_at_bar)"
            ),
            "initial_distance_atr": (
                "abs(last_completed_close - line_at_checkpoint) / "
                "ATR_of_last_completed_bar"
            ),
            "distance_contraction_atr": (
                "initial_distance_atr - minimum_future_distance_atr"
            ),
            "crossed_into_at_most_8_atr": "any future distance <= 8",
        },
        "role_aware_support_and_resistance": True,
        "distant_actionable": False,
        "temporal_policy": "not_evaluated",
    }
    payload["transition_evidence"] = {
        "fields": [
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
        ],
        "fixed_geometry_fields": list(payload["lineage_identity"]["geometry_fields"]),
        "no_op_retention_recorded_in_checkpoint_state": True,
        "no_op_retention_persisted_as_transition": False,
        "effective_at_uses_available_at": True,
    }
    payload["reconciliation"].update(
        {
            "unique_gap_key_fields": list(UNIQUE_GAP_KEY_FIELDS),
            "candidate_key_fields": list(CANDIDATE_KEY_FIELDS),
            "provider_role_gaps_map_two_to_one": True,
            "coverage_denominator": 176,
            "strict_active_near_reserved_for_current_r1_seed": True,
            "persisted_active_near_resolves_reentry_conflict": True,
            "fixed_geometry_across_checkpoints": True,
            "state_retention_allowed": True,
            "event_precedence_frozen": True,
            "zero_inflation_denominator_blocks": True,
            "semantic_rederivation": {
                "json_members": True,
                "csv_members": True,
                "forged_lifecycle_state_rejected": True,
                "forged_transition_trigger_rejected": True,
                "forged_role_rejected": True,
                "forged_recovery_status_rejected": True,
                "forged_recovery_mechanism_rejected": True,
                "forged_future_outcome_rejected": True,
                "forged_decision_rejected": True,
                "forged_manifest_rejected": True,
            },
        }
    )
    payload["decision"] = {
        "statuses": list(DECISION_STATUSES),
        "evidence_flags": [
            "unique_gap_count",
            "actionable_recovery_count",
            "structural_only_recovery_count",
            "role_reversal_recovery_count",
            "distance_persistence_recovery_count",
            "unrecovered_gap_count",
            "candidate_inflation_ratio",
            "reversal_pending_without_contact_count",
            "retired_lineage_count",
            "recovered_actionable_gap_48h_survival_rate",
            "recovered_actionable_gap_96h_survival_rate",
            "recovered_actionable_gap_96h_contact_rate",
        ],
        "freeze_status": FREEZE_STATUS,
        "study_result": "not_evaluated",
    }
    payload.pop("decision_statuses", None)
    payload.pop("decision_evidence_flags", None)
    payload["study_controls"].update(
        {
            "contract_freeze_status": FREEZE_STATUS,
            "study_execution_during_freeze": False,
            "lifecycle_implementation": False,
            "study_run": False,
        }
    )
    revised_top_level = (
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
    )
    return {key: payload[key] for key in revised_top_level}


def contract_payload() -> dict[str, Any]:
    """Return defensive copy of canonical contract payload."""
    return copy.deepcopy(_contract_payload())


def lineage_identity(
    *,
    asset: str,
    timeframe: str,
    original_anchor_role: str,
    first_anchor_pivot_id: str,
    second_anchor_pivot_id: str,
) -> str:
    """Derive identity independent of checkpoint and mutable lifecycle state."""
    payload = {
        "asset": asset,
        "timeframe": timeframe,
        "original_anchor_role": original_anchor_role,
        "first_anchor_pivot_id": first_anchor_pivot_id,
        "second_anchor_pivot_id": second_anchor_pivot_id,
    }
    return deterministic_hash(LINEAGE_NAMESPACE, payload)


def legal_transition(previous_state: str, current_state: str) -> bool:
    """Return whether state change or explicit state retention is allowed."""
    if previous_state == "REVERSAL_PENDING" and current_state in {
        "REVERSED_ACTIVE_NEAR",
        "REVERSED_PERSISTED_DISTANT",
    }:
        return False
    if previous_state == current_state:
        return state_retention_allowed(previous_state)
    return current_state in LEGAL_TRANSITIONS.get(previous_state, ())


def state_retention_allowed(state: str) -> bool:
    """Return whether checkpoint state may persist without an event."""
    return STATE_RETENTION_ALLOWED.get(state, False)


def transition_allowed(
    previous_state: str,
    current_state: str,
    *,
    reversal_contact_confirmed: bool = False,
) -> bool:
    """Apply contextual contact guard to declared state transitions."""
    if previous_state == "REVERSAL_PENDING" and current_state in {
        "REVERSED_ACTIVE_NEAR",
        "REVERSED_PERSISTED_DISTANT",
    }:
        return reversal_contact_confirmed and current_state in LEGAL_TRANSITIONS.get(
            previous_state, ()
        )
    return legal_transition(previous_state, current_state)


def _transition_triggers(previous_state: str, current_state: str) -> frozenset[str]:
    return TRANSITION_TRIGGER_MATRIX.get((previous_state, current_state), frozenset())


def _retirement_reason_for_trigger(trigger: str) -> str | None:
    if trigger == "reversed_role_sustained_breach_confirmed":
        return "reversed_role_sustained_breach"
    if trigger in {
        "original_projection_invalid",
        "reversed_projection_invalid",
    }:
        return trigger
    return None


def original_role_breach(*, role: str, close: float, line: float, atr: float) -> bool:
    """Evaluate one strict original-role close without replaying a series."""
    if role not in {"support", "resistance"} or not all(
        math.isfinite(value) for value in (close, line, atr)
    ) or atr <= 0:
        raise ContractFreezeError("invalid original-role breach input")
    if role == "support":
        return close < line - 0.5 * atr
    return close > line + 0.5 * atr


def update_breach_counter(
    previous_count: int,
    *,
    breaching_close: bool,
    strict_lineage_active: bool,
) -> int:
    """Increment consecutive breach count or reset it on a clean close."""
    if previous_count < 0:
        raise ContractFreezeError("negative breach counter")
    if not strict_lineage_active:
        return 0
    return previous_count + 1 if breaching_close else 0


def reversal_contact_confirmed(
    *,
    low: float,
    high: float,
    line: float,
    atr: float,
    contact_available_at: int,
    second_breach_available_at: int,
) -> bool:
    """Apply exact post-breach contact zone and availability ordering."""
    if not all(math.isfinite(value) for value in (low, high, line, atr)) or atr <= 0:
        raise ContractFreezeError("invalid reversal-contact input")
    return (
        contact_available_at > second_breach_available_at
        and low <= line + 0.35 * atr
        and high >= line - 0.35 * atr
    )


def semantic_role_for_state(state: str, original_role: str) -> str | None:
    """Map lifecycle state to active semantic role; pending/retired are inactive."""
    if original_role not in {"support", "resistance"}:
        raise ContractFreezeError("invalid original anchor role")
    if state in {
        "NOT_YET_STRICT_ACTIVE",
        "REVERSAL_PENDING",
        "RETIRED",
    }:
        return None
    if state in {"STRICT_ACTIVE_NEAR", "PERSISTED_ACTIVE_NEAR", "PERSISTED_DISTANT"}:
        return original_role
    if state in {"REVERSED_ACTIVE_NEAR", "REVERSED_PERSISTED_DISTANT"}:
        return "resistance" if original_role == "support" else "support"
    raise ContractFreezeError("unknown lifecycle state")


def aggregate_gap_recovery(
    candidates: list[Mapping[str, Any]],
    *,
    provider_role_records: int,
) -> dict[str, Any]:
    """Aggregate prefiltered current-role candidates at one unique gap."""
    if provider_role_records != 2:
        raise ContractFreezeError("unique gap requires exactly two provider-role records")
    actionable_states = {
        "STRICT_ACTIVE_NEAR",
        "PERSISTED_ACTIVE_NEAR",
        "REVERSED_ACTIVE_NEAR",
    }
    structural_states = {"PERSISTED_DISTANT", "REVERSED_PERSISTED_DISTANT"}
    mechanisms = [
        mechanism
        for mechanism in RECOVERY_MECHANISMS
        if any(mechanism in candidate.get("mechanisms", ()) for candidate in candidates)
    ]
    if any(candidate.get("state") in actionable_states for candidate in candidates):
        status = "ACTIONABLE"
    elif any(candidate.get("state") in structural_states for candidate in candidates):
        status = "STRUCTURAL_ONLY"
    else:
        status = "NOT_RECOVERED"
    reason = None
    if status == "NOT_RECOVERED":
        if any(not candidate.get("prior_strict_lineage", True) for candidate in candidates):
            reason = "NO_PRIOR_STRICT_LINEAGE"
        elif any(candidate.get("pending_without_contact", False) for candidate in candidates):
            reason = "REVERSAL_PENDING_NO_CONTACT"
        else:
            reason = "ALL_RELEVANT_LINEAGES_RETIRED"
    return {
        "recovery_status": status,
        "recovery_mechanisms": mechanisms,
        "unrecovered_reason": reason,
    }


def unique_observation_keys(
    observations: list[tuple[str, int, str, str]],
) -> tuple[tuple[str, int, str, str], ...]:
    """Deduplicate candidate observations by frozen candidate key."""
    return tuple(sorted(set(observations)))


def outcome_rate(success_count: int, evaluable_count: int) -> dict[str, Any]:
    """Return null rate with explicit zero support when denominator is empty."""
    if success_count < 0 or evaluable_count < 0 or success_count > evaluable_count:
        raise ContractFreezeError("invalid outcome counts")
    return {
        "rate": None if evaluable_count == 0 else success_count / evaluable_count,
        "evaluable_count": evaluable_count,
    }


def candidate_outcome_rate(outcomes: list[Mapping[str, bool]]) -> dict[str, Any]:
    """Aggregate one outcome per recovered actionable candidate."""
    return outcome_rate(
        sum(1 for outcome in outcomes if outcome.get("evaluable") and outcome.get("successful")),
        sum(1 for outcome in outcomes if outcome.get("evaluable")),
    )


def gap_outcome_rate(outcomes: list[Mapping[str, bool]]) -> dict[str, Any]:
    """Aggregate one unique gap with any successful evaluable candidate."""
    evaluable = [outcome for outcome in outcomes if outcome.get("evaluable")]
    return outcome_rate(
        int(any(outcome.get("successful") for outcome in evaluable)),
        int(bool(evaluable)),
    )


def expanded_structural_cell_median(counts: list[int]) -> float:
    """Compute median over all 176 checkpoint-role cells, including zeros."""
    if len(counts) != len(DATASETS) * CHECKPOINTS_PER_DATASET * len(ROLES):
        raise ContractFreezeError("expanded structural cell count must cover 176 cells")
    if any(count < 0 for count in counts):
        raise ContractFreezeError("negative expanded structural cell count")
    return float(median(counts))


def available_at(candle_timestamp: int, timeframe: str) -> int:
    """Return bar availability timestamp in epoch seconds."""
    if timeframe not in INTERVAL_SECONDS:
        raise ContractFreezeError("unsupported owner timeframe")
    return candle_timestamp + INTERVAL_SECONDS[timeframe]


def checkpoint_processes_bar(
    *,
    previous_checkpoint: int,
    current_checkpoint: int,
    candle_timestamp: int,
    timeframe: str,
) -> bool:
    """Apply exact available-at interval boundary without replaying data."""
    available_timestamp = available_at(candle_timestamp, timeframe)
    return previous_checkpoint < available_timestamp <= current_checkpoint


def lineage_is_eligible(*, appears_in_exact_strict_seed: bool) -> bool:
    """Only exact Phase 11R.1 strict seeds enter lifecycle state."""
    return appears_in_exact_strict_seed


def candidate_recovers_gap(*, current_semantic_role: str, gap_role: str) -> bool:
    """Require current semantic role equality before recovery attribution."""
    return current_semantic_role == gap_role


def _opposite_role(role: str) -> str:
    if role not in ROLES:
        raise LifecycleStudyError("invalid role for lifecycle attribution")
    return "resistance" if role == "support" else "support"


def _is_relevant_inactive_lineage(
    lineage: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    gap_role: str,
) -> bool:
    """Keep pending/retired history for reason attribution only."""
    lifecycle_state = state.get("state")
    if lifecycle_state == "REVERSAL_PENDING":
        return _opposite_role(lineage["original_anchor_role"]) == gap_role
    if lifecycle_state == "RETIRED":
        return (
            lineage["original_anchor_role"] == gap_role
            or state.get("last_active_semantic_role") == gap_role
        )
    return False


def future_horizon_bars(timeframe: str, horizon_hours: int) -> int:
    """Return exact owner-timeframe bar count for approved horizon."""
    if timeframe not in INTERVAL_SECONDS or horizon_hours not in HORIZONS_HOURS:
        raise ContractFreezeError("unsupported future horizon")
    return horizon_hours * 3_600 // INTERVAL_SECONDS[timeframe]


def classify_recovery(
    *,
    state: str,
    prior_strict_lineage: bool = True,
    reversal_pending_without_contact: bool = False,
    all_relevant_lineages_retired: bool = False,
) -> dict[str, Any]:
    """Return orthogonal recovery status and mechanism evidence."""
    if not prior_strict_lineage:
        return {
            "recovery_status": "NOT_RECOVERED",
            "recovery_mechanisms": [],
            "unrecovered_reason": "NO_PRIOR_STRICT_LINEAGE",
        }
    if reversal_pending_without_contact:
        return {
            "recovery_status": "NOT_RECOVERED",
            "recovery_mechanisms": [],
            "unrecovered_reason": "REVERSAL_PENDING_NO_CONTACT",
        }
    if all_relevant_lineages_retired or state == "RETIRED":
        return {
            "recovery_status": "NOT_RECOVERED",
            "recovery_mechanisms": [],
            "unrecovered_reason": "ALL_RELEVANT_LINEAGES_RETIRED",
        }
    if state in {"STRICT_ACTIVE_NEAR", "PERSISTED_ACTIVE_NEAR", "REVERSED_ACTIVE_NEAR"}:
        mechanisms: list[str] = []
        if state == "PERSISTED_ACTIVE_NEAR":
            mechanisms.append("DISTANCE_PERSISTENCE")
        if state == "REVERSED_ACTIVE_NEAR":
            mechanisms.append("ROLE_REVERSAL")
        return {
            "recovery_status": "ACTIONABLE",
            "recovery_mechanisms": mechanisms,
            "unrecovered_reason": None,
        }
    if state in {"PERSISTED_DISTANT", "REVERSED_PERSISTED_DISTANT"}:
        mechanism = (
            "ROLE_REVERSAL"
            if state == "REVERSED_PERSISTED_DISTANT"
            else "DISTANCE_PERSISTENCE"
        )
        return {
            "recovery_status": "STRUCTURAL_ONLY",
            "recovery_mechanisms": [mechanism],
            "unrecovered_reason": None,
        }
    raise ContractFreezeError("state has no deterministic recovery classification")


class LifecycleStudyError(ContractFreezeError):
    """Raised when lifecycle replay or publication validation fails."""


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise LifecycleStudyError(f"{field} must be an ISO string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LifecycleStudyError(f"invalid {field}") from exc
    if parsed.tzinfo is None:
        raise LifecycleStudyError(f"{field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _datetime_from_ns(value: int) -> datetime:
    seconds, remainder = divmod(int(value), NANOSECONDS)
    return datetime.fromtimestamp(seconds, tz=UTC) + timedelta(
        microseconds=remainder // 1_000
    )


def _datetime_to_ns(value: datetime) -> int:
    value = value.astimezone(UTC)
    return int(value.timestamp()) * NANOSECONDS + value.microsecond * 1_000


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise LifecycleStudyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise LifecycleStudyError(f"non-finite JSON constant: {value}")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise LifecycleStudyError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict) or raw != _canonical_bytes(value):
        raise LifecycleStudyError(f"non-canonical JSON artifact: {path}")
    return value


def _inventory(root: Path) -> tuple[dict[str, Any], ...]:
    if not root.is_dir() or root.is_symlink():
        raise LifecycleStudyError(f"artifact root missing: {root}")
    items: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise LifecycleStudyError(f"symlink is not allowed: {path}")
        items.append(
            {
                "path": path.relative_to(root).as_posix(),
                "byte_length": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return tuple(items)


def _inventory_sha256(inventory: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_bytes(_canonical_bytes(list(inventory)))


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value))


def _csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        raise LifecycleStudyError("CSV payload cannot be empty")
    fields = tuple(rows[0])
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row[field] for field in fields})
    return buffer.getvalue().encode("utf-8")


def _finite(value: object, *, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise LifecycleStudyError(f"{field} is not numeric") from exc
    if not math.isfinite(result):
        raise LifecycleStudyError(f"{field} is not finite")
    return result


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class LifecycleLineage:
    lineage_id: str
    dataset_id: str
    asset: str
    timeframe: str
    original_anchor_role: str
    first_anchor_pivot_id: str
    second_anchor_pivot_id: str
    first_anchor_timestamp: str
    first_anchor_price: float
    second_anchor_timestamp: str
    second_anchor_price: float
    first_strict_checkpoint: int
    source_input_identity: str
    geometry: Mapping[str, Any]

    def __post_init__(self) -> None:
        if self.original_anchor_role not in ROLES:
            raise LifecycleStudyError("invalid lineage role")
        if not self.lineage_id or not self.first_anchor_pivot_id or not self.second_anchor_pivot_id:
            raise LifecycleStudyError("lineage identity fields are required")
        first_time = _parse_iso(self.first_anchor_timestamp, field="first_anchor_timestamp")
        second_time = _parse_iso(self.second_anchor_timestamp, field="second_anchor_timestamp")
        if self.first_strict_checkpoint < 1:
            raise LifecycleStudyError("invalid first strict checkpoint")
        geometry = phase11r1.LineGeometry.from_dict(dict(self.geometry))
        expected_id = lineage_identity(
            asset=self.asset,
            timeframe=self.timeframe,
            original_anchor_role=self.original_anchor_role,
            first_anchor_pivot_id=self.first_anchor_pivot_id,
            second_anchor_pivot_id=self.second_anchor_pivot_id,
        )
        if self.lineage_id != expected_id:
            raise LifecycleStudyError("lineage identity does not match anchor identity")
        if geometry.start_time != first_time or geometry.end_time != second_time:
            raise LifecycleStudyError("geometry/first-anchor timestamp mismatch")
        if geometry.start_price != self.first_anchor_price or geometry.end_price != self.second_anchor_price:
            raise LifecycleStudyError("geometry/anchor price mismatch")
        object.__setattr__(self, "geometry", _freeze(dict(self.geometry)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "lineage_id": self.lineage_id,
            "dataset_id": self.dataset_id,
            "asset": self.asset,
            "timeframe": self.timeframe,
            "original_anchor_role": self.original_anchor_role,
            "first_anchor_pivot_id": self.first_anchor_pivot_id,
            "second_anchor_pivot_id": self.second_anchor_pivot_id,
            "first_anchor_timestamp": self.first_anchor_timestamp,
            "first_anchor_price": self.first_anchor_price,
            "second_anchor_timestamp": self.second_anchor_timestamp,
            "second_anchor_price": self.second_anchor_price,
            "first_strict_checkpoint": self.first_strict_checkpoint,
            "source_input_identity": self.source_input_identity,
            "geometry": _thaw(self.geometry),
        }


@dataclass(frozen=True, slots=True)
class LifecycleBar:
    timestamp_ns: int
    available_at_ns: int
    high: float
    low: float
    close: float
    atr: float

    def __post_init__(self) -> None:
        if self.available_at_ns <= self.timestamp_ns:
            raise LifecycleStudyError("bar availability must follow timestamp")
        if self.high < self.low or self.low > self.close or self.high < self.close:
            raise LifecycleStudyError("invalid OHLC bar")
        if self.atr <= 0 or not math.isfinite(self.atr):
            raise LifecycleStudyError("bar ATR must be positive and finite")


@dataclass(frozen=True, slots=True)
class LifecycleCheckpoint:
    dataset_id: str
    checkpoint_index: int
    observed_at: str
    source_input_identity: str
    strict_lineage_ids: tuple[str, ...]
    last_completed_timestamp_ns: int

    def __post_init__(self) -> None:
        _parse_iso(self.observed_at, field="checkpoint.observed_at")
        if self.checkpoint_index < 1 or self.last_completed_timestamp_ns <= 0:
            raise LifecycleStudyError("invalid checkpoint")
        if tuple(sorted(set(self.strict_lineage_ids))) != self.strict_lineage_ids:
            raise LifecycleStudyError("strict seed lineage IDs must be sorted and unique")


def _lineage_from_seed(dataset_id: str, checkpoint_index: int, seed: Any) -> LifecycleLineage:
    first = seed.first
    second = seed.second
    geometry = seed.geometry.to_dict()
    lineage_id = lineage_identity(
        asset=first.asset,
        timeframe=first.timeframe,
        original_anchor_role=seed.role,
        first_anchor_pivot_id=first.pivot_id,
        second_anchor_pivot_id=second.pivot_id,
    )
    return LifecycleLineage(
        lineage_id=lineage_id,
        dataset_id=dataset_id,
        asset=first.asset,
        timeframe=first.timeframe,
        original_anchor_role=seed.role,
        first_anchor_pivot_id=first.pivot_id,
        second_anchor_pivot_id=second.pivot_id,
        first_anchor_timestamp=_iso(first.pivot_time),
        first_anchor_price=float(first.price),
        second_anchor_timestamp=_iso(second.pivot_time),
        second_anchor_price=float(second.price),
        first_strict_checkpoint=checkpoint_index,
        source_input_identity=first.source_input_identity,
        geometry=geometry,
    )


def _bars_for_data(data: Any) -> tuple[LifecycleBar, ...]:
    atr = phase11r1._atr(data)
    interval_ns = INTERVAL_SECONDS[data.timeframe] * NANOSECONDS
    return tuple(
        LifecycleBar(
            timestamp_ns=int(timestamp),
            available_at_ns=int(timestamp) + interval_ns,
            high=_finite(data.high[position], field=f"high[{position}]"),
            low=_finite(data.low[position], field=f"low[{position}]"),
            close=_finite(data.close[position], field=f"close[{position}]"),
            atr=_finite(atr[position], field=f"atr[{position}]"),
        )
        for position, timestamp in enumerate(data.timestamps)
    )


def build_lifecycle_inputs(scope: Sequence[Any]) -> dict[str, Any]:
    """Derive fixed geometry, strict seed membership and owner bars from R1."""
    lineages: dict[str, LifecycleLineage] = {}
    checkpoints: dict[str, list[LifecycleCheckpoint]] = defaultdict(list)
    bars: dict[str, tuple[LifecycleBar, ...]] = {}
    for dataset in scope:
        bars[dataset.dataset_id] = _bars_for_data(dataset.data)
        for checkpoint in dataset.checkpoints:
            pools = phase11r1._seed_pool(
                checkpoint.data,
                prefix_last_position=checkpoint.prefix_last_position,
                checkpoint=checkpoint.checkpoint,
            )
            strict_ids: list[str] = []
            for role in ROLES:
                for seed in pools[role]:
                    lineage = _lineage_from_seed(
                        dataset.dataset_id, checkpoint.checkpoint_index, seed
                    )
                    existing = lineages.get(lineage.lineage_id)
                    if existing is None:
                        lineages[lineage.lineage_id] = lineage
                    else:
                        existing_payload = existing.to_dict()
                        lineage_payload = lineage.to_dict()
                        existing_payload.pop("first_strict_checkpoint")
                        lineage_payload.pop("first_strict_checkpoint")
                        if existing_payload != lineage_payload:
                            raise LifecycleStudyError("lineage geometry changed across checkpoints")
                        if lineage.first_strict_checkpoint < existing.first_strict_checkpoint:
                            lineages[lineage.lineage_id] = replace(
                                existing,
                                first_strict_checkpoint=lineage.first_strict_checkpoint,
                            )
                    strict_ids.append(lineage.lineage_id)
            checkpoint_entry = LifecycleCheckpoint(
                dataset_id=dataset.dataset_id,
                checkpoint_index=checkpoint.checkpoint_index,
                observed_at=_iso(checkpoint.checkpoint),
                source_input_identity=checkpoint.data.input_identity,
                strict_lineage_ids=tuple(sorted(set(strict_ids))),
                last_completed_timestamp_ns=int(
                    checkpoint.data.timestamps[checkpoint.prefix_last_position]
                ),
            )
            checkpoints[dataset.dataset_id].append(checkpoint_entry)
    return {
        "lineages": tuple(lineages.values()),
        "checkpoints": {
            dataset: tuple(sorted(values, key=lambda item: item.checkpoint_index))
            for dataset, values in checkpoints.items()
        },
        "bars": bars,
    }


def _strict_lineage_ids_from_r2_checkpoint(
    checkpoint_payload: Mapping[str, Any], *, asset: str, timeframe: str
) -> tuple[str, ...]:
    """Derive R3A lineage IDs from retained R2 seed pairs, not current fields."""
    derived: list[str] = []
    roles = checkpoint_payload.get("roles")
    if not isinstance(roles, Mapping):
        raise LifecycleStudyError("retained R2 checkpoint roles are missing")
    for role in ROLES:
        role_payload = roles.get(role)
        if not isinstance(role_payload, Mapping):
            raise LifecycleStudyError("retained R2 checkpoint role is missing")
        final_ids = role_payload.get("final_seed_ids")
        pairs = role_payload.get("pairs")
        if (
            not isinstance(final_ids, list)
            or final_ids != sorted(set(final_ids))
            or not isinstance(pairs, list)
        ):
            raise LifecycleStudyError("retained R2 strict seed fields are invalid")
        pair_by_seed: dict[str, Mapping[str, Any]] = {}
        for pair in pairs:
            if not isinstance(pair, Mapping) or pair.get("seed_id") is None:
                continue
            seed_id = pair["seed_id"]
            if seed_id in pair_by_seed:
                raise LifecycleStudyError("retained R2 seed pair IDs are duplicated")
            pair_by_seed[seed_id] = pair
        if tuple(sorted(pair_by_seed)) != tuple(final_ids):
            raise LifecycleStudyError("retained R2 final seed/pair sets disagree")
        for seed_id in final_ids:
            pair = pair_by_seed[seed_id]
            first_pivot_id = pair.get("first_pivot_id")
            second_pivot_id = pair.get("second_pivot_id")
            if not isinstance(first_pivot_id, str) or not isinstance(second_pivot_id, str):
                raise LifecycleStudyError("retained R2 seed pair anchors are missing")
            derived.append(
                lineage_identity(
                    asset=asset,
                    timeframe=timeframe,
                    original_anchor_role=role,
                    first_anchor_pivot_id=first_pivot_id,
                    second_anchor_pivot_id=second_pivot_id,
                )
            )
    return tuple(sorted(set(derived)))


def _retained_r2_strict_seed_expectations(
    scope: Sequence[Any],
) -> dict[tuple[str, int], tuple[str, ...]]:
    """Read retained R2 seed evidence and independently derive lineage IDs."""
    expectations: dict[tuple[str, int], tuple[str, ...]] = {}
    for dataset in scope:
        payload = _load_json(
            PHASE11R2_ROOT / "datasets" / dataset.dataset_id / "seed_funnel.json"
        )
        checkpoints = payload.get("checkpoints")
        if not isinstance(checkpoints, list):
            raise LifecycleStudyError("retained R2 checkpoint evidence is missing")
        for checkpoint_payload in checkpoints:
            checkpoint_index = checkpoint_payload.get("checkpoint_index")
            if isinstance(checkpoint_index, bool) or not isinstance(checkpoint_index, int):
                raise LifecycleStudyError("retained R2 checkpoint index is invalid")
            expectations[(dataset.dataset_id, checkpoint_index)] = (
                _strict_lineage_ids_from_r2_checkpoint(
                    checkpoint_payload,
                    asset=dataset.data.asset,
                    timeframe=dataset.data.timeframe,
                )
            )
        expected_dataset_checkpoints = {
            (dataset.dataset_id, checkpoint.checkpoint_index)
            for checkpoint in dataset.checkpoints
        }
        actual_dataset_checkpoints = {
            key for key in expectations if key[0] == dataset.dataset_id
        }
        if actual_dataset_checkpoints != expected_dataset_checkpoints:
            raise LifecycleStudyError("retained R2 strict checkpoint evidence is incomplete")
    return expectations


def _coerce_lineage(value: LifecycleLineage | Mapping[str, Any]) -> LifecycleLineage:
    if isinstance(value, LifecycleLineage):
        return value
    try:
        return LifecycleLineage(**dict(value))
    except (TypeError, ValueError) as exc:
        raise LifecycleStudyError("invalid lifecycle lineage") from exc


def _coerce_bar(value: LifecycleBar | Mapping[str, Any]) -> LifecycleBar:
    if isinstance(value, LifecycleBar):
        return value
    try:
        return LifecycleBar(**dict(value))
    except (TypeError, ValueError) as exc:
        raise LifecycleStudyError("invalid lifecycle bar") from exc


def _coerce_checkpoint(
    value: LifecycleCheckpoint | Mapping[str, Any],
) -> LifecycleCheckpoint:
    if isinstance(value, LifecycleCheckpoint):
        return value
    try:
        payload = dict(value)
        payload["strict_lineage_ids"] = tuple(payload["strict_lineage_ids"])
        return LifecycleCheckpoint(**payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise LifecycleStudyError("invalid lifecycle checkpoint") from exc


def _bar_evidence(bar: LifecycleBar) -> dict[str, Any]:
    return {
        "timestamp": _iso(_datetime_from_ns(bar.timestamp_ns)),
        "available_at": _iso(_datetime_from_ns(bar.available_at_ns)),
        "close": bar.close,
        "atr": bar.atr,
    }


def _geometry_value(lineage: LifecycleLineage, timestamp_ns: int) -> float:
    geometry = phase11r1.LineGeometry.from_dict(_thaw(lineage.geometry))
    return _finite(
        phase11r1._line_value(geometry, _datetime_from_ns(timestamp_ns)),
        field="line projection",
    )


def _distance_atr(
    lineage: LifecycleLineage,
    bar: LifecycleBar,
    *,
    line_timestamp_ns: int | None = None,
) -> float:
    line = _geometry_value(
        lineage, bar.timestamp_ns if line_timestamp_ns is None else line_timestamp_ns
    )
    return abs(bar.close - line) / bar.atr


def _state_record(
    lineage: LifecycleLineage,
    runtime: Mapping[str, Any],
    checkpoint: LifecycleCheckpoint,
    bar: LifecycleBar | None,
    *,
    checkpoint_bar: LifecycleBar | None = None,
) -> dict[str, Any]:
    """Persist event and checkpoint measurements from their own clocks."""
    if checkpoint_bar is None and bar is not None:
        # Direct synthetic callers may only provide one bar. Canonical replay
        # always supplies a separate checkpoint bar for event transitions.
        checkpoint_bar = bar
    checkpoint_projection = None
    checkpoint_distance = None
    event_projection = None
    event_distance = None
    checkpoint_ns = _datetime_to_ns(
        _parse_iso(checkpoint.observed_at, field="checkpoint.observed_at")
    )
    if checkpoint_bar is not None:
        try:
            checkpoint_projection = _geometry_value(lineage, checkpoint_ns)
            checkpoint_distance = _distance_atr(
                lineage,
                checkpoint_bar,
                line_timestamp_ns=checkpoint_ns,
            )
        except LifecycleStudyError:
            checkpoint_projection = None
            checkpoint_distance = None
    if bar is not None:
        try:
            event_projection = _geometry_value(lineage, bar.timestamp_ns)
            event_distance = _distance_atr(lineage, bar)
        except LifecycleStudyError:
            event_projection = None
            event_distance = None
    return {
        "lineage_id": lineage.lineage_id,
        "dataset_id": lineage.dataset_id,
        "checkpoint_index": checkpoint.checkpoint_index,
        "checkpoint_observed_at": checkpoint.observed_at,
        "state": runtime["state"],
        "current_semantic_role": semantic_role_for_state(
            runtime["state"], lineage.original_anchor_role
        ),
        "last_active_semantic_role": runtime.get("last_active_semantic_role"),
        "original_anchor_role": lineage.original_anchor_role,
        "fixed_geometry": lineage.to_dict()["geometry"],
        "projection_at_checkpoint": checkpoint_projection,
        "checkpoint_distance_atr": checkpoint_distance,
        "event_projection": event_projection,
        "event_distance_atr": event_distance,
        "source_input_identity": checkpoint.source_input_identity,
        "reversal_count": runtime["reversal_count"],
        "first_same_role_breach_bar": runtime.get("first_same_role_breach_bar"),
        "second_same_role_breach_bar": runtime.get("second_same_role_breach_bar"),
        "first_reversal_contact_bar": runtime.get("first_reversal_contact_bar"),
        "retirement_reason": runtime.get("retirement_reason"),
    }


def _transition(
    lineage: LifecycleLineage,
    runtime: dict[str, Any],
    current_state: str,
    *,
    trigger: str,
    effective_at: str,
    checkpoint: LifecycleCheckpoint,
    bar: LifecycleBar | None,
    checkpoint_bar: LifecycleBar | None = None,
) -> dict[str, Any] | None:
    previous = runtime["state"]
    if previous == current_state:
        return None
    contact = trigger == "reversal_contact_confirmed_after_breach"
    if not transition_allowed(previous, current_state, reversal_contact_confirmed=contact):
        raise LifecycleStudyError(
            f"illegal lifecycle transition {previous}->{current_state}"
        )
    if trigger not in _transition_triggers(previous, current_state):
        raise LifecycleStudyError(
            f"trigger does not match lifecycle transition {previous}->{current_state}"
        )
    runtime["state"] = current_state
    active_role = semantic_role_for_state(current_state, lineage.original_anchor_role)
    if active_role is not None:
        runtime["last_active_semantic_role"] = active_role
    if current_state == "RETIRED" and runtime.get("retirement_reason") is None:
        runtime["retirement_reason"] = _retirement_reason_for_trigger(trigger)
    evidence = _state_record(
        lineage,
        runtime,
        checkpoint,
        bar,
        checkpoint_bar=checkpoint_bar,
    )
    return {
        "lineage_id": lineage.lineage_id,
        "dataset_id": lineage.dataset_id,
        "previous_state": previous,
        "current_state": current_state,
        "trigger": trigger,
        "effective_at": effective_at,
        "checkpoint_observed_at": checkpoint.observed_at,
        "original_anchor_role": lineage.original_anchor_role,
        "current_semantic_role": evidence["current_semantic_role"],
        "fixed_geometry": lineage.to_dict()["geometry"],
        "projection_at_checkpoint": evidence["projection_at_checkpoint"],
        "checkpoint_distance_atr": evidence["checkpoint_distance_atr"],
        "event_projection": evidence["event_projection"],
        "event_distance_atr": evidence["event_distance_atr"],
        "first_same_role_breach_bar": runtime.get("first_same_role_breach_bar"),
        "second_same_role_breach_bar": runtime.get("second_same_role_breach_bar"),
        "first_reversal_contact_bar": runtime.get("first_reversal_contact_bar"),
        "reversal_count": runtime["reversal_count"],
        "retirement_reason": runtime.get("retirement_reason"),
        "source_input_identity": checkpoint.source_input_identity,
    }


def _process_lineage_bar(
    lineage: LifecycleLineage,
    runtime: dict[str, Any],
    bar: LifecycleBar,
    checkpoint: LifecycleCheckpoint,
    transitions: list[dict[str, Any]],
    checkpoint_bar: LifecycleBar | None = None,
) -> None:
    state = runtime["state"]
    if state in {"NOT_YET_STRICT_ACTIVE", "RETIRED"}:
        return
    try:
        line = _geometry_value(lineage, bar.timestamp_ns)
    except LifecycleStudyError:
        line = None
    if state == "REVERSAL_PENDING":
        # Pending state has no valid breach/retirement path. A bad projection
        # cannot erase pending provenance before a later contact is observed.
        if line is None or not math.isfinite(line) or line <= 0:
            return
        if reversal_contact_confirmed(
            low=bar.low,
            high=bar.high,
            line=line,
            atr=bar.atr,
            contact_available_at=bar.available_at_ns,
            second_breach_available_at=runtime["second_same_role_breach_available_ns"],
        ):
            runtime["reversal_count"] += 1
            runtime["first_reversal_contact_bar"] = _bar_evidence(bar)
            next_state = (
                "REVERSED_ACTIVE_NEAR"
                if abs(bar.close - line) / bar.atr <= 8.0
                else "REVERSED_PERSISTED_DISTANT"
            )
            runtime["reversed_breach_count"] = 0
            event = _transition(
                lineage,
                runtime,
                next_state,
                trigger="reversal_contact_confirmed_after_breach",
                effective_at=_iso(_datetime_from_ns(bar.available_at_ns)),
                checkpoint=checkpoint,
                bar=bar,
                checkpoint_bar=checkpoint_bar,
            )
            if event:
                transitions.append(event)
        return
    reversed_role = semantic_role_for_state(state, lineage.original_anchor_role)
    active_role = reversed_role if state.startswith("REVERSED") else lineage.original_anchor_role
    projection_valid = line is not None and math.isfinite(line) and line > 0
    if line is None or not math.isfinite(line):
        breaching = False
    else:
        # Breach semantics deliberately run before positive-projection
        # invalidation. Same-bar sustained breach therefore wins.
        breaching = original_role_breach(
            role=active_role,
            close=bar.close,
            line=line,
            atr=bar.atr,
        )
    if state.startswith("REVERSED"):
        count = update_breach_counter(
            runtime["reversed_breach_count"],
            breaching_close=breaching,
            strict_lineage_active=True,
        )
        runtime["reversed_breach_count"] = count
        if count >= 2:
            event = _transition(
                lineage,
                runtime,
                "RETIRED",
                trigger="reversed_role_sustained_breach_confirmed",
                effective_at=_iso(_datetime_from_ns(bar.available_at_ns)),
                checkpoint=checkpoint,
                bar=bar,
                checkpoint_bar=checkpoint_bar,
            )
            if event:
                transitions.append(event)
            return
        if not projection_valid:
            event = _transition(
                lineage,
                runtime,
                "RETIRED",
                trigger="reversed_projection_invalid",
                effective_at=_iso(_datetime_from_ns(bar.available_at_ns)),
                checkpoint=checkpoint,
                bar=bar,
                checkpoint_bar=checkpoint_bar,
            )
            if event:
                transitions.append(event)
        return
    count = update_breach_counter(
        runtime["same_role_breach_count"],
        breaching_close=breaching,
        strict_lineage_active=True,
    )
    runtime["same_role_breach_count"] = count
    if breaching and count == 1:
        runtime["first_same_role_breach_bar"] = _bar_evidence(bar)
        runtime["first_same_role_breach_available_ns"] = bar.available_at_ns
    if count >= 2:
        runtime["second_same_role_breach_bar"] = _bar_evidence(bar)
        runtime["second_same_role_breach_available_ns"] = bar.available_at_ns
        event = _transition(
            lineage,
            runtime,
            "REVERSAL_PENDING",
            trigger="same_role_sustained_breach_confirmed",
            effective_at=_iso(_datetime_from_ns(bar.available_at_ns)),
            checkpoint=checkpoint,
            bar=bar,
            checkpoint_bar=checkpoint_bar,
        )
        if event:
            transitions.append(event)
        return
    if not projection_valid:
        event = _transition(
            lineage,
            runtime,
            "RETIRED",
            trigger="original_projection_invalid",
            effective_at=_iso(_datetime_from_ns(bar.available_at_ns)),
            checkpoint=checkpoint,
            bar=bar,
            checkpoint_bar=checkpoint_bar,
        )
        if event:
            transitions.append(event)


def _checkpoint_classify(
    lineage: LifecycleLineage,
    runtime: dict[str, Any],
    checkpoint: LifecycleCheckpoint,
    last_bar: LifecycleBar | None,
    transitions: list[dict[str, Any]],
) -> None:
    state = runtime["state"]
    if state == "RETIRED" or state == "REVERSAL_PENDING":
        return
    if state == "NOT_YET_STRICT_ACTIVE" and lineage.lineage_id not in checkpoint.strict_lineage_ids:
        return
    if last_bar is None:
        raise LifecycleStudyError("checkpoint has no completed bar")
    checkpoint_ns = _datetime_to_ns(
        _parse_iso(checkpoint.observed_at, field="checkpoint.observed_at")
    )
    line = _geometry_value(lineage, checkpoint_ns)
    distance = abs(last_bar.close - line) / last_bar.atr
    strict = lineage.lineage_id in checkpoint.strict_lineage_ids
    if state.startswith("REVERSED"):
        target = (
            "REVERSED_ACTIVE_NEAR" if distance <= 8.0 else "REVERSED_PERSISTED_DISTANT"
        )
        trigger = (
            "reversed_distance_returned_at_most_8_atr"
            if target == "REVERSED_ACTIVE_NEAR"
            else "reversed_distance_exceeded_8_atr"
        )
    elif strict:
        target = "STRICT_ACTIVE_NEAR"
        trigger = "strict_seed_confirmed"
    else:
        target = "PERSISTED_ACTIVE_NEAR" if distance <= 8.0 else "PERSISTED_DISTANT"
        trigger = (
            "distance_returned_at_most_8_atr"
            if target == "PERSISTED_ACTIVE_NEAR"
            else "distance_exceeded_8_atr"
        )
    event = _transition(
        lineage,
        runtime,
        target,
        trigger=trigger,
        effective_at=checkpoint.observed_at,
        checkpoint=checkpoint,
        bar=None,
        checkpoint_bar=last_bar,
    )
    if event:
        transitions.append(event)


def derive_lifecycle_evidence(
    *,
    lineages: Iterable[LifecycleLineage | Mapping[str, Any]],
    checkpoints: Mapping[str, Iterable[LifecycleCheckpoint | Mapping[str, Any]]],
    bars: Mapping[str, Iterable[LifecycleBar | Mapping[str, Any]]],
) -> dict[str, Any]:
    """Replay owner bars then scheduled checkpoints with immutable geometry."""
    lineage_values = tuple(sorted((_coerce_lineage(item) for item in lineages), key=lambda item: item.lineage_id))
    lineage_by_id = {item.lineage_id: item for item in lineage_values}
    if len(lineage_by_id) != len(lineage_values):
        raise LifecycleStudyError("duplicate lineage identity")
    checkpoint_values = {
        dataset: tuple(sorted((_coerce_checkpoint(item) for item in values), key=lambda item: item.checkpoint_index))
        for dataset, values in checkpoints.items()
    }
    bar_values = {
        dataset: tuple(sorted((_coerce_bar(item) for item in values), key=lambda item: item.timestamp_ns))
        for dataset, values in bars.items()
    }
    states_by_dataset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    transitions_by_dataset: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for dataset_id, dataset_checkpoints in sorted(checkpoint_values.items()):
        dataset_lineages = tuple(item for item in lineage_values if item.dataset_id == dataset_id)
        runtime = {
            item.lineage_id: {
                "state": "NOT_YET_STRICT_ACTIVE",
                "last_active_semantic_role": None,
                "same_role_breach_count": 0,
                "reversed_breach_count": 0,
                "reversal_count": 0,
                "retirement_reason": None,
            }
            for item in dataset_lineages
        }
        activated_lineage_ids: set[str] = set()
        prior_checkpoint_ns = 0
        dataset_bars = bar_values.get(dataset_id, ())
        for checkpoint in dataset_checkpoints:
            checkpoint_ns = _datetime_to_ns(_parse_iso(checkpoint.observed_at, field="checkpoint.observed_at"))
            last_bar = next(
                (
                    bar
                    for bar in reversed(dataset_bars)
                    if bar.timestamp_ns <= checkpoint.last_completed_timestamp_ns
                ),
                None,
            )
            interval_bars = tuple(
                bar
                for bar in dataset_bars
                if prior_checkpoint_ns < bar.available_at_ns <= checkpoint_ns
            )
            for bar in interval_bars:
                for lineage in dataset_lineages:
                    if lineage.lineage_id not in activated_lineage_ids:
                        continue
                    _process_lineage_bar(
                        lineage,
                        runtime[lineage.lineage_id],
                        bar,
                        checkpoint,
                        transitions_by_dataset[dataset_id],
                        checkpoint_bar=last_bar,
                    )
            for lineage in dataset_lineages:
                if (
                    lineage.lineage_id not in activated_lineage_ids
                    and lineage.first_strict_checkpoint == checkpoint.checkpoint_index
                ):
                    if lineage.lineage_id not in checkpoint.strict_lineage_ids:
                        raise LifecycleStudyError(
                            "lineage first strict checkpoint is not in checkpoint seed set"
                        )
                    activated_lineage_ids.add(lineage.lineage_id)
                if lineage.lineage_id not in activated_lineage_ids:
                    continue
                _checkpoint_classify(
                    lineage,
                    runtime[lineage.lineage_id],
                    checkpoint,
                    last_bar,
                    transitions_by_dataset[dataset_id],
                )
                states_by_dataset[dataset_id].append(
                    _state_record(
                        lineage,
                        runtime[lineage.lineage_id],
                        checkpoint,
                        None,
                        checkpoint_bar=last_bar,
                    )
                )
            prior_checkpoint_ns = checkpoint_ns
    return {
        "lineages": [item.to_dict() for item in lineage_values],
        "checkpoint_states": {
            dataset: values for dataset, values in sorted(states_by_dataset.items())
        },
        "transitions": {
            dataset: values for dataset, values in sorted(transitions_by_dataset.items())
        },
    }


def _future_rows(
    bars: Sequence[LifecycleBar], checkpoint: LifecycleCheckpoint, horizon_hours: int
) -> tuple[LifecycleBar, ...]:
    checkpoint_ns = _datetime_to_ns(_parse_iso(checkpoint.observed_at, field="checkpoint.observed_at"))
    end_ns = checkpoint_ns + horizon_hours * 3_600 * NANOSECONDS
    rows = tuple(bar for bar in bars if checkpoint_ns < bar.timestamp_ns <= end_ns)
    if not bars:
        raise LifecycleStudyError("future horizon has no bars")
    interval_ns = bars[0].available_at_ns - bars[0].timestamp_ns
    if interval_ns not in {INTERVAL_SECONDS["1h"] * NANOSECONDS, INTERVAL_SECONDS["4h"] * NANOSECONDS}:
        raise LifecycleStudyError("future horizon interval is unsupported")
    expected = horizon_hours * 3_600 * NANOSECONDS // interval_ns
    if len(rows) != expected:
        raise LifecycleStudyError("future horizon row count is incomplete")
    expected_timestamps = tuple(
        checkpoint_ns + interval_ns * offset for offset in range(1, expected + 1)
    )
    if tuple(bar.timestamp_ns for bar in rows) != expected_timestamps:
        raise LifecycleStudyError("future horizon timestamps are not exact")
    return rows


def _evaluate_candidate_outcome(
    state_record: Mapping[str, Any],
    lineage: LifecycleLineage,
    checkpoint: LifecycleCheckpoint,
    bars: Sequence[LifecycleBar],
    horizon_hours: int,
    *,
    gap: Mapping[str, Any],
    candidate_recovery_status: str | None = None,
    candidate_recovery_mechanisms: Sequence[str] | None = None,
) -> dict[str, Any]:
    rows = _future_rows(bars, checkpoint, horizon_hours)
    role = state_record["current_semantic_role"]
    if role not in ROLES:
        raise LifecycleStudyError("outcome requires active semantic role")
    first_contact: LifecycleBar | None = None
    first_breach: LifecycleBar | None = None
    consecutive = 0
    distances: list[float] = []
    for bar in rows:
        line = _geometry_value(lineage, bar.timestamp_ns)
        distance = abs(bar.close - line) / bar.atr
        distances.append(distance)
        if role == "support":
            contact = bar.low <= line + 0.35 * bar.atr and bar.high >= line - 0.35 * bar.atr
        else:
            contact = bar.low <= line + 0.35 * bar.atr and bar.high >= line - 0.35 * bar.atr
        if first_contact is None and contact:
            first_contact = bar
        breach = original_role_breach(role=role, close=bar.close, line=line, atr=bar.atr)
        consecutive = consecutive + 1 if breach else 0
        if first_breach is None and consecutive >= 2:
            first_breach = bar
    survival = first_breach is None
    reaction = False
    reaction_bar: LifecycleBar | None = None
    if first_contact is not None:
        contact_index = rows.index(first_contact)
        breach_index = rows.index(first_breach) if first_breach is not None else len(rows)
        for bar in rows[contact_index + 1 : breach_index]:
            line = _geometry_value(lineage, bar.timestamp_ns)
            if role == "support":
                reaction = bar.high - _geometry_value(lineage, first_contact.timestamp_ns) >= first_contact.atr
            else:
                reaction = _geometry_value(lineage, first_contact.timestamp_ns) - bar.low >= first_contact.atr
            if reaction:
                reaction_bar = bar
                break
    structural_only = state_record["state"] in {
        "PERSISTED_DISTANT",
        "REVERSED_PERSISTED_DISTANT",
    }
    candidate_recovery_status = candidate_recovery_status or (
        "STRUCTURAL_ONLY" if structural_only else "ACTIONABLE"
    )
    candidate_recovery_mechanisms = list(
        gap["recovery_mechanisms"]
        if candidate_recovery_mechanisms is None
        else candidate_recovery_mechanisms
    )
    payload: dict[str, Any] = {
        "dataset_id": state_record["dataset_id"],
        "checkpoint_index": state_record["checkpoint_index"],
        "semantic_role": role,
        "lineage_id": lineage.lineage_id,
        "state": state_record["state"],
        "horizon_hours": horizon_hours,
        "gap_id": gap["gap_id"],
        "recovery_status": gap["recovery_status"],
        "gap_recovery_status": gap["recovery_status"],
        "gap_recovery_mechanisms": list(gap["recovery_mechanisms"]),
        "candidate_recovery_status": candidate_recovery_status,
        "recovery_mechanisms": candidate_recovery_mechanisms,
        "evaluable": True,
        "structural_only": structural_only,
    }
    if structural_only:
        initial_bar = next(
            (bar for bar in reversed(bars) if bar.timestamp_ns <= checkpoint.last_completed_timestamp_ns),
            None,
        )
        checkpoint_ns = _datetime_to_ns(
            _parse_iso(checkpoint.observed_at, field="checkpoint.observed_at")
        )
        initial_distance = (
            None
            if initial_bar is None
            else _distance_atr(lineage, initial_bar, line_timestamp_ns=checkpoint_ns)
        )
        minimum = min(distances) if distances else None
        payload.update(
            {
                "zone_contact_within_horizon": first_contact is not None,
                "minimum_future_distance_atr": minimum,
                "initial_distance_atr": initial_distance,
                "distance_contraction_atr": None if minimum is None or initial_distance is None else initial_distance - minimum,
                "crossed_into_at_most_8_atr": bool(minimum is not None and minimum <= 8.0),
            }
        )
        return payload
    payload.update(
        {
            "survival": survival,
            "zone_contact": first_contact is not None,
            "zone_contact_and_survival": first_contact is not None and survival,
            "post_contact_reaction": reaction,
            "first_contact_offset_bars": None if first_contact is None else rows.index(first_contact) + 1,
            "first_sustained_breach_offset_bars": None if first_breach is None else rows.index(first_breach) + 1,
            "contact_bar": None if first_contact is None else _bar_evidence(first_contact),
            "reaction_bar": None if reaction_bar is None else _bar_evidence(reaction_bar),
        }
    )
    return payload


def derive_future_outcomes(
    lifecycle: Mapping[str, Any],
    *,
    lineages: Iterable[LifecycleLineage | Mapping[str, Any]],
    checkpoints: Mapping[str, Iterable[LifecycleCheckpoint | Mapping[str, Any]]],
    bars: Mapping[str, Iterable[LifecycleBar | Mapping[str, Any]]],
    gap_records: Mapping[str, Iterable[Mapping[str, Any]]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Build outcomes only for candidate keys recovered by unique gaps."""
    lineage_by_id = {
        item.lineage_id: item for item in (_coerce_lineage(value) for value in lineages)
    }
    checkpoints_by_key = {
        (item.dataset_id, item.checkpoint_index): item
        for values in checkpoints.values()
        for item in (_coerce_checkpoint(value) for value in values)
    }
    bars_by_dataset = {
        dataset: tuple(_coerce_bar(value) for value in values)
        for dataset, values in bars.items()
    }
    gap_by_candidate: dict[tuple[str, int, str, str], Mapping[str, Any]] = {}
    if gap_records is None:
        # Backward-compatible diagnostic mode for direct unit callers. The
        # publication path always supplies explicit recovered gap records.
        for dataset, records in lifecycle["checkpoint_states"].items():
            for record in records:
                if record["current_semantic_role"] in ROLES:
                    synthetic_gap = {
                        "gap_id": deterministic_hash(
                            "trendline_v2_phase11r3a_direct_outcome_gap",
                            {
                                "dataset_id": dataset,
                                "checkpoint_index": record["checkpoint_index"],
                                "semantic_role": record["current_semantic_role"],
                            },
                        ),
                        "recovery_status": "ACTIONABLE",
                        "recovery_mechanisms": [],
                    }
                    key = (
                        dataset,
                        int(record["checkpoint_index"]),
                        record["current_semantic_role"],
                        record["lineage_id"],
                    )
                    gap_by_candidate[key] = synthetic_gap
    else:
        for dataset, records in gap_records.items():
            for gap in records:
                if gap["recovery_status"] == "NOT_RECOVERED":
                    continue
                for lineage_id in gap.get("candidate_lineage_ids", ()):
                    key = (
                        dataset,
                        int(gap["checkpoint_index"]),
                        gap["semantic_role"],
                        lineage_id,
                    )
                    if key in gap_by_candidate:
                        raise LifecycleStudyError("candidate contributes to multiple gap records")
                    gap_by_candidate[key] = gap
    results: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for dataset, records in lifecycle["checkpoint_states"].items():
        for record in records:
            if record["current_semantic_role"] is None:
                continue
            key = (
                dataset,
                int(record["checkpoint_index"]),
                record["current_semantic_role"],
                record["lineage_id"],
            )
            gap = gap_by_candidate.get(key)
            if gap is None:
                continue
            lineage = lineage_by_id[record["lineage_id"]]
            checkpoint = checkpoints_by_key[(dataset, record["checkpoint_index"])]
            candidate_recovery = next(
                (
                    item
                    for item in gap.get("candidate_recovery", ())
                    if item.get("lineage_id") == record["lineage_id"]
                ),
                None,
            )
            if candidate_recovery is None:
                candidate_status = (
                    "STRUCTURAL_ONLY"
                    if record["state"]
                    in {"PERSISTED_DISTANT", "REVERSED_PERSISTED_DISTANT"}
                    else "ACTIONABLE"
                )
                candidate_mechanisms = list(gap["recovery_mechanisms"])
            else:
                candidate_status = candidate_recovery["recovery_status"]
                candidate_mechanisms = list(
                    candidate_recovery["recovery_mechanisms"]
                )
            for horizon in HORIZONS_HOURS:
                results[dataset].append(
                    _evaluate_candidate_outcome(
                        record,
                        lineage,
                        checkpoint,
                        bars_by_dataset[dataset],
                        horizon,
                        gap=gap,
                        candidate_recovery_status=candidate_status,
                        candidate_recovery_mechanisms=candidate_mechanisms,
                    )
                )
    datasets = set(results) | set(bars_by_dataset) | set(checkpoints)
    return {dataset: list(results.get(dataset, ())) for dataset in sorted(datasets)}


def _source_snapshot() -> dict[str, Any]:
    """Hash only approved retained evidence and four BTC/ETH raw inputs."""
    phase11r1_inventory = tuple(
        item for item in _inventory(PHASE11R1_ROOT) if item["path"] != "manifest.json"
    )
    phase11r2_inventory = tuple(
        item for item in _inventory(PHASE11R2_ROOT) if item["path"] != "manifest.json"
    )
    if _inventory_sha256(phase11r1_inventory) != PHASE11R1_INVENTORY:
        raise LifecycleStudyError("Phase 11R.1 source inventory mismatch")
    if _inventory_sha256(phase11r2_inventory) != PHASE11R2_INVENTORY:
        raise LifecycleStudyError("Phase 11R.2 source inventory mismatch")
    return {
        "phase11r1_inventory": list(phase11r1_inventory),
        "phase11r2_inventory": list(phase11r2_inventory),
        "phase9c2_allowed_raw_inventory": list(phase11r2._allowed_raw_inventory()),
    }


def verify_retained_sources() -> dict[str, Any]:
    """Verify retained dependencies without opening SUI raw or temporal paths."""
    phase11r2._assert_phase11r1_dependency()
    phase11r2._assert_phase11r1_bundle()
    phase11r2._assert_phase9c2_binding()
    snapshot = _source_snapshot()
    if any("sui" in item["path"].lower() for item in snapshot["phase9c2_allowed_raw_inventory"]):
        raise LifecycleStudyError("forbidden SUI raw source in allowlist")
    return snapshot


def _source_audit(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    if dict(before) != dict(after):
        raise LifecycleStudyError("retained source mutation detected")
    payload = {
        "schema_version": "trendline_v2_phase11r3a_source_audit_v1",
        "phase11r1": {
            "root": str(PHASE11R1_ROOT),
            "contract_id": PHASE11R1_CONTRACT_ID,
            "decision_id": PHASE11R1_DECISION_ID,
            "manifest_id": PHASE11R1_MANIFEST_ID,
            "inventory_sha256": PHASE11R1_INVENTORY,
        },
        "phase11r2": {
            "root": str(PHASE11R2_ROOT),
            "contract_id": PHASE11R2_CONTRACT_ID,
            "decision_id": PHASE11R2_DECISION_ID,
            "manifest_id": PHASE11R2_MANIFEST_ID,
            "inventory_sha256": PHASE11R2_INVENTORY,
            "source_audit_id": PHASE11R2_SOURCE_AUDIT_ID,
        },
        "phase9c2": {
            "root": str(PHASE9C2_ROOT),
            "decision_id": PHASE9C2_DECISION_ID,
            "manifest_id": PHASE9C2_MANIFEST_ID,
            "source_inventory_sha256": PHASE9C2_SOURCE_INVENTORY,
            "allowed_raw_inventory_sha256": PHASE9C2_RAW_INVENTORY,
            "raw_sui_accessed": False,
        },
        "temporal_accessed": False,
        "holdout_accessed": False,
        "network_request_count": 0,
        "provider_execution_count": 0,
        "source_immutability": {
            "verified": True,
            "before_equals_after": True,
        },
        "source_before": dict(before),
        "source_after": dict(after),
    }
    return {**payload, "source_audit_id": deterministic_hash("trendline_v2_phase11r3a_source_audit", payload)}


def _phase11r2_gap_records(
    lifecycle: Mapping[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    """Map two provider-role gap rows to one lifecycle recovery row."""
    records_by_key: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for dataset in DATASETS:
        path = PHASE11R2_ROOT / "datasets" / dataset / "seed_funnel.json"
        payload = _load_json(path)
        for case in payload.get("coverage_cases", ()):
            key = (dataset, int(case["checkpoint_index"]), case["role"])
            records_by_key[key].append(case)
    states = defaultdict(list)
    for record in (
        state
        for dataset in DATASETS
        for state in lifecycle["checkpoint_states"].get(dataset, ())
    ):
        states[(record["dataset_id"], int(record["checkpoint_index"]))].append(record)
    lineages = {
        item["lineage_id"]: item for item in lifecycle.get("lineages", ())
    }
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (dataset, checkpoint_index, role), provider_cases in sorted(records_by_key.items()):
        if len(provider_cases) != 2:
            raise LifecycleStudyError("provider-role gap must map exactly two records")
        candidates: list[dict[str, Any]] = []
        active_candidate_ids: list[str] = []
        for lineage in lineages.values():
            if lineage["dataset_id"] != dataset:
                continue
            state = next(
                (
                    item
                    for item in states.get((dataset, checkpoint_index), ())
                    if item["lineage_id"] == lineage["lineage_id"]
                ),
                None,
            )
            if state is None:
                continue
            lifecycle_state = state["state"]
            current_role = state["current_semantic_role"]
            relevant_inactive = _is_relevant_inactive_lineage(
                lineage, state, gap_role=role
            )
            if current_role != role and not relevant_inactive:
                continue
            mechanisms = []
            if lifecycle_state in {"PERSISTED_ACTIVE_NEAR", "PERSISTED_DISTANT"}:
                mechanisms.append("DISTANCE_PERSISTENCE")
            if lifecycle_state in {"REVERSED_ACTIVE_NEAR", "REVERSED_PERSISTED_DISTANT"}:
                mechanisms.append("ROLE_REVERSAL")
            candidates.append(
                {
                    "lineage_id": lineage["lineage_id"] if current_role == role else None,
                    "state": lifecycle_state,
                    "mechanisms": mechanisms,
                    "prior_strict_lineage": lineage["first_strict_checkpoint"] < checkpoint_index,
                    "pending_without_contact": lifecycle_state == "REVERSAL_PENDING",
                }
            )
            if current_role == role:
                active_candidate_ids.append(lineage["lineage_id"])
        if not candidates:
            prior = any(
                lineage["dataset_id"] == dataset
                and lineage["first_strict_checkpoint"] < checkpoint_index
                and lineage["original_anchor_role"] == role
                for lineage in lineages.values()
            )
            candidates = [
                {
                    "state": "NOT_YET_STRICT_ACTIVE",
                    "mechanisms": [],
                    "prior_strict_lineage": prior,
                    "pending_without_contact": False,
                }
            ]
        recovery = aggregate_gap_recovery(candidates, provider_role_records=2)
        record = {
            "gap_id": deterministic_hash(
                "trendline_v2_phase11r3a_unique_gap",
                {
                    "dataset_id": dataset,
                    "checkpoint_index": checkpoint_index,
                    "semantic_role": role,
                },
            ),
            "dataset_id": dataset,
            "checkpoint_index": checkpoint_index,
            "semantic_role": role,
            "provider_role_record_count": len(provider_cases),
            "candidate_lineage_ids": sorted(
                active_candidate_ids
            ),
            "candidate_recovery": [
                {
                    "lineage_id": candidate["lineage_id"],
                    "state": candidate["state"],
                    "recovery_status": (
                        "ACTIONABLE"
                        if candidate["state"]
                        in {
                            "STRICT_ACTIVE_NEAR",
                            "PERSISTED_ACTIVE_NEAR",
                            "REVERSED_ACTIVE_NEAR",
                        }
                        else "STRUCTURAL_ONLY"
                    ),
                    "recovery_mechanisms": list(candidate["mechanisms"]),
                }
                for candidate in candidates
                if candidate.get("lineage_id") is not None
            ],
            **recovery,
        }
        result[dataset].append(record)
    if sum(len(values) for values in result.values()) != UNIQUE_GAP_COUNT:
        raise LifecycleStudyError("Phase 11R.2 unique gap count mismatch")
    return {dataset: values for dataset, values in sorted(result.items())}


def _policy_metrics(
    dataset: str,
    lifecycle: Mapping[str, Any],
    gap_records: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    states = list(lifecycle["checkpoint_states"].get(dataset, ()))
    cells = {
        (checkpoint_index, role): 0
        for checkpoint_index in range(1, CHECKPOINTS_PER_DATASET + 1)
        for role in ROLES
    }
    strict = 0
    actionable = 0
    structural = 0
    strict_keys: set[tuple[int, str, str]] = set()
    actionable_keys: set[tuple[int, str, str]] = set()
    structural_keys: set[tuple[int, str, str]] = set()
    for record in states:
        role = record["current_semantic_role"]
        if role is None:
            continue
        key = (record["checkpoint_index"], role)
        cells[key] = cells.get(key, 0) + 1
        observation_key = (int(record["checkpoint_index"]), role, record["lineage_id"])
        if record["state"] == "STRICT_ACTIVE_NEAR":
            strict += 1
            strict_keys.add(observation_key)
        if record["state"] in {"STRICT_ACTIVE_NEAR", "PERSISTED_ACTIVE_NEAR", "REVERSED_ACTIVE_NEAR"}:
            actionable += 1
            actionable_keys.add(observation_key)
        if record["state"] in {
            "STRICT_ACTIVE_NEAR",
            "PERSISTED_ACTIVE_NEAR",
            "REVERSED_ACTIVE_NEAR",
            "PERSISTED_DISTANT",
            "REVERSED_PERSISTED_DISTANT",
        }:
            structural += 1
            structural_keys.add(observation_key)
    values = list(cells.values())
    cell_count = len(cells)
    strict_cells = sum(value > 0 for key, value in cells.items() if any(
        record["checkpoint_index"] == key[0]
        and record["current_semantic_role"] == key[1]
        and record["state"] == "STRICT_ACTIVE_NEAR"
        for record in states
    ))
    actionable_cells = sum(
        any(
            record["checkpoint_index"] == key[0]
            and record["current_semantic_role"] == key[1]
            and record["state"] in {
                "STRICT_ACTIVE_NEAR",
                "PERSISTED_ACTIVE_NEAR",
                "REVERSED_ACTIVE_NEAR",
            }
            for record in states
        )
        for key in cells
    )
    structural_cells = sum(
        any(
            record["checkpoint_index"] == key[0]
            and record["current_semantic_role"] == key[1]
            and record["state"] in {
                "STRICT_ACTIVE_NEAR",
                "PERSISTED_ACTIVE_NEAR",
                "REVERSED_ACTIVE_NEAR",
                "PERSISTED_DISTANT",
                "REVERSED_PERSISTED_DISTANT",
            }
            for record in states
        )
        for key in cells
    )

    def _candidate_rate(field: str, horizon: int) -> dict[str, Any]:
        eligible = [
            outcome for outcome in outcomes
            if not outcome.get("structural_only", False)
            and outcome.get("evaluable") is True
            and outcome.get("horizon_hours") == horizon
        ]
        return outcome_rate(sum(bool(item.get(field)) for item in eligible), len(eligible))

    candidate_rates = {
        str(horizon): {
            "survival": _candidate_rate("survival", horizon),
            "contact": _candidate_rate("zone_contact", horizon),
            "reaction": _candidate_rate("post_contact_reaction", horizon),
        }
        for horizon in HORIZONS_HOURS
    }

    def _gap_rate(field: str, horizon: int) -> dict[str, Any]:
        grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for outcome in outcomes:
            if (
                outcome.get("structural_only", False)
                or outcome.get("horizon_hours") != horizon
                or outcome.get("evaluable") is not True
            ):
                continue
            grouped[outcome["gap_id"]].append(outcome)
        return outcome_rate(
            sum(any(bool(item.get(field)) for item in group) for group in grouped.values()),
            len(grouped),
        )

    return {
        "schema_version": "trendline_v2_phase11r3a_policy_metrics_v1",
        "dataset_id": dataset,
        "checkpoint_role_cell_count": cell_count,
        "strict_observation_count": strict,
        "expanded_actionable_observation_count": actionable,
        "expanded_structural_observation_count": structural,
        "strict_actionable_coverage": outcome_rate(strict_cells, cell_count),
        "expanded_actionable_coverage": outcome_rate(actionable_cells, cell_count),
        "expanded_structural_coverage": outcome_rate(structural_cells, cell_count),
        "strict_actionable_cell_count": strict_cells,
        "expanded_actionable_cell_count": actionable_cells,
        "expanded_structural_cell_count": structural_cells,
        "added_actionable_observation_count": len(actionable_keys - strict_keys),
        "added_structural_only_observation_count": len(structural_keys - actionable_keys),
        "candidate_inflation_ratio": None if not strict else structural / strict,
        "candidate_inflation_evaluable_count": strict,
        "maximum_lineages_per_checkpoint_role_cell": max(values, default=0),
        "median_lineages_per_checkpoint_role_cell": float(median(values)) if values else 0.0,
        "role_reversal_recovery_count": sum(
            "ROLE_REVERSAL" in record["recovery_mechanisms"]
            for record in gap_records
        ),
        "distance_persistence_recovery_count": sum(
            "DISTANCE_PERSISTENCE" in record["recovery_mechanisms"]
            for record in gap_records
        ),
        "reversal_pending_without_contact_count": sum(
            record.get("unrecovered_reason") == "REVERSAL_PENDING_NO_CONTACT"
            for record in gap_records
        ),
        "retired_lineage_recovery_count": sum(
            record.get("unrecovered_reason") == "ALL_RELEVANT_LINEAGES_RETIRED"
            for record in gap_records
        ),
        "gap_count": len(gap_records),
        "gap_status_counts": {
            status: sum(1 for record in gap_records if record["recovery_status"] == status)
            for status in RECOVERY_STATUSES
        },
        "outcome_rates": {
            "candidate_level": {
                **candidate_rates,
            },
            "unique_gap_level": {
                "48h_survival": _gap_rate("survival", 48),
                "96h_survival": _gap_rate("survival", 96),
                "96h_contact": _gap_rate("zone_contact", 96),
            },
        },
    }


def build_lifecycle_evidence(
    lifecycle_inputs: Mapping[str, Any],
    *,
    source_audit: Mapping[str, Any] | None = None,
    gap_records: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    lifecycle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic dataset members from a pure lifecycle replay."""
    if lifecycle is None:
        lifecycle = derive_lifecycle_evidence(
            lineages=lifecycle_inputs["lineages"],
            checkpoints=lifecycle_inputs["checkpoints"],
            bars=lifecycle_inputs["bars"],
        )
    outcomes = derive_future_outcomes(
        lifecycle,
        lineages=lifecycle_inputs["lineages"],
        checkpoints=lifecycle_inputs["checkpoints"],
        bars=lifecycle_inputs["bars"],
        gap_records=gap_records,
    )
    datasets: dict[str, dict[str, Any]] = {}
    for dataset in DATASETS:
        dataset_lineages = [
            lineage for lineage in lifecycle["lineages"] if lineage["dataset_id"] == dataset
        ]
        dataset_gaps = list((gap_records or {}).get(dataset, ()))
        checkpoint_values = lifecycle_inputs["checkpoints"].get(dataset, ())
        strict_expectations = lifecycle_inputs.get("strict_seed_expectations", {})
        strict_reconciliation = [
            {
                "checkpoint_index": checkpoint.checkpoint_index,
                "strict_lineage_ids": list(checkpoint.strict_lineage_ids),
                "expected_strict_lineage_ids": list(
                    strict_expectations.get(
                        (dataset, checkpoint.checkpoint_index),
                        checkpoint.strict_lineage_ids,
                    )
                ),
                "strict_identity_match": tuple(checkpoint.strict_lineage_ids)
                == tuple(
                    strict_expectations.get(
                        (dataset, checkpoint.checkpoint_index),
                        checkpoint.strict_lineage_ids,
                    )
                ),
                "strict_count_match": len(checkpoint.strict_lineage_ids)
                == len(
                    strict_expectations.get(
                        (dataset, checkpoint.checkpoint_index),
                        checkpoint.strict_lineage_ids,
                    )
                ),
            }
            for checkpoint in checkpoint_values
        ]
        if any(
            item["strict_identity_match"] is not True
            or item["strict_count_match"] is not True
            for item in strict_reconciliation
        ):
            raise LifecycleStudyError("retained R2 strict seed reconciliation mismatch")
        payloads = {
            "lineage_lifecycle": {
                "schema_version": "trendline_v2_phase11r3a_lineage_lifecycle_v1",
                "dataset_id": dataset,
                "lineages": dataset_lineages,
                "checkpoint_states": lifecycle["checkpoint_states"].get(dataset, []),
                "transitions": lifecycle["transitions"].get(dataset, []),
                "strict_seed_reconciliation": strict_reconciliation,
            },
            "gap_recovery": {
                "schema_version": "trendline_v2_phase11r3a_gap_recovery_v1",
                "dataset_id": dataset,
                "records": dataset_gaps,
            },
            "recovered_outcomes": {
                "schema_version": "trendline_v2_phase11r3a_recovered_outcomes_v1",
                "dataset_id": dataset,
                "outcomes": outcomes.get(dataset, []),
            },
        }
        payloads["policy_metrics"] = _policy_metrics(
            dataset,
            lifecycle,
            dataset_gaps,
            outcomes.get(dataset, []),
        )
        datasets[dataset] = {
            name: {**payload, "evidence_id": _dataset_evidence_id(payload)}
            for name, payload in payloads.items()
        }
    return {
        "lineages": lifecycle["lineages"],
        "datasets": datasets,
        "source_audit": dict(source_audit or {}),
    }


def _dataset_evidence_id(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "evidence_id"}
    return deterministic_hash("trendline_v2_phase11r3a_dataset_evidence", body)


def _csv_member_rows(evidence: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    lifecycle_rows: list[dict[str, Any]] = []
    gap_rows: list[dict[str, Any]] = []
    outcome_rows: list[dict[str, Any]] = []
    for dataset in DATASETS:
        dataset_payload = evidence["datasets"][dataset]
        for state in dataset_payload["lineage_lifecycle"]["checkpoint_states"]:
            lifecycle_rows.append(
                {
                    "dataset_id": dataset,
                    "checkpoint_index": state["checkpoint_index"],
                    "lineage_id": state["lineage_id"],
                    "state": state["state"],
                    "semantic_role": state["current_semantic_role"] or "",
                }
            )
        for gap in dataset_payload["gap_recovery"]["records"]:
            gap_rows.append(
                {
                    "dataset_id": dataset,
                    "checkpoint_index": gap["checkpoint_index"],
                    "semantic_role": gap["semantic_role"],
                    "recovery_status": gap["recovery_status"],
                    "recovery_mechanisms": ",".join(gap["recovery_mechanisms"]),
                    "unrecovered_reason": gap["unrecovered_reason"] or "",
                }
            )
        for outcome in dataset_payload["recovered_outcomes"]["outcomes"]:
            if outcome.get("structural_only"):
                outcome_rows.append(
                    {
                        "dataset_id": dataset,
                        "checkpoint_index": outcome["checkpoint_index"],
                        "semantic_role": outcome["semantic_role"],
                        "lineage_id": outcome["lineage_id"],
                        "horizon_hours": outcome["horizon_hours"],
                        "survival": "",
                        "zone_contact": str(
                            outcome["zone_contact_within_horizon"]
                        ).lower(),
                        "post_contact_reaction": "",
                    }
                )
            else:
                outcome_rows.append(
                    {
                        "dataset_id": dataset,
                        "checkpoint_index": outcome["checkpoint_index"],
                        "semantic_role": outcome["semantic_role"],
                        "lineage_id": outcome["lineage_id"],
                        "horizon_hours": outcome["horizon_hours"],
                        "survival": str(outcome["survival"]).lower(),
                        "zone_contact": str(outcome["zone_contact"]).lower(),
                        "post_contact_reaction": str(outcome["post_contact_reaction"]).lower(),
                    }
                )
    if not gap_rows:
        gap_rows.append(
            {
                "dataset_id": "",
                "checkpoint_index": 0,
                "semantic_role": "",
                "recovery_status": "",
                "recovery_mechanisms": "",
                "unrecovered_reason": "",
            }
        )
    if not outcome_rows:
        outcome_rows.append(
            {
                "dataset_id": "",
                "checkpoint_index": 0,
                "semantic_role": "",
                "lineage_id": "",
                "horizon_hours": 0,
                "survival": "",
                "zone_contact": "",
                "post_contact_reaction": "",
            }
        )
    return {
        "lifecycle_summary.csv": sorted(lifecycle_rows, key=lambda row: tuple(row.values())),
        "gap_recovery_summary.csv": sorted(gap_rows, key=lambda row: tuple(row.values())),
        "outcome_summary.csv": sorted(outcome_rows, key=lambda row: tuple(row.values())),
    }


def _csv_members(evidence: Mapping[str, Any]) -> dict[str, bytes]:
    return {name: _csv_bytes(rows) for name, rows in _csv_member_rows(evidence).items()}


def _aggregate_lifecycle_id(evidence: Mapping[str, Any], csv_members: Mapping[str, bytes]) -> str:
    return deterministic_hash(
        "trendline_v2_phase11r3a_lifecycle_evidence",
        {
            "datasets": {
                dataset: {
                    key: value
                    for key, value in evidence["datasets"][dataset].items()
                    if key != "evidence_id"
                }
                for dataset in DATASETS
            },
            "csv_sha256": {name: _sha256_bytes(value) for name, value in sorted(csv_members.items())},
        },
    )


def _aggregate_policy_metrics(evidence: Mapping[str, Any]) -> dict[str, Any]:
    metrics = [
        evidence["datasets"][dataset]["policy_metrics"]
        for dataset in DATASETS
    ]
    cell_count = sum(item["checkpoint_role_cell_count"] for item in metrics)
    strict = sum(item["strict_observation_count"] for item in metrics)
    actionable = sum(item["expanded_actionable_observation_count"] for item in metrics)
    structural = sum(item["expanded_structural_observation_count"] for item in metrics)
    strict_cells = sum(item["strict_actionable_cell_count"] for item in metrics)
    actionable_cells = sum(item["expanded_actionable_cell_count"] for item in metrics)
    structural_cells = sum(item["expanded_structural_cell_count"] for item in metrics)
    full_cell_counts = [
        sum(
            state["current_semantic_role"] == role
            and state["state"] in {
                "STRICT_ACTIVE_NEAR",
                "PERSISTED_ACTIVE_NEAR",
                "REVERSED_ACTIVE_NEAR",
                "PERSISTED_DISTANT",
                "REVERSED_PERSISTED_DISTANT",
            }
            for state in evidence["datasets"][dataset]["lineage_lifecycle"]["checkpoint_states"]
            if state["checkpoint_index"] == checkpoint_index
        )
        for dataset in DATASETS
        for checkpoint_index in range(1, CHECKPOINTS_PER_DATASET + 1)
        for role in ROLES
    ]
    gaps = [
        gap
        for dataset in DATASETS
        for gap in evidence["datasets"][dataset]["gap_recovery"]["records"]
    ]
    outcomes = [
        outcome
        for dataset in DATASETS
        for outcome in evidence["datasets"][dataset]["recovered_outcomes"]["outcomes"]
    ]

    def candidate_rate(field: str, horizon: int) -> dict[str, Any]:
        eligible = [
            outcome for outcome in outcomes
            if not outcome.get("structural_only", False)
            and outcome.get("evaluable") is True
            and outcome.get("horizon_hours") == horizon
        ]
        return outcome_rate(sum(bool(item.get(field)) for item in eligible), len(eligible))

    candidate_rates = {
        str(horizon): {
            "survival": candidate_rate("survival", horizon),
            "contact": candidate_rate("zone_contact", horizon),
            "reaction": candidate_rate("post_contact_reaction", horizon),
        }
        for horizon in HORIZONS_HOURS
    }

    if strict == 0:
        raise LifecycleStudyError("zero pooled strict observations block inflation")

    def gap_rate(field: str, horizon: int) -> dict[str, Any]:
        grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for outcome in outcomes:
            if (
                outcome.get("structural_only", False)
                or outcome.get("horizon_hours") != horizon
                or outcome.get("evaluable") is not True
            ):
                continue
            grouped[outcome["gap_id"]].append(outcome)
        return outcome_rate(
            sum(any(bool(item.get(field)) for item in group) for group in grouped.values()),
            len(grouped),
        )

    return {
        "coverage_denominator": cell_count,
        "strict_observation_count": strict,
        "expanded_actionable_observation_count": actionable,
        "expanded_structural_observation_count": structural,
        "strict_actionable_coverage": outcome_rate(strict_cells, cell_count),
        "expanded_actionable_coverage": outcome_rate(actionable_cells, cell_count),
        "expanded_structural_coverage": outcome_rate(structural_cells, cell_count),
        "added_actionable_observation_count": sum(
            item["added_actionable_observation_count"] for item in metrics
        ),
        "added_structural_only_observation_count": sum(
            item["added_structural_only_observation_count"] for item in metrics
        ),
        "candidate_inflation_ratio": structural / strict,
        "candidate_inflation_evaluable_count": strict,
        "maximum_lineages_per_checkpoint_role_cell": max(
            full_cell_counts,
            default=0,
        ),
        "median_lineages_per_checkpoint_role_cell": float(median(full_cell_counts))
        if full_cell_counts
        else 0.0,
        "gap_status_counts": {
            status: sum(1 for gap in gaps if gap["recovery_status"] == status)
            for status in RECOVERY_STATUSES
        },
        "role_reversal_recovery_count": sum(
            "ROLE_REVERSAL" in gap["recovery_mechanisms"] for gap in gaps
        ),
        "distance_persistence_recovery_count": sum(
            "DISTANCE_PERSISTENCE" in gap["recovery_mechanisms"] for gap in gaps
        ),
        "reversal_pending_without_contact_count": sum(
            gap.get("unrecovered_reason") == "REVERSAL_PENDING_NO_CONTACT"
            for gap in gaps
        ),
        "retired_lineage_recovery_count": sum(
            gap.get("unrecovered_reason") == "ALL_RELEVANT_LINEAGES_RETIRED"
            for gap in gaps
        ),
        "outcome_rates": {
            "candidate_level": {
                **candidate_rates,
            },
            "unique_gap_level": {
                "48h_survival": gap_rate("survival", 48),
                "96h_survival": gap_rate("survival", 96),
                "96h_contact": gap_rate("zone_contact", 96),
            },
        },
    }


def _decision_from_evidence(
    evidence: Mapping[str, Any],
    *,
    source_audit_id: str,
    csv_members: Mapping[str, bytes],
) -> dict[str, Any]:
    lifecycle_id = _aggregate_lifecycle_id(evidence, csv_members)
    records = [
        record
        for dataset in DATASETS
        for record in evidence["datasets"][dataset]["lineage_lifecycle"]["checkpoint_states"]
    ]
    transitions = [
        transition
        for dataset in DATASETS
        for transition in evidence["datasets"][dataset]["lineage_lifecycle"]["transitions"]
    ]
    gaps = [
        gap
        for dataset in DATASETS
        for gap in evidence["datasets"][dataset]["gap_recovery"]["records"]
    ]
    outcomes = [
        outcome
        for dataset in DATASETS
        for outcome in evidence["datasets"][dataset]["recovered_outcomes"]["outcomes"]
    ]
    unrecovered_gap_count = sum(
        1 for gap in gaps if gap["recovery_status"] == "NOT_RECOVERED"
    )
    unresolved_evidence_count = int(evidence.get("unresolved_evidence_count", 0))
    if unresolved_evidence_count < 0:
        raise LifecycleStudyError("unresolved evidence count cannot be negative")
    aggregate_metrics = _aggregate_policy_metrics(evidence)
    payload = {
        "schema_version": "trendline_v2_phase11r3a_decision_v1",
        "study_contract_id": CONTRACT_ID,
        "source_audit_id": source_audit_id,
        "lifecycle_evidence_id": lifecycle_id,
        "study_status": (
            "CAUSAL_SEED_LIFECYCLE_FEASIBILITY_COMPLETE"
            if unresolved_evidence_count == 0
            else "CAUSAL_SEED_LIFECYCLE_FEASIBILITY_INCOMPLETE"
        ),
        "unresolved_count": unresolved_evidence_count,
        "unresolved_evidence_count": unresolved_evidence_count,
        "unrecovered_gap_count": unrecovered_gap_count,
        "policy_metrics": aggregate_metrics,
        "counts": {
            "lineage_count": len(evidence["lineages"]),
            "checkpoint_state_count": len(records),
            "transition_count": len(transitions),
            "unique_gap_count": len(gaps),
            "outcome_count": len(outcomes),
            "actionable_recovery_count": sum(1 for gap in gaps if gap["recovery_status"] == "ACTIONABLE"),
            "structural_only_recovery_count": sum(1 for gap in gaps if gap["recovery_status"] == "STRUCTURAL_ONLY"),
            "unrecovered_gap_count": unrecovered_gap_count,
            "retired_lineage_count": len(
                {
                    record["lineage_id"]
                    for record in records
                    if record["state"] == "RETIRED"
                }
            ),
        },
        "execution": {
            "provider_execution_count": 0,
            "network_request_count": 0,
            "legacy_execution_count": 0,
            "holdout_accessed": False,
            "temporal_accessed": False,
        },
        "derivation_counts": {
            "validation_datasets": len(DATASETS),
            "checkpoints": CHECKPOINT_COUNT,
            "checkpoint_reconstructions": CHECKPOINT_COUNT * 2,
            "future_outcomes": len(outcomes),
        },
        "source_snapshot_ids": {
            "phase11r1_inventory": PHASE11R1_INVENTORY,
            "phase11r2_inventory": PHASE11R2_INVENTORY,
            "phase9c2_raw_inventory": PHASE9C2_RAW_INVENTORY,
        },
        "decision_flags": {
            "zero_forbidden_reads": True,
            "fixed_geometry": True,
            "source_snapshots_unchanged": True,
            "role_reversal_recovery_count": aggregate_metrics[
                "role_reversal_recovery_count"
            ],
            "distance_persistence_recovery_count": aggregate_metrics[
                "distance_persistence_recovery_count"
            ],
            "candidate_inflation_ratio": aggregate_metrics[
                "candidate_inflation_ratio"
            ],
            "reversal_pending_without_contact_count": aggregate_metrics[
                "reversal_pending_without_contact_count"
            ],
            "retired_lineage_recovery_count": aggregate_metrics[
                "retired_lineage_recovery_count"
            ],
            "recovered_actionable_gap_48h_survival_rate": aggregate_metrics[
                "outcome_rates"
            ]["unique_gap_level"]["48h_survival"],
            "recovered_actionable_gap_96h_survival_rate": aggregate_metrics[
                "outcome_rates"
            ]["unique_gap_level"]["96h_survival"],
            "recovered_actionable_gap_96h_contact_rate": aggregate_metrics[
                "outcome_rates"
            ]["unique_gap_level"]["96h_contact"],
        },
    }
    return {**payload, "decision_id": deterministic_hash("trendline_v2_phase11r3a_decision", payload)}


def _study_contract() -> dict[str, Any]:
    triplet = contract_triplet()
    return {
        "schema_version": "trendline_v2_phase11r3a_study_contract_v1",
        "contract_id": triplet["contract_id"],
        "contract_json_sha256": triplet["canonical_json_sha256"],
        "contract_json_byte_length": triplet["canonical_json_byte_length"],
        "payload": triplet["payload"],
    }


def _manifest_for_staging(
    staging: Path,
    *,
    decision: Mapping[str, Any],
    source_audit_id: str,
    lifecycle_evidence_id: str,
) -> dict[str, Any]:
    actual = _inventory(staging)
    members = tuple(item for item in actual if item["path"] != "manifest.json")
    expected = tuple(sorted(path for path in EXPECTED_ARTIFACT_PATHS if path != "manifest.json"))
    if tuple(item["path"] for item in members) != expected:
        raise LifecycleStudyError("published artifact path set mismatch")
    payload = {
        "schema_version": "trendline_v2_phase11r3a_manifest_v1",
        "study_contract_id": CONTRACT_ID,
        "source_audit_id": source_audit_id,
        "lifecycle_evidence_id": lifecycle_evidence_id,
        "decision_id": decision["decision_id"],
        "member_count": len(members),
        "members": list(members),
        "output_inventory_sha256": _inventory_sha256(members),
    }
    return {
        **payload,
        "manifest_id": deterministic_hash("trendline_v2_phase11r3a_manifest", payload),
    }


def _derive_lifecycle_study_evidence(
    *,
    source_before: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive canonical evidence from retained sources, never from output files."""
    before = dict(source_before or verify_retained_sources())
    scope = phase11r2._load_allowed_scope()
    inputs_first = build_lifecycle_inputs(scope)
    inputs_second = build_lifecycle_inputs(scope)
    strict_expectations = _retained_r2_strict_seed_expectations(scope)
    inputs_first = {**inputs_first, "strict_seed_expectations": strict_expectations}
    inputs_second = {**inputs_second, "strict_seed_expectations": strict_expectations}
    if _input_fingerprint(inputs_first) != _input_fingerprint(inputs_second):
        raise LifecycleStudyError("checkpoint reconstruction is not deterministic")
    lifecycle = derive_lifecycle_evidence(
        lineages=inputs_first["lineages"],
        checkpoints=inputs_first["checkpoints"],
        bars=inputs_first["bars"],
    )
    gaps = _phase11r2_gap_records(lifecycle)
    after = verify_retained_sources()
    source_audit = _source_audit(before, after)
    return build_lifecycle_evidence(
        inputs_first,
        lifecycle=lifecycle,
        source_audit=source_audit,
        gap_records=gaps,
    )


def _derived_member_bytes(evidence: Mapping[str, Any]) -> dict[str, bytes]:
    """Return exact non-manifest bytes expected from canonical evidence."""
    members = {
        "study_contract.json": _canonical_bytes(_study_contract()),
        "source_audit.json": _canonical_bytes(evidence["source_audit"]),
    }
    for dataset in DATASETS:
        for member, payload in evidence["datasets"][dataset].items():
            members[f"datasets/{dataset}/{member}.json"] = _canonical_bytes(payload)
    csv_members = _csv_members(evidence)
    members.update(csv_members)
    decision = _decision_from_evidence(
        evidence,
        source_audit_id=evidence["source_audit"]["source_audit_id"],
        csv_members=csv_members,
    )
    members["decision.json"] = _canonical_bytes(decision)
    expected_paths = tuple(sorted(path for path in EXPECTED_ARTIFACT_PATHS if path != "manifest.json"))
    if tuple(sorted(members)) != expected_paths:
        raise LifecycleStudyError("derived evidence path set mismatch")
    return members


def _write_bundle_without_manifest(staging: Path, evidence: Mapping[str, Any]) -> dict[str, Any]:
    members = _derived_member_bytes(evidence)
    for relative, value in members.items():
        path = staging / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    decision = _load_json(staging / "decision.json")
    csv_members = {
        name: members[name]
        for name in ("lifecycle_summary.csv", "gap_recovery_summary.csv", "outcome_summary.csv")
    }
    return {
        "decision": decision,
        "csv_members": csv_members,
        "lifecycle_evidence_id": decision["lifecycle_evidence_id"],
    }


def _publish_lifecycle_evidence(
    evidence: Mapping[str, Any],
    *,
    output_root: Path,
) -> dict[str, Any]:
    """Publish synthetic fixture evidence for tests only."""
    if output_root.exists():
        raise LifecycleStudyError("existing lifecycle-study output root refused")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_root.parent)
    )
    try:
        written = _write_bundle_without_manifest(staging, evidence)
        manifest = _manifest_for_staging(
            staging,
            decision=written["decision"],
            source_audit_id=evidence["source_audit"]["source_audit_id"],
            lifecycle_evidence_id=written["lifecycle_evidence_id"],
        )
        _write_json(staging / "manifest.json", manifest)
        _verify_synthetic_lifecycle_bundle_for_tests(staging)
        if output_root.exists():
            raise LifecycleStudyError("output root appeared during publication")
        os.replace(staging, output_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return _verify_synthetic_lifecycle_bundle_for_tests(output_root)


def _input_fingerprint(inputs: Mapping[str, Any]) -> str:
    return deterministic_hash(
        "trendline_v2_phase11r3a_lifecycle_input_fingerprint",
        {
            "lineages": inputs["lineages"],
            "checkpoints": {
                dataset: [
                    {
                        "dataset_id": checkpoint.dataset_id,
                        "checkpoint_index": checkpoint.checkpoint_index,
                        "observed_at": checkpoint.observed_at,
                        "source_input_identity": checkpoint.source_input_identity,
                        "strict_lineage_ids": list(checkpoint.strict_lineage_ids),
                        "last_completed_timestamp_ns": checkpoint.last_completed_timestamp_ns,
                    }
                    for checkpoint in checkpoints
                ]
                for dataset, checkpoints in sorted(inputs["checkpoints"].items())
            },
            "bar_counts": {
                dataset: len(values) for dataset, values in sorted(inputs["bars"].items())
            },
            "strict_seed_expectations": {
                f"{dataset}:{checkpoint_index}": list(expected_ids)
                for (dataset, checkpoint_index), expected_ids in sorted(
                    inputs.get("strict_seed_expectations", {}).items()
                )
            },
        },
    )


def run_lifecycle_study(*, output_root: str | Path = OUTPUT_ROOT) -> dict[str, Any]:
    """Run one bounded offline validation study and publish atomically."""
    root = Path(output_root)
    _execution_guard(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{root.name}.", dir=root.parent))
    try:
        source_before = verify_retained_sources()
        evidence = _derive_lifecycle_study_evidence(source_before=source_before)
        written = _write_bundle_without_manifest(staging, evidence)
        if dict(source_before) != dict(verify_retained_sources()):
            raise LifecycleStudyError("source changed before manifest publication")
        manifest = _manifest_for_staging(
            staging,
            decision=written["decision"],
            source_audit_id=evidence["source_audit"]["source_audit_id"],
            lifecycle_evidence_id=written["lifecycle_evidence_id"],
        )
        _write_json(staging / "manifest.json", manifest)
        _verify_lifecycle_bundle(staging, expected_evidence=evidence)
        if dict(source_before) != dict(verify_retained_sources()):
            raise LifecycleStudyError("source changed after manifest publication")
        if root.exists():
            raise LifecycleStudyError("output root appeared during study")
        os.replace(staging, root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return _verify_lifecycle_bundle(root, expected_evidence=evidence)


def _validate_dataset_payload(
    dataset: str,
    payloads: Mapping[str, Mapping[str, Any]],
    *,
    expected_strict_lineage_ids: Mapping[int, Sequence[str]] | None = None,
) -> None:
    lifecycle = payloads["lineage_lifecycle"]
    lineages = lifecycle.get("lineages")
    if not isinstance(lineages, list):
        raise LifecycleStudyError("lineage payload must contain list")
    lineage_by_id = {item["lineage_id"]: item for item in lineages}
    if len(lineage_by_id) != len(lineages):
        raise LifecycleStudyError("duplicate lineage in dataset payload")
    for lineage in lineages:
        expected_lineage_id = lineage_identity(
            asset=lineage["asset"],
            timeframe=lineage["timeframe"],
            original_anchor_role=lineage["original_anchor_role"],
            first_anchor_pivot_id=lineage["first_anchor_pivot_id"],
            second_anchor_pivot_id=lineage["second_anchor_pivot_id"],
        )
        if lineage["lineage_id"] != expected_lineage_id:
            raise LifecycleStudyError("lineage anchor identity mismatch")
        geometry = phase11r1.LineGeometry.from_dict(lineage["geometry"])
        if (
            _iso(geometry.start_time) != lineage["first_anchor_timestamp"]
            or _iso(geometry.end_time) != lineage["second_anchor_timestamp"]
            or geometry.start_price != lineage["first_anchor_price"]
            or geometry.end_price != lineage["second_anchor_price"]
        ):
            raise LifecycleStudyError("lineage geometry/anchor mismatch")
    for name, payload in payloads.items():
        if payload.get("dataset_id") != dataset:
            raise LifecycleStudyError(f"dataset identity mismatch in {name}")
        if payload.get("evidence_id") != _dataset_evidence_id(payload):
            raise LifecycleStudyError(f"dataset evidence identity mismatch in {name}")
    strict_reconciliation = lifecycle.get("strict_seed_reconciliation")
    if not isinstance(strict_reconciliation, list):
        raise LifecycleStudyError("strict seed reconciliation is missing")
    if expected_strict_lineage_ids is not None:
        reconciliation_keys = {
            int(item.get("checkpoint_index")) for item in strict_reconciliation
        }
        if reconciliation_keys != set(expected_strict_lineage_ids):
            raise LifecycleStudyError("strict seed source reconciliation is incomplete")
    for item in strict_reconciliation:
        actual_ids = item.get("strict_lineage_ids")
        expected_ids = item.get("expected_strict_lineage_ids")
        if (
            not isinstance(actual_ids, list)
            or not isinstance(expected_ids, list)
        ):
            raise LifecycleStudyError("strict seed reconciliation mismatch")
        if expected_strict_lineage_ids is not None:
            checkpoint_index = int(item.get("checkpoint_index"))
            expected_from_source = tuple(
                expected_strict_lineage_ids.get(checkpoint_index, ())
            )
            if (
                tuple(expected_ids) != expected_from_source
                or tuple(actual_ids) != expected_from_source
            ):
                raise LifecycleStudyError("strict seed source reconciliation mismatch")
        if (
            actual_ids != sorted(set(actual_ids))
            or actual_ids != expected_ids
            or item.get("strict_identity_match") is not True
            or item.get("strict_count_match") is not True
        ):
            raise LifecycleStudyError("strict seed reconciliation mismatch")
        if any(lineage_id not in lineage_by_id for lineage_id in actual_ids):
            raise LifecycleStudyError("strict seed references unknown lineage")
    for state in lifecycle.get("checkpoint_states", ()):
        lineage = lineage_by_id.get(state["lineage_id"])
        if lineage is None or state["state"] not in STATES:
            raise LifecycleStudyError("invalid lifecycle state binding")
        if int(state["checkpoint_index"]) < int(lineage["first_strict_checkpoint"]):
            raise LifecycleStudyError("future lineage appears before strict activation")
        if state["fixed_geometry"] != lineage["geometry"]:
            raise LifecycleStudyError("lifecycle geometry was rewritten")
        if "distance_atr" in state:
            raise LifecycleStudyError("ambiguous lifecycle distance field")
        expected_role = semantic_role_for_state(
            state["state"], lineage["original_anchor_role"]
        )
        if state["current_semantic_role"] != expected_role:
            raise LifecycleStudyError("lifecycle semantic role mismatch")
        retirement_reason = state.get("retirement_reason")
        if state["state"] == "RETIRED":
            if retirement_reason not in RETIREMENT_REASONS:
                raise LifecycleStudyError("invalid lifecycle retirement reason")
        elif retirement_reason is not None:
            raise LifecycleStudyError("active lifecycle state has retirement reason")
        if "checkpoint_distance_atr" not in state or "event_projection" not in state:
            raise LifecycleStudyError("lifecycle timestamp evidence is incomplete")
        if state["event_projection"] is not None or state.get("event_distance_atr") is not None:
            raise LifecycleStudyError("checkpoint state contains event timestamp evidence")
    for transition in lifecycle.get("transitions", ()):
        lineage = lineage_by_id.get(transition["lineage_id"])
        if lineage is None or transition["current_state"] not in STATES:
            raise LifecycleStudyError("invalid transition lineage")
        if transition["fixed_geometry"] != lineage["geometry"]:
            raise LifecycleStudyError("transition geometry was rewritten")
        if "distance_atr" in transition:
            raise LifecycleStudyError("ambiguous transition distance field")
        if transition["trigger"] not in TRANSITION_TRIGGERS:
            raise LifecycleStudyError("unknown transition trigger")
        if transition["original_anchor_role"] != lineage["original_anchor_role"]:
            raise LifecycleStudyError("transition role binding mismatch")
        if transition["current_semantic_role"] != semantic_role_for_state(
            transition["current_state"], lineage["original_anchor_role"]
        ):
            raise LifecycleStudyError("transition semantic role mismatch")
        _parse_iso(transition["effective_at"], field="transition.effective_at")
        _parse_iso(
            transition["checkpoint_observed_at"],
            field="transition.checkpoint_observed_at",
        )
        checkpoint_triggers = {
            "strict_seed_confirmed",
            "distance_exceeded_8_atr",
            "distance_returned_at_most_8_atr",
            "reversed_distance_exceeded_8_atr",
            "reversed_distance_returned_at_most_8_atr",
        }
        if "event_projection" not in transition or "event_distance_atr" not in transition:
            raise LifecycleStudyError("transition timestamp evidence is incomplete")
        if transition["trigger"] in checkpoint_triggers:
            if (
                transition["event_projection"] is not None
                or transition["event_distance_atr"] is not None
                or transition.get("projection_at_checkpoint") is None
                or transition.get("checkpoint_distance_atr") is None
            ):
                raise LifecycleStudyError("checkpoint transition timestamp evidence mismatch")
        elif (
            transition.get("projection_at_checkpoint") is None
            or transition.get("checkpoint_distance_atr") is None
        ):
            raise LifecycleStudyError("bar transition checkpoint evidence is missing")
        allowed_triggers = _transition_triggers(
            transition["previous_state"], transition["current_state"]
        )
        if transition["trigger"] not in allowed_triggers:
            raise LifecycleStudyError("transition trigger does not match state edge")
        retirement_reason = transition.get("retirement_reason")
        if transition["current_state"] == "RETIRED":
            if retirement_reason not in RETIREMENT_REASONS:
                raise LifecycleStudyError("invalid retirement reason")
            if retirement_reason != _retirement_reason_for_trigger(transition["trigger"]):
                raise LifecycleStudyError("retirement reason does not match trigger")
        elif retirement_reason is not None:
            raise LifecycleStudyError("non-retired transition has retirement reason")
        if not transition_allowed(
            transition["previous_state"],
            transition["current_state"],
            reversal_contact_confirmed=transition["trigger"] == "reversal_contact_confirmed_after_breach",
        ):
            raise LifecycleStudyError("illegal transition in artifact")
    checkpoint_state_by_key = {}
    for state in lifecycle.get("checkpoint_states", ()):
        state_key = (state["lineage_id"], int(state["checkpoint_index"]))
        if state_key in checkpoint_state_by_key:
            raise LifecycleStudyError("duplicate lifecycle checkpoint state")
        checkpoint_state_by_key[state_key] = state
    for gap in payloads["gap_recovery"].get("records", ()):
        expected_gap_id = deterministic_hash(
            "trendline_v2_phase11r3a_unique_gap",
            {
                "dataset_id": dataset,
                "checkpoint_index": gap.get("checkpoint_index"),
                "semantic_role": gap.get("semantic_role"),
            },
        )
        if gap.get("gap_id") != expected_gap_id:
            raise LifecycleStudyError("gap identity mismatch")
        if (
            gap.get("dataset_id") != dataset
            or gap.get("provider_role_record_count") != 2
            or gap.get("semantic_role") not in ROLES
        ):
            raise LifecycleStudyError("gap binding mismatch")
        if gap["recovery_status"] not in RECOVERY_STATUSES:
            raise LifecycleStudyError("invalid recovery status")
        if any(mechanism not in RECOVERY_MECHANISMS for mechanism in gap["recovery_mechanisms"]):
            raise LifecycleStudyError("invalid recovery mechanism")
        if list(gap["recovery_mechanisms"]) != [
            mechanism
            for mechanism in RECOVERY_MECHANISMS
            if mechanism in gap["recovery_mechanisms"]
        ]:
            raise LifecycleStudyError("gap mechanisms are not canonical")
        candidate_ids = gap.get("candidate_lineage_ids")
        if not isinstance(candidate_ids, list) or candidate_ids != sorted(set(candidate_ids)):
            raise LifecycleStudyError("gap candidate lineage IDs are not canonical")
        if any(candidate_id not in lineage_by_id for candidate_id in candidate_ids):
            raise LifecycleStudyError("gap references unknown lineage")
        candidate_recovery = gap.get("candidate_recovery")
        candidate_recovery_by_id: dict[str, Mapping[str, Any]] = {}
        if candidate_recovery is not None:
            if not isinstance(candidate_recovery, list):
                raise LifecycleStudyError("candidate recovery evidence is invalid")
            for candidate in candidate_recovery:
                candidate_id = candidate.get("lineage_id")
                candidate_state = candidate.get("state")
                state = checkpoint_state_by_key.get(
                    (candidate_id, int(gap["checkpoint_index"]))
                )
                expected_candidate_status = {
                    "STRICT_ACTIVE_NEAR": "ACTIONABLE",
                    "PERSISTED_ACTIVE_NEAR": "ACTIONABLE",
                    "REVERSED_ACTIVE_NEAR": "ACTIONABLE",
                    "PERSISTED_DISTANT": "STRUCTURAL_ONLY",
                    "REVERSED_PERSISTED_DISTANT": "STRUCTURAL_ONLY",
                }.get(candidate_state)
                mechanisms = candidate.get("recovery_mechanisms")
                if (
                    not isinstance(candidate_id, str)
                    or candidate_id in candidate_recovery_by_id
                    or candidate_id not in candidate_ids
                    or state is None
                    or candidate_state != state["state"]
                    or candidate.get("recovery_status") != expected_candidate_status
                    or not isinstance(mechanisms, list)
                    or mechanisms != [
                        mechanism
                        for mechanism in RECOVERY_MECHANISMS
                        if mechanism in mechanisms
                    ]
                    or any(
                        mechanism not in RECOVERY_MECHANISMS
                        for mechanism in mechanisms or ()
                    )
                ):
                    raise LifecycleStudyError("candidate recovery evidence is invalid")
                candidate_recovery_by_id[candidate_id] = candidate
            if set(candidate_recovery_by_id) != set(candidate_ids):
                raise LifecycleStudyError("candidate recovery evidence is incomplete")
        if gap["recovery_status"] == "NOT_RECOVERED":
            if gap.get("unrecovered_reason") not in UNRECOVERED_REASONS:
                raise LifecycleStudyError("invalid unrecovered reason")
        elif gap.get("unrecovered_reason") is not None:
            raise LifecycleStudyError("recovered gap has unrecovered reason")
    gap_records = payloads["gap_recovery"].get("records", ())
    outcomes = payloads["recovered_outcomes"].get("outcomes", ())
    gap_by_id = {gap["gap_id"]: gap for gap in gap_records}
    seen_outcome_keys: set[tuple[str, int, str, str, int]] = set()
    for outcome in outcomes:
        if outcome["semantic_role"] not in ROLES or outcome["horizon_hours"] not in HORIZONS_HOURS:
            raise LifecycleStudyError("invalid future outcome")
        gap = gap_by_id.get(outcome.get("gap_id"))
        if gap is None or outcome["lineage_id"] not in gap.get("candidate_lineage_ids", ()):
            raise LifecycleStudyError("future outcome is not bound to a recovered gap")
        outcome_key = (
            dataset,
            int(outcome["checkpoint_index"]),
            outcome["semantic_role"],
            outcome["lineage_id"],
            int(outcome["horizon_hours"]),
        )
        if outcome_key in seen_outcome_keys:
            raise LifecycleStudyError("duplicate future outcome key")
        seen_outcome_keys.add(outcome_key)
        lineage = lineage_by_id.get(outcome["lineage_id"])
        state = next(
            (
                item
                for item in lifecycle.get("checkpoint_states", ())
                if item["lineage_id"] == outcome["lineage_id"]
                and int(item["checkpoint_index"]) == int(outcome["checkpoint_index"])
            ),
            None,
        )
        if lineage is None or state is None:
            raise LifecycleStudyError("future outcome lineage/state binding mismatch")
        if outcome["state"] != state["state"] or outcome["semantic_role"] != state["current_semantic_role"]:
            raise LifecycleStudyError("future outcome lifecycle binding mismatch")
        if list(outcome.get("gap_recovery_mechanisms", ())) != list(gap["recovery_mechanisms"]):
            raise LifecycleStudyError("future outcome gap recovery binding mismatch")
        candidate_recovery = next(
            (
                item
                for item in gap.get("candidate_recovery", ())
                if item.get("lineage_id") == outcome["lineage_id"]
            ),
            None,
        )
        if candidate_recovery is not None:
            if outcome.get("candidate_recovery_status") != candidate_recovery["recovery_status"]:
                raise LifecycleStudyError("future outcome candidate status mismatch")
            if list(outcome.get("recovery_mechanisms", ())) != list(
                candidate_recovery["recovery_mechanisms"]
            ):
                raise LifecycleStudyError("future outcome candidate recovery binding mismatch")
        if outcome["semantic_role"] != gap["semantic_role"]:
            raise LifecycleStudyError("future outcome role binding mismatch")
        if outcome.get("structural_only"):
            if gap["recovery_status"] not in {"ACTIONABLE", "STRUCTURAL_ONLY"}:
                raise LifecycleStudyError("structural outcome status mismatch")
            if outcome.get("candidate_recovery_status") != "STRUCTURAL_ONLY":
                raise LifecycleStudyError("structural candidate status mismatch")
            if any(field in outcome for field in (
                "survival", "zone_contact", "zone_contact_and_survival",
                "post_contact_reaction", "first_contact_offset_bars",
                "first_sustained_breach_offset_bars",
            )):
                raise LifecycleStudyError("structural outcome contains actionable evidence")
            continue
        if gap["recovery_status"] != "ACTIONABLE":
            raise LifecycleStudyError("actionable outcome status mismatch")
        if outcome.get("candidate_recovery_status") != "ACTIONABLE":
            raise LifecycleStudyError("actionable candidate status mismatch")
        if outcome["zone_contact_and_survival"] != (
            outcome["zone_contact"] and outcome["survival"]
        ):
            raise LifecycleStudyError("future outcome contact/survival mismatch")
        if outcome["post_contact_reaction"] and not outcome["zone_contact"]:
            raise LifecycleStudyError("future reaction requires prior contact")
        contact_offset = outcome["first_contact_offset_bars"]
        breach_offset = outcome["first_sustained_breach_offset_bars"]
        if contact_offset is not None and contact_offset < 1:
            raise LifecycleStudyError("future contact offset must be positive")
        if breach_offset is not None and breach_offset < 1:
            raise LifecycleStudyError("future breach offset must be positive")
        if contact_offset is not None and breach_offset is not None and contact_offset >= breach_offset:
            raise LifecycleStudyError("future reaction chronology is invalid")
    expected_metrics = _policy_metrics(
        dataset,
        {"checkpoint_states": {dataset: lifecycle.get("checkpoint_states", ())}},
        gap_records,
        outcomes,
    )
    expected_metrics_payload = {
        "schema_version": "trendline_v2_phase11r3a_policy_metrics_v1",
        **expected_metrics,
    }
    expected_metrics_payload["evidence_id"] = _dataset_evidence_id(expected_metrics_payload)
    if payloads["policy_metrics"] != expected_metrics_payload:
        raise LifecycleStudyError("policy metrics semantic rederivation mismatch")


def _verify_lifecycle_bundle(
    root: Path,
    *,
    expected_evidence: Mapping[str, Any] | None = None,
    allow_synthetic: bool = False,
) -> dict[str, Any]:
    actual = _inventory(root)
    expected = tuple(sorted(EXPECTED_ARTIFACT_PATHS))
    if tuple(item["path"] for item in actual) != expected:
        raise LifecycleStudyError("lifecycle artifact inventory mismatch")
    contract = _load_json(root / "study_contract.json")
    if contract.get("contract_id") != CONTRACT_ID:
        raise LifecycleStudyError("study contract identity mismatch")
    validate_contract_identity(contract.get("payload", {}))
    source_audit = _load_json(root / "source_audit.json")
    expected_source_audit_fields = {
        "schema_version",
        "phase11r1",
        "phase11r2",
        "phase9c2",
        "temporal_accessed",
        "holdout_accessed",
        "network_request_count",
        "provider_execution_count",
        "source_immutability",
        "source_before",
        "source_after",
        "source_audit_id",
    }
    if set(source_audit) != expected_source_audit_fields:
        raise LifecycleStudyError("source audit fields are not canonical")
    if source_audit.get("source_audit_id") != deterministic_hash(
        "trendline_v2_phase11r3a_source_audit",
        {key: value for key, value in source_audit.items() if key != "source_audit_id"},
    ):
        raise LifecycleStudyError("source audit identity mismatch")
    if source_audit.get("temporal_accessed") or source_audit.get("holdout_accessed"):
        raise LifecycleStudyError("forbidden holdout or temporal access recorded")
    if source_audit.get("source_before") != source_audit.get("source_after"):
        raise LifecycleStudyError("source audit contains mutated source snapshots")
    if source_audit.get("source_immutability", {}).get("verified") is not True:
        raise LifecycleStudyError("source immutability was not verified")
    if source_audit.get("phase11r1", {}).get("inventory_sha256") != PHASE11R1_INVENTORY:
        raise LifecycleStudyError("Phase 11R.1 source identity mismatch")
    if source_audit.get("phase11r2", {}).get("inventory_sha256") != PHASE11R2_INVENTORY:
        raise LifecycleStudyError("Phase 11R.2 source identity mismatch")
    if source_audit.get("phase9c2", {}).get("allowed_raw_inventory_sha256") != PHASE9C2_RAW_INVENTORY:
        raise LifecycleStudyError("Phase 9C.2 raw source identity mismatch")
    if source_audit.get("phase11r1", {}).get("decision_id") != PHASE11R1_DECISION_ID:
        raise LifecycleStudyError("Phase 11R.1 decision identity mismatch")
    if source_audit.get("phase11r2", {}).get("decision_id") != PHASE11R2_DECISION_ID:
        raise LifecycleStudyError("Phase 11R.2 decision identity mismatch")
    if source_audit.get("phase9c2", {}).get("decision_id") != PHASE9C2_DECISION_ID:
        raise LifecycleStudyError("Phase 9C.2 decision identity mismatch")
    source_snapshot_fields = {
        "phase11r1_inventory",
        "phase11r2_inventory",
        "phase9c2_allowed_raw_inventory",
    }
    synthetic_snapshot_fields = {"synthetic"}

    def source_snapshot_mode(value: Any) -> str:
        if not isinstance(value, Mapping):
            raise LifecycleStudyError("source snapshot structure is invalid")
        keys = set(value)
        if keys == synthetic_snapshot_fields and value.get("synthetic") is True:
            if not allow_synthetic:
                raise LifecycleStudyError(
                    "synthetic source marker is not permitted in canonical verification"
                )
            return "synthetic"
        if keys != source_snapshot_fields:
            raise LifecycleStudyError("source snapshot fields are not canonical")
        if any(not isinstance(value[field], list) for field in source_snapshot_fields):
            raise LifecycleStudyError("source snapshot inventory fields are invalid")
        return "canonical"

    before_mode = source_snapshot_mode(source_audit.get("source_before"))
    after_mode = source_snapshot_mode(source_audit.get("source_after"))
    if before_mode != after_mode:
        raise LifecycleStudyError("source snapshot modes do not match")
    if before_mode == "canonical":
        if _source_snapshot() != source_audit["source_before"]:
            raise LifecycleStudyError("live retained source snapshot mismatch")
        if expected_evidence is None:
            expected_evidence = _derive_lifecycle_study_evidence(
                source_before=source_audit["source_before"]
            )
    if expected_evidence is not None:
        expected_members = _derived_member_bytes(expected_evidence)
        for relative, expected_bytes in expected_members.items():
            actual_bytes = (root / relative).read_bytes()
            if actual_bytes != expected_bytes:
                raise LifecycleStudyError(
                    f"source-backed lifecycle rederivation mismatch: {relative}"
                )
    datasets: dict[str, dict[str, Any]] = {}
    for dataset in DATASETS:
        payloads: dict[str, Mapping[str, Any]] = {}
        for member in (
            "lineage_lifecycle",
            "gap_recovery",
            "recovered_outcomes",
            "policy_metrics",
        ):
            payloads[member] = _load_json(root / "datasets" / dataset / f"{member}.json")
        expected_strict = None
        if expected_evidence is not None:
            expected_strict = {
                int(item["checkpoint_index"]): tuple(
                    item["expected_strict_lineage_ids"]
                )
                for item in expected_evidence["datasets"][dataset][
                    "lineage_lifecycle"
                ]["strict_seed_reconciliation"]
            }
        _validate_dataset_payload(
            dataset,
            payloads,
            expected_strict_lineage_ids=expected_strict,
        )
        datasets[dataset] = dict(payloads)
    evidence = {
        "lineages": [
            lineage
            for dataset in DATASETS
            for lineage in datasets[dataset]["lineage_lifecycle"]["lineages"]
        ],
        "datasets": datasets,
        "source_audit": source_audit,
    }
    csv_members = {
        name: (root / name).read_bytes()
        for name in (
            "lifecycle_summary.csv",
            "gap_recovery_summary.csv",
            "outcome_summary.csv",
        )
    }
    expected_csv = _csv_members(evidence)
    if csv_members != expected_csv:
        raise LifecycleStudyError("CSV semantic rederivation mismatch")
    decision = _load_json(root / "decision.json")
    expected_decision = _decision_from_evidence(
        evidence,
        source_audit_id=source_audit["source_audit_id"],
        csv_members=csv_members,
    )
    if decision != expected_decision:
        raise LifecycleStudyError("decision semantic rederivation mismatch")
    manifest = _load_json(root / "manifest.json")
    expected_manifest = _manifest_for_staging(
        root,
        decision=decision,
        source_audit_id=source_audit["source_audit_id"],
        lifecycle_evidence_id=decision["lifecycle_evidence_id"],
    )
    if manifest != expected_manifest:
        raise LifecycleStudyError("manifest semantic rederivation mismatch")
    return {
        "study_status": decision["study_status"],
        "decision_id": decision["decision_id"],
        "manifest_id": manifest["manifest_id"],
        "output_inventory_sha256": manifest["output_inventory_sha256"],
        "file_count": len(actual),
        "manifest_member_count": manifest["member_count"],
        "unresolved_count": decision["unresolved_count"],
    }


def _verify_synthetic_lifecycle_bundle_for_tests(
    root: Path,
    *,
    expected_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Explicit test-only verifier for isolated synthetic bundles."""
    return _verify_lifecycle_bundle(
        root,
        expected_evidence=expected_evidence,
        allow_synthetic=True,
    )


def require_fresh_output_root(root: Path = OUTPUT_ROOT) -> None:
    """Refuse existing publication root before any future source access."""
    if root.exists():
        raise ContractFreezeError("existing lifecycle-study output root refused")


def _derive_contract_triplet() -> dict[str, Any]:
    payload = _contract_payload()
    canonical = canonical_json(payload)
    encoded = canonical.encode("utf-8")
    return {
        "payload": payload,
        "canonical_json": canonical,
        "canonical_json_byte_length": len(encoded),
        "canonical_json_sha256": hashlib.sha256(encoded).hexdigest(),
        "contract_id": deterministic_hash(CONTRACT_NAMESPACE, payload),
    }


def contract_triplet() -> dict[str, Any]:
    """Return derived frozen contract identity without source access."""
    return _validated_contract_triplet()


def _validated_contract_triplet() -> dict[str, Any]:
    derived = _derive_contract_triplet()
    if EXPECTED_CONTRACT_ID is None:
        return derived
    checks = (
        derived["contract_id"] == EXPECTED_CONTRACT_ID,
        derived["canonical_json_sha256"] == EXPECTED_CONTRACT_JSON_SHA256,
        derived["canonical_json_byte_length"] == EXPECTED_CONTRACT_JSON_BYTE_LENGTH,
    )
    if not all(checks):
        raise ContractFreezeError("contract identity drift")
    return derived


def validate_contract_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate supplied payload against frozen identity without source access."""
    canonical = canonical_json(dict(payload))
    encoded = canonical.encode("utf-8")
    derived = {
        "canonical_json_byte_length": len(encoded),
        "canonical_json_sha256": hashlib.sha256(encoded).hexdigest(),
        "contract_id": deterministic_hash(CONTRACT_NAMESPACE, dict(payload)),
    }
    expected = contract_triplet()
    if derived != {
        key: expected[key]
        for key in (
            "canonical_json_byte_length",
            "canonical_json_sha256",
            "contract_id",
        )
    }:
        raise ContractFreezeError("supplied contract payload identity mismatch")
    return derived


def _execution_guard(root: Path = OUTPUT_ROOT) -> None:
    require_fresh_output_root(root)
    if os.environ.get("TRENDLINE_V2_ALLOW_PHASE11R3A_LIFECYCLE_STUDY") != "1":
        raise ContractFreezeError("lifecycle study execution guard not enabled")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--execute-lifecycle-study", action="store_true")
    group.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.execute_lifecycle_study:
        _execution_guard()
        result = run_lifecycle_study()
        print(json.dumps(result, sort_keys=True))
        return 0
    triplet = contract_triplet()
    if args.verify:
        if OUTPUT_ROOT.exists():
            print(json.dumps(_verify_lifecycle_bundle(OUTPUT_ROOT), sort_keys=True))
        else:
            print(
                json.dumps(
                    {
                        "contract_id": triplet["contract_id"],
                        "canonical_json_byte_length": triplet[
                            "canonical_json_byte_length"
                        ],
                        "canonical_json_sha256": triplet["canonical_json_sha256"],
                        "status": FREEZE_STATUS,
                    },
                    sort_keys=True,
                )
            )
    else:
        print(FREEZE_STATUS)
    return 0


EXPECTED_CONTRACT_ID: str | None = (
    "df65b38a0bbdf675e97336bcb3a750ba64483cfee32428ec08c4b40da63d85b1"
)
EXPECTED_CONTRACT_JSON_SHA256: str | None = (
    "154fe9a3168b5c16c17156fd278acc8d63433ba645aca14727bad50b429423e8"
)
EXPECTED_CONTRACT_JSON_BYTE_LENGTH: int | None = 22226
_validated_triplet = _validated_contract_triplet()
CONTRACT_ID = _validated_triplet["contract_id"]
CONTRACT_JSON_SHA256 = _validated_triplet["canonical_json_sha256"]
CONTRACT_JSON_BYTE_LENGTH = _validated_triplet["canonical_json_byte_length"]


if __name__ == "__main__":
    raise SystemExit(main())
