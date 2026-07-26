"""Phase 11R.2 sparse-geometry failure attribution.

This module freezes an offline attribution contract.  It imports the committed
Phase 11R.1 research engine but never changes or calls the runtime provider.
Attribution execution is deliberately guarded and is not part of contract
freeze validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from itertools import combinations
from typing import Any, Mapping, Sequence

from scripts import analyze_trendline_v2_independent_sparse_geometry as phase11r1
from libs.models.trendline_v2.domain.geometry import LineGeometry
from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash


BASE_COMMIT = "f99997c10b83082b3d3ce8de6b82f8add0996a71"
PHASE11R1_SCRIPT_BLOB = "102159f511f0a2d0598a521cf7ee42aa1cfaf64b"
PHASE11R1_SCRIPT_SHA256 = "47d4b43ce556789b7992da3777356a05682ac5165b759c4b74682f89c808ee48"
PHASE11R1_ROOT = phase11r1.OUTPUT_ROOT
VALIDATION_ROOT = phase11r1.VALIDATION_ROOT
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase11r2_failure_attribution/20260522_20260701"
)
VALIDATION_DATASETS = tuple(phase11r1.VALIDATION_DATASETS)
ROLES = tuple(phase11r1.ROLES)
PRIMARY_PROVIDERS = tuple(phase11r1.PRIMARY_PROVIDERS)
CONTROL_PROVIDER = phase11r1.CONTROL_PROVIDERS[0]
ALL_METHODS = tuple(phase11r1.VALIDATION_METHODS)
HORIZONS_HOURS = (48, 96)
CHECKPOINTS_PER_DATASET = phase11r1.CHECKPOINTS_PER_DATASET
EXPECTED_CHECKPOINT_RECONSTRUCTIONS = len(VALIDATION_DATASETS) * CHECKPOINTS_PER_DATASET * 2
CONTRACT_NAMESPACE = (
    "trendline_v2_phase11r2_sparse_geometry_failure_attribution_contract"
)
PAIR_LINEAGE_NAMESPACE = "trendline_v2_phase11r2_pair_lineage"
PAIR_EVALUATION_NAMESPACE = "trendline_v2_phase11r2_pair_evaluation"
SEED_FUNNEL_NAMESPACE = "trendline_v2_phase11r2_seed_funnel"
ATTRIBUTION_NAMESPACE = "trendline_v2_phase11r2_attribution"
MANIFEST_NAMESPACE = "trendline_v2_phase11r2_manifest"
DECISION_NAMESPACE = "trendline_v2_phase11r2_decision"
SOURCE_AUDIT_NAMESPACE = "trendline_v2_phase11r2_source_audit"

PHASE9C2_DECISION_ID = "4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c"
PHASE9C2_MANIFEST_ID = "beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81"
PHASE9C2_OUTPUT_INVENTORY = "ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532"
PHASE9C2_SOURCE_INVENTORY = "631f23915654009fbc5d4fe6adbd5a2b9c300107bc54e6660930c404fc9598be"
PHASE9C2_RAW_FILE_INVENTORY = "2f2db301ca6c9c355bb4d645bb2d631836749748835c0419573e7cf52d27de27"
PHASE11R1_CONTRACT_ID = "3bcad03fdd5df8b3af6754bdb38b0436cc93528964298607dd1169950cc312d3"
PHASE11R1_DECISION_ID = "a06d0ca3a7a08b89db7a065133d5c30eeaa51800172187f4b75e7146e21e29fa"
PHASE11R1_MANIFEST_ID = "6393883d533a6b56eb2abfb7b1402bee6eb75cfb366f59e942b7e44bb128ab32"
PHASE11R1_INVENTORY = "17cf5aa6f70b58a21fe436ca63a98f88ab6356250de13befa94100ac96c4ae50"
PHASE11R1_LOCK_ID = "ef381809b4d0155c625be28e752786099272910d7633a9c0d29101b8a2f81815"

DECISION_STATUSES = (
    "SPARSE_GEOMETRY_FAILURE_ATTRIBUTION_COMPLETE",
    "SPARSE_GEOMETRY_FAILURE_ATTRIBUTION_INCOMPLETE",
    "SPARSE_GEOMETRY_FAILURE_ATTRIBUTION_BLOCKED",
)
FUNNEL_STAGES = (
    "ordered_pair",
    "minimum_span_96h",
    "minimum_three_touches_at_0.35_ATR",
    "no_two_close_sustained_breach_at_0.5_ATR",
    "positive_finite_checkpoint_projection",
    "checkpoint_distance_at_most_8_ATR",
    "final_seed",
)
FUNNEL_LABELS = (
    "NO_ORDERED_PAIR",
    "NO_MINIMUM_SPAN_PAIR",
    "NO_THREE_TOUCH_PAIR",
    "ALL_PAIRS_CURRENTLY_BREACHED",
    "ALL_PROJECTIONS_NONPOSITIVE",
    "ALL_PAIRS_BEYOND_8_ATR",
    "SEED_AVAILABLE",
)
THEIL_STAGES = (
    "common_seed_exists",
    "initial_inliers_at_least_3",
    "final_inliers_at_least_3",
    "final_inlier_span_at_least_96h",
    "no_sustained_breach_after_final_inlier",
    "positive_checkpoint_projection",
    "checkpoint_distance_at_most_8_ATR",
    "deduplication",
    "ranked_candidate",
)
THEIL_LABELS = (
    "INITIAL_INLIERS_LT_3",
    "FINAL_INLIERS_LT_3",
    "FINAL_SPAN_LT_96H",
    "FINAL_LINE_BREACHED",
    "FINAL_PROJECTION_NONPOSITIVE",
    "FINAL_DISTANCE_GT_8_ATR",
    "DEDUPED_BY_LOWER_SEED_ID",
    "CANDIDATE_AVAILABLE",
)
THEIL_FAILURE_LABELS = THEIL_LABELS[:6]
CHURN_LABEL_PREFIXES = (
    "INCUMBENT_SEED_LOST_",
    "INCUMBENT_REFIT_LOST_",
    "INCUMBENT_DEDUPED_BY_LOWER_SEED",
    "INCUMBENT_ELIGIBLE_RANK_DISPLACED",
    "SAME_ORIGIN_GEOMETRY_DRIFT",
)
INVERSION_LABELS = (
    "NO_NON_INVERTED_ELIGIBLE_COMBINATION",
    "INDEPENDENT_ROLE_RANKING_SELECTED_INVERTED_PAIR",
)
REGRET_LABELS = ("PRIMARY_FAIL_CONTROL_SURVIVE", "PRIMARY_SURVIVE_CONTROL_FAIL")
EXPECTED_ALLOWED_RAW_PATHS = tuple(
    f"datasets/{dataset}/provider_result.json" for dataset in VALIDATION_DATASETS
)
FORBIDDEN_RAW_PATHS = (
    "datasets/suiusdt_1h/provider_result.json",
    "datasets/suiusdt_4h/provider_result.json",
)
FORBIDDEN_ROOTS = ("/tmp/trendline_v2_phase10c2_lookback_eviction",)
EXPECTED_ARTIFACT_PATHS = tuple(
    sorted(
        {
            "study_contract.json",
            "source_audit.json",
            "coverage_funnel_summary.csv",
            "churn_summary.csv",
            "inversion_summary.csv",
            "survival_regret_summary.csv",
            "decision.json",
            "manifest.json",
            *{
                f"datasets/{dataset}/{member}"
                for dataset in VALIDATION_DATASETS
                for member in (
                    "seed_funnel.json",
                    "churn_attribution.json",
                    "inversion_attribution.json",
                    "survival_regret.json",
                )
            },
        }
    )
)


class AttributionError(RuntimeError):
    """Expected attribution contract or evidence failure."""


class AttributionBlocked(AttributionError):
    """Attribution cannot continue without changing approved scope."""


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _canonical_json_bytes(value: object) -> bytes:
    return canonical_json(value).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=phase11r1._reject_duplicate_keys,
            parse_constant=phase11r1._reject_constant,
        )
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise AttributionError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict) or raw != _canonical_bytes(value):
        raise AttributionError(f"non-canonical JSON artifact: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value))


def _inventory(root: Path) -> tuple[dict[str, Any], ...]:
    if not root.is_dir() or root.is_symlink():
        raise AttributionError(f"bundle root missing: {root}")
    items: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise AttributionError(f"symlink not allowed: {path}")
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


def _csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        raise AttributionError("empty CSV payload")
    fields = tuple(rows[0])
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows({field: row[field] for field in fields} for row in rows)
    return stream.getvalue().encode("utf-8")


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise AttributionError(f"{field} must be ISO text")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AttributionError(f"invalid {field}") from exc
    if result.tzinfo is None:
        raise AttributionError(f"{field} must be timezone-aware")
    return result.astimezone(UTC)


def _contract_payload() -> dict[str, Any]:
    """Return exact contract preimage. No source access occurs here."""
    return {
        "schema_version": CONTRACT_NAMESPACE,
        "base_commit": BASE_COMMIT,
        "phase11r1_dependency": {
            "commit": BASE_COMMIT,
            "script_path": "scripts/analyze_trendline_v2_independent_sparse_geometry.py",
            "script_git_blob": PHASE11R1_SCRIPT_BLOB,
            "script_sha256": PHASE11R1_SCRIPT_SHA256,
            "contract_id": PHASE11R1_CONTRACT_ID,
            "decision_id": PHASE11R1_DECISION_ID,
            "manifest_id": PHASE11R1_MANIFEST_ID,
            "inventory_sha256": PHASE11R1_INVENTORY,
            "validation_lock_id": PHASE11R1_LOCK_ID,
        },
        "sources": {
            "phase11r1_root": str(PHASE11R1_ROOT),
            "phase11r1_contract_id": PHASE11R1_CONTRACT_ID,
            "phase11r1_decision_id": PHASE11R1_DECISION_ID,
            "phase11r1_manifest_id": PHASE11R1_MANIFEST_ID,
            "phase11r1_inventory_sha256": PHASE11R1_INVENTORY,
            "phase11r1_validation_lock_id": PHASE11R1_LOCK_ID,
            "phase9c2_root": str(VALIDATION_ROOT),
            "phase9c2_decision_id": PHASE9C2_DECISION_ID,
            "phase9c2_manifest_id": PHASE9C2_MANIFEST_ID,
            "phase9c2_output_inventory_sha256": PHASE9C2_OUTPUT_INVENTORY,
            "phase9c2_source_inventory_sha256": PHASE9C2_SOURCE_INVENTORY,
            "phase9c2_allowed_raw_inventory_sha256": PHASE9C2_RAW_FILE_INVENTORY,
            "allowed_raw_paths": list(EXPECTED_ALLOWED_RAW_PATHS),
            "forbidden_raw_paths": list(FORBIDDEN_RAW_PATHS),
            "forbidden_roots": list(FORBIDDEN_ROOTS),
            "phase11r1_persisted_sui_placeholder_reads": "allowed",
            "phase9c2_raw_sui_reads": "prohibited",
            "source_immutability": {
                "tracked": [
                    "phase11r1_bundle_inventory_sha256",
                    "allowed_raw_inventory_sha256",
                    "phase11r1_script_sha256",
                ],
                "policy": "exact_before_after_equality",
            },
        },
        "independence": {
            "network_requests": 0,
            "legacy_executions": 0,
            "runtime_v2_provider_executions": 0,
            "holdout_access": False,
            "temporal_access": False,
            "source_mutation": "fail_closed",
            "execution_mode": "research_local_reconstruction_only",
        },
        "targets": {
            "datasets": list(VALIDATION_DATASETS),
            "checkpoint_count_per_dataset": CHECKPOINTS_PER_DATASET,
            "roles": list(ROLES),
            "primary_providers": list(PRIMARY_PROVIDERS),
            "control_provider": CONTROL_PROVIDER,
            "coverage": "every_dataset_checkpoint_role_without_primary_line",
            "churn": "every_primary_replacement_event_both_roles",
            "inversion": "every_selected_primary_pair_with_support_above_resistance",
            "survival_regret": "every_matched_48h_or_96h_disagreement",
        },
        "seed_funnel": {
            "stages": list(FUNNEL_STAGES),
            "thresholds": {
                "minimum_span_hours": 96,
                "touch_atr": 0.35,
                "breach_atr": 0.5,
                "breach_consecutive_bars": 2,
                "maximum_distance_atr": 8.0,
            },
            "labels": list(FUNNEL_LABELS),
            "namespaces": [PAIR_LINEAGE_NAMESPACE, PAIR_EVALUATION_NAMESPACE, SEED_FUNNEL_NAMESPACE],
            "seed_identity_match": "phase11r1._seed_pool",
        },
        "theil_sen_attrition": {
            "stages": list(THEIL_STAGES),
            "labels": list(THEIL_LABELS),
            "candidate_identity_match": "phase11r1._theil_sen_provider",
            "deduplication": "lowest_seed_id_per_touch_or_inlier_set",
        },
        "churn_attribution": {
            "origin_key": ["role", "first_anchor_pivot_id", "second_anchor_pivot_id"],
            "labels": list(CHURN_LABEL_PREFIXES),
            "ambiguous_origin": "BLOCK",
            "rank_vector": "persist_full_vector_and_first_difference",
            "geometry_drift": ["anchor_jaccard", "projection_distance_atr", "slope_distance_bps_per_day"],
            "pair_evidence_fields": ["incumbent_pair_lineage_id", "incumbent_pair_evaluation_id", "incumbent_first_failure_stage", "incumbent_passed_stages"],
            "deduplication_evidence_fields": ["incumbent_seed_id", "retained_lower_seed_id", "shared_final_inlier_ids", "deduplication_id"],
        },
        "inversion_attribution": {
            "labels": list(INVERSION_LABELS),
            "candidate_space": "all_eligible_support_resistance_combinations",
            "selected_rank_requirement": {"support": 1, "resistance": 1},
            "rank_penalty": "support_rank_minus_1_plus_resistance_rank_minus_1",
            "tie_break": ["rank_penalty", "support_rank", "resistance_rank", "support_line_id", "resistance_line_id"],
            "checkpoint_projection": "timestamp_space",
            "reconciliation": "persisted_phase11r1_channel_inversion_count_by_provider",
        },
        "survival_regret": {
            "matched_key": ["checkpoint_index", "role"],
            "horizons_hours": list(HORIZONS_HOURS),
            "labels": list(REGRET_LABELS),
            "signed_differences": ["current_distance_atr", "structural_span_hours", "touch_count", "absolute_slope_bps_per_day"],
            "reconciliation": "phase11r1 matched latest-wide control outcomes",
        },
        "reconciliation": {
            "zero_unresolved": True,
            "seed_counts_and_ids": True,
            "selected_lines": True,
            "replacement_counts": True,
            "inversion_cases": True,
            "survival_wins_losses_ties": True,
            "all_primary_coverage_cases": True,
            "semantic_rederivation": True,
            "unresolved_cases_complete": True,
        },
        "artifacts": {
            "output_root": str(OUTPUT_ROOT),
            "member_count": 23,
            "file_count_including_manifest": 24,
            "paths": list(EXPECTED_ARTIFACT_PATHS),
        },
        "execution_accounting": {
            "validation_datasets": len(VALIDATION_DATASETS),
            "checkpoints": len(VALIDATION_DATASETS) * CHECKPOINTS_PER_DATASET,
            "derivation_repeats": 2,
            "attribution_checkpoint_reconstructions": EXPECTED_CHECKPOINT_RECONSTRUCTIONS,
            "phase11r1_bundle_verifications": 1,
            "source_immutability_snapshots": 2,
            "raw_sui_accesses": 0,
            "temporal_accesses": 0,
            "network_requests": 0,
            "legacy_executions": 0,
            "runtime_v2_provider_executions": 0,
        },
        "decision_statuses": list(DECISION_STATUSES),
        "study_controls": {
            "cli_execute": "--execute-attribution",
            "cli_verify": "--verify",
            "execute_environment": "TRENDLINE_V2_ALLOW_PHASE11R2_ATTRIBUTION=1",
            "existing_output_root": "refuse_before_source_access",
            "publication": "one_atomic_directory_replacement",
            "parameter_search": False,
            "threshold_changes": False,
            "new_provider": False,
            "counterfactual_promotion": False,
            "execution_authorized_at_freeze": False,
        },
    }


# Filled after contract preimage is computed. Kept explicit for reviewer pinning.
CONTRACT_ID = "d3a52e28ce11ffb86bb05aff826ce48ad11b9035c6796e9e938a616463686089"
CONTRACT_JSON_SHA256 = "359549fc158b0785f55c49e949f15780be912ca1097b62b96a5d4b14c96d20a1"
CONTRACT_JSON_BYTE_LENGTH = 8504


def contract_id(payload: Mapping[str, Any]) -> str:
    return deterministic_hash(CONTRACT_NAMESPACE, payload)


def _contract_triplet() -> tuple[str, int, str]:
    raw = _canonical_json_bytes(_contract_payload())
    return contract_id(_contract_payload()), len(raw), _sha256_bytes(raw)


def _assert_contract_triplet() -> None:
    derived_id, derived_length, derived_sha = _contract_triplet()
    if (derived_id, derived_length, derived_sha) != (
        CONTRACT_ID,
        CONTRACT_JSON_BYTE_LENGTH,
        CONTRACT_JSON_SHA256,
    ):
        raise AttributionError(
            "attribution contract identity drift: "
            f"derived={(derived_id, derived_length, derived_sha)}"
        )


def _git_rev_parse(expression: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", expression],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise AttributionBlocked(f"git identity unavailable: {expression}")
    return result.stdout.strip()


def _git_is_ancestor(ancestor: str, descendant: str = "HEAD") -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _assert_phase11r1_dependency() -> None:
    if not _git_is_ancestor(BASE_COMMIT):
        raise AttributionBlocked("frozen Phase 11R.1 base is not an ancestor")
    path = Path(phase11r1.__file__).resolve()
    if _sha256_file(path) != PHASE11R1_SCRIPT_SHA256:
        raise AttributionBlocked("Phase 11R.1 script SHA-256 differs")
    if _git_rev_parse(f"{BASE_COMMIT}:scripts/{path.name}") != PHASE11R1_SCRIPT_BLOB:
        raise AttributionBlocked("Phase 11R.1 script Git blob differs")


def _assert_phase11r1_bundle() -> dict[str, Any]:
    """Verify Phase 11R.1 without touching Phase 9C.2 SUI raw files.

    Persisted Phase 11R.1 SUI entries are only no-finalist placeholders.  The
    four validation memberships and metrics are replayed against the explicit
    BTC/ETH raw allowlist below; the Phase 11R.1 full verifier is forbidden
    because it inventories Phase 9C.2 holdout files.
    """
    root_inventory = _inventory(PHASE11R1_ROOT)
    expected_paths = tuple(phase11r1._expected_artifact_paths())
    if tuple(item["path"] for item in root_inventory) != expected_paths:
        raise AttributionBlocked("Phase 11R.1 artifact path set mismatch")
    manifest = phase11r1._load_json(PHASE11R1_ROOT / "manifest.json")
    members = tuple(item for item in root_inventory if item["path"] != "manifest.json")
    if (
        manifest.get("manifest_id") != PHASE11R1_MANIFEST_ID
        or manifest.get("study_contract_id") != PHASE11R1_CONTRACT_ID
        or manifest.get("decision_id") != PHASE11R1_DECISION_ID
        or manifest.get("member_count") != len(members)
        or tuple(manifest.get("members", ())) != members
        or manifest.get("output_inventory_sha256") != PHASE11R1_INVENTORY
        or manifest.get("manifest_id")
        != deterministic_hash(
            phase11r1.MANIFEST_NAMESPACE,
            {key: value for key, value in manifest.items() if key != "manifest_id"},
        )
    ):
        raise AttributionBlocked("Phase 11R.1 manifest identity mismatch")
    contract, contract_id = phase11r1._validated_contract()
    persisted_contract = phase11r1._load_json(PHASE11R1_ROOT / "study_contract.json")
    if persisted_contract != {"contract_id": contract_id, "payload": contract}:
        raise AttributionBlocked("Phase 11R.1 contract mismatch")
    source_audit = phase11r1._load_json(PHASE11R1_ROOT / "source_audit.json")
    if (
        source_audit.get("source_audit_id")
        != deterministic_hash(
            phase11r1.SOURCE_AUDIT_NAMESPACE,
            {key: value for key, value in source_audit.items() if key != "source_audit_id"},
        )
        or source_audit.get("loaded_dataset_ids") != list(VALIDATION_DATASETS)
        or source_audit.get("holdout_accessed") is not False
        or source_audit.get("temporal_accessed") is not False
        or source_audit.get("phase9c2", {}).get("manifest_id") != PHASE9C2_MANIFEST_ID
        or source_audit.get("phase9c2", {}).get("source_inventory_sha256") != PHASE9C2_SOURCE_INVENTORY
    ):
        raise AttributionBlocked("Phase 11R.1 source audit mismatch")
    lock = phase11r1._load_json(PHASE11R1_ROOT / "validation_lock.json")
    phase11r1._verify_lock_bytes(PHASE11R1_ROOT / "validation_lock.json", lock)
    if (
        lock.get("validation_lock_id") != PHASE11R1_LOCK_ID
        or lock.get("study_contract_id") != PHASE11R1_CONTRACT_ID
        or lock.get("winner_provider_id") is not None
        or lock.get("validation_dataset_ids") != list(VALIDATION_DATASETS)
    ):
        raise AttributionBlocked("Phase 11R.1 validation lock mismatch")
    for dataset_id in phase11r1.HOLDOUT_DATASETS:
        membership = phase11r1._load_json(
            PHASE11R1_ROOT / "datasets" / dataset_id / "checkpoint_membership.json"
        )
        metrics = phase11r1._load_json(
            PHASE11R1_ROOT / "datasets" / dataset_id / "provider_metrics.json"
        )
        expected_membership, expected_metrics = phase11r1._unopened_dataset(
            dataset_id, reason="NO_VALIDATION_FINALIST"
        )
        if membership != expected_membership or metrics != expected_metrics:
            raise AttributionBlocked("Phase 11R.1 SUI placeholder mismatch")
    validation_metrics: dict[str, Mapping[str, Any]] = {}
    for dataset_id in VALIDATION_DATASETS:
        scope = phase11r1._load_scope_dataset(VALIDATION_ROOT, dataset_id)
        membership = phase11r1._load_json(
            PHASE11R1_ROOT / "datasets" / dataset_id / "checkpoint_membership.json"
        )
        metrics = phase11r1._load_json(
            PHASE11R1_ROOT / "datasets" / dataset_id / "provider_metrics.json"
        )
        phase11r1._validate_membership(
            membership,
            metrics=metrics,
            scope=scope,
            expected_method_ids=ALL_METHODS,
            phase="validation",
        )
        validation_metrics[dataset_id] = metrics
    aggregate = {
        provider_id: phase11r1._aggregate_metrics(
            validation_metrics, provider_id, phase="validation"
        )
        for provider_id in PRIMARY_PROVIDERS
    }
    ranking = phase11r1._rank_validation(aggregate)
    winner = next((row["provider_id"] for row in ranking if row["gate_passed"]), None)
    if winner is not None:
        raise AttributionBlocked("Phase 11R.1 no-winner decision drifted")
    expected_validation = {
        "aggregate": aggregate,
        "ranking": ranking,
        "winner_provider_id": None,
    }
    decision = phase11r1._load_json(PHASE11R1_ROOT / "decision.json")
    expected_decision = phase11r1._decision_payload(
        status="NO_INDEPENDENT_SPARSE_PROVIDER_FINALIST",
        contract_id=PHASE11R1_CONTRACT_ID,
        validation=expected_validation,
        lock=lock,
        holdout_status="UNOPENED_NO_VALIDATION_FINALIST",
        temporal_status="UNOPENED_NO_HOLDOUT_PASS",
        method_derivation_counts={"validation": 704, "holdout": 0, "temporal": 0},
        scope_method_ids={"validation": ALL_METHODS, "holdout": (), "temporal": ()},
    )
    if decision != expected_decision:
        raise AttributionBlocked("Phase 11R.1 no-winner decision mismatch")
    return {
        "study_status": decision["study_status"],
        "decision_id": decision["decision_id"],
        "manifest_id": manifest["manifest_id"],
        "output_inventory_sha256": manifest["output_inventory_sha256"],
        "validation_metrics": validation_metrics,
        "source_audit": source_audit,
        "root_inventory": root_inventory,
    }


def _assert_allowed_raw_path(path: Path) -> None:
    resolved = path.resolve()
    root = VALIDATION_ROOT.resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise AttributionBlocked(f"raw path outside approved validation root: {path}") from exc
    if relative in FORBIDDEN_RAW_PATHS or "sui" in relative.lower():
        raise AttributionBlocked(f"forbidden raw path access: {relative}")
    if any(str(resolved).startswith(root_path) for root_path in FORBIDDEN_ROOTS):
        raise AttributionBlocked(f"forbidden root access: {resolved}")
    if relative not in EXPECTED_ALLOWED_RAW_PATHS:
        raise AttributionBlocked(f"raw path not in exact allowlist: {relative}")


def _allowed_raw_inventory() -> tuple[dict[str, Any], ...]:
    items: list[dict[str, Any]] = []
    for relative in EXPECTED_ALLOWED_RAW_PATHS:
        path = VALIDATION_ROOT / relative
        _assert_allowed_raw_path(path)
        if not path.is_file() or path.is_symlink():
            raise AttributionBlocked(f"approved raw input missing: {path}")
        items.append(
            {
                "path": relative,
                "byte_length": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    inventory = tuple(items)
    if _inventory_sha256(inventory) != PHASE9C2_RAW_FILE_INVENTORY:
        raise AttributionBlocked("Phase 9C.2 allowed raw inventory mismatch")
    return inventory


def _assert_phase9c2_binding() -> None:
    """Bind frozen Phase 9C.2 metadata without opening forbidden raw files."""
    manifest = _load_json(VALIDATION_ROOT / "manifest.json")
    if (
        manifest.get("manifest_id") != PHASE9C2_MANIFEST_ID
        or manifest.get("source_inventory_sha256") != PHASE9C2_SOURCE_INVENTORY
    ):
        raise AttributionBlocked("Phase 9C.2 manifest identity mismatch")
    decision = _load_json(VALIDATION_ROOT / "decision.json")
    if decision.get("decision_id") != PHASE9C2_DECISION_ID:
        raise AttributionBlocked("Phase 9C.2 decision identity mismatch")
    _allowed_raw_inventory()


def _load_allowed_scope() -> tuple[Any, ...]:
    _assert_phase9c2_binding()
    return tuple(
        phase11r1._load_scope_dataset(VALIDATION_ROOT, dataset)
        for dataset in VALIDATION_DATASETS
    )


def _pivot_lineage_id(pivot_a: Mapping[str, Any], pivot_b: Mapping[str, Any], *, role: str, asset: str, timeframe: str) -> str:
    return deterministic_hash(
        PAIR_LINEAGE_NAMESPACE,
        {
            "asset": asset,
            "timeframe": timeframe,
            "role": role,
            "first_pivot_id": pivot_a["pivot_id"],
            "second_pivot_id": pivot_b["pivot_id"],
        },
    )


def _line_geometry(line: Mapping[str, Any]) -> LineGeometry:
    try:
        return LineGeometry.from_dict(line["geometry"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AttributionError("invalid line geometry") from exc


def _line_projection(line: Mapping[str, Any], timestamp: datetime) -> float:
    return float(_line_geometry(line).value_at(timestamp))


def _funnel_for_checkpoint(cp: Any) -> dict[str, Any]:
    """Reconstruct exact Phase 11R.1 pair eligibility with exclusive failures."""
    data = cp.data
    pivots = phase11r1._hierarchical_pivots(
        data, prefix_last_position=cp.prefix_last_position, checkpoint=cp.checkpoint
    )
    atr = phase11r1._atr(data)
    by_role = {role: tuple(p for p in pivots if p.role == role) for role in ROLES}
    seed_pool = phase11r1._seed_pool(
        data, prefix_last_position=cp.prefix_last_position, checkpoint=cp.checkpoint
    )
    role_results: dict[str, dict[str, Any]] = {}
    for role in ROLES:
        pair_records: list[dict[str, Any]] = []
        stage_pass = {stage: 0 for stage in FUNNEL_STAGES}
        first_fail = {stage: 0 for stage in FUNNEL_STAGES[:-1]}
        role_pivots = by_role[role]

        def record_pair(
            *,
            first: Any,
            second: Any,
            lineage_id: str,
            passed: Mapping[str, bool],
            first_failure_stage: str | None,
            touch_pivot_ids: Sequence[str] = (),
            breach_position: int | None = None,
            checkpoint_projection: float | None = None,
            checkpoint_distance_atr: float | None = None,
            seed_id: str | None = None,
        ) -> None:
            pair_records.append(
                {
                    "pair_lineage_id": lineage_id,
                    "checkpoint_index": cp.checkpoint_index,
                    "source_input_identity": data.input_identity,
                    "first_pivot_id": first.pivot_id,
                    "second_pivot_id": second.pivot_id,
                    "passed_stages": dict(passed),
                    "first_failure_stage": first_failure_stage,
                    "touch_pivot_ids": list(touch_pivot_ids),
                    "breach_position": breach_position,
                    "checkpoint_projection": checkpoint_projection,
                    "checkpoint_distance_atr": checkpoint_distance_atr,
                    "seed_id": seed_id,
                }
            )

        for first, second in combinations(role_pivots, 2):
            if first.source_position >= second.source_position:
                continue
            geometry = phase11r1._geometry(first, second)
            lineage_id = _pivot_lineage_id(
                first.to_dict(), second.to_dict(), role=role, asset=data.asset, timeframe=data.timeframe
            )
            stage = "ordered_pair"
            passed = {name: False for name in FUNNEL_STAGES}
            passed["ordered_pair"] = True
            stage_pass["ordered_pair"] += 1
            span_hours = (second.pivot_time - first.pivot_time).total_seconds() / 3600
            if span_hours < 96:
                first_fail["minimum_span_96h"] += 1
                record_pair(
                    first=first,
                    second=second,
                    lineage_id=lineage_id,
                    passed=passed,
                    first_failure_stage="minimum_span_96h",
                )
                continue
            passed["minimum_span_96h"] = True
            stage_pass["minimum_span_96h"] += 1
            touches = tuple(
                pivot
                for pivot in role_pivots
                if first.source_position <= pivot.source_position <= cp.prefix_last_position
                and abs(pivot.price - phase11r1._line_value(geometry, pivot.pivot_time))
                <= phase11r1.TOUCH_ATR * atr[pivot.source_position]
            )
            if len(touches) < 3:
                first_fail["minimum_three_touches_at_0.35_ATR"] += 1
                record_pair(
                    first=first,
                    second=second,
                    lineage_id=lineage_id,
                    passed=passed,
                    first_failure_stage="minimum_three_touches_at_0.35_ATR",
                    touch_pivot_ids=[p.pivot_id for p in touches],
                )
                continue
            passed["minimum_three_touches_at_0.35_ATR"] = True
            stage_pass["minimum_three_touches_at_0.35_ATR"] += 1
            breached, breach_position = phase11r1._sustained_breach(
                data, atr, geometry, role, second.source_position + 1, cp.prefix_last_position
            )
            if breached:
                first_fail["no_two_close_sustained_breach_at_0.5_ATR"] += 1
                record_pair(
                    first=first,
                    second=second,
                    lineage_id=lineage_id,
                    passed=passed,
                    first_failure_stage="no_two_close_sustained_breach_at_0.5_ATR",
                    touch_pivot_ids=[p.pivot_id for p in touches],
                    breach_position=breach_position,
                )
                continue
            passed["no_two_close_sustained_breach_at_0.5_ATR"] = True
            stage_pass["no_two_close_sustained_breach_at_0.5_ATR"] += 1
            checkpoint_line = phase11r1._line_value(geometry, cp.checkpoint)
            if checkpoint_line <= 0 or not __import__("math").isfinite(checkpoint_line):
                first_fail["positive_finite_checkpoint_projection"] += 1
                record_pair(
                    first=first,
                    second=second,
                    lineage_id=lineage_id,
                    passed=passed,
                    first_failure_stage="positive_finite_checkpoint_projection",
                    touch_pivot_ids=[p.pivot_id for p in touches],
                    checkpoint_projection=checkpoint_line,
                )
                continue
            passed["positive_finite_checkpoint_projection"] = True
            stage_pass["positive_finite_checkpoint_projection"] += 1
            checkpoint_close = float(data.close[cp.prefix_last_position])
            distance = abs(checkpoint_close - checkpoint_line) / atr[cp.prefix_last_position]
            if distance > phase11r1.MAX_DISTANCE_ATR:
                first_fail["checkpoint_distance_at_most_8_ATR"] += 1
                record_pair(
                    first=first,
                    second=second,
                    lineage_id=lineage_id,
                    passed=passed,
                    first_failure_stage="checkpoint_distance_at_most_8_ATR",
                    touch_pivot_ids=[p.pivot_id for p in touches],
                    checkpoint_projection=checkpoint_line,
                    checkpoint_distance_atr=distance,
                )
                continue
            passed["checkpoint_distance_at_most_8_ATR"] = True
            passed["final_seed"] = True
            stage_pass["checkpoint_distance_at_most_8_ATR"] += 1
            stage_pass["final_seed"] += 1
            seed = next(
                (candidate for candidate in seed_pool[role] if candidate.first.pivot_id == first.pivot_id and candidate.second.pivot_id == second.pivot_id),
                None,
            )
            if seed is None:
                raise AttributionBlocked("reconstructed final seed missing from Phase 11R.1 seed pool")
            record_pair(
                first=first,
                second=second,
                lineage_id=lineage_id,
                passed=passed,
                first_failure_stage=None,
                touch_pivot_ids=[p.pivot_id for p in touches],
                checkpoint_projection=checkpoint_line,
                checkpoint_distance_atr=distance,
                seed_id=seed.seed_id,
            )
        for pair in pair_records:
            pair["pair_evaluation_id"] = deterministic_hash(
                PAIR_EVALUATION_NAMESPACE,
                {
                    "pair_lineage_id": pair["pair_lineage_id"],
                    "checkpoint_index": cp.checkpoint_index,
                    "source_input_identity": data.input_identity,
                    "passed_stages": pair["passed_stages"],
                    "first_failure_stage": pair.get("first_failure_stage"),
                    "touch_pivot_ids": pair.get("touch_pivot_ids", []),
                    "breach_position": pair.get("breach_position"),
                    "checkpoint_projection": pair.get("checkpoint_projection"),
                    "checkpoint_distance_atr": pair.get("checkpoint_distance_atr"),
                    "seed_id": pair.get("seed_id"),
                },
            )
        label = "SEED_AVAILABLE"
        first_zero = None
        for stage, label_value in zip(FUNNEL_STAGES, FUNNEL_LABELS):
            if stage_pass[stage] == 0:
                label = label_value
                first_zero = stage
                break
        final_ids = tuple(sorted(seed.seed_id for seed in seed_pool[role]))
        reconstructed_ids = tuple(sorted(record["seed_id"] for record in pair_records if record.get("seed_id")))
        if final_ids != reconstructed_ids:
            raise AttributionBlocked("final seed identity set differs from Phase 11R.1")
        role_results[role] = {
            "role": role,
            "input_confirmed_pivot_count": len(role_pivots),
            "ordered_pair_count": stage_pass["ordered_pair"],
            "stage_pass_counts": stage_pass,
            "exclusive_first_failure_counts": first_fail,
            "final_seed_count": len(final_ids),
            "final_seed_ids": list(final_ids),
            "final_seed_set_id": deterministic_hash(SEED_FUNNEL_NAMESPACE, {"dataset_id": cp.dataset_id, "checkpoint_index": cp.checkpoint_index, "role": role, "seed_ids": final_ids}),
            "first_zero_stage": first_zero,
            "label": label,
            "pairs": pair_records,
        }
    return {"dataset_id": cp.dataset_id, "checkpoint_index": cp.checkpoint_index, "checkpoint": phase11r1._iso(cp.checkpoint), "source_input_identity": data.input_identity, "roles": role_results, "funnel_id": deterministic_hash(SEED_FUNNEL_NAMESPACE, {"dataset_id": cp.dataset_id, "checkpoint_index": cp.checkpoint_index, "roles": role_results})}


def _theil_trace(seed: Any, cp: Any) -> dict[str, Any]:
    """Explain each Theil-Sen gate while delegating geometry primitives to v1."""
    data = cp.data
    atr = phase11r1._atr(data)
    result: dict[str, Any] = {"seed_id": seed.seed_id, "role": seed.role, "status": None, "stages": {stage: False for stage in THEIL_STAGES}}
    result["stages"]["common_seed_exists"] = True
    if len(seed.touches) < 3:
        result["status"] = "INITIAL_INLIERS_LT_3"
        return result
    initial_slope, initial_intercept = phase11r1._median_sen_geometry(seed.touches)
    initial = tuple(p for p in seed.touches if abs(p.price - (initial_slope * p.pivot_time.timestamp() + initial_intercept)) <= 0.5 * atr[p.source_position])
    result["initial_inlier_ids"] = [p.pivot_id for p in initial]
    if len(initial) < 3:
        result["status"] = "INITIAL_INLIERS_LT_3"
        return result
    result["stages"]["initial_inliers_at_least_3"] = True
    slope, intercept = phase11r1._median_sen_geometry(initial)
    final = tuple(p for p in seed.touches if abs(p.price - (slope * p.pivot_time.timestamp() + intercept)) <= 0.5 * atr[p.source_position])
    result["final_inlier_ids"] = [p.pivot_id for p in final]
    if len(final) < 3:
        result["status"] = "FINAL_INLIERS_LT_3"
        return result
    result["stages"]["final_inliers_at_least_3"] = True
    ordered = tuple(sorted(final, key=lambda p: p.source_position))
    span_hours = (ordered[-1].pivot_time - ordered[0].pivot_time).total_seconds() / 3600
    result["final_inlier_span_hours"] = span_hours
    if span_hours < 96:
        result["status"] = "FINAL_SPAN_LT_96H"
        return result
    result["stages"]["final_inlier_span_at_least_96h"] = True
    geometry = phase11r1._geometry_from_slope(ordered, slope, intercept)
    breached, breach_position = phase11r1._sustained_breach(data, atr, geometry, seed.role, ordered[-1].source_position + 1, cp.prefix_last_position)
    result["breach_position"] = breach_position
    if breached:
        result["status"] = "FINAL_LINE_BREACHED"
        return result
    result["stages"]["no_sustained_breach_after_final_inlier"] = True
    projection = phase11r1._line_value(geometry, cp.checkpoint)
    result["checkpoint_projection"] = projection
    if projection <= 0:
        result["status"] = "FINAL_PROJECTION_NONPOSITIVE"
        return result
    result["stages"]["positive_checkpoint_projection"] = True
    distance = abs(float(data.close[cp.prefix_last_position]) - projection) / atr[cp.prefix_last_position]
    result["checkpoint_distance_atr"] = distance
    if distance > phase11r1.MAX_DISTANCE_ATR:
        result["status"] = "FINAL_DISTANCE_GT_8_ATR"
        return result
    result["stages"]["checkpoint_distance_at_most_8_ATR"] = True
    candidate = phase11r1._theil_sen_candidate(seed, data=data, atr=atr, checkpoint=cp.checkpoint, prefix_last_position=cp.prefix_last_position)
    if candidate is None:
        raise AttributionBlocked("Theil trace passed gates but v1 candidate is absent")
    result.update({"candidate": candidate, "stages": {**result["stages"], "deduplication": True, "ranked_candidate": True}, "status": "CANDIDATE_AVAILABLE"})
    return result


def _all_theil_candidates(seeds: Mapping[str, Sequence[Any]], cp: Any) -> tuple[dict[str, Any], ...]:
    deduped: dict[tuple[str, ...], tuple[str, dict[str, Any], dict[str, Any]]] = {}
    for role in ROLES:
        for seed in seeds[role]:
            trace = _theil_trace(seed, cp)
            candidate = trace.get("candidate")
            if candidate is None:
                continue
            key = tuple(p["pivot_id"] for p in candidate["touch_or_inlier_pivots"])
            previous = deduped.get(key)
            if previous is None or seed.seed_id < previous[0]:
                deduped[key] = (seed.seed_id, candidate, trace)
    result: list[dict[str, Any]] = []
    for role in ROLES:
        candidates = [item for item in deduped.values() if item[1]["role"] == role]
        candidates.sort(key=lambda item: tuple(item[1]["provider_evidence"]["rank"]))
        for rank, (_, candidate, trace) in enumerate(candidates, 1):
            copy = dict(candidate)
            copy["candidate_rank"] = rank
            copy["attribution_trace"] = trace
            result.append(copy)
    return tuple(result)


def _theil_attrition_for_checkpoint(cp: Any, canonical_run: Mapping[str, Any]) -> dict[str, Any]:
    seeds = phase11r1._seed_pool(
        cp.data, prefix_last_position=cp.prefix_last_position, checkpoint=cp.checkpoint
    )
    traces: list[dict[str, Any]] = []
    by_touch_set: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for role in ROLES:
        for seed in seeds[role]:
            trace = _theil_trace(seed, cp)
            traces.append(trace)
            candidate = trace.get("candidate")
            if candidate is not None:
                key = tuple(p["pivot_id"] for p in candidate["touch_or_inlier_pivots"])
                by_touch_set.setdefault(key, []).append(trace)
    for candidates in by_touch_set.values():
        candidates.sort(key=lambda trace: trace["candidate"]["provider_evidence"]["seed_id"])
        retained_seed_id = candidates[0]["candidate"]["provider_evidence"]["seed_id"]
        shared_final_inlier_ids = [
            pivot["pivot_id"] for pivot in candidates[0]["candidate"]["touch_or_inlier_pivots"]
        ]
        for trace in candidates[1:]:
            incumbent_seed_id = trace["candidate"]["provider_evidence"]["seed_id"]
            trace["status"] = "DEDUPED_BY_LOWER_SEED_ID"
            trace["stages"]["deduplication"] = False
            trace["stages"]["ranked_candidate"] = False
            trace["selected"] = False
            trace.update(
                {
                    "incumbent_seed_id": incumbent_seed_id,
                    "retained_lower_seed_id": retained_seed_id,
                    "shared_final_inlier_ids": shared_final_inlier_ids,
                    "deduplication_id": deterministic_hash(
                        ATTRIBUTION_NAMESPACE,
                        {
                            "incumbent_seed_id": incumbent_seed_id,
                            "retained_lower_seed_id": retained_seed_id,
                            "shared_final_inlier_ids": shared_final_inlier_ids,
                        },
                    ),
                }
            )
    eligible = [trace for trace in traces if trace.get("status") == "CANDIDATE_AVAILABLE"]
    eligible_by_role: dict[str, list[dict[str, Any]]] = {role: [] for role in ROLES}
    for trace in eligible:
        eligible_by_role[trace["role"]].append(trace)
    for role in ROLES:
        eligible_by_role[role].sort(key=lambda trace: tuple(trace["candidate"]["provider_evidence"]["rank"]))
        for rank, trace in enumerate(eligible_by_role[role], 1):
            trace["candidate_rank"] = rank
            trace["selected"] = rank == 1
    selected_ids = {
        line["line_id"]
        for line in canonical_run["outputs"][PRIMARY_PROVIDERS[1]]
    }
    ranked_ids = {
        trace["candidate"]["line_id"]
        for trace in eligible
    }
    reconstructed_selected_ids = {
        trace["candidate"]["line_id"]
        for traces in eligible_by_role.values()
        for trace in traces
        if trace.get("selected") is True
    }
    if selected_ids != reconstructed_selected_ids:
        raise AttributionBlocked("Theil-Sen selected line set differs from Phase 11R.1")
    stage_counts = {
        stage: sum(bool(trace["stages"].get(stage)) for trace in traces)
        for stage in THEIL_STAGES
    }
    return {
        "seed_count": sum(len(seeds[role]) for role in ROLES),
        "stage_pass_counts": stage_counts,
        "failure_counts": {
            label: sum(trace.get("status") == label for trace in traces)
            for label in THEIL_LABELS
        },
        "traces": traces,
        "candidate_ids": sorted(ranked_ids),
        "attrition_id": deterministic_hash(
            ATTRIBUTION_NAMESPACE,
            {
                "stage_pass_counts": stage_counts,
                "failure_counts": {
                    label: sum(trace.get("status") == label for trace in traces)
                    for label in THEIL_LABELS
                },
                "candidate_ids": sorted(ranked_ids),
            },
        ),
    }


def _hierarchical_candidates(seeds: Mapping[str, Sequence[Any]], cp: Any) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    for role in ROLES:
        ranked = sorted(seeds[role], key=lambda seed: phase11r1._rank_hierarchical(seed, cp.prefix_last_position))
        for rank, seed in enumerate(ranked, 1):
            line = phase11r1._line_record(provider_id=PRIMARY_PROVIDERS[0], seed=seed, geometry=seed.geometry, pivots=seed.touches, checkpoint=cp.checkpoint, data=cp.data, prefix_last_position=cp.prefix_last_position, provider_evidence={"method": PRIMARY_PROVIDERS[0], "seed_id": seed.seed_id, "rank": list(phase11r1._rank_hierarchical(seed, cp.prefix_last_position))}, anchor_pivots=(seed.first, seed.second))
            line["candidate_rank"] = rank
            result.append(line)
    return tuple(result)


def _candidate_context(
    provider_id: str, seeds: Mapping[str, Sequence[Any]], cp: Any
) -> dict[str, Any]:
    candidates = (
        _hierarchical_candidates(seeds, cp)
        if provider_id == PRIMARY_PROVIDERS[0]
        else _all_theil_candidates(seeds, cp)
    )
    by_role = {role: [line for line in candidates if line["role"] == role] for role in ROLES}
    by_seed = {
        role: {
            line["provider_evidence"]["seed_id"]: line for line in lines
        }
        for role, lines in by_role.items()
    }
    set_ids = {
        role: deterministic_hash(
            ATTRIBUTION_NAMESPACE,
            {
                "provider_id": provider_id,
                "dataset_id": cp.dataset_id,
                "checkpoint_index": cp.checkpoint_index,
                "role": role,
                "line_ids": [line["line_id"] for line in lines],
            },
        )
        for role, lines in by_role.items()
    }
    return {"candidates": candidates, "by_role": by_role, "by_seed": by_seed, "candidate_set_ids": set_ids}


def _theil_trace_by_seed(seeds: Mapping[str, Sequence[Any]], cp: Any) -> dict[str, dict[str, Any]]:
    return {
        seed.seed_id: _theil_trace(seed, cp)
        for role in ROLES
        for seed in seeds[role]
    }


def _deduped_theil_origin(
    seed: Any, traces: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any] | None:
    trace = traces.get(seed.seed_id)
    if trace is None or trace.get("status") != "CANDIDATE_AVAILABLE":
        return None
    candidate = trace.get("candidate")
    if candidate is None:
        return None
    target_ids = tuple(pivot["pivot_id"] for pivot in candidate["touch_or_inlier_pivots"])
    retained = [
        other
        for other in traces.values()
        if other.get("status") == "CANDIDATE_AVAILABLE"
        and other.get("candidate") is not None
        and tuple(p["pivot_id"] for p in other["candidate"]["touch_or_inlier_pivots"]) == target_ids
        and other["candidate"]["provider_evidence"]["seed_id"] < seed.seed_id
    ]
    if not retained:
        return None
    retained.sort(key=lambda item: item["candidate"]["provider_evidence"]["seed_id"])
    lower = retained[0]
    retained_seed_id = lower["candidate"]["provider_evidence"]["seed_id"]
    return {
        "incumbent_seed_id": seed.seed_id,
        "retained_lower_seed_id": retained_seed_id,
        "shared_final_inlier_ids": list(target_ids),
        "deduplication_id": deterministic_hash(
            ATTRIBUTION_NAMESPACE,
            {
                "incumbent_seed_id": seed.seed_id,
                "retained_lower_seed_id": retained_seed_id,
                "shared_final_inlier_ids": list(target_ids),
            },
        ),
    }


def _first_rank_difference(left: Sequence[Any], right: Sequence[Any]) -> int | None:
    for index, (left_value, right_value) in enumerate(zip(left, right)):
        if left_value != right_value:
            return index
    return None if len(left) == len(right) else min(len(left), len(right))


def _churn_attribution(
    membership_by_dataset: Mapping[str, Mapping[str, Any]],
    scopes: Mapping[str, Any],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for dataset_id, membership in membership_by_dataset.items():
        scope = scopes[dataset_id]
        prior_runs = membership["checkpoints"]
        for position, run in enumerate(prior_runs[1:], 1):
            previous_run = prior_runs[position - 1]
            cp = scope.checkpoints[position]
            previous_cp = scope.checkpoints[position - 1]
            funnel = _funnel_for_checkpoint(cp)
            current_seeds = phase11r1._seed_pool(cp.data, prefix_last_position=cp.prefix_last_position, checkpoint=cp.checkpoint)
            previous_seeds = phase11r1._seed_pool(previous_cp.data, prefix_last_position=previous_cp.prefix_last_position, checkpoint=previous_cp.checkpoint)
            for provider_id in PRIMARY_PROVIDERS:
                events = run.get("provider_stability", {}).get(provider_id, ())
                for event in events:
                    if event.get("state") != "replacement":
                        continue
                    role = event["role"]
                    old = next((line for line in previous_run["outputs"][provider_id] if line["line_id"] == event["previous_line_id"]), None)
                    new = next((line for line in run["outputs"][provider_id] if line["line_id"] == event["line_id"]), None)
                    if old is None or new is None:
                        raise AttributionBlocked("replacement line missing from canonical membership")
                    previous_context = _candidate_context(provider_id, previous_seeds, previous_cp)
                    previous_matches = [
                        line for line in previous_context["by_role"][role]
                        if line["line_id"] == old["line_id"]
                    ]
                    if len(previous_matches) != 1:
                        raise AttributionBlocked("replacement origin absent or ambiguous")
                    origin_seed_id = previous_matches[0]["provider_evidence"].get("seed_id")
                    origin_seed = next(
                        (seed for seed in previous_seeds[role] if seed.seed_id == origin_seed_id),
                        None,
                    )
                    if origin_seed is None:
                        raise AttributionBlocked("replacement origin absent or ambiguous")
                    current_pair = next((pair for pair in funnel["roles"][role]["pairs"] if pair.get("first_pivot_id") == origin_seed.first.pivot_id and pair.get("second_pivot_id") == origin_seed.second.pivot_id), None)
                    current_context = _candidate_context(provider_id, current_seeds, cp)
                    incumbent: Mapping[str, Any] | None = None
                    label: str
                    retained_dedup: dict[str, Any] | None = None
                    incumbent_first_failure_stage = None
                    incumbent_passed_stages: Mapping[str, Any] = {}
                    if current_pair is None:
                        label = "INCUMBENT_SEED_LOST_ordered_pair"
                        incumbent_first_failure_stage = "ordered_pair"
                    elif not current_pair.get("seed_id"):
                        incumbent_first_failure_stage = current_pair.get("first_failure_stage")
                        if incumbent_first_failure_stage is None:
                            raise AttributionBlocked("pair failure has no first stage")
                        incumbent_passed_stages = current_pair.get("passed_stages", {})
                        label = f"INCUMBENT_SEED_LOST_{incumbent_first_failure_stage}"
                    elif provider_id == PRIMARY_PROVIDERS[1]:
                        trace_by_seed = _theil_trace_by_seed(current_seeds, cp)
                        trace = trace_by_seed.get(current_pair["seed_id"])
                        if trace is None:
                            raise AttributionBlocked("current Theil seed missing")
                        incumbent_passed_stages = trace.get("stages", {})
                        if trace.get("status") != "CANDIDATE_AVAILABLE":
                            label = f"INCUMBENT_REFIT_LOST_{trace.get('status')}"
                            incumbent_first_failure_stage = trace.get("status")
                        else:
                            retained_dedup = _deduped_theil_origin(
                                next(seed for seed in current_seeds[role] if seed.seed_id == current_pair["seed_id"]),
                                trace_by_seed,
                            )
                            incumbent = current_context["by_seed"][role].get(current_pair["seed_id"])
                            if retained_dedup is not None:
                                label = "INCUMBENT_DEDUPED_BY_LOWER_SEED"
                            elif incumbent is None:
                                raise AttributionBlocked("Theil eligible incumbent missing")
                            elif new["provider_evidence"].get("seed_id") == current_pair["seed_id"]:
                                label = "SAME_ORIGIN_GEOMETRY_DRIFT"
                            else:
                                label = "INCUMBENT_ELIGIBLE_RANK_DISPLACED"
                    else:
                        incumbent = current_context["by_seed"][role].get(current_pair["seed_id"])
                        if incumbent is None:
                            raise AttributionBlocked("hierarchical eligible incumbent missing")
                        if new["provider_evidence"].get("seed_id") == current_pair["seed_id"]:
                            label = "SAME_ORIGIN_GEOMETRY_DRIFT"
                        else:
                            label = "INCUMBENT_ELIGIBLE_RANK_DISPLACED"
                    if not any(label.startswith(prefix) for prefix in CHURN_LABEL_PREFIXES):
                        raise AttributionBlocked("unresolved replacement attribution")
                    checkpoint = phase11r1._parse_iso(run["checkpoint"], field="checkpoint")
                    atr = phase11r1._atr(cp.data)[cp.prefix_last_position]
                    old_geometry = _line_geometry(old)
                    new_geometry = _line_geometry(new)
                    old_ids = {p["pivot_id"] for p in old["anchor_pivots"]}
                    new_ids = {p["pivot_id"] for p in new["anchor_pivots"]}
                    union = old_ids | new_ids
                    record = {
                        "dataset_id": dataset_id,
                        "checkpoint_index": run["checkpoint_index"],
                        "provider_id": provider_id,
                        "role": role,
                        "previous_line_id": old["line_id"],
                        "line_id": new["line_id"],
                        "origin_seed_id": origin_seed.seed_id,
                        "origin_first_pivot_id": origin_seed.first.pivot_id,
                        "origin_second_pivot_id": origin_seed.second.pivot_id,
                        "incumbent_pair_lineage_id": _pivot_lineage_id(origin_seed.first.to_dict(), origin_seed.second.to_dict(), role=role, asset=cp.data.asset, timeframe=cp.data.timeframe),
                        "incumbent_pair_evaluation_id": current_pair.get("pair_evaluation_id") if current_pair else None,
                        "incumbent_first_failure_stage": incumbent_first_failure_stage,
                        "incumbent_passed_stages": dict(incumbent_passed_stages),
                        "cause": label,
                        "anchor_jaccard": len(old_ids & new_ids) / len(union) if union else 1.0,
                        "projection_distance_atr": abs(old_geometry.value_at(checkpoint) - new_geometry.value_at(checkpoint)) / atr,
                        "slope_distance_bps_per_day": abs(old_geometry.slope_per_second - new_geometry.slope_per_second) * 86400 / cp.data.close[cp.prefix_last_position] * 10000,
                        "old_geometry": old["geometry"],
                        "new_geometry": new["geometry"],
                    }
                    if label == "INCUMBENT_DEDUPED_BY_LOWER_SEED":
                        record.update(retained_dedup or {})
                    if label == "INCUMBENT_ELIGIBLE_RANK_DISPLACED":
                        if incumbent is None:
                            raise AttributionBlocked("rank displacement lacks incumbent")
                        winner_candidate = next(
                            (
                                line
                                for line in current_context["by_role"][role]
                                if line["line_id"] == new["line_id"]
                            ),
                            None,
                        )
                        if winner_candidate is None:
                            raise AttributionBlocked("rank displacement winner missing")
                        incumbent_rank_vector = list(incumbent["provider_evidence"]["rank"])
                        winner_rank_vector = list(winner_candidate["provider_evidence"]["rank"])
                        record.update({
                            "incumbent_current_rank": incumbent["candidate_rank"],
                            "winner_current_rank": winner_candidate["candidate_rank"],
                            "incumbent_rank_vector": incumbent_rank_vector,
                            "winner_rank_vector": winner_rank_vector,
                            "first_differing_rank_component": _first_rank_difference(incumbent_rank_vector, winner_rank_vector),
                            "candidate_set_id": current_context["candidate_set_ids"][role],
                        })
                    else:
                        winner_candidate = next(
                            (
                                line
                                for line in current_context["by_role"][role]
                                if line["line_id"] == new["line_id"]
                            ),
                            None,
                        )
                        record.update({
                            "incumbent_current_rank": incumbent.get("candidate_rank") if incumbent else None,
                            "winner_current_rank": winner_candidate.get("candidate_rank") if winner_candidate else None,
                            "incumbent_rank_vector": list(incumbent["provider_evidence"]["rank"]) if incumbent else None,
                            "winner_rank_vector": list(winner_candidate["provider_evidence"].get("rank", [])) if winner_candidate else None,
                            "first_differing_rank_component": None,
                            "candidate_set_id": current_context["candidate_set_ids"][role],
                        })
                    record["attribution_id"] = deterministic_hash(ATTRIBUTION_NAMESPACE, record)
                    records.append(record)
                    counts[label] = counts.get(label, 0) + 1
    canonical_replacements = sum(
        event.get("state") == "replacement"
        for membership in membership_by_dataset.values()
        for run in membership["checkpoints"]
        for provider_id in PRIMARY_PROVIDERS
        for event in run.get("provider_stability", {}).get(provider_id, ())
    )
    if len(records) != canonical_replacements:
        raise AttributionBlocked("replacement attribution count mismatch")
    return {"records": records, "cause_counts": counts, "attributed_replacement_count": len(records), "canonical_replacement_count": canonical_replacements, "unresolved_count": 0, "attribution_id": deterministic_hash(ATTRIBUTION_NAMESPACE, {"records": records, "cause_counts": counts})}


def _inversion_attribution(membership: Mapping[str, Any], scope: Any) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    persisted_metrics = phase11r1._load_json(
        PHASE11R1_ROOT / "datasets" / scope.dataset_id / "provider_metrics.json"
    )
    for run, cp in zip(membership["checkpoints"], scope.checkpoints):
        for provider_id in PRIMARY_PROVIDERS:
            selected = {line["role"]: line for line in run["outputs"][provider_id]}
            if set(selected) != set(ROLES):
                continue
            checkpoint = phase11r1._parse_iso(run["checkpoint"], field="checkpoint")
            if _line_projection(selected["support"], checkpoint) <= _line_projection(selected["resistance"], checkpoint):
                continue
            seeds = phase11r1._seed_pool(cp.data, prefix_last_position=cp.prefix_last_position, checkpoint=cp.checkpoint)
            candidates = _hierarchical_candidates(seeds, cp) if provider_id == PRIMARY_PROVIDERS[0] else _all_theil_candidates(seeds, cp)
            by_role = {role: [line for line in candidates if line["role"] == role] for role in ROLES}
            ranks = {role: next((line["candidate_rank"] for line in by_role[role] if line["line_id"] == selected[role]["line_id"]), None) for role in ROLES}
            if any(value is None for value in ranks.values()):
                raise AttributionBlocked("selected inverted line missing from eligible candidate list")
            if ranks != {"support": 1, "resistance": 1}:
                raise AttributionBlocked("inversion requires rank-one selected lines")
            combinations_rows: list[dict[str, Any]] = []
            for support in by_role["support"]:
                for resistance in by_role["resistance"]:
                    support_projection = _line_projection(support, checkpoint)
                    resistance_projection = _line_projection(resistance, checkpoint)
                    combinations_rows.append({"support_line_id": support["line_id"], "resistance_line_id": resistance["line_id"], "support_rank": support["candidate_rank"], "resistance_rank": resistance["candidate_rank"], "support_projection": support_projection, "resistance_projection": resistance_projection, "projection_gap": support_projection - resistance_projection, "inverted": support_projection > resistance_projection})
            non_inverted = [row for row in combinations_rows if not row["inverted"]]
            label = "INDEPENDENT_ROLE_RANKING_SELECTED_INVERTED_PAIR" if non_inverted else "NO_NON_INVERTED_ELIGIBLE_COMBINATION"
            closest = None
            if non_inverted:
                closest = sorted(non_inverted, key=lambda row: (row["support_rank"] - 1 + row["resistance_rank"] - 1, row["support_rank"], row["resistance_rank"], row["support_line_id"], row["resistance_line_id"]))[0]
            selected_support_projection = _line_projection(selected["support"], checkpoint)
            selected_resistance_projection = _line_projection(selected["resistance"], checkpoint)
            row = {"dataset_id": scope.dataset_id, "checkpoint_index": run["checkpoint_index"], "provider_id": provider_id, "role_pair": ["support", "resistance"], "candidate_set_ids": {role: deterministic_hash(ATTRIBUTION_NAMESPACE, {"dataset_id": scope.dataset_id, "checkpoint_index": run["checkpoint_index"], "provider_id": provider_id, "role": role, "line_ids": [line["line_id"] for line in by_role[role]]}) for role in ROLES}, "selected_support_line_id": selected["support"]["line_id"], "selected_resistance_line_id": selected["resistance"]["line_id"], "selected_support_rank": ranks["support"], "selected_resistance_rank": ranks["resistance"], "selected_support_projection": selected_support_projection, "selected_resistance_projection": selected_resistance_projection, "total_combination_count": len(combinations_rows), "non_inverted_combination_count": len(non_inverted), "combinations": combinations_rows, "closest_non_inverted_pair": closest, "rank_penalty": (closest["support_rank"] - 1 + closest["resistance_rank"] - 1) if closest else None, "support_only_resolves": any(not combination["inverted"] and combination["resistance_line_id"] == selected["resistance"]["line_id"] for combination in combinations_rows), "resistance_only_resolves": any(not combination["inverted"] and combination["support_line_id"] == selected["support"]["line_id"] for combination in combinations_rows), "classification": label}
            row["attribution_id"] = deterministic_hash(ATTRIBUTION_NAMESPACE, row)
            records.append(row)
    derived_by_provider = {
        provider_id: sum(record["provider_id"] == provider_id for record in records)
        for provider_id in PRIMARY_PROVIDERS
    }
    canonical_by_provider = {
        provider_id: persisted_metrics[provider_id]["channel_inversion_count"]
        for provider_id in PRIMARY_PROVIDERS
    }
    if derived_by_provider != canonical_by_provider:
        raise AttributionBlocked(
            f"inversion count reconciliation mismatch: {scope.dataset_id}"
        )
    return {"records": records, "inversion_count": len(records), "derived_inversion_count_by_provider": derived_by_provider, "canonical_inversion_count_by_provider": canonical_by_provider, "existing_non_inverted_count": sum(bool(record["non_inverted_combination_count"]) for record in records), "attribution_id": deterministic_hash(ATTRIBUTION_NAMESPACE, {"records": records, "derived_inversion_count_by_provider": derived_by_provider, "canonical_inversion_count_by_provider": canonical_by_provider})}


def _survival_regret(membership: Mapping[str, Any], scope: Any, provider_id: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    wins = losses = ties = 0
    reconciliation: dict[str, dict[str, int | float]] = {
        str(horizon): {
            "matched_count": 0,
            "primary_survival_count": 0,
            "control_survival_count": 0,
            "primary_wins": 0,
            "primary_losses": 0,
            "ties": 0,
        }
        for horizon in HORIZONS_HOURS
    }
    for run, cp in zip(membership["checkpoints"], scope.checkpoints):
        primary_by_role = {line["role"]: line for line in run["outputs"][provider_id]}
        control_by_role = {line["role"]: line for line in run["outputs"][CONTROL_PROVIDER]}
        for role in ROLES:
            if role not in primary_by_role or role not in control_by_role:
                continue
            primary = primary_by_role[role]
            control = control_by_role[role]
            for horizon in HORIZONS_HOURS:
                p_outcome = primary["future_evaluation"][str(horizon)]
                c_outcome = control["future_evaluation"][str(horizon)]
                p_survives = bool(p_outcome["survives_tolerant_owner_tf"])
                c_survives = bool(c_outcome["survives_tolerant_owner_tf"])
                summary = reconciliation[str(horizon)]
                summary["matched_count"] += 1
                summary["primary_survival_count"] += int(p_survives)
                summary["control_survival_count"] += int(c_survives)
                if p_survives == c_survives:
                    ties += 1
                    summary["ties"] += 1
                    continue
                label = "PRIMARY_SURVIVE_CONTROL_FAIL" if p_survives else "PRIMARY_FAIL_CONTROL_SURVIVE"
                if p_survives:
                    wins += 1
                    summary["primary_wins"] += 1
                else:
                    losses += 1
                    summary["primary_losses"] += 1
                p_slope = abs(float(primary["slope_per_second"])) * 86400 / float(cp.data.close[cp.prefix_last_position]) * 10000
                c_slope = abs(float(control["slope_per_second"])) * 86400 / float(cp.data.close[cp.prefix_last_position]) * 10000
                record = {"dataset_id": scope.dataset_id, "provider_id": provider_id, "checkpoint_index": run["checkpoint_index"], "checkpoint": run["checkpoint"], "role": role, "horizon_hours": horizon, "classification": label, "primary_line_id": primary["line_id"], "control_line_id": control["line_id"], "primary": {"projection": primary["projected_price_at_checkpoint"], "current_distance_atr": primary["current_distance_atr"], "structural_span_hours": primary["structural_span_hours"], "touch_or_inlier_count": primary["touch_or_inlier_count"], "absolute_slope_bps_per_day": p_slope, "anchor_ids": [p["pivot_id"] for p in primary["anchor_pivots"]], "first_contact_offset_bars": p_outcome["first_contact_offset_bars"], "first_sustained_breach_offset_bars": p_outcome["first_sustained_breach_offset_bars"], "reaction": p_outcome["has_role_consistent_reaction"], "survival": p_survives}, "control": {"projection": control["projected_price_at_checkpoint"], "current_distance_atr": control["current_distance_atr"], "structural_span_hours": control["structural_span_hours"], "touch_or_inlier_count": control["touch_or_inlier_count"], "absolute_slope_bps_per_day": c_slope, "anchor_ids": [p["pivot_id"] for p in control["anchor_pivots"]], "first_contact_offset_bars": c_outcome["first_contact_offset_bars"], "first_sustained_breach_offset_bars": c_outcome["first_sustained_breach_offset_bars"], "reaction": c_outcome["has_role_consistent_reaction"], "survival": c_survives}, "signed_differences": {"current_distance_atr": primary["current_distance_atr"] - control["current_distance_atr"], "structural_span_hours": primary["structural_span_hours"] - control["structural_span_hours"], "touch_count": primary["touch_or_inlier_count"] - control["touch_or_inlier_count"], "absolute_slope_bps_per_day": p_slope - c_slope}}
                record["regret_id"] = deterministic_hash(ATTRIBUTION_NAMESPACE, record)
                records.append(record)
    for summary in reconciliation.values():
        summary["survival_delta"] = (
            summary["primary_survival_count"] / summary["matched_count"]
            - summary["control_survival_count"] / summary["matched_count"]
            if summary["matched_count"]
            else 0.0
        )
    return {"provider_id": provider_id, "horizons_hours": list(HORIZONS_HOURS), "records": records, "primary_wins": wins, "primary_losses": losses, "ties": ties, "reconciliation": reconciliation, "attribution_id": deterministic_hash(ATTRIBUTION_NAMESPACE, {"provider_id": provider_id, "records": records, "primary_wins": wins, "primary_losses": losses, "ties": ties, "reconciliation": reconciliation})}


def _reconcile_survival_with_phase11r1(
    membership: Mapping[str, Any],
    result: Mapping[str, Any],
    dataset_id: str,
    provider_id: str,
) -> dict[str, Any]:
    metrics = phase11r1._load_json(
        PHASE11R1_ROOT / "datasets" / dataset_id / "provider_metrics.json"
    )[provider_id]
    _, control_lines, matched_keys = phase11r1._matched_control_lines(
        membership["checkpoints"],
        primary_provider_id=provider_id,
        control_provider_id=CONTROL_PROVIDER,
    )
    expected_control = phase11r1._outcome_rates(control_lines)
    checks: dict[str, bool] = {}
    for horizon in HORIZONS_HOURS:
        key = str(horizon)
        actual = result["reconciliation"][key]
        expected_delta = metrics["deltas_vs_latest_wide"][key]["survival_delta"]
        expected_control_count = metrics["matched_latest_wide_outcomes"][key]["survival_success_count"]
        checks[key] = (
            actual["matched_count"] == len(matched_keys)
            and actual["control_survival_count"] == expected_control_count
            and actual["survival_delta"] == expected_delta
            and expected_control[key]["sample_count"] == len(matched_keys)
        )
    if not all(checks.values()):
        raise AttributionBlocked(
            f"matched survival reconciliation mismatch: {dataset_id}/{provider_id}"
        )
    return {
        "matched_sample_count": len(matched_keys),
        "matched_sample_keys": [list(key) for key in matched_keys],
        "checks": checks,
        "phase11r1_delta": {
            key: metrics["deltas_vs_latest_wide"][key]["survival_delta"]
            for key in map(str, HORIZONS_HOURS)
        },
    }


def _coverage_cases(membership: Mapping[str, Any]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for run in membership["checkpoints"]:
        for provider_id in PRIMARY_PROVIDERS:
            roles = {line["role"] for line in run["outputs"][provider_id]}
            for role in ROLES:
                if role not in roles:
                    cases.append({"checkpoint_index": run["checkpoint_index"], "role": role, "provider_id": provider_id})
    return cases


def _source_snapshot() -> dict[str, Any]:
    phase11r1_inventory = _inventory(PHASE11R1_ROOT)
    phase11r1_members = tuple(
        item for item in phase11r1_inventory if item["path"] != "manifest.json"
    )
    if _inventory_sha256(phase11r1_members) != PHASE11R1_INVENTORY:
        raise AttributionBlocked("Phase 11R.1 source inventory changed")
    return {
        "phase11r1_bundle_inventory_sha256": _inventory_sha256(phase11r1_members),
        "allowed_raw_inventory_sha256": _inventory_sha256(_allowed_raw_inventory()),
        "phase11r1_script_sha256": _sha256_file(Path(phase11r1.__file__).resolve()),
    }


def _build_source_audit(
    *,
    source_before: Mapping[str, Any] | None = None,
    source_after: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if source_before is None:
        source_before = _source_snapshot()
    if source_after is None:
        source_after = source_before
    if dict(source_before) != dict(source_after):
        raise AttributionBlocked("source inventory or script changed during attribution")
    payload = {
        "schema_version": "trendline_v2_phase11r2_source_audit_v1",
        "phase11r1": {"root": str(PHASE11R1_ROOT), "contract_id": PHASE11R1_CONTRACT_ID, "decision_id": PHASE11R1_DECISION_ID, "manifest_id": PHASE11R1_MANIFEST_ID, "inventory_sha256": PHASE11R1_INVENTORY, "validation_lock_id": PHASE11R1_LOCK_ID},
        "phase9c2": {"root": str(VALIDATION_ROOT), "decision_id": PHASE9C2_DECISION_ID, "manifest_id": PHASE9C2_MANIFEST_ID, "output_inventory_sha256": PHASE9C2_OUTPUT_INVENTORY, "source_inventory_sha256": PHASE9C2_SOURCE_INVENTORY, "allowed_raw_inventory_sha256": PHASE9C2_RAW_FILE_INVENTORY, "allowed_raw_paths": list(EXPECTED_ALLOWED_RAW_PATHS)},
        "loaded_dataset_ids": list(VALIDATION_DATASETS),
        "holdout_accessed": False,
        "temporal_accessed": False,
        "network_request_count": 0,
        "legacy_execution_count": 0,
        "runtime_v2_provider_execution_count": 0,
        "attribution_checkpoint_reconstructions": EXPECTED_CHECKPOINT_RECONSTRUCTIONS,
        "raw_sui_accesses": 0,
        "phase11r1_persisted_sui_placeholder_reads_allowed": True,
        "phase9c2_raw_sui_reads_prohibited": True,
        "source_immutability": {
            "before": dict(source_before),
            "after": dict(source_after),
            "verified": True,
        },
    }
    return {**payload, "source_audit_id": deterministic_hash(SOURCE_AUDIT_NAMESPACE, payload)}


def _decision_payload(*, status: str, unresolved_count: int, flags: Mapping[str, Any], counts: Mapping[str, Any], unresolved_cases: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    payload = {
        "schema_version": "trendline_v2_phase11r2_decision_v1",
        "study_status": status,
        "study_contract_id": CONTRACT_ID,
        "phase11r1_decision_id": PHASE11R1_DECISION_ID,
        "unresolved_count": unresolved_count,
        "unresolved_cases": [dict(case) for case in unresolved_cases],
        "evidence_flags": dict(flags),
        "reconciliation_counts": dict(counts),
        "holdout_accessed": False,
        "temporal_accessed": False,
        "network_request_count": 0,
        "legacy_execution_count": 0,
        "runtime_v2_provider_execution_count": 0,
    }
    return {**payload, "decision_id": deterministic_hash(DECISION_NAMESPACE, payload)}


def _manifest_from_members(
    members: Sequence[Mapping[str, Any]], decision: Mapping[str, Any]
) -> dict[str, Any]:
    expected = tuple(item for item in EXPECTED_ARTIFACT_PATHS if item != "manifest.json")
    if tuple(item["path"] for item in members) != expected:
        raise AttributionError("attribution artifact path set mismatch")
    payload = {"schema_version": "trendline_v2_phase11r2_manifest_v1", "study_contract_id": CONTRACT_ID, "decision_id": decision["decision_id"], "member_count": len(members), "members": list(members), "output_inventory_sha256": _inventory_sha256(members)}
    return {**payload, "manifest_id": deterministic_hash(MANIFEST_NAMESPACE, payload)}


def _manifest(staging: Path, decision: Mapping[str, Any]) -> dict[str, Any]:
    members = tuple(item for item in _inventory(staging) if item["path"] != "manifest.json")
    return _manifest_from_members(members, decision)


def _evidence_member_bytes(evidence: Mapping[str, Any]) -> dict[str, bytes]:
    members: dict[str, bytes] = {
        "study_contract.json": _canonical_bytes(evidence["study_contract"]),
        "source_audit.json": _canonical_bytes(evidence["source_audit"]),
        "decision.json": _canonical_bytes(evidence["decision"]),
    }
    for dataset in VALIDATION_DATASETS:
        for member, payload in evidence["dataset_payloads"][dataset].items():
            members[f"datasets/{dataset}/{member}.json"] = _canonical_bytes(payload)
    members.update(evidence["csv"])
    return members


def _evidence_member_inventory(evidence: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    member_bytes = _evidence_member_bytes(evidence)
    expected_paths = tuple(
        path for path in EXPECTED_ARTIFACT_PATHS if path != "manifest.json"
    )
    if tuple(sorted(member_bytes)) != expected_paths:
        raise AttributionError("derived evidence path set mismatch")
    return tuple(
        {
            "path": path,
            "byte_length": len(member_bytes[path]),
            "sha256": _sha256_bytes(member_bytes[path]),
        }
        for path in expected_paths
    )


def _derive_attribution(
    scopes: Mapping[str, Any],
    memberships: Mapping[str, Mapping[str, Any]],
    *,
    source_before: Mapping[str, Any],
) -> dict[str, Any]:
    """Pure research-local derivation used by generation and verification."""
    funnels: dict[str, list[dict[str, Any]]] = {dataset: [] for dataset in VALIDATION_DATASETS}
    theil_attrition: dict[str, list[dict[str, Any]]] = {dataset: [] for dataset in VALIDATION_DATASETS}
    for dataset in VALIDATION_DATASETS:
        scope = scopes[dataset]
        for repeat in range(2):
            runs = [_funnel_for_checkpoint(cp) for cp in scope.checkpoints]
            if repeat == 0:
                funnels[dataset] = runs
            elif runs != funnels[dataset]:
                raise AttributionBlocked("repeated funnel reconstruction differs")
            for run, canonical in zip(runs, memberships[dataset]["checkpoints"]):
                for role in ROLES:
                    expected = canonical["seed_pool_counts"][role]
                    if run["roles"][role]["final_seed_count"] != expected:
                        raise AttributionBlocked("seed count does not reproduce Phase 11R.1")
                if repeat == 0:
                    theil_attrition[dataset].append(
                        _theil_attrition_for_checkpoint(
                            scope.checkpoints[run["checkpoint_index"] - 1], canonical
                        )
                    )
    churn = _churn_attribution(memberships, scopes)
    inversions = {dataset: _inversion_attribution(memberships[dataset], scopes[dataset]) for dataset in VALIDATION_DATASETS}
    regrets = {dataset: {provider: _survival_regret(memberships[dataset], scopes[dataset], provider) for provider in PRIMARY_PROVIDERS} for dataset in VALIDATION_DATASETS}
    for dataset in VALIDATION_DATASETS:
        for provider in PRIMARY_PROVIDERS:
            regrets[dataset][provider]["canonical_reconciliation"] = _reconcile_survival_with_phase11r1(memberships[dataset], regrets[dataset][provider], dataset, provider)
    coverage: dict[str, list[dict[str, Any]]] = {}
    unresolved_cases: list[dict[str, Any]] = []
    for dataset in VALIDATION_DATASETS:
        coverage[dataset] = []
        funnel_by_index = {
            run["checkpoint_index"]: run for run in funnels[dataset]
        }
        for case in _coverage_cases(memberships[dataset]):
            funnel_role = funnel_by_index[case["checkpoint_index"]]["roles"][case["role"]]
            if funnel_role["label"] not in FUNNEL_LABELS:
                unresolved_cases.append(
                    {
                        **case,
                        "kind": "coverage",
                        "reason": "unknown_funnel_label",
                        "funnel_label": funnel_role["label"],
                    }
                )
                continue
            final_seed_count = funnel_role["final_seed_count"]
            if final_seed_count == 0:
                origin = "COMMON_SEED_POOL_EMPTY"
                cause = funnel_role["label"]
            elif case["provider_id"] == PRIMARY_PROVIDERS[0]:
                raise AttributionBlocked(
                    "hierarchical coverage missing despite common seed pool"
                )
            else:
                checkpoint_attrition = theil_attrition[dataset][
                    case["checkpoint_index"] - 1
                ]
                terminal = next(
                    (
                        trace["status"]
                        for trace in checkpoint_attrition["traces"]
                        if trace["role"] == case["role"]
                        and trace["status"] in THEIL_FAILURE_LABELS
                    ),
                    None,
                )
                if terminal is None:
                    raise AttributionBlocked(
                        "Theil coverage failure has no terminal attribution"
                    )
                origin = "METHOD_SPECIFIC_ATTRITION"
                cause = terminal
            coverage[dataset].append(
                {
                    **case,
                    "attribution_label": cause,
                    "cause": cause,
                    "final_seed_count": final_seed_count,
                    "origin": origin,
                }
            )
    flags = {"coverage_failures_originating_in_common_seed_pool": any(case["origin"] == "COMMON_SEED_POOL_EMPTY" for cases in coverage.values() for case in cases), "method_specific_fit_attrition_present": any(any(trace.get("status") not in {"CANDIDATE_AVAILABLE", "DEDUPED_BY_LOWER_SEED_ID"} for checkpoint in dataset for trace in checkpoint["traces"]) for dataset in theil_attrition.values()), "observed_inversion_has_existing_non_inverted_combination": any(value["existing_non_inverted_count"] for value in inversions.values()), "rank_displacement_replacement_count": churn["cause_counts"].get("INCUMBENT_ELIGIBLE_RANK_DISPLACED", 0), "incumbent_eligibility_loss_count": sum(value for key, value in churn["cause_counts"].items() if key.startswith("INCUMBENT_SEED_LOST_")), "same_origin_geometry_drift_count": churn["cause_counts"].get("SAME_ORIGIN_GEOMETRY_DRIFT", 0), "matched_survival_primary_win_count": sum(value["primary_wins"] for dataset in regrets.values() for value in dataset.values()), "matched_survival_primary_loss_count": sum(value["primary_losses"] for dataset in regrets.values() for value in dataset.values())}
    counts = {"coverage_case_count": sum(len(value) for value in coverage.values()), "attributed_replacement_count": churn["attributed_replacement_count"], "canonical_replacement_count": churn["canonical_replacement_count"], "inversion_case_count": sum(value["inversion_count"] for value in inversions.values()), "survival_regret_case_count": sum(len(value["records"]) for dataset in regrets.values() for value in dataset.values()), "survival_reconciliation_count": sum(len(value["canonical_reconciliation"]["checks"]) for dataset in regrets.values() for value in dataset.values())}
    source_after = _source_snapshot()
    completion_checks = {"coverage": not unresolved_cases, "replacements": churn["attributed_replacement_count"] == churn["canonical_replacement_count"], "inversions": all(value["derived_inversion_count_by_provider"] == value["canonical_inversion_count_by_provider"] for value in inversions.values()), "survival": all(check for dataset in regrets.values() for value in dataset.values() for check in value["canonical_reconciliation"]["checks"].values()), "seeds": all(run["roles"][role]["final_seed_count"] == len(run["roles"][role]["final_seed_ids"]) for runs in funnels.values() for run in runs for role in ROLES), "source_immutable": dict(source_before) == dict(source_after)}
    for check_name, passed in completion_checks.items():
        if not passed:
            unresolved_cases.append({"kind": "completion_check", "check": check_name})
    unresolved = len(unresolved_cases)
    status = "SPARSE_GEOMETRY_FAILURE_ATTRIBUTION_COMPLETE" if unresolved == 0 else "SPARSE_GEOMETRY_FAILURE_ATTRIBUTION_INCOMPLETE"
    counts["unresolved_case_count"] = unresolved
    decision = _decision_payload(status=status, unresolved_count=unresolved, flags=flags, counts=counts, unresolved_cases=unresolved_cases)
    source_audit = _build_source_audit(source_before=source_before, source_after=source_after)
    dataset_payloads: dict[str, dict[str, Any]] = {}
    for dataset in VALIDATION_DATASETS:
        dataset_payloads[dataset] = {"seed_funnel": {"dataset_id": dataset, "checkpoints": funnels[dataset], "coverage_cases": coverage[dataset], "theil_sen_attrition": theil_attrition[dataset], "study_id": deterministic_hash(ATTRIBUTION_NAMESPACE, {"checkpoints": funnels[dataset], "coverage_cases": coverage[dataset], "theil_sen_attrition": theil_attrition[dataset]})}, "churn_attribution": {"dataset_id": dataset, "records": [record for record in churn["records"] if record["dataset_id"] == dataset]}, "inversion_attribution": inversions[dataset], "survival_regret": regrets[dataset]}
    csv_rows = [{"dataset_id": dataset, "checkpoint_index": run["checkpoint_index"], "role": role, "label": run["roles"][role]["label"], "final_seed_count": run["roles"][role]["final_seed_count"], "first_zero_stage": run["roles"][role]["first_zero_stage"]} for dataset, runs in funnels.items() for run in runs for role in ROLES]
    churn_grouped: dict[tuple[str, str, str], int] = {}
    for record in churn["records"]:
        key = (record["dataset_id"], record["provider_id"], record["cause"])
        churn_grouped[key] = churn_grouped.get(key, 0) + 1
    churn_rows = [{"dataset_id": dataset, "provider_id": provider, "cause": cause, "count": count} for (dataset, provider, cause), count in sorted(churn_grouped.items())]
    inversion_rows = [{"dataset_id": dataset, "inversion_count": inversions[dataset]["inversion_count"], "existing_non_inverted_count": inversions[dataset]["existing_non_inverted_count"]} for dataset in VALIDATION_DATASETS]
    regret_rows = [{"dataset_id": dataset, "provider_id": provider, "primary_wins": value["primary_wins"], "primary_losses": value["primary_losses"], "ties": value["ties"]} for dataset, values in regrets.items() for provider, value in values.items()]
    return {"status": status, "decision": decision, "source_audit": source_audit, "dataset_payloads": dataset_payloads, "csv": {"coverage_funnel_summary.csv": _csv_bytes(csv_rows), "churn_summary.csv": _csv_bytes(churn_rows or [{"dataset_id": "", "provider_id": "", "cause": "", "count": 0}]), "inversion_summary.csv": _csv_bytes(inversion_rows), "survival_regret_summary.csv": _csv_bytes(regret_rows)}, "study_contract": {"schema_version": "trendline_v2_phase11r2_study_contract_v1", "contract_id": CONTRACT_ID, "contract_json_sha256": CONTRACT_JSON_SHA256, "contract_json_byte_length": CONTRACT_JSON_BYTE_LENGTH, "payload": _contract_payload()}, "source_before": dict(source_before), "source_after": source_after}


def _write_attribution_bundle(staging: Path, evidence: Mapping[str, Any]) -> dict[str, Any]:
    _write_json(staging / "study_contract.json", evidence["study_contract"])
    _write_json(staging / "source_audit.json", evidence["source_audit"])
    for dataset in VALIDATION_DATASETS:
        for member, payload in evidence["dataset_payloads"][dataset].items():
            _write_json(staging / "datasets" / dataset / f"{member}.json", payload)
    for name, value in evidence["csv"].items():
        (staging / name).write_bytes(value)
    _write_json(staging / "decision.json", evidence["decision"])
    manifest = _manifest(staging, evidence["decision"])
    _write_json(staging / "manifest.json", manifest)
    return manifest


def _run_attribution(output_root: Path) -> dict[str, Any]:
    _assert_contract_triplet()
    _assert_phase11r1_dependency()
    _assert_phase11r1_bundle()
    source_before = _source_snapshot()
    scopes = {scope.dataset_id: scope for scope in _load_allowed_scope()}
    memberships = {dataset: _load_json(PHASE11R1_ROOT / "datasets" / dataset / "checkpoint_membership.json") for dataset in VALIDATION_DATASETS}
    evidence = _derive_attribution(scopes, memberships, source_before=source_before)
    manifest = _write_attribution_bundle(output_root, evidence)
    if _source_snapshot() != evidence["source_after"]:
        raise AttributionBlocked("source changed before attribution publication")
    return {"study_status": evidence["status"], "decision_id": evidence["decision"]["decision_id"], "manifest_id": manifest["manifest_id"], "output_inventory_sha256": manifest["output_inventory_sha256"], "attribution_checkpoint_reconstructions": EXPECTED_CHECKPOINT_RECONSTRUCTIONS}


def _verify_bundle(output_root: Path) -> dict[str, Any]:
    _assert_contract_triplet()
    if not output_root.is_dir():
        raise AttributionError(f"attribution bundle missing: {output_root}")
    _assert_phase11r1_dependency()
    _assert_phase11r1_bundle()
    source_before = _source_snapshot()
    scopes = {scope.dataset_id: scope for scope in _load_allowed_scope()}
    memberships = {
        dataset: _load_json(
            PHASE11R1_ROOT / "datasets" / dataset / "checkpoint_membership.json"
        )
        for dataset in VALIDATION_DATASETS
    }
    expected = _derive_attribution(
        scopes, memberships, source_before=source_before
    )
    actual = _inventory(output_root)
    if tuple(item["path"] for item in actual) != EXPECTED_ARTIFACT_PATHS:
        raise AttributionError("attribution bundle path set mismatch")
    expected_members = _evidence_member_inventory(expected)
    actual_members = tuple(item for item in actual if item["path"] != "manifest.json")
    if actual_members != expected_members:
        raise AttributionError("attribution evidence member inventory mismatch")
    expected_manifest = _manifest_from_members(
        expected_members, expected["decision"]
    )
    manifest = _load_json(output_root / "manifest.json")
    if manifest != expected_manifest:
        raise AttributionError("attribution manifest semantic mismatch")
    expected_manifest_item = {
        "path": "manifest.json",
        "byte_length": len(_canonical_bytes(expected_manifest)),
        "sha256": _sha256_bytes(_canonical_bytes(expected_manifest)),
    }
    expected_inventory = tuple(
        sorted((*expected_members, expected_manifest_item), key=lambda item: item["path"])
    )
    if actual != expected_inventory:
        raise AttributionError("attribution bundle inventory mismatch")
    for relative, expected_bytes in _evidence_member_bytes(expected).items():
        path = output_root / relative
        if path.read_bytes() != expected_bytes:
            raise AttributionError(f"attribution artifact content mismatch: {relative}")
    source_after = _source_snapshot()
    if source_after != expected["source_after"]:
        raise AttributionBlocked("source changed during attribution verification")
    if expected["source_audit"].get("source_immutability", {}).get("verified") is not True:
        raise AttributionError("source immutability was not verified")
    return {
        "study_status": expected["status"],
        "decision_id": expected["decision"]["decision_id"],
        "manifest_id": expected_manifest["manifest_id"],
        "output_inventory_sha256": expected_manifest["output_inventory_sha256"],
        "network_request_count": 0,
        "raw_sui_accesses": 0,
        "temporal_accesses": 0,
    }


def run_attribution(*, output_root: str | Path = OUTPUT_ROOT) -> dict[str, Any]:
    root = Path(output_root)
    if root.exists():
        raise FileExistsError(f"refusing existing attribution output root: {root}")
    if os.environ.get("TRENDLINE_V2_ALLOW_PHASE11R2_ATTRIBUTION") != "1":
        raise AttributionError("attribution execution requires TRENDLINE_V2_ALLOW_PHASE11R2_ATTRIBUTION=1")
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{root.name}.", dir=root.parent))
    try:
        result = _run_attribution(staging)
        staging.replace(root)
        return result
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-attribution", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    if args.execute_attribution == args.verify:
        parser.error("choose exactly one of --execute-attribution or --verify")
    try:
        result = run_attribution(output_root=args.output_root) if args.execute_attribution else _verify_bundle(args.output_root)
    except (AttributionError, FileExistsError, OSError) as exc:
        print(str(exc))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
