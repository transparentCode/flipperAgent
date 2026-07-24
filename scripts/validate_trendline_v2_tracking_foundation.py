"""Validate and publish the read-only Phase 10A tracking birth study."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping, Sequence

from libs.models.trendline_v2.domain.identity import canonical_json, deterministic_hash
from libs.models.trendline_v2.domain.validation import ContractValidationError
from libs.models.trendline_v2.api import track_trendline_families
from libs.models.trendline_v2.selection import CandidateSelectionSnapshot, SelectionStatus
from libs.models.trendline_v2.tracking import (
    SUPPORTED_SELECTION_POLICY_IDENTITY,
    ExactSelectedStructureTrackingPolicy,
    FamilyTrackingTransitionType,
    TrendlineTrackingSnapshot,
)

from scripts import validate_trendline_v2_canonical_selection as phase9d


SOURCE_ROOT = Path("/tmp/trendline_v2_phase9d_canonical_selection/20260522_20260701")
OUTPUT_ROOT = Path(
    "/tmp/trendline_v2_phase10a_tracking_foundation/20260522_20260701"
)
STUDY_SCHEMA = "trendline_v2_phase_10a_tracking_foundation_v1"
DATASET_SCHEMA = f"{STUDY_SCHEMA}_dataset"
SOURCE_AUDIT_SCHEMA = f"{STUDY_SCHEMA}_source_audit"
CONTRACT_SCHEMA = f"{STUDY_SCHEMA}_contract"
DECISION_SCHEMA = f"{STUDY_SCHEMA}_decision"
MANIFEST_SCHEMA = f"{STUDY_SCHEMA}_manifest"
DECISION_NAMESPACE = "trendline_v2_phase_10a_tracking_foundation_decision"
MANIFEST_NAMESPACE = "trendline_v2_phase_10a_tracking_foundation_manifest"
PHASE9D_DECISION_ID = (
    "c7daee89ffe745e12d4c8dcad65fc27a9c19f7da3b460acc32360af0f814b6cd"
)
PHASE9D_COMMIT = "722109c5ed86e5d3974e0b2f7fb0d7a637da7a4f"
PHASE9D_MANIFEST_ID = (
    "51fb6ff236e8e6f94d47082c00fa27dc5692ab8e629e0a10959f35ccc2675585"
)
PHASE9D_OUTPUT_INVENTORY_SHA256 = (
    "aca26bb086c3cd0b8ce04c152ab1b71fa240068c92c8f5691a7848fe3900ecb8"
)
PHASE9C2_SOURCE_INVENTORY_SHA256 = (
    "ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532"
)
EXPECTED_SELECTION_POLICY_IDENTITY = SUPPORTED_SELECTION_POLICY_IDENTITY
EXPECTED_SELECTION_SNAPSHOT_IDS = {
    "btcusdt_1h": "ed7959f4591e749f087d5dbb83c74df2a31125c51c2c77303068553e2f1190ab",
    "btcusdt_4h": "31330b3c58cb0ee8f33979683c080bc881d2d04b8ea76bbe18cacbdce2eb67da",
    "ethusdt_1h": "7178dedceef1b0c97b99777a40b07dad808942330902edd093f83d9cd1ec812b",
    "ethusdt_4h": "f9c48aec092b623b89175e56888f88049fb652d75c62da56005d044a16070f56",
    "suiusdt_1h": "d2a762fb7ff6c6e1dba2df9fdba877a00511678634c36cab7f75213ac02702db",
    "suiusdt_4h": "c2175d14d052f8893612508e5c23a66c60322d824191873e6a521da830909b6b",
}
EXPECTED_SELECTED_COUNTS = {
    "btcusdt_1h": 422,
    "btcusdt_4h": 106,
    "ethusdt_1h": 433,
    "ethusdt_4h": 109,
    "suiusdt_1h": 437,
    "suiusdt_4h": 112,
}
DATASET_ORDER = tuple(EXPECTED_SELECTED_COUNTS)


class TrackingStudyError(RuntimeError):
    """Expected bounded study or artifact validation failure."""


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
        raw = path.read_bytes()
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise TrackingStudyError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict) or raw != _canonical_bytes(value):
        raise TrackingStudyError(f"non-canonical JSON artifact: {path}")
    return value


def _inventory(root: Path) -> tuple[dict[str, Any], ...]:
    if not root.is_dir() or root.is_symlink():
        raise TrackingStudyError(f"source root is missing: {root}")
    members: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise TrackingStudyError(f"source file is a symlink: {path}")
        members.append(
            {
                "path": path.relative_to(root).as_posix(),
                "byte_length": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return tuple(members)


def _inventory_sha256(inventory: Sequence[Mapping[str, Any]]) -> str:
    return _sha256_bytes(_canonical_bytes(list(inventory)))


def _write_atomic(path: Path, data: bytes) -> None:
    if path.exists():
        raise FileExistsError(f"refusing existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        if path.exists():
            raise FileExistsError(f"refusing existing output: {path}")
        os.replace(temporary, path)
    except Exception:
        handle.close()
        temporary.unlink(missing_ok=True)
        raise


def _csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        raise TrackingStudyError("cannot serialize empty tracking summary")
    fields = tuple(rows[0])
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows({field: row[field] for field in fields} for row in rows)
    return buffer.getvalue().encode("utf-8")


@dataclass(frozen=True, slots=True)
class SelectionRecord:
    dataset_id: str
    selection: CandidateSelectionSnapshot


def _verify_phase9d_source(source_root: Path) -> tuple[dict[str, Any], ...]:
    """Run the committed Phase 9D verifier and return its immutable output inventory."""

    before = _inventory(source_root)
    if (
        len(before) != 11
        or _inventory_sha256(before) != PHASE9D_OUTPUT_INVENTORY_SHA256
    ):
        raise TrackingStudyError("Phase 9D source inventory drift")
    try:
        verified = phase9d.verify_study_bundle(
            source_root=phase9d.SOURCE_ROOT,
            output_root=source_root,
        )
    except Exception as exc:
        raise TrackingStudyError("Phase 9D source verification failed") from exc
    if (
        verified["decision_id"] != PHASE9D_DECISION_ID
        or verified["manifest_id"] != PHASE9D_MANIFEST_ID
        or verified["output_inventory_sha256"] != PHASE9D_OUTPUT_INVENTORY_SHA256
        or verified["source_inventory_sha256"] != PHASE9C2_SOURCE_INVENTORY_SHA256
    ):
        raise TrackingStudyError("Phase 9D source identity drift")
    after = _inventory(source_root)
    if before != after or _inventory_sha256(after) != PHASE9D_OUTPUT_INVENTORY_SHA256:
        raise TrackingStudyError("Phase 9D source changed during verification")
    return before


def _load_selection_records(source_root: Path) -> tuple[SelectionRecord, ...]:
    records: list[SelectionRecord] = []
    for dataset_id in DATASET_ORDER:
        path = source_root / "datasets" / dataset_id / "selection_snapshot.json"
        payload = _load_json(path)
        expected_keys = {
            "schema_version",
            "dataset_id",
            "source_snapshot_id",
            "selection_snapshot",
        }
        if set(payload) != expected_keys:
            raise TrackingStudyError(f"selection artifact keys mismatch: {dataset_id}")
        if (
            payload["schema_version"] != phase9d.DATASET_SCHEMA
            or payload["dataset_id"] != dataset_id
        ):
            raise TrackingStudyError(f"selection artifact identity mismatch: {dataset_id}")
        try:
            selection = CandidateSelectionSnapshot.from_dict(payload["selection_snapshot"])
        except ContractValidationError as exc:
            raise TrackingStudyError(f"invalid selection snapshot: {dataset_id}") from exc
        if (
            selection.snapshot_id != EXPECTED_SELECTION_SNAPSHOT_IDS[dataset_id]
            or selection.status is not SelectionStatus.SELECTED
            or selection.selection_policy_identity != EXPECTED_SELECTION_POLICY_IDENTITY
            or payload["source_snapshot_id"] != selection.source_snapshot_id
            or len(selection.selected_candidates) != EXPECTED_SELECTED_COUNTS[dataset_id]
        ):
            raise TrackingStudyError(f"selection snapshot contract mismatch: {dataset_id}")
        records.append(SelectionRecord(dataset_id=dataset_id, selection=selection))
    return tuple(records)


def _initial_tracking(
    records: Sequence[SelectionRecord],
    policy: ExactSelectedStructureTrackingPolicy,
) -> tuple[TrendlineTrackingSnapshot, ...]:
    snapshots = tuple(
        track_trendline_families(record.selection, previous=None, policy=policy)
        for record in records
    )
    for record, snapshot in zip(records, snapshots):
        selected_count = len(record.selection.selected_candidates)
        if (
            snapshot.status.value != "updated"
            or snapshot.source_selection_status is not SelectionStatus.SELECTED
            or snapshot.source_selection_snapshot_id != record.selection.snapshot_id
            or len(snapshot.active_families) != selected_count
            or len(snapshot.transitions) != selected_count
            or snapshot.diagnostics.birth_count != selected_count
            or any(
                transition.transition_type is not FamilyTrackingTransitionType.BIRTH
                for transition in snapshot.transitions
            )
        ):
            raise TrackingStudyError(f"initial tracking birth parity mismatch: {record.dataset_id}")
        family_candidate_ids = tuple(
            family.current_candidate.candidate_id for family in snapshot.active_families
        )
        source_candidate_ids = tuple(
            candidate.candidate_id for candidate in record.selection.selected_candidates
        )
        if set(family_candidate_ids) != set(source_candidate_ids):
            raise TrackingStudyError(f"initial candidate parity mismatch: {record.dataset_id}")
        if len({family.family_id for family in snapshot.active_families}) != selected_count:
            raise TrackingStudyError(f"initial family identity collision: {record.dataset_id}")
    return snapshots


def _study_contract(policy: ExactSelectedStructureTrackingPolicy) -> dict[str, Any]:
    return {
        "schema_version": CONTRACT_SCHEMA,
        "source": {
            "phase9d_commit": PHASE9D_COMMIT,
            "decision_id": PHASE9D_DECISION_ID,
            "manifest_id": PHASE9D_MANIFEST_ID,
            "output_inventory_sha256": PHASE9D_OUTPUT_INVENTORY_SHA256,
            "upstream_source_inventory_sha256": PHASE9C2_SOURCE_INVENTORY_SHA256,
        },
        "tracking_policy": {
            "policy_identity": policy.policy_identity,
            "policy": policy.to_dict(),
        },
        "identity_namespaces": {
            "tracking_policy": "trendline_v2_tracking_policy",
            "tracked_family": "trendline_v2_tracked_family",
            "transition": "trendline_v2_family_tracking_transition",
            "tracking_snapshot": "trendline_v2_tracking_snapshot",
        },
        "execution": {
            "source_selection_snapshot_count": 6,
            "tracking_update_execution_count": 6,
            "historical_provider_execution_count": 6,
            "phase10a_provider_execution_count": 0,
            "network_request_count": 0,
        },
        "boundaries": {
            "REAL_TEMPORAL_REPLAY": "NOT_AUTHORIZED",
            "APPROXIMATE_MATCHING": "NOT_AUTHORIZED",
            "TRACKING_PERSISTENCE": "NOT_AUTHORIZED",
            "INTERACTIONS": "NOT_AUTHORIZED",
            "EVENTS": "NOT_AUTHORIZED",
            "MTF": "NOT_AUTHORIZED",
            "VIEWER_MIGRATION": "NOT_AUTHORIZED",
        },
    }


def _source_audit(
    inventory: Sequence[Mapping[str, Any]],
    records: Sequence[SelectionRecord],
    snapshots: Sequence[TrendlineTrackingSnapshot],
) -> dict[str, Any]:
    return {
        "schema_version": SOURCE_AUDIT_SCHEMA,
        "source": {
            "phase9d_decision_id": PHASE9D_DECISION_ID,
            "phase9d_manifest_id": PHASE9D_MANIFEST_ID,
            "phase9d_output_inventory_sha256": PHASE9D_OUTPUT_INVENTORY_SHA256,
            "phase9c2_source_inventory_sha256": PHASE9C2_SOURCE_INVENTORY_SHA256,
            "member_count": len(inventory),
        },
        "pre_run_inventory": list(inventory),
        "post_run_inventory": list(inventory),
        "source_immutability_verified": True,
        "source_selection_snapshot_ids": [record.selection.snapshot_id for record in records],
        "tracking_snapshot_ids": [snapshot.snapshot_id for snapshot in snapshots],
        "source_selection_snapshot_count": len(records),
        "tracking_update_execution_count": len(snapshots),
        "historical_provider_execution_count": 6,
        "phase10a_provider_execution_count": 0,
        "network_request_count": 0,
    }


def _birth_summary(
    records: Sequence[SelectionRecord],
    snapshots: Sequence[TrendlineTrackingSnapshot],
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "dataset_id": record.dataset_id,
            "source_selection_snapshot_id": record.selection.snapshot_id,
            "tracking_snapshot_id": snapshot.snapshot_id,
            "selected_candidate_count": len(record.selection.selected_candidates),
            "active_family_count": len(snapshot.active_families),
            "birth_count": snapshot.diagnostics.birth_count,
            "continuation_count": snapshot.diagnostics.continuation_count,
            "source_removed_count": snapshot.diagnostics.source_removed_count,
            "tracking_status": snapshot.status.value,
        }
        for record, snapshot in zip(records, snapshots)
    )


def _decision(
    records: Sequence[SelectionRecord],
    snapshots: Sequence[TrendlineTrackingSnapshot],
    policy: ExactSelectedStructureTrackingPolicy,
) -> dict[str, Any]:
    without_id = {
        "schema_version": DECISION_SCHEMA,
        "study_status": "TRACKING_FOUNDATION_INITIAL_BIRTHS_VERIFIED",
        "tracking_policy_identity": policy.policy_identity,
        "source": {
            "phase9d_decision_id": PHASE9D_DECISION_ID,
            "phase9d_manifest_id": PHASE9D_MANIFEST_ID,
            "phase9d_output_inventory_sha256": PHASE9D_OUTPUT_INVENTORY_SHA256,
            "phase9c2_source_inventory_sha256": PHASE9C2_SOURCE_INVENTORY_SHA256,
        },
        "datasets": [
            {
                "dataset_id": record.dataset_id,
                "source_selection_snapshot_id": record.selection.snapshot_id,
                "tracking_snapshot_id": snapshot.snapshot_id,
                "selected_source_candidate_count": len(record.selection.selected_candidates),
                "active_tracked_family_count": len(snapshot.active_families),
                "birth_count": snapshot.diagnostics.birth_count,
                "continuation_count": snapshot.diagnostics.continuation_count,
                "source_removed_count": snapshot.diagnostics.source_removed_count,
            }
            for record, snapshot in zip(records, snapshots)
        ],
        "dataset_count": len(records),
        "source_selection_snapshot_count": len(records),
        "tracking_update_execution_count": len(snapshots),
        "selected_source_candidate_count": sum(
            len(record.selection.selected_candidates) for record in records
        ),
        "active_tracked_family_count": sum(len(snapshot.active_families) for snapshot in snapshots),
        "birth_transition_count": sum(snapshot.diagnostics.birth_count for snapshot in snapshots),
        "continuation_transition_count": sum(
            snapshot.diagnostics.continuation_count for snapshot in snapshots
        ),
        "source_removed_transition_count": sum(
            snapshot.diagnostics.source_removed_count for snapshot in snapshots
        ),
        "execution": {
            "historical_provider_execution_count": 6,
            "phase10a_provider_execution_count": 0,
            "network_request_count": 0,
        },
        "boundaries": {
            "REAL_TEMPORAL_REPLAY": "NOT_AUTHORIZED",
            "APPROXIMATE_MATCHING": "NOT_AUTHORIZED",
            "TRACKING_PERSISTENCE": "NOT_AUTHORIZED",
            "INTERACTIONS": "NOT_AUTHORIZED",
            "EVENTS": "NOT_AUTHORIZED",
            "MTF": "NOT_AUTHORIZED",
            "VIEWER_MIGRATION": "NOT_AUTHORIZED",
        },
        "limitation": (
            "The external Phase 10A bundle validates initial births from one frozen "
            "selection snapshot per dataset. Continuation, source removal, "
            "unavailable-source carry-forward and reappearance rejection are "
            "validated hermetically but have not yet been measured through a real "
            "multi-snapshot market replay."
        ),
    }
    return {**without_id, "decision_id": deterministic_hash(DECISION_NAMESPACE, without_id)}


def _member_inventory(root: Path) -> tuple[dict[str, Any], ...]:
    return tuple(item for item in _inventory(root) if item["path"] != "manifest.json")


def _manifest(root: Path, *, decision: Mapping[str, Any], policy: ExactSelectedStructureTrackingPolicy) -> dict[str, Any]:
    members = _member_inventory(root)
    if len(members) != 10:
        raise TrackingStudyError(f"expected ten tracking members, got {len(members)}")
    without_id = {
        "schema_version": MANIFEST_SCHEMA,
        "decision_id": decision["decision_id"],
        "tracking_policy_identity": policy.policy_identity,
        "phase9d_output_inventory_sha256": PHASE9D_OUTPUT_INVENTORY_SHA256,
        "member_count": len(members),
        "members": list(members),
    }
    return {
        **without_id,
        "manifest_id": deterministic_hash(MANIFEST_NAMESPACE, without_id),
    }


def _payloads(
    records: Sequence[SelectionRecord],
    snapshots: Sequence[TrendlineTrackingSnapshot],
    inventory: Sequence[Mapping[str, Any]],
    policy: ExactSelectedStructureTrackingPolicy,
) -> dict[str, bytes]:
    values: dict[str, bytes] = {}
    for record, snapshot in zip(records, snapshots):
        payload = {
            "schema_version": DATASET_SCHEMA,
            "dataset_id": record.dataset_id,
            "source_selection_snapshot_id": record.selection.snapshot_id,
            "tracking_snapshot": snapshot.to_dict(),
        }
        values[f"datasets/{record.dataset_id}/tracking_snapshot.json"] = _canonical_bytes(payload)
    values["study_contract.json"] = _canonical_bytes(_study_contract(policy))
    values["source_audit.json"] = _canonical_bytes(_source_audit(inventory, records, snapshots))
    values["birth_summary.csv"] = _csv_bytes(_birth_summary(records, snapshots))
    values["decision.json"] = _canonical_bytes(_decision(records, snapshots, policy))
    return values


def _write_bundle(
    output_root: Path,
    *,
    records: Sequence[SelectionRecord],
    snapshots: Sequence[TrendlineTrackingSnapshot],
    inventory: Sequence[Mapping[str, Any]],
    policy: ExactSelectedStructureTrackingPolicy,
) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(f"refusing existing output root: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_root.parent))
    try:
        values = _payloads(records, snapshots, inventory, policy)
        for relative, data in values.items():
            _write_atomic(staging / relative, data)
        decision = _load_json(staging / "decision.json")
        manifest = _manifest(staging, decision=decision, policy=policy)
        _write_atomic(staging / "manifest.json", _canonical_bytes(manifest))
        if output_root.exists():
            raise FileExistsError(f"refusing existing output root: {output_root}")
        os.replace(staging, output_root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    actual_manifest = _load_json(output_root / "manifest.json")
    return {
        "output_root": str(output_root),
        "decision_id": decision["decision_id"],
        "manifest_id": actual_manifest["manifest_id"],
        "output_inventory_sha256": _inventory_sha256(_inventory(output_root)),
    }


def _verify_published_bundle(
    output_root: Path,
    *,
    records: Sequence[SelectionRecord],
    snapshots: Sequence[TrendlineTrackingSnapshot],
    inventory: Sequence[Mapping[str, Any]],
    policy: ExactSelectedStructureTrackingPolicy,
) -> dict[str, Any]:
    expected_values = _payloads(records, snapshots, inventory, policy)
    for relative, expected_bytes in expected_values.items():
        actual = output_root / relative
        try:
            if actual.read_bytes() != expected_bytes:
                raise TrackingStudyError(f"tracking artifact mismatch: {relative}")
        except OSError as exc:
            raise TrackingStudyError(f"missing tracking artifact: {relative}") from exc
    for record in records:
        path = output_root / "datasets" / record.dataset_id / "tracking_snapshot.json"
        payload = _load_json(path)
        try:
            restored = TrendlineTrackingSnapshot.from_dict(payload["tracking_snapshot"])
        except (KeyError, ContractValidationError) as exc:
            raise TrackingStudyError(f"invalid persisted tracking snapshot: {record.dataset_id}") from exc
        if restored.snapshot_id != payload["tracking_snapshot"]["snapshot_id"]:
            raise TrackingStudyError(f"tracking snapshot identity mismatch: {record.dataset_id}")
    decision = _load_json(output_root / "decision.json")
    manifest = _load_json(output_root / "manifest.json")
    expected_manifest = _manifest(output_root, decision=decision, policy=policy)
    if manifest != expected_manifest:
        raise TrackingStudyError("tracking manifest semantic mismatch")
    actual_inventory = _inventory(output_root)
    if len(actual_inventory) != 11:
        raise TrackingStudyError("tracking bundle must contain eleven files")
    if manifest["members"] != list(_member_inventory(output_root)):
        raise TrackingStudyError("tracking manifest members mismatch")
    return {
        "study_status": decision["study_status"],
        "decision_id": decision["decision_id"],
        "manifest_id": manifest["manifest_id"],
        "source_inventory_sha256": _inventory_sha256(inventory),
        "output_inventory_sha256": _inventory_sha256(actual_inventory),
        "tracking_policy_identity": policy.policy_identity,
    }


def build_study(
    *,
    source_root: str | Path = SOURCE_ROOT,
    output_root: str | Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    """Build the initial-birth study from one verified Phase 9D snapshot per dataset."""

    source_path = Path(source_root)
    output_path = Path(output_root)
    inventory = _verify_phase9d_source(source_path)
    records = _load_selection_records(source_path)
    after_load = _inventory(source_path)
    if inventory != after_load:
        raise TrackingStudyError("Phase 9D source changed while loading selections")
    policy = ExactSelectedStructureTrackingPolicy()
    snapshots = _initial_tracking(records, policy)
    result = _write_bundle(
        output_path,
        records=records,
        snapshots=snapshots,
        inventory=inventory,
        policy=policy,
    )
    verified = verify_study_bundle(source_root=source_path, output_root=output_path)
    if verified["manifest_id"] != result["manifest_id"]:
        raise TrackingStudyError("post-publication tracking manifest mismatch")
    return result


def verify_study_bundle(
    *,
    source_root: str | Path = SOURCE_ROOT,
    output_root: str | Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    """Independently reload and verify the tracking bundle and its source binding."""

    source_path = Path(source_root)
    output_path = Path(output_root)
    inventory = _verify_phase9d_source(source_path)
    records = _load_selection_records(source_path)
    if inventory != _inventory(source_path):
        raise TrackingStudyError("Phase 9D source changed while loading selections")
    policy = ExactSelectedStructureTrackingPolicy()
    snapshots = _initial_tracking(records, policy)
    return _verify_published_bundle(
        output_path,
        records=records,
        snapshots=snapshots,
        inventory=inventory,
        policy=policy,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = (
            verify_study_bundle(source_root=args.source_root, output_root=args.output_root)
            if args.verify
            else build_study(source_root=args.source_root, output_root=args.output_root)
        )
    except (ContractValidationError, FileExistsError, OSError, TrackingStudyError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
