"""Validate and publish the read-only Phase 9D selection parity study."""

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
from libs.models.trendline_v2.selection import (
    CandidateSelectionSnapshot,
    LatestValidPredecessorPolicy,
    select_latest_valid_predecessors,
)

from scripts import analyze_trendline_v2_fresh_scope_family_validation as phase9c2


SOURCE_ROOT = Path("/tmp/trendline_v2_phase9c2_fresh_scope_family_validation/20260522_20260701")
OUTPUT_ROOT = Path("/tmp/trendline_v2_phase9d_canonical_selection/20260522_20260701")
SOURCE_INVENTORY_SHA256 = "ed2eba9415a0e035560cb2f48dc9c0581ec758f9ffabcb629793ba6bca69e532"
SOURCE_DECISION_ID = "4b734cbf99e1453bccdedb95f397f4b34e020f29e3d18808a131456647f78f7c"
SOURCE_MANIFEST_ID = "beab5b9acb2bfc3c25ba9cb5cb31c33c1a31e6069c1d7906f3ed5e1c2d798c81"
SOURCE_SCHEMA = "trendline_v2_phase_9c2_fresh_scope_family_validation_v1"
STUDY_SCHEMA = "trendline_v2_phase_9d_canonical_selection_v1"
DECISION_NAMESPACE = "trendline_v2_phase_9d_decision"
MANIFEST_NAMESPACE = "trendline_v2_phase_9d_manifest"
DATASET_SCHEMA = "trendline_v2_phase_9d_selection_snapshot_v1"
EXPECTED_SELECTED_COUNTS = {
    "btcusdt_1h": 422,
    "btcusdt_4h": 106,
    "ethusdt_1h": 433,
    "ethusdt_4h": 109,
    "suiusdt_1h": 437,
    "suiusdt_4h": 112,
}
DATASET_ORDER = tuple(EXPECTED_SELECTED_COUNTS)
EXPECTED_SOURCE_CANDIDATE_COUNT = 15_287
EXPECTED_SELECTED_CANDIDATE_COUNT = 1_619
EXPECTED_POLICY_IDENTITY = "3213d919e3e325b99ce156272759a42799bf296545b95c338ea803c087f99afc"
FAMILY_ID = "latest_valid_predecessor_v1"


class SelectionStudyError(RuntimeError):
    """Expected bounded parity or artifact validation failure."""


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
        raise SelectionStudyError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(value, dict) or raw != _canonical_bytes(value):
        raise SelectionStudyError(f"non-canonical JSON artifact: {path}")
    return value


def _inventory(root: Path) -> tuple[dict[str, Any], ...]:
    if not root.is_dir() or root.is_symlink():
        raise SelectionStudyError(f"source root is missing: {root}")
    return tuple(
        {
            "path": path.relative_to(root).as_posix(),
            "byte_length": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    )


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
        raise SelectionStudyError("cannot serialize an empty parity summary")
    buffer = io.StringIO(newline="")
    fields = tuple(rows[0])
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows({field: row[field] for field in fields} for row in rows)
    return buffer.getvalue().encode("utf-8")


@dataclass(frozen=True, slots=True)
class SelectionRecord:
    dataset_id: str
    source_snapshot_id: str
    selection: CandidateSelectionSnapshot
    expected_candidate_ids: tuple[str, ...]
    source_candidate_count: int
    provider_result_id: str

    @property
    def selected_candidate_ids(self) -> tuple[str, ...]:
        return tuple(candidate.candidate_id for candidate in self.selection.selected_candidates)

    @property
    def missing_candidate_ids(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.expected_candidate_ids) - set(self.selected_candidate_ids)))

    @property
    def unexpected_candidate_ids(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.selected_candidate_ids) - set(self.expected_candidate_ids)))


def _verify_phase9c2_source(source_root: Path) -> tuple[dict[str, Any], ...]:
    before = _inventory(source_root)
    if len(before) != 38 or _inventory_sha256(before) != SOURCE_INVENTORY_SHA256:
        raise SelectionStudyError("Phase 9C.2 source inventory drift")
    try:
        verified = phase9c2.verify_study_bundle(
            source_root=phase9c2.SOURCE_ROOT,
            output_root=source_root,
        )
    except Exception as exc:
        raise SelectionStudyError("Phase 9C.2 source bundle verification failed") from exc
    if (
        verified["decision_id"] != SOURCE_DECISION_ID
        or verified["manifest_id"] != SOURCE_MANIFEST_ID
    ):
        raise SelectionStudyError("Phase 9C.2 decision or manifest identity drift")
    after = _inventory(source_root)
    if before != after or _inventory_sha256(after) != SOURCE_INVENTORY_SHA256:
        raise SelectionStudyError("Phase 9C.2 source changed during selection study")
    return before


