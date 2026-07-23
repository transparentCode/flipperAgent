"""Compare predeclared causal candidate-eligibility families.

This study consumes only the verified Phase 9B.1 artifact bundle. It never
calls a provider, evaluator, network adapter, model runtime, or viewer.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash


ASSET = "BTCUSDT"
TIMEFRAME = "4h"
SOURCE_ROOT = Path(
    "/private/tmp/trendline_v2_phase9b1_birth_evidence/"
    "btcusdt_4h_20250801_20251201"
)
OUTPUT_ROOT = Path(
    "/private/tmp/trendline_v2_phase9b2_eligibility_families/"
    "btcusdt_4h_20250801_20251201"
)

PHASE9B1_STUDY_ID = (
    "91604d9404fba7769380d8566d38192b20c987eac990d24733b87506acdd512f"
)
PHASE9B1_MANIFEST_ID = (
    "630481cbb07def66e08e6e1f4256c885a7d5f59b044efcba94eb2ca8783fbef4"
)
PHASE9B1_INVENTORY_SHA256 = (
    "a6c4ff28f05614a048099d83dbedc612e5d13192762d2f9c5c948564aac8d016"
)
PHASE9B1_SOURCE_IDENTITY = (
    "079b7cec1dde131fb91180ee910cdb84499d27bb4ac64cd1ca46eaf355fc0358"
)
PHASE9B1_PHASE9A_STUDY_ID = (
    "8b8ea045a5e14293224250602024a3234b91e023fbac4f70e0011d6c914f1f46"
)
EXPECTED_CANDIDATE_COUNT = 2697
EXPECTED_SUPPORT_COUNT = 1501
EXPECTED_RESISTANCE_COUNT = 1196
EXPECTED_SECOND_ANCHOR_GROUP_COUNT = 321
EXPECTED_ROW_COUNT = 732

REQUIRED_SOURCE_MEMBERS = (
    "candidate_records.json",
    "cohort_summary.csv",
    "decision.json",
    "feature_associations.json",
    "feature_contract.json",
    "manifest.json",
    "source_audit.json",
)
SOURCE_DATA_MEMBERS = tuple(
    name for name in REQUIRED_SOURCE_MEMBERS if name != "manifest.json"
)
EXPECTED_MEMBER_HASHES = {
    "candidate_records.json": "924c28bf44c0d5f7affee9a3136582bd6881ea0482875931ce40943d29dcd282",
    "cohort_summary.csv": "56d6f6aee611f72f93c66e75490f39abe07ed388868f29a2123f4f876f8c4291",
    "decision.json": "eed4b28c9e23319f65f301cbe079de4e4a9a25059eef47ec98eddb7f64b12104",
    "feature_associations.json": "38c0c94a813526604bc81514c82f74a69235612a5b17f074b95697bebd75ac63",
    "feature_contract.json": "224023d466c2b131c8bde05a448796819bedaf44a9c7754e3e091962ab341545",
    "source_audit.json": "3e7008d739cdcd3b948a8801283c3538c47f8483bc27d2b1683e6ad29df8b2b7",
}

HORIZONS = (6, 12, 24)
ROLES = ("support", "resistance")
SEGMENTS = ("early", "late")

SELECTOR_FIELDS = (
    "candidate_id",
    "candidate_structure_id",
    "role",
    "first_anchor_id",
    "second_anchor_id",
    "first_anchor_time",
    "second_anchor_time",
    "same_role_extrema_skip_count",
    "minimum_body_clearance_bps",
    "minimum_anchor_prominence_bps",
)
FORBIDDEN_SELECTOR_FIELDS = (
    "evaluations",
    "future_contact_count",
    "future_body_violation_count",
    "has_exact_contact",
    "survives_exact_side",
    "contact_and_survives_exact_side",
    "first_contact_offset_bars",
    "first_body_violation_offset_bars",
    "chronological_outcome_aggregates",
)

FAMILY_DEFINITIONS = (
    {
        "family_id": "all_candidates_control_v1",
        "kind": "control",
        "membership": "all persisted Phase 9B.1 birth records",
    },
    {
        "family_id": "adjacent_extrema_only_v1",
        "kind": "predicate",
        "membership": "same_role_extrema_skip_count == 0",
    },
    {
        "family_id": "skip_le_1_v1",
        "kind": "predicate",
        "membership": "same_role_extrema_skip_count <= 1",
    },
    {
        "family_id": "skip_le_3_v1",
        "kind": "predicate",
        "membership": "same_role_extrema_skip_count <= 3",
    },
    {
        "family_id": "latest_valid_predecessor_v1",
        "kind": "one_per_second_anchor",
        "membership": "greatest first_anchor_time, then structure ID, then candidate ID",
    },
    {
        "family_id": "earliest_valid_predecessor_v1",
        "kind": "one_per_second_anchor",
        "membership": "smallest first_anchor_time, then structure ID, then candidate ID",
    },
    {
        "family_id": "max_minimum_body_clearance_v1",
        "kind": "one_per_second_anchor",
        "membership": "greatest minimum_body_clearance_bps, then structure ID, then candidate ID",
    },
    {
        "family_id": "max_minimum_anchor_prominence_v1",
        "kind": "one_per_second_anchor",
        "membership": "greatest minimum_anchor_prominence_bps, then structure ID, then candidate ID",
    },
)
FAMILY_IDS = tuple(item["family_id"] for item in FAMILY_DEFINITIONS)
SELECTOR_CONTRACT_ID = deterministic_hash(
    "trendline_v2_phase_9b2_selector_contract_v1",
    {
        "schema_version": "trendline_v2_phase_9b2_selector_contract_v1",
        "allowed_fields": list(SELECTOR_FIELDS),
        "forbidden_fields": list(FORBIDDEN_SELECTOR_FIELDS),
        "families": list(FAMILY_DEFINITIONS),
    },
)


class StudyArtifactError(ValueError):
    """Raised when immutable study evidence fails validation."""


@dataclass(frozen=True)
class StudyBinding:
    """Expected source identity, population and member hashes."""

    study_id: str
    manifest_id: str
    inventory_sha256: str
    source_identity: str
    phase9a_study_id: str
    candidate_count: int
    support_count: int
    resistance_count: int
    second_anchor_group_count: int
    row_count: int
    member_hashes: Mapping[str, str]


REAL_BINDING = StudyBinding(
    study_id=PHASE9B1_STUDY_ID,
    manifest_id=PHASE9B1_MANIFEST_ID,
    inventory_sha256=PHASE9B1_INVENTORY_SHA256,
    source_identity=PHASE9B1_SOURCE_IDENTITY,
    phase9a_study_id=PHASE9B1_PHASE9A_STUDY_ID,
    candidate_count=EXPECTED_CANDIDATE_COUNT,
    support_count=EXPECTED_SUPPORT_COUNT,
    resistance_count=EXPECTED_RESISTANCE_COUNT,
    second_anchor_group_count=EXPECTED_SECOND_ANCHOR_GROUP_COUNT,
    row_count=EXPECTED_ROW_COUNT,
    member_hashes=EXPECTED_MEMBER_HASHES,
)


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError(f"non-finite JSON constant: {value}")


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise StudyArtifactError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict):
        raise StudyArtifactError(f"artifact must be an object: {path}")
    if path.read_bytes() != _canonical_bytes(value):
        raise StudyArtifactError(f"artifact is not canonical JSON: {path}")
    return value


def _require_equal(actual: object, expected: object, *, field_name: str) -> None:
    if actual != expected:
        raise StudyArtifactError(
            f"source validation mismatch for {field_name}: {actual!r} != {expected!r}"
        )


def _finite_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StudyArtifactError(f"{field_name} is not numeric")
    result = float(value)
    if not math.isfinite(result):
        raise StudyArtifactError(f"{field_name} is not finite")
    return result


def _iso_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise StudyArtifactError(f"{field_name} is not canonical UTC")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise StudyArtifactError(f"{field_name} is not canonical UTC") from exc


def _safe_relative_path(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise StudyArtifactError(f"{field_name} is unsafe")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise StudyArtifactError(f"{field_name} is unsafe")
    if str(path) != value or "\\" in value:
        raise StudyArtifactError(f"{field_name} is not canonical")
    return value


def _artifact_inventory(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir() or root.is_symlink():
        raise StudyArtifactError(f"BLOCKED_SOURCE_ARTIFACT: missing root {root}")
    paths = sorted(root.rglob("*"), key=lambda path: str(path.relative_to(root)))
    if any(path.is_symlink() for path in paths):
        raise StudyArtifactError(f"source tree contains symlink: {root}")
    inventory: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            continue
        relative = _safe_relative_path(
            str(path.relative_to(root)), field_name="inventory path"
        )
        inventory.append(
            {
                "path": relative,
                "byte_length": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return inventory


def _inventory_digest(inventory: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_bytes(_canonical_bytes(list(inventory)))


def _validate_canonical_json_tree(root: Path) -> None:
    for path in sorted(root.rglob("*.json")):
        _load_json(path)


def _validate_member_hashes(
    root: Path,
    manifest: Mapping[str, Any],
    binding: StudyBinding,
) -> None:
    members = manifest.get("members")
    if not isinstance(members, list):
        raise StudyArtifactError("source manifest members are invalid")
    member_paths: list[str] = []
    for index, member in enumerate(members):
        if not isinstance(member, dict):
            raise StudyArtifactError(f"source manifest member {index} is invalid")
        path = _safe_relative_path(member.get("path"), field_name="manifest member path")
        member_paths.append(path)
        if not isinstance(member.get("byte_length"), int) or isinstance(
            member.get("byte_length"), bool
        ) or member["byte_length"] < 0:
            raise StudyArtifactError("source manifest member size is invalid")
        sha = member.get("sha256")
        if not isinstance(sha, str) or len(sha) != 64 or sha != sha.lower():
            raise StudyArtifactError("source manifest member hash is invalid")
        file_path = root / path
        if not file_path.is_file():
            raise StudyArtifactError(f"source manifest member missing: {path}")
        _require_equal(file_path.stat().st_size, member["byte_length"], field_name=f"size:{path}")
        _require_equal(_sha256_file(file_path), sha, field_name=f"sha256:{path}")
        if path not in binding.member_hashes:
            raise StudyArtifactError(f"unexpected source member: {path}")
        _require_equal(binding.member_hashes[path], sha, field_name=f"approved sha256:{path}")
    if tuple(member_paths) != tuple(sorted(set(member_paths))):
        raise StudyArtifactError("source manifest members are not sorted and unique")
    _require_equal(tuple(member_paths), tuple(sorted(SOURCE_DATA_MEMBERS)), field_name="source data members")


def _validate_record(record: Mapping[str, Any], *, row_count: int) -> None:
    required = {
        "candidate_id",
        "candidate_structure_id",
        "role",
        "first_anchor_id",
        "second_anchor_id",
        "first_anchor_time",
        "second_anchor_time",
        "candidate_available_at",
        "anchor_source_positions",
        "chronological_segment",
        "same_role_extrema_skip_count",
        "minimum_body_clearance_bps",
        "minimum_anchor_prominence_bps",
        "evaluations",
    }
    missing = required.difference(record)
    if missing:
        raise StudyArtifactError(f"candidate record missing fields: {sorted(missing)}")
    for name in (
        "candidate_id",
        "candidate_structure_id",
        "first_anchor_id",
        "second_anchor_id",
    ):
        if not isinstance(record[name], str) or not record[name]:
            raise StudyArtifactError(f"candidate record {name} is invalid")
    if record["role"] not in ROLES or record["chronological_segment"] not in SEGMENTS:
        raise StudyArtifactError("candidate record role or segment is invalid")
    _iso_datetime(record["first_anchor_time"], field_name="first_anchor_time")
    _iso_datetime(record["second_anchor_time"], field_name="second_anchor_time")
    _iso_datetime(record["candidate_available_at"], field_name="candidate_available_at")
    positions = record["anchor_source_positions"]
    if (
        not isinstance(positions, list)
        or len(positions) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in positions)
        or positions[0] < 0
        or positions[1] <= positions[0]
        or positions[1] >= row_count
    ):
        raise StudyArtifactError("candidate anchor source positions are invalid")
    skip = record["same_role_extrema_skip_count"]
    if isinstance(skip, bool) or not isinstance(skip, int) or skip < 0:
        raise StudyArtifactError("candidate skip count is invalid")
    _finite_number(record["minimum_body_clearance_bps"], field_name="minimum body clearance")
    _finite_number(record["minimum_anchor_prominence_bps"], field_name="minimum anchor prominence")
    evaluations = record["evaluations"]
    if not isinstance(evaluations, dict) or set(evaluations) != {str(h) for h in HORIZONS}:
        raise StudyArtifactError("candidate evaluations are invalid")
    for horizon in HORIZONS:
        evaluation = evaluations[str(horizon)]
        if not isinstance(evaluation, dict):
            raise StudyArtifactError("candidate evaluation is invalid")
        available = evaluation.get("evaluation_available")
        if not isinstance(available, bool):
            raise StudyArtifactError("evaluation availability is invalid")
        fields = (
            "future_contact_count",
            "future_body_violation_count",
        )
        if available:
            for field in fields:
                value = evaluation.get(field)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise StudyArtifactError(f"evaluation {field} is invalid")
            for field in ("has_exact_contact", "survives_exact_side", "contact_and_survives_exact_side"):
                if not isinstance(evaluation.get(field), bool):
                    raise StudyArtifactError(f"evaluation {field} is invalid")
        else:
            for field in fields:
                if evaluation.get(field) is not None:
                    raise StudyArtifactError(f"unavailable evaluation {field} must be null")


def _validate_source(
    source_root: Path,
    *,
    binding: StudyBinding,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], list[dict[str, Any]]]:
    _validate_canonical_json_tree(source_root)
    inventory = _artifact_inventory(source_root)
    _require_equal(_inventory_digest(inventory), binding.inventory_sha256, field_name="Phase 9B.1 inventory")
    _require_equal(
        tuple(item["path"] for item in inventory),
        tuple(sorted(REQUIRED_SOURCE_MEMBERS)),
        field_name="Phase 9B.1 member set",
    )
    manifest = _load_json(source_root / "manifest.json")
    manifest_without_id = dict(manifest)
    manifest_id = manifest_without_id.pop("manifest_id", None)
    _require_equal(manifest_id, binding.manifest_id, field_name="Phase 9B.1 manifest ID")
    _require_equal(
        deterministic_hash("trendline_v2_phase_9b1_manifest", manifest_without_id),
        manifest_id,
        field_name="Phase 9B.1 manifest hash",
    )
    _validate_member_hashes(source_root, manifest, binding)
    _require_equal(manifest.get("study_id"), binding.study_id, field_name="Phase 9B.1 study ID")
    _require_equal(manifest.get("source_identity"), binding.source_identity, field_name="source identity")
    _require_equal(manifest.get("candidate_count"), binding.candidate_count, field_name="candidate count")
    _require_equal(manifest.get("provider_execution_count"), 0, field_name="provider execution count")
    _require_equal(manifest.get("network_request_count"), 0, field_name="network request count")

    source_audit = _load_json(source_root / "source_audit.json")
    _require_equal(source_audit.get("source_identity"), binding.source_identity, field_name="audit source identity")
    _require_equal(source_audit.get("source_immutability_verified"), True, field_name="source immutability")
    _require_equal(source_audit.get("provider_execution_count"), 0, field_name="audit provider executions")
    _require_equal(source_audit.get("network_request_count"), 0, field_name="audit network requests")
    _require_equal(source_audit.get("post_run_source_inventory_sha256"), source_audit.get("source_inventory_sha256"), field_name="source audit inventory")

    candidate_payload = _load_json(source_root / "candidate_records.json")
    _require_equal(candidate_payload.get("source_identity"), binding.source_identity, field_name="candidate source identity")
    _require_equal(candidate_payload.get("phase9a_study_id"), binding.phase9a_study_id, field_name="Phase 9A study ID")
    records = candidate_payload.get("records")
    if not isinstance(records, list):
        raise StudyArtifactError("candidate records are not a list")
    _require_equal(len(records), binding.candidate_count, field_name="candidate record count")
    seen_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise StudyArtifactError("candidate record is not an object")
        _validate_record(record, row_count=binding.row_count)
        candidate_id = record["candidate_id"]
        if candidate_id in seen_ids:
            raise StudyArtifactError("candidate IDs are not unique")
        seen_ids.add(candidate_id)
    support_count = sum(record["role"] == "support" for record in records)
    resistance_count = sum(record["role"] == "resistance" for record in records)
    _require_equal(support_count, binding.support_count, field_name="support count")
    _require_equal(resistance_count, binding.resistance_count, field_name="resistance count")
    groups = {(record["role"], record["second_anchor_id"]) for record in records}
    _require_equal(len(groups), binding.second_anchor_group_count, field_name="second anchor group count")
    decision = _load_json(source_root / "decision.json")
    _require_equal(decision.get("study_id"), binding.study_id, field_name="decision study ID")
    _require_equal(decision.get("study_status"), "DESCRIPTIVE_EVIDENCE_ONLY", field_name="decision status")
    for field in (
        "QUALITY_SCORE_SELECTION",
        "ELIGIBILITY_RULE_SELECTION",
        "PARAMETER_PROMOTION",
        "TRACKER_START",
    ):
        _require_equal(decision.get(field), "NOT_AUTHORIZED", field_name=field)
    _require_equal(decision.get("candidate_count"), binding.candidate_count, field_name="decision candidate count")
    _require_equal(decision.get("support_count"), binding.support_count, field_name="decision support count")
    _require_equal(decision.get("resistance_count"), binding.resistance_count, field_name="decision resistance count")
    _load_json(source_root / "feature_contract.json")
    _load_json(source_root / "feature_associations.json")
    return (
        {
            "source_identity": binding.source_identity,
            "study_id": binding.study_id,
            "manifest_id": binding.manifest_id,
            "inventory_sha256": binding.inventory_sha256,
            "phase9a_study_id": binding.phase9a_study_id,
            "row_count": binding.row_count,
        },
        tuple(records),
        inventory,
    )


def _membership_sort_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        record["role"],
        record["second_anchor_time"],
        record["first_anchor_time"],
        record["candidate_structure_id"],
        record["candidate_id"],
    )


def _group_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return record["role"], record["second_anchor_id"]


def _select_one(
    records: Sequence[Mapping[str, Any]],
    *,
    value_field: str | None = None,
    reverse_value: bool = False,
) -> tuple[dict[str, Any], ...]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        groups[_group_key(record)].append(record)
    selected: list[dict[str, Any]] = []
    for group_records in groups.values():
        if value_field is None:
            target_time = (
                max(item["first_anchor_time"] for item in group_records)
                if reverse_value
                else min(item["first_anchor_time"] for item in group_records)
            )
            ordered = sorted(
                (
                    item
                    for item in group_records
                    if item["first_anchor_time"] == target_time
                ),
                key=lambda item: (
                    item["candidate_structure_id"],
                    item["candidate_id"],
                ),
            )
        elif reverse_value:
            ordered = sorted(
                group_records,
                key=lambda item: (
                    -_finite_number(item[value_field], field_name=value_field),
                    item["candidate_structure_id"],
                    item["candidate_id"],
                ),
            )
        else:
            ordered = sorted(
                group_records,
                key=lambda item: (
                    _finite_number(item[value_field], field_name=value_field),
                    item["candidate_structure_id"],
                    item["candidate_id"],
                ),
                reverse=False,
            )
        selected.append(dict(ordered[0]))
    return tuple(sorted(selected, key=_membership_sort_key))


def _select_families(records: Sequence[Mapping[str, Any]]) -> dict[str, tuple[dict[str, Any], ...]]:
    ordered = tuple(sorted((dict(record) for record in records), key=_membership_sort_key))
    return {
        "all_candidates_control_v1": ordered,
        "adjacent_extrema_only_v1": tuple(
            record for record in ordered if record["same_role_extrema_skip_count"] == 0
        ),
        "skip_le_1_v1": tuple(
            record for record in ordered if record["same_role_extrema_skip_count"] <= 1
        ),
        "skip_le_3_v1": tuple(
            record for record in ordered if record["same_role_extrema_skip_count"] <= 3
        ),
        "latest_valid_predecessor_v1": _select_one(ordered, value_field=None, reverse_value=True),
        "earliest_valid_predecessor_v1": _select_one(ordered, value_field=None, reverse_value=False),
        "max_minimum_body_clearance_v1": _select_one(
            ordered, value_field="minimum_body_clearance_bps", reverse_value=True
        ),
        "max_minimum_anchor_prominence_v1": _select_one(
            ordered, value_field="minimum_anchor_prominence_bps", reverse_value=True
        ),
    }


def _membership_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": record["candidate_id"],
        "candidate_structure_id": record["candidate_structure_id"],
        "role": record["role"],
        "first_anchor_id": record["first_anchor_id"],
        "second_anchor_id": record["second_anchor_id"],
        "candidate_available_at": record["candidate_available_at"],
    }


def _percentile95(values: Sequence[float | int]) -> float | int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def _stats(values: Sequence[float | int]) -> dict[str, float | int | None]:
    if not values:
        return {"minimum": None, "median": None, "p95": None, "maximum": None}
    return {
        "minimum": min(values),
        "median": statistics.median(values),
        "p95": _percentile95(values),
        "maximum": max(values),
    }


def _finite_overlap(records: Sequence[Mapping[str, Any]], row_count: int) -> dict[str, Any]:
    counts = [
        sum(
            first <= position <= second
            for record in records
            for first, second in (record["anchor_source_positions"],)
        )
        for position in range(row_count)
    ]
    return {
        "definition": "finite_anchor_to_anchor_overlap; inclusive source-position intervals",
        "row_count": row_count,
        "counts": _stats(counts),
    }


def _admission_burst(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = Counter(record["candidate_available_at"] for record in records)
    values = list(counts.values())
    return {
        "availability_bar_count": len(counts),
        "admissions_per_availability_bar": _stats(values),
    }


def _group_counts(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = Counter(_group_key(record) for record in records)
    return {
        "candidate_count_per_second_anchor": _stats(list(counts.values())),
        "nonempty_group_count": len(counts),
    }


def _descriptor_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    fields = (
        "anchor_span_bars",
        "same_role_extrema_skip_count",
        "minimum_body_clearance_bps",
        "minimum_anchor_prominence_bps",
        "absolute_slope_bps_per_day",
    )
    return {
        field: {
            **_stats([record[field] for record in records]),
            "unique_value_count": len({record[field] for record in records}),
        }
        for field in fields
    }


def _metric_summary(records: Sequence[Mapping[str, Any]], horizon: int) -> dict[str, Any]:
    eligible = [record for record in records if record["evaluations"][str(horizon)]["evaluation_available"]]
    if not eligible:
        return {
            "evaluation_available_count": 0,
            "contact_rate": None,
            "exact_side_survival_rate": None,
            "contact_and_survival_rate": None,
            "median_future_contact_count": None,
            "median_future_body_violation_count": None,
        }
    evaluations = [record["evaluations"][str(horizon)] for record in eligible]
    return {
        "evaluation_available_count": len(eligible),
        "contact_rate": sum(item["has_exact_contact"] for item in evaluations) / len(evaluations),
        "exact_side_survival_rate": sum(item["survives_exact_side"] for item in evaluations) / len(evaluations),
        "contact_and_survival_rate": sum(item["contact_and_survives_exact_side"] for item in evaluations) / len(evaluations),
        "median_future_contact_count": statistics.median(item["future_contact_count"] for item in evaluations),
        "median_future_body_violation_count": statistics.median(item["future_body_violation_count"] for item in evaluations),
    }


def _group_weighted_metric(records: Sequence[Mapping[str, Any]], horizon: int) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        groups[_group_key(record)].append(record)
    group_metrics: list[dict[str, Any]] = []
    for group_records in groups.values():
        eligible = [
            record
            for record in group_records
            if record["evaluations"][str(horizon)]["evaluation_available"]
        ]
        if not eligible:
            continue
        evaluations = [record["evaluations"][str(horizon)] for record in eligible]
        group_metrics.append(
            {
                "rates": _metric_summary(group_records, horizon),
                "mean_future_contact_count": statistics.mean(
                    item["future_contact_count"] for item in evaluations
                ),
                "mean_future_body_violation_count": statistics.mean(
                    item["future_body_violation_count"] for item in evaluations
                ),
            }
        )
    if not group_metrics:
        return {
            "evaluation_available_count": 0,
            "weighted_group_count": 0,
            "contact_rate": None,
            "exact_side_survival_rate": None,
            "contact_and_survival_rate": None,
            "mean_of_group_mean_future_contact_count": None,
            "mean_of_group_mean_future_body_violation_count": None,
        }
    fields = (
        "contact_rate",
        "exact_side_survival_rate",
        "contact_and_survival_rate",
    )
    return {
        "evaluation_available_count": sum(
            item["rates"]["evaluation_available_count"] for item in group_metrics
        ),
        "weighted_group_count": len(group_metrics),
        **{
            field: statistics.mean(item["rates"][field] for item in group_metrics)
            for field in fields
        },
        "mean_of_group_mean_future_contact_count": statistics.mean(
            item["mean_future_contact_count"] for item in group_metrics
        ),
        "mean_of_group_mean_future_body_violation_count": statistics.mean(
            item["mean_future_body_violation_count"] for item in group_metrics
        ),
    }


def _delta_value(early: object, late: object) -> object:
    if early is None or late is None:
        return {"value": None, "reason": "early_or_late_metric_undefined"}
    return late - early  # type: ignore[operator]


def _early_to_late_delta(role_segment: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for role in ROLES:
        early = role_segment[f"{role}/early"]
        late = role_segment[f"{role}/late"]
        role_result: dict[str, Any] = {}
        for weighting in (
            "candidate_weighted_descriptive",
            "second_anchor_group_weighted_descriptive",
        ):
            early_metric = early[weighting]
            late_metric = late[weighting]
            metric_fields = (
                "evaluation_available_count",
                "contact_rate",
                "exact_side_survival_rate",
                "contact_and_survival_rate",
            )
            if weighting == "candidate_weighted_descriptive":
                metric_fields += (
                    "median_future_contact_count",
                    "median_future_body_violation_count",
                )
            else:
                metric_fields += (
                    "mean_of_group_mean_future_contact_count",
                    "mean_of_group_mean_future_body_violation_count",
                )
            role_result[weighting] = {
                "candidate_count_delta": _delta_value(
                    early["candidate_count"], late["candidate_count"]
                ),
                "unique_second_anchor_group_count_delta": _delta_value(
                    early["unique_second_anchor_group_count"],
                    late["unique_second_anchor_group_count"],
                ),
                **{
                    f"{field}_delta": _delta_value(
                        early_metric[field], late_metric[field]
                    )
                    for field in metric_fields
                },
            }
        result[role] = role_result
    return result


def _outcome_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for horizon in HORIZONS:
        role_segment: dict[str, Any] = {}
        for role in ROLES:
            for segment in SEGMENTS:
                cohort = [
                    record
                    for record in records
                    if record["role"] == role and record["chronological_segment"] == segment
                ]
                role_segment[f"{role}/{segment}"] = {
                    "candidate_count": len(cohort),
                    "unique_second_anchor_group_count": len({_group_key(record) for record in cohort}),
                    "candidate_weighted_descriptive": _metric_summary(cohort, horizon),
                    "second_anchor_group_weighted_descriptive": _group_weighted_metric(cohort, horizon),
                }
        result[str(horizon)] = {
            "candidate_weighted_descriptive": _metric_summary(records, horizon),
            "second_anchor_group_weighted_descriptive": _group_weighted_metric(records, horizon),
            "role_segment": role_segment,
            "early_to_late": _early_to_late_delta(role_segment),
        }
    return result


def _family_metrics(
    records: Sequence[Mapping[str, Any]],
    *,
    control_ids: set[str],
    row_count: int,
    expected_group_count: int,
) -> dict[str, Any]:
    ids = {record["candidate_id"] for record in records}
    anchor_ids = {
        anchor_id
        for record in records
        for anchor_id in (record["first_anchor_id"], record["second_anchor_id"])
    }
    groups = {_group_key(record) for record in records}
    return {
        "candidate_count": len(records),
        "candidate_fraction_of_control": len(records) / len(control_ids) if control_ids else None,
        "support_count": sum(record["role"] == "support" for record in records),
        "resistance_count": sum(record["role"] == "resistance" for record in records),
        "early_count": sum(record["chronological_segment"] == "early" for record in records),
        "late_count": sum(record["chronological_segment"] == "late" for record in records),
        "unique_structure_count": len({record["candidate_structure_id"] for record in records}),
        "unique_anchor_count": len(anchor_ids),
        "unique_second_anchor_group_count": len(groups),
        "second_anchor_group_coverage_ratio": len(groups) / expected_group_count,
        "candidate_count_per_second_anchor": _group_counts(records),
        "admission_burst": _admission_burst(records),
        "finite_anchor_to_anchor_overlap": _finite_overlap(records, row_count),
        "birth_descriptor_summaries": _descriptor_summary(records),
        "control_subset_verified": ids.issubset(control_ids),
    }


def _overlap_matrix(families: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    sets = {
        family_id: {record["candidate_id"] for record in records}
        for family_id, records in families.items()
    }
    pairs: dict[str, Any] = {}
    for index, left in enumerate(FAMILY_IDS):
        for right in FAMILY_IDS[index + 1 :]:
            intersection = len(sets[left] & sets[right])
            union = len(sets[left] | sets[right])
            left_size = len(sets[left])
            right_size = len(sets[right])
            pairs[f"{left}|{right}"] = {
                "left_family_id": left,
                "right_family_id": right,
                "intersection_count": intersection,
                "union_count": union,
                "jaccard_membership_ratio": intersection / union if union else None,
                "left_containment_ratio": intersection / left_size if left_size else None,
                "right_containment_ratio": intersection / right_size if right_size else None,
            }
    return {"pairwise_membership": pairs}


def _architecture_classification(
    family_id: str,
    records: Sequence[Mapping[str, Any]],
    *,
    control_ids: set[str],
    repeat_matches: Mapping[str, bool],
) -> str:
    ids = {record["candidate_id"] for record in records}
    if not ids.issubset(control_ids):
        return "INVALID_MEMBERSHIP_CONTRACT"
    if not all(repeat_matches.values()):
        return "INVALID_NONDETERMINISTIC_SELECTOR"
    if not all(record["role"] in ROLES for record in records):
        return "INVALID_ROLE_OR_SEGMENT_COVERAGE"
    if not all(record["chronological_segment"] in SEGMENTS for record in records):
        return "INVALID_ROLE_OR_SEGMENT_COVERAGE"
    if {record["role"] for record in records} != set(ROLES):
        return "INVALID_ROLE_OR_SEGMENT_COVERAGE"
    if {record["chronological_segment"] for record in records} != set(SEGMENTS):
        return "INVALID_ROLE_OR_SEGMENT_COVERAGE"
    if family_id != "all_candidates_control_v1":
        counts = Counter(_group_key(record) for record in records)
        if any(count != 1 for count in counts.values()):
            if family_id in {
                "latest_valid_predecessor_v1",
                "earliest_valid_predecessor_v1",
                "max_minimum_body_clearance_v1",
                "max_minimum_anchor_prominence_v1",
            }:
                return "INVALID_MEMBERSHIP_CONTRACT"
    return "ARCHITECTURALLY_VALID_FOR_FRESH_SCOPE_STUDY"


def _summary_rows(
    families: Mapping[str, Sequence[Mapping[str, Any]]],
    outcomes: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for family_id in FAMILY_IDS:
        for role in ROLES:
            for segment in SEGMENTS:
                cohort_key = f"{role}/{segment}"
                for horizon in HORIZONS:
                    outcome = outcomes[family_id][str(horizon)]
                    role_segment = outcome["role_segment"][cohort_key]
                    for weighting in (
                        "candidate_weighted_descriptive",
                        "second_anchor_group_weighted_descriptive",
                    ):
                        metric = role_segment[weighting]
                        delta = outcome["early_to_late"][role][weighting]
                        rows.append({
                            "family_id": family_id,
                            "role": role,
                            "chronological_segment": segment,
                            "horizon_bars": horizon,
                            "weighting_method": weighting,
                            "candidate_count": role_segment["candidate_count"],
                            "unique_second_anchor_group_count": role_segment["unique_second_anchor_group_count"],
                            "evaluation_available_count": metric["evaluation_available_count"],
                            "contact_rate": metric["contact_rate"],
                            "exact_side_survival_rate": metric["exact_side_survival_rate"],
                            "contact_and_survival_rate": metric["contact_and_survival_rate"],
                            "median_future_contact_count": metric.get("median_future_contact_count"),
                            "median_future_body_violation_count": metric.get("median_future_body_violation_count"),
                            "mean_of_group_mean_future_contact_count": metric.get(
                                "mean_of_group_mean_future_contact_count"
                            ),
                            "mean_of_group_mean_future_body_violation_count": metric.get(
                                "mean_of_group_mean_future_body_violation_count"
                            ),
                            **{
                                field: delta.get(field)
                                for field in (
                                    "candidate_count_delta",
                                    "unique_second_anchor_group_count_delta",
                                    "evaluation_available_count_delta",
                                    "contact_rate_delta",
                                    "exact_side_survival_rate_delta",
                                    "contact_and_survival_rate_delta",
                                    "median_future_contact_count_delta",
                                    "median_future_body_violation_count_delta",
                                    "mean_of_group_mean_future_contact_count_delta",
                                    "mean_of_group_mean_future_body_violation_count_delta",
                                )
                            },
                        })
    return tuple(rows)


def _write_atomic(path: Path, data: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refusing existing output file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        if path.exists():
            raise FileExistsError(f"refusing output overwrite: {path}")
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    _write_atomic(path, _canonical_bytes(payload))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        raise StudyArtifactError("family summary cannot be empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = tuple(rows[0])
    temporary_handle = tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
        newline="",
        encoding="utf-8",
    )
    temporary = Path(temporary_handle.name)
    try:
        writer = csv.DictWriter(
            temporary_handle,
            fieldnames=fieldnames,
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
        temporary_handle.flush()
        os.fsync(temporary_handle.fileno())
        temporary_handle.close()
        if path.exists():
            raise FileExistsError(f"refusing existing output file: {path}")
        os.replace(temporary, path)
    except Exception:
        temporary_handle.close()
        temporary.unlink(missing_ok=True)
        raise


def _verify_family_invariants(
    families: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    expected_group_count: int,
) -> None:
    if tuple(families) != FAMILY_IDS:
        raise StudyArtifactError("family definition set drifted")
    control_ids = {record["candidate_id"] for record in families[FAMILY_IDS[0]]}
    if len(control_ids) != len(families[FAMILY_IDS[0]]):
        raise StudyArtifactError("control contains duplicate candidates")
    for family_id, records in families.items():
        ids = [record["candidate_id"] for record in records]
        if len(ids) != len(set(ids)) or not set(ids).issubset(control_ids):
            raise StudyArtifactError(f"invalid membership for {family_id}")
    if not (
        set(record["candidate_id"] for record in families["adjacent_extrema_only_v1"])
        <= set(record["candidate_id"] for record in families["skip_le_1_v1"])
        <= set(record["candidate_id"] for record in families["skip_le_3_v1"])
        <= control_ids
    ):
        raise StudyArtifactError("skip-family containment failed")
    for family_id in FAMILY_IDS[4:]:
        counts = Counter(_group_key(record) for record in families[family_id])
        if len(counts) != expected_group_count or any(value != 1 for value in counts.values()):
            raise StudyArtifactError(f"one-per-second-anchor invariant failed: {family_id}")


def run_study(
    *,
    source_root: str | Path = SOURCE_ROOT,
    output_root: str | Path = OUTPUT_ROOT,
    _binding: StudyBinding | None = None,
    _before_post_run_check: Callable[[Path], None] | None = None,
    _during_manifest_write: Callable[[Path], None] | None = None,
) -> dict[str, Path]:
    """Build one deterministic descriptive family-comparison bundle."""

    binding = REAL_BINDING if _binding is None else _binding
    source_root = Path(source_root)
    output_root = Path(output_root)
    if output_root.exists():
        raise FileExistsError(f"refusing existing output root: {output_root}")
    context, records, inventory_before = _validate_source(source_root, binding=binding)
    families = _select_families(records)
    _verify_family_invariants(families, expected_group_count=binding.second_anchor_group_count)
    control_ids = {record["candidate_id"] for record in families[FAMILY_IDS[0]]}
    repeat_families = _select_families(tuple(reversed(records)))
    repeat_matches = {
        family_id: tuple(record["candidate_id"] for record in families[family_id])
        == tuple(record["candidate_id"] for record in repeat_families[family_id])
        for family_id in FAMILY_IDS
    }
    _verify_family_invariants(repeat_families, expected_group_count=binding.second_anchor_group_count)
    metrics = {
        family_id: _family_metrics(
            families[family_id],
            control_ids=control_ids,
            row_count=binding.row_count,
            expected_group_count=binding.second_anchor_group_count,
        )
        for family_id in FAMILY_IDS
    }
    outcomes = {
        family_id: _outcome_summary(families[family_id])
        for family_id in FAMILY_IDS
    }
    classifications = {
        family_id: _architecture_classification(
            family_id,
            families[family_id],
            control_ids=control_ids,
            repeat_matches=repeat_matches,
        )
        for family_id in FAMILY_IDS
    }
    family_membership = {
        "schema_version": "trendline_v2_phase_9b2_family_membership_v1",
        "source_identity": context["source_identity"],
        "selector_contract_id": SELECTOR_CONTRACT_ID,
        "families": {
            family_id: [_membership_record(record) for record in families[family_id]]
            for family_id in FAMILY_IDS
        },
    }
    family_contract = {
        "schema_version": "trendline_v2_phase_9b2_family_contract_v1",
        "selector_contract_id": SELECTOR_CONTRACT_ID,
        "selector_fields": list(SELECTOR_FIELDS),
        "forbidden_selector_fields": list(FORBIDDEN_SELECTOR_FIELDS),
        "family_definitions": list(FAMILY_DEFINITIONS),
        "membership_group_key": ["role", "second_anchor_id"],
        "ordering": [
            "role",
            "second_anchor_time",
            "first_anchor_time",
            "candidate_structure_id",
            "candidate_id",
        ],
        "continuation_horizons_bars": list(HORIZONS),
        "future_labels_read_after_membership_freeze": True,
    }
    overlap = _overlap_matrix(families)
    decision_without_id = {
        "schema_version": "trendline_v2_phase_9b2_decision_v1",
        "study_status": "DESCRIPTIVE_EVIDENCE_ONLY",
        "source_identity": context["source_identity"],
        "phase9b1_study_id": binding.study_id,
        "phase9b1_manifest_id": binding.manifest_id,
        "phase9b1_inventory_sha256": binding.inventory_sha256,
        "selector_contract_id": SELECTOR_CONTRACT_ID,
        "family_architecture_classification": classifications,
        "family_candidate_counts": {
            family_id: metrics[family_id]["candidate_count"]
            for family_id in FAMILY_IDS
        },
        "family_density_summaries": metrics,
        "family_anchor_coverage": {
            family_id: {
                "unique_second_anchor_group_count": metrics[family_id]["unique_second_anchor_group_count"],
                "second_anchor_group_coverage_ratio": metrics[family_id]["second_anchor_group_coverage_ratio"],
            }
            for family_id in FAMILY_IDS
        },
        "family_outcome_summaries": outcomes,
        "family_early_to_late_deltas": {
            family_id: {
                str(horizon): outcomes[family_id][str(horizon)]["early_to_late"]
                for horizon in HORIZONS
            }
            for family_id in FAMILY_IDS
        },
        "family_overlap_summary": overlap,
        "determinism": {
            "input_order_independent": all(repeat_matches.values()),
            "repeat_matches": repeat_matches,
            "selector_uses_only_declared_fields": True,
        },
        "limitations": [
            "The source is one exploratory BTCUSDT 4h window. Families were defined after reviewing Phase 9B.1 architecture evidence. Outcome summaries are descriptive, candidate-dependent, and unsuitable for selecting a production eligibility rule without fresh cross-asset/timeframe evidence.",
            "Candidate records share anchors and overlapping finite geometry. Candidate-weighted and second-anchor-group-weighted rates are descriptive, not independent-sample or inferential evidence.",
            "Finite overlap covers inclusive anchor-to-anchor source intervals only; it is not live active-family density.",
        ],
        "ELIGIBILITY_FAMILY_SELECTION": "NOT_AUTHORIZED",
        "CANONICAL_FILTER_IMPLEMENTATION": "NOT_AUTHORIZED",
        "QUALITY_SCORE_SELECTION": "NOT_AUTHORIZED",
        "PARAMETER_PROMOTION": "NOT_AUTHORIZED",
        "TRACKER_START": "NOT_AUTHORIZED",
        "PHASE_9C_START": "NOT_AUTHORIZED",
    }
    decision = {
        **decision_without_id,
        "decision_id": deterministic_hash(
            "trendline_v2_phase_9b2_decision_v1", decision_without_id
        ),
    }
    summary_rows = _summary_rows(families, outcomes)

    output_root.mkdir(parents=True, exist_ok=False)
    _write_json(output_root / "family_contract.json", family_contract)
    _write_json(output_root / "family_membership.json", family_membership)
    _write_csv(output_root / "family_summary.csv", summary_rows)
    _write_json(output_root / "outcome_summary.json", {
        "schema_version": "trendline_v2_phase_9b2_outcome_summary_v1",
        "source_identity": context["source_identity"],
        "outcomes": outcomes,
    })
    _write_json(output_root / "overlap_matrix.json", {
        "schema_version": "trendline_v2_phase_9b2_overlap_matrix_v1",
        "source_identity": context["source_identity"],
        **overlap,
    })
    _write_json(output_root / "decision.json", decision)
    if _before_post_run_check is not None:
        _before_post_run_check(source_root)
    inventory_after = _artifact_inventory(source_root)
    if inventory_after != inventory_before:
        raise StudyArtifactError("source changed during eligibility-family study")
    source_audit = {
        "schema_version": "trendline_v2_phase_9b2_source_audit_v1",
        "phase9b1_study_id": binding.study_id,
        "phase9b1_manifest_id": binding.manifest_id,
        "phase9b1_inventory_sha256": binding.inventory_sha256,
        "source_identity": context["source_identity"],
        "source_files": inventory_before,
        "pre_run_inventory_sha256": _inventory_digest(inventory_before),
        "post_run_inventory_sha256": _inventory_digest(inventory_after),
        "source_immutability_verified": True,
        "provider_execution_count": 0,
        "network_request_count": 0,
    }
    _write_json(output_root / "source_audit.json", source_audit)
    members = tuple(
        sorted(
            (
                "source_audit.json",
                "family_contract.json",
                "family_membership.json",
                "family_summary.csv",
                "outcome_summary.json",
                "overlap_matrix.json",
                "decision.json",
            )
        )
    )
    manifest_without_id = {
        "schema_version": "trendline_v2_phase_9b2_manifest_v1",
        "study_status": "DESCRIPTIVE_EVIDENCE_ONLY",
        "source_identity": context["source_identity"],
        "phase9b1_study_id": binding.study_id,
        "phase9b1_manifest_id": binding.manifest_id,
        "phase9b1_inventory_sha256": binding.inventory_sha256,
        "selector_contract_id": SELECTOR_CONTRACT_ID,
        "family_ids": list(FAMILY_IDS),
        "candidate_count_control": len(families[FAMILY_IDS[0]]),
        "provider_execution_count": 0,
        "network_request_count": 0,
        "members": [
            {
                "path": name,
                "byte_length": (output_root / name).stat().st_size,
                "sha256": _sha256_file(output_root / name),
            }
            for name in members
        ],
    }
    manifest = {
        **manifest_without_id,
        "manifest_id": deterministic_hash(
            "trendline_v2_phase_9b2_manifest_v1", manifest_without_id
        ),
    }
    if _during_manifest_write is not None:
        _during_manifest_write(source_root)
    _write_json(output_root / "manifest.json", manifest)
    if _artifact_inventory(source_root) != inventory_before:
        raise StudyArtifactError(
            "source changed after eligibility-family artifact completion"
        )
    return {
        name.removesuffix(".json").removesuffix(".csv"): output_root / name
        for name in (*members, "manifest.json")
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    try:
        paths = run_study(source_root=args.source_root, output_root=args.output_root)
    except (FileExistsError, StudyArtifactError) as exc:
        print(str(exc))
        return 2
    print(json.dumps({name: str(path) for name, path in paths.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
