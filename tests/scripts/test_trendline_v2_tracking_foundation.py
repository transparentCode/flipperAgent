from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

import pytest

from libs.models.trendline_v2.domain import (
    AnchorRef,
    CandidateEvidence,
    DiscoverySnapshot,
    LineCandidate,
    LineGeometry,
    LineRole,
)
from libs.models.trendline_v2.domain.identity import deterministic_hash, provider_identity
from libs.models.trendline_v2.selection import LatestValidPredecessorPolicy, select_latest_valid_predecessors
from libs.models.trendline_v2.tracking import (
    ExactSelectedStructureTrackingPolicy,
    FamilyTrackingTransitionType,
)
from scripts import validate_trendline_v2_tracking_foundation as study


UTC = timezone.utc
BASE = datetime(2026, 3, 1, tzinfo=UTC)
PROVIDER_ID = provider_identity("confirmed_extrema_pair", "v1")
EXPECTED_TRACKING_SNAPSHOT_IDS = {
    "btcusdt_1h": "3b6508ddce3495af3d7eeefc2c467007abe54a50c723e9a8bd4c312e7721b26b",
    "btcusdt_4h": "8412309f155294e819b5243e3ee1af276d1bcf5c0ca971aaed97558965bbb2b9",
    "ethusdt_1h": "584b6b2c032f65176f8a993ffa50ab41b62509ada163ab9fd5de119c6848cfb5",
    "ethusdt_4h": "c7f342c906ae1d551b0e2d982f2db88a807fa2ac885b76b66d733a20dd62f919",
    "suiusdt_1h": "6fbbedaf9345c1b50d7419d5ed297c472ee3330110309f86c82cd636e6e34fca",
    "suiusdt_4h": "4d80da14de530fd51e49d01e88bbce11b929156616e6bf9e0d9e00e2cf5092e4",
}
EXPECTED_DECISION_ID = "44fe6f1c0c86563416f023c1c7530be61f30b0755ccf5335fbe0a4086df9ff0f"
EXPECTED_MANIFEST_ID = "064a641c797c655d2726a4d332168cd3740159790dff1129047ca8bd12979d6a"
EXPECTED_OUTPUT_INVENTORY = "bc560cda8f4cd478313b8e4fb84338dc332679940ba6a56fde7b50dc97415080"


def _hash(value: str) -> str:
    return deterministic_hash("trendline_v2_tracking_script_test", value)


def _record(dataset_id: str) -> study.SelectionRecord:
    first_time = BASE + timedelta(hours=1)
    second_time = BASE + timedelta(hours=10)
    first = AnchorRef(
        anchor_id=_hash(f"{dataset_id}:first"),
        pivot_time=first_time,
        confirmation_time=first_time + timedelta(hours=1),
        price=90.0,
    )
    second = AnchorRef(
        anchor_id=_hash(f"{dataset_id}:second"),
        pivot_time=second_time,
        confirmation_time=second_time + timedelta(hours=1),
        price=100.0,
    )
    candidate = LineCandidate.create(
        asset="BTCUSDT",
        timeframe="4h",
        role=LineRole.SUPPORT,
        geometry=LineGeometry(first_time, second_time, 90.0, 100.0),
        anchors=(first, second),
        evidence=CandidateEvidence(2, 2, (second_time - first_time).total_seconds()),
        observed_at=BASE + timedelta(hours=20),
        provider_name="confirmed_extrema_pair",
        provider_version="v1",
    )
    source = DiscoverySnapshot(
        asset=candidate.asset,
        timeframe=candidate.timeframe,
        observed_at=candidate.observed_at,
        input_identity=_hash(f"{dataset_id}:input"),
        config_identity=_hash("config"),
        provider_identity=PROVIDER_ID,
        status="valid",
        candidates=(candidate,),
    )
    selection = select_latest_valid_predecessors(
        source,
        policy=LatestValidPredecessorPolicy(),
    )
    return study.SelectionRecord(dataset_id=dataset_id, selection=selection)


def _records() -> tuple[study.SelectionRecord, ...]:
    return tuple(_record(dataset_id) for dataset_id in study.DATASET_ORDER)


def _source_inventory(root: Path) -> tuple[dict[str, object], ...]:
    root.mkdir(parents=True, exist_ok=True)
    (root / "source.json").write_bytes(b"source")
    return study._inventory(root)


def _build_hermetic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, tuple[study.SelectionRecord, ...], tuple[dict[str, object], ...]]:
    source = tmp_path / "source"
    inventory = _source_inventory(source)
    records = _records()
    monkeypatch.setattr(study, "_verify_phase9d_source", lambda _root: inventory)
    monkeypatch.setattr(study, "_load_selection_records", lambda _root: records)
    output = tmp_path / "tracking"
    study.build_study(source_root=source, output_root=output)
    return output, records, inventory


def test_hermetic_initial_birth_bundle_round_trip_and_atomic_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, records, inventory = _build_hermetic(tmp_path, monkeypatch)
    verified = study._verify_published_bundle(
        output,
        records=records,
        snapshots=study._initial_tracking(records, ExactSelectedStructureTrackingPolicy()),
        inventory=inventory,
        policy=ExactSelectedStructureTrackingPolicy(),
    )
    assert verified["tracking_policy_identity"] == ExactSelectedStructureTrackingPolicy().policy_identity
    assert len(tuple(path for path in output.rglob("*") if path.is_file())) == 11
    assert not tuple(output.parent.glob(f".{output.name}.*"))
    assert (output / "birth_summary.csv").read_text().endswith("\n")