def _evaluate_source(source_root: Path) -> tuple[SelectionRecord, ...]:
    _verify_phase9c2_source(source_root)
    context = phase9c2._load_cohort()
    config = phase9c2._foundation_config()
    provider_config = phase9c2._provider_config()
    policy = LatestValidPredecessorPolicy()
    if policy.policy_identity != EXPECTED_POLICY_IDENTITY:
        raise SelectionStudyError("Phase 9D policy identity drift")
    records: list[SelectionRecord] = []
    for dataset in context.datasets:
        result = phase9c2._load_persisted_provider_result(
            source_root,
            dataset,
            config,
            provider_config,
        )
        source_snapshot = result.to_snapshot()
        selection = select_latest_valid_predecessors(source_snapshot, policy=policy)
        membership = phase9c2._load_json(
            source_root / "datasets" / dataset.dataset_id / "family_membership.json"
        )
        try:
            expected_ids = tuple(
                sorted(
                    item["candidate_id"]
                    for item in membership["families"][FAMILY_ID]
                )
            )
        except (KeyError, TypeError) as exc:
            raise SelectionStudyError(
                f"missing Phase 9C.2 family membership: {dataset.dataset_id}"
            ) from exc
        record = SelectionRecord(
            dataset_id=dataset.dataset_id,
            source_snapshot_id=source_snapshot.snapshot_id,
            selection=selection,
            expected_candidate_ids=expected_ids,
            source_candidate_count=len(source_snapshot.candidates),
            provider_result_id=phase9c2._provider_result_id(result),
        )
        if selection.status.value != "selected":
            raise SelectionStudyError(f"valid Phase 9C.2 source did not select: {dataset.dataset_id}")
        if record.missing_candidate_ids or record.unexpected_candidate_ids:
            raise SelectionStudyError(f"selection membership mismatch: {dataset.dataset_id}")
        if len(record.selected_candidate_ids) != EXPECTED_SELECTED_COUNTS[dataset.dataset_id]:
            raise SelectionStudyError(f"selected count mismatch: {dataset.dataset_id}")
        records.append(record)
    if sum(record.source_candidate_count for record in records) != EXPECTED_SOURCE_CANDIDATE_COUNT:
        raise SelectionStudyError("source candidate total mismatch")
    if sum(len(record.selected_candidate_ids) for record in records) != EXPECTED_SELECTED_CANDIDATE_COUNT:
        raise SelectionStudyError("selected candidate total mismatch")
    return tuple(records)


def _dataset_payload(record: SelectionRecord) -> dict[str, Any]:
    return {
        "schema_version": DATASET_SCHEMA,
        "dataset_id": record.dataset_id,
        "source_snapshot_id": record.source_snapshot_id,
        "selection_snapshot": record.selection.to_dict(),
    }


def _source_audit(
    inventory: Sequence[Mapping[str, Any]],
    records: Sequence[SelectionRecord],
) -> dict[str, Any]:
    return {
        "schema_version": f"{STUDY_SCHEMA}_source_audit",
        "source": {
            "schema_version": SOURCE_SCHEMA,
            "decision_id": SOURCE_DECISION_ID,
            "manifest_id": SOURCE_MANIFEST_ID,
            "inventory_sha256": SOURCE_INVENTORY_SHA256,
            "member_count": len(inventory),
        },
        "pre_run_inventory": list(inventory),
        "post_run_inventory": list(inventory),
        "source_immutability_verified": True,
        "provider_result_ids": [record.provider_result_id for record in records],
        "selection_execution_count": len(records),
        "historical_provider_execution_count": len(records),
        "phase9d_provider_execution_count": 0,
        "network_request_count": 0,
    }


def _study_contract(policy: LatestValidPredecessorPolicy) -> dict[str, Any]:
    return {
        "schema_version": f"{STUDY_SCHEMA}_contract",
        "source": {
            "schema_version": SOURCE_SCHEMA,
            "decision_id": SOURCE_DECISION_ID,
            "manifest_id": SOURCE_MANIFEST_ID,
            "inventory_sha256": SOURCE_INVENTORY_SHA256,
        },
        "selection_policy": {
            "policy_identity": policy.policy_identity,
            "policy": policy.to_dict(),
            "runtime_forbidden_inputs": [
                "candidate_structure_id",
                "quality",
                "ATR",
                "future_outcomes",
                "tracking_state",
            ],
        },
        "identity_namespaces": {
            "policy": "trendline_v2_candidate_selection_policy",
            "decision": "trendline_v2_candidate_selection_decision",
            "candidate_set": "trendline_v2_candidate_set",
            "snapshot": "trendline_v2_candidate_selection_snapshot",
        },
        "execution": {
            "selection_execution_count": 6,
            "historical_provider_execution_count": 6,
            "phase9d_provider_execution_count": 0,
            "network_request_count": 0,
        },
        "boundaries": {
            "TRACKING_START": "NOT_AUTHORIZED",
            "RUNTIME_CONSUMER_MIGRATION": "NOT_AUTHORIZED",
            "DISCOVERY_DEFAULT_FILTERING": "NOT_AUTHORIZED",
            "VIEWER_DEFAULT_SELECTION": "NOT_AUTHORIZED",
            "CANONICAL_PROVIDER_CONFIG_PROMOTION": "NOT_AUTHORIZED",
            "MTF": "NOT_AUTHORIZED",
        },
    }


def _parity_rows(records: Sequence[SelectionRecord]) -> tuple[dict[str, Any], ...]:
    rows = []
    for record in records:
        rows.append(
            {
                "dataset_id": record.dataset_id,
                "source_snapshot_id": record.source_snapshot_id,
                "selection_snapshot_id": record.selection.snapshot_id,
                "source_candidate_count": record.source_candidate_count,
                "expected_selected_count": len(record.expected_candidate_ids),
                "selected_candidate_count": len(record.selected_candidate_ids),
                "missing_candidate_count": len(record.missing_candidate_ids),
                "unexpected_candidate_count": len(record.unexpected_candidate_ids),
                "membership_parity": record.missing_candidate_ids == ()
                and record.unexpected_candidate_ids == (),
            }
        )
    return tuple(rows)


def _decision(records: Sequence[SelectionRecord], policy: LatestValidPredecessorPolicy) -> dict[str, Any]:
    without_id = {
        "schema_version": f"{STUDY_SCHEMA}_decision",
        "study_status": "SELECTION_LAYER_PARITY_VERIFIED",
        "selection_policy_identity": policy.policy_identity,
        "source": {
            "decision_id": SOURCE_DECISION_ID,
            "manifest_id": SOURCE_MANIFEST_ID,
            "inventory_sha256": SOURCE_INVENTORY_SHA256,
        },
        "datasets": [
            {
                "dataset_id": record.dataset_id,
                "source_snapshot_id": record.source_snapshot_id,
                "selection_snapshot_id": record.selection.snapshot_id,
                "source_candidate_count": record.source_candidate_count,
                "selected_candidate_count": len(record.selected_candidate_ids),
                "missing_candidate_count": len(record.missing_candidate_ids),
                "unexpected_candidate_count": len(record.unexpected_candidate_ids),
                "membership_parity": not record.missing_candidate_ids
                and not record.unexpected_candidate_ids,
            }
            for record in records
        ],
        "dataset_count": len(records),
        "source_candidate_count": sum(record.source_candidate_count for record in records),
        "selected_candidate_count": sum(len(record.selected_candidate_ids) for record in records),
        "missing_candidate_count": sum(len(record.missing_candidate_ids) for record in records),
        "unexpected_candidate_count": sum(len(record.unexpected_candidate_ids) for record in records),
        "membership_parity": all(
            not record.missing_candidate_ids and not record.unexpected_candidate_ids
            for record in records
        ),
        "execution": {
            "selection_execution_count": len(records),
            "historical_provider_execution_count": len(records),
            "phase9d_provider_execution_count": 0,
            "network_request_count": 0,
        },
        "boundaries": {
            "TRACKING_START": "NOT_AUTHORIZED",
            "RUNTIME_CONSUMER_MIGRATION": "NOT_AUTHORIZED",
            "DISCOVERY_DEFAULT_FILTERING": "NOT_AUTHORIZED",
            "VIEWER_DEFAULT_SELECTION": "NOT_AUTHORIZED",
            "CANONICAL_PROVIDER_CONFIG_PROMOTION": "NOT_AUTHORIZED",
            "MTF": "NOT_AUTHORIZED",
        },
    }
    return {**without_id, "decision_id": deterministic_hash(DECISION_NAMESPACE, without_id)}


def _member_inventory(root: Path) -> tuple[dict[str, Any], ...]:
    return tuple(item for item in _inventory(root) if item["path"] != "manifest.json")


def _manifest(
    root: Path,
    *,
    decision: Mapping[str, Any],
    policy: LatestValidPredecessorPolicy,
) -> dict[str, Any]:
    members = _member_inventory(root)
    if len(members) != 10:
        raise SelectionStudyError(f"expected ten manifest members, got {len(members)}")
    without_id = {
        "schema_version": f"{STUDY_SCHEMA}_manifest",
        "decision_id": decision["decision_id"],
        "selection_policy_identity": policy.policy_identity,
        "source_inventory_sha256": SOURCE_INVENTORY_SHA256,
        "member_count": len(members),
        "members": list(members),
    }
    return {
        **without_id,
        "manifest_id": deterministic_hash(MANIFEST_NAMESPACE, without_id),
    }