def test_existing_output_root_is_not_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, _, _ = _build_hermetic(tmp_path, monkeypatch)
    before = (output / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        study.build_study(source_root=tmp_path / "source", output_root=output)
    assert (output / "manifest.json").read_bytes() == before


def test_mutated_tracking_member_is_rejected_even_after_manifest_rebinding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, records, inventory = _build_hermetic(tmp_path, monkeypatch)
    path = output / "datasets" / "btcusdt_1h" / "tracking_snapshot.json"
    payload = study._load_json(path)
    payload["tracking_snapshot"]["tracking_policy_identity"] = _hash("forged")
    path.write_bytes(study._canonical_bytes(payload))
    manifest = study._load_json(output / "manifest.json")
    manifest["members"] = [
        {
            "path": item["path"],
            "byte_length": (output / item["path"]).stat().st_size,
            "sha256": study._sha256_file(output / item["path"]),
        }
        for item in manifest["members"]
    ]
    without_id = {key: value for key, value in manifest.items() if key != "manifest_id"}
    manifest["manifest_id"] = study.deterministic_hash(study.MANIFEST_NAMESPACE, without_id)
    (output / "manifest.json").write_bytes(study._canonical_bytes(manifest))
    snapshots = study._initial_tracking(records, ExactSelectedStructureTrackingPolicy())
    with pytest.raises(study.TrackingStudyError, match="tracking artifact mismatch"):
        study._verify_published_bundle(
            output,
            records=records,
            snapshots=snapshots,
            inventory=inventory,
            policy=ExactSelectedStructureTrackingPolicy(),
        )


def test_source_mutation_during_load_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    inventory = _source_inventory(source)
    records = _records()
    monkeypatch.setattr(study, "_verify_phase9d_source", lambda _root: inventory)

    def mutate(_root: Path) -> tuple[study.SelectionRecord, ...]:
        (source / "source.json").write_bytes(b"changed")
        return records

    monkeypatch.setattr(study, "_load_selection_records", mutate)
    with pytest.raises(study.TrackingStudyError, match="source changed"):
        study.build_study(source_root=source, output_root=tmp_path / "tracking")


def test_initial_tracking_is_zero_provider_and_network_and_all_births(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = _records()
    calls: list[str] = []
    original = study.track_trendline_families

    def tracked(*args: object, **kwargs: object):
        calls.append("tracking")
        return original(*args, **kwargs)

    monkeypatch.setattr(study, "track_trendline_families", tracked)
    snapshots = study._initial_tracking(records, ExactSelectedStructureTrackingPolicy())
    assert len(calls) == 6
    assert sum(len(snapshot.active_families) for snapshot in snapshots) == 6
    assert sum(
        transition.transition_type is FamilyTrackingTransitionType.BIRTH
        for snapshot in snapshots
        for transition in snapshot.transitions
    ) == 6


def test_invalid_non_birth_persisted_snapshot_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output, records, inventory = _build_hermetic(tmp_path, monkeypatch)
    path = output / "datasets" / "btcusdt_1h" / "tracking_snapshot.json"
    payload = study._load_json(path)
    payload["tracking_snapshot"]["transitions"][0]["transition_type"] = "continue"
    path.write_bytes(study._canonical_bytes(payload))
    snapshots = study._initial_tracking(records, ExactSelectedStructureTrackingPolicy())
    with pytest.raises(study.TrackingStudyError):
        study._verify_published_bundle(
            output,
            records=records,
            snapshots=snapshots,
            inventory=inventory,
            policy=ExactSelectedStructureTrackingPolicy(),
        )


@pytest.mark.skipif(
    os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1",
    reason="requires the frozen Phase 9D evidence bundle",
)
def test_external_phase9d_tracking_bundle_exact_identities() -> None:
    result = study.verify_study_bundle()
    assert result["study_status"] == "TRACKING_FOUNDATION_INITIAL_BIRTHS_VERIFIED"
    assert result["tracking_policy_identity"] == study.ExactSelectedStructureTrackingPolicy().policy_identity
    assert result["source_inventory_sha256"] == study.PHASE9D_OUTPUT_INVENTORY_SHA256
    assert result["output_inventory_sha256"] == EXPECTED_OUTPUT_INVENTORY
    decision = study._load_json(study.OUTPUT_ROOT / "decision.json")
    manifest = study._load_json(study.OUTPUT_ROOT / "manifest.json")
    assert decision["decision_id"] == EXPECTED_DECISION_ID == result["decision_id"]
    assert manifest["manifest_id"] == EXPECTED_MANIFEST_ID == result["manifest_id"]
    assert decision["selected_source_candidate_count"] == 1619
    assert decision["active_tracked_family_count"] == 1619
    assert decision["birth_transition_count"] == 1619
    assert decision["continuation_transition_count"] == 0
    assert decision["source_removed_transition_count"] == 0
    assert [
        dataset["source_selection_snapshot_id"] for dataset in decision["datasets"]
    ] == [study.EXPECTED_SELECTION_SNAPSHOT_IDS[dataset_id] for dataset_id in study.DATASET_ORDER]
    assert [
        dataset["tracking_snapshot_id"] for dataset in decision["datasets"]
    ] == [EXPECTED_TRACKING_SNAPSHOT_IDS[dataset_id] for dataset_id in study.DATASET_ORDER]
    audit = study._load_json(study.OUTPUT_ROOT / "source_audit.json")
    assert audit["source_selection_snapshot_ids"] == [
        study.EXPECTED_SELECTION_SNAPSHOT_IDS[dataset_id] for dataset_id in study.DATASET_ORDER
    ]
    assert audit["tracking_snapshot_ids"] == [
        EXPECTED_TRACKING_SNAPSHOT_IDS[dataset_id] for dataset_id in study.DATASET_ORDER
    ]