def _payloads(
    records: Sequence[SelectionRecord],
    inventory: Sequence[Mapping[str, Any]],
    policy: LatestValidPredecessorPolicy,
) -> dict[str, bytes]:
    values: dict[str, bytes] = {}
    for record in records:
        path = f"datasets/{record.dataset_id}/selection_snapshot.json"
        values[path] = _canonical_bytes(_dataset_payload(record))
    values["study_contract.json"] = _canonical_bytes(_study_contract(policy))
    values["source_audit.json"] = _canonical_bytes(_source_audit(inventory, records))
    values["parity_summary.csv"] = _csv_bytes(_parity_rows(records))
    decision = _decision(records, policy)
    values["decision.json"] = _canonical_bytes(decision)
    return values


def _write_bundle(
    output_root: Path,
    *,
    records: Sequence[SelectionRecord],
    inventory: Sequence[Mapping[str, Any]],
    policy: LatestValidPredecessorPolicy,
) -> dict[str, Any]:
    if output_root.exists():
        raise FileExistsError(f"refusing existing output root: {output_root}")
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.", dir=output_root.parent))
    try:
        values = _payloads(records, inventory, policy)
        for relative, data in values.items():
            _write_atomic(staging / relative, data)
        decision = _load_json(staging / "decision.json")
        manifest = _manifest(staging, decision=decision, policy=policy)
        _write_atomic(staging / "manifest.json", _canonical_bytes(manifest))
        if output_root.exists():
            raise FileExistsError(f"refusing existing output root: {output_root}")
        os.replace(staging, output_root)
        return {
            "output_root": str(output_root),
            "decision_id": decision["decision_id"],
            "manifest_id": manifest["manifest_id"],
            "inventory_sha256": _inventory_sha256(_inventory(output_root)),
        }
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def build_study(
    *,
    source_root: str | Path = SOURCE_ROOT,
    output_root: str | Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    """Run six in-memory selections over the verified Phase 9C.2 source."""

    source_path = Path(source_root)
    output_path = Path(output_root)
    inventory = _verify_phase9c2_source(source_path)
    records = _evaluate_source(source_path)
    result = _write_bundle(
        output_path,
        records=records,
        inventory=inventory,
        policy=LatestValidPredecessorPolicy(),
    )
    verified = verify_study_bundle(source_root=source_path, output_root=output_path)
    if verified["manifest_id"] != result["manifest_id"]:
        raise SelectionStudyError("post-publication manifest verification mismatch")
    return result


def verify_study_bundle(
    *,
    source_root: str | Path = SOURCE_ROOT,
    output_root: str | Path = OUTPUT_ROOT,
) -> dict[str, Any]:
    """Independently rederive and validate the published Phase 9D bundle."""

    source_path = Path(source_root)
    output_path = Path(output_root)
    source_inventory = _verify_phase9c2_source(source_path)
    records = _evaluate_source(source_path)
    policy = LatestValidPredecessorPolicy()
    expected_values = _payloads(records, source_inventory, policy)
    for relative, expected_bytes in expected_values.items():
        actual = output_path / relative
        if actual.read_bytes() != expected_bytes:
            raise SelectionStudyError(f"selection artifact mismatch: {relative}")
    actual_manifest = _load_json(output_path / "manifest.json")
    decision = _load_json(output_path / "decision.json")
    expected_manifest = _manifest(output_path, decision=decision, policy=policy)
    if actual_manifest != expected_manifest:
        raise SelectionStudyError("selection manifest semantic mismatch")
    if actual_manifest["manifest_id"] != deterministic_hash(
        MANIFEST_NAMESPACE,
        {key: value for key, value in actual_manifest.items() if key != "manifest_id"},
    ):
        raise SelectionStudyError("selection manifest identity mismatch")
    actual_inventory = _inventory(output_path)
    if len(actual_inventory) != 11:
        raise SelectionStudyError("selection bundle must contain eleven files")
    if actual_manifest["members"] != list(_member_inventory(output_path)):
        raise SelectionStudyError("selection manifest members mismatch")
    return {
        "study_status": decision["study_status"],
        "decision_id": decision["decision_id"],
        "manifest_id": actual_manifest["manifest_id"],
        "source_inventory_sha256": _inventory_sha256(source_inventory),
        "output_inventory_sha256": _inventory_sha256(actual_inventory),
        "membership_parity": decision["membership_parity"],
    }


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
    except (ContractValidationError, FileExistsError, OSError, SelectionStudyError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
