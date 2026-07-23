from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import os
from pathlib import Path
import socket

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
from scripts import validate_trendline_v2_canonical_selection as study


UTC = timezone.utc
BASE = datetime(2026, 3, 1, tzinfo=UTC)
PROVIDER_ID = provider_identity("confirmed_extrema_pair", "v1")
EXPECTED_SNAPSHOT_IDS = {
    "btcusdt_1h": (
        "2506622d81c90004940d519625a849633471b2824687243aa12cffc238ed8c9f",
        "ed7959f4591e749f087d5dbb83c74df2a31125c51c2c77303068553e2f1190ab",
    ),
    "btcusdt_4h": (
        "ac7e968c474e12d39c68bbc0c394669f60c0f3ff63276f5c439c8bb35dff3151",
        "31330b3c58cb0ee8f33979683c080bc881d2d04b8ea76bbe18cacbdce2eb67da",
    ),
    "ethusdt_1h": (
        "ee08d3b89a53897634bb6ec15803e3298dd7fe30dfb0b41493f5ea92c03d3628",
        "7178dedceef1b0c97b99777a40b07dad808942330902edd093f83d9cd1ec812b",
    ),
    "ethusdt_4h": (
        "25ba95a404aa74e5eae9c9c040c065e35d159b43b80dd38591d7ee00f75fbb93",
        "f9c48aec092b623b89175e56888f88049fb652d75c62da56005d044a16070f56",
    ),
    "suiusdt_1h": (
        "c6d5d93d0a106a9cbeff5a1ee92b65abc81992a6dce083600e9dc6368ddf0d95",
        "d2a762fb7ff6c6e1dba2df9fdba877a00511678634c36cab7f75213ac02702db",
    ),
    "suiusdt_4h": (
        "32931d377b02d19cf3ebfe684327969e815bdced6eb60cef706359c896fb9a7a",
        "c2175d14d052f8893612508e5c23a66c60322d824191873e6a521da830909b6b",
    ),
}


def _hash(value: str) -> str:
    return deterministic_hash("trendline_v2_selection_script_test", value)


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
    return study.SelectionRecord(
        dataset_id=dataset_id,
        source_snapshot_id=source.snapshot_id,
        selection=selection,
        expected_candidate_ids=(candidate.candidate_id,),
        source_candidate_count=1,
        provider_result_id=_hash(f"{dataset_id}:provider"),
    )


def _records() -> tuple[study.SelectionRecord, ...]:
    return tuple(
        _record(dataset_id)
        for dataset_id in study.DATASET_ORDER
    )


def _inventory() -> tuple[dict[str, object], ...]:
    return ({"path": "source.json", "byte_length": 1, "sha256": "0" * 64},)


def _rebind_manifest(root: Path) -> None:
    manifest = study._load_json(root / "manifest.json")
    members = [
        {
            "path": path.relative_to(root).as_posix(),
            "byte_length": path.stat().st_size,
            "sha256": study._sha256_file(path),
        }
        for path in sorted(
            item for item in root.rglob("*") if item.is_file() and item.name != "manifest.json"
        )
    ]
    rebound = {key: value for key, value in manifest.items() if key != "manifest_id"}
    rebound["member_count"] = len(members)
    rebound["members"] = members
    rebound["manifest_id"] = study.deterministic_hash(study.MANIFEST_NAMESPACE, rebound)
    (root / "manifest.json").write_bytes(study._canonical_bytes(rebound))


def _patch_evaluation_inputs(
    monkeypatch: pytest.MonkeyPatch,
    expected_ids_by_dataset: dict[str, tuple[str, ...]],
    *,
    selected_counts: dict[str, int] | None = None,
) -> None:
    records = _records()
    source_snapshots = {}
    persisted_results = {}
    for record in records:
        candidate = record.selection.selected_candidates[0]
        source_snapshots[record.dataset_id] = DiscoverySnapshot(
            asset=candidate.asset,
            timeframe=candidate.timeframe,
            observed_at=candidate.observed_at,
            input_identity=record.selection.input_identity,
            config_identity=record.selection.discovery_config_identity,
            provider_identity=PROVIDER_ID,
            status="valid",
            candidates=(candidate,),
        )
        persisted_results[record.dataset_id] = SimpleNamespace(
            to_snapshot=lambda dataset_id=record.dataset_id: source_snapshots[dataset_id],
            to_dict=lambda dataset_id=record.dataset_id: {"dataset_id": dataset_id},
        )
    datasets = tuple(SimpleNamespace(dataset_id=record.dataset_id) for record in records)

    monkeypatch.setattr(study, "_verify_phase9c2_source", lambda _root: ())
    monkeypatch.setattr(
        study.phase9c2,
        "_load_cohort",
        lambda: SimpleNamespace(datasets=datasets),
    )
    monkeypatch.setattr(
        study.phase9c2,
        "_load_persisted_provider_result",
        lambda _root, dataset, _config, _provider: persisted_results[dataset.dataset_id],
    )
    monkeypatch.setattr(
        study.phase9c2,
        "_load_json",
        lambda path: {
            "families": {
                study.FAMILY_ID: [
                    {"candidate_id": candidate_id}
                    for candidate_id in expected_ids_by_dataset[path.parent.name]
                ]
            }
        },
    )
    monkeypatch.setattr(
        study,
        "EXPECTED_SELECTED_COUNTS",
        selected_counts or {record.dataset_id: 1 for record in records},
    )
    monkeypatch.setattr(study, "EXPECTED_SOURCE_CANDIDATE_COUNT", len(records))
    monkeypatch.setattr(study, "EXPECTED_SELECTED_CANDIDATE_COUNT", len(records))


def test_hermetic_bundle_round_trip_and_atomic_publication(tmp_path: Path, monkeypatch) -> None:
    records = _records()
    inventory = _inventory()
    monkeypatch.setattr(study, "_verify_phase9c2_source", lambda _root: inventory)
    monkeypatch.setattr(study, "_evaluate_source", lambda _root: records)
    output = tmp_path / "selection"

    result = study.build_study(source_root=tmp_path / "source", output_root=output)
    verified = study.verify_study_bundle(source_root=tmp_path / "source", output_root=output)

    assert result["decision_id"] == verified["decision_id"]
    assert verified["study_status"] == "SELECTION_LAYER_PARITY_VERIFIED"
    assert verified["membership_parity"] is True
    assert len([path for path in output.rglob("*") if path.is_file()]) == 11
    assert not tuple(output.parent.glob(f".{output.name}.*"))


def test_existing_output_root_is_not_overwritten(tmp_path: Path, monkeypatch) -> None:
    records = _records()
    inventory = _inventory()
    monkeypatch.setattr(study, "_verify_phase9c2_source", lambda _root: inventory)
    monkeypatch.setattr(study, "_evaluate_source", lambda _root: records)
    output = tmp_path / "selection"
    study.build_study(source_root=tmp_path / "source", output_root=output)
    before = (output / "manifest.json").read_bytes()

    with pytest.raises(FileExistsError):
        study.build_study(source_root=tmp_path / "source", output_root=output)
    assert (output / "manifest.json").read_bytes() == before


def test_mutated_member_is_rejected_after_outer_artifact_rebinding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    records = _records()
    inventory = _inventory()
    monkeypatch.setattr(study, "_verify_phase9c2_source", lambda _root: inventory)
    monkeypatch.setattr(study, "_evaluate_source", lambda _root: records)
    output = tmp_path / "selection"
    study.build_study(source_root=tmp_path / "source", output_root=output)

    payload = study._load_json(output / "datasets" / "btcusdt_1h" / "selection_snapshot.json")
    payload["selection_snapshot"]["source_candidate_set_identity"] = _hash("forged")
    (output / "datasets" / "btcusdt_1h" / "selection_snapshot.json").write_bytes(
        study._canonical_bytes(payload)
    )
    manifest = study._load_json(output / "manifest.json")
    member = next(
        item for item in manifest["members"]
        if item["path"] == "datasets/btcusdt_1h/selection_snapshot.json"
    )
    member["byte_length"] = (output / member["path"]).stat().st_size
    member["sha256"] = study._sha256_file(output / member["path"])
    manifest["members"] = sorted(manifest["members"], key=lambda item: item["path"])
    without_id = {key: value for key, value in manifest.items() if key != "manifest_id"}
    manifest["manifest_id"] = study.deterministic_hash(study.MANIFEST_NAMESPACE, without_id)
    (output / "manifest.json").write_bytes(study._canonical_bytes(manifest))

    with pytest.raises(study.SelectionStudyError, match="selection artifact mismatch"):
        study.verify_study_bundle(source_root=tmp_path / "source", output_root=output)


def test_parity_rejects_missing_expected_selected_id(tmp_path: Path, monkeypatch) -> None:
    records = _records()
    expected = {record.dataset_id: record.selected_candidate_ids for record in records}
    expected[records[0].dataset_id] = (_hash("missing"),)
    _patch_evaluation_inputs(monkeypatch, expected)

    with pytest.raises(study.SelectionStudyError, match="selection membership mismatch"):
        study._evaluate_source(tmp_path / "source")


def test_parity_rejects_unexpected_selected_id(tmp_path: Path, monkeypatch) -> None:
    records = _records()
    expected = {record.dataset_id: record.selected_candidate_ids for record in records}
    expected[records[0].dataset_id] = ()
    _patch_evaluation_inputs(monkeypatch, expected)

    with pytest.raises(study.SelectionStudyError, match="selection membership mismatch"):
        study._evaluate_source(tmp_path / "source")


def test_parity_rejects_selected_count_mismatch(tmp_path: Path, monkeypatch) -> None:
    records = _records()
    expected = {record.dataset_id: record.selected_candidate_ids for record in records}
    selected_counts = {record.dataset_id: 1 for record in records}
    selected_counts[records[0].dataset_id] = 2
    _patch_evaluation_inputs(
        monkeypatch,
        expected,
        selected_counts=selected_counts,
    )

    with pytest.raises(study.SelectionStudyError, match="selected count mismatch"):
        study._evaluate_source(tmp_path / "source")


def test_policy_identity_mismatch_is_rejected_after_manifest_rebinding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    records = _records()
    inventory = _inventory()
    monkeypatch.setattr(study, "_verify_phase9c2_source", lambda _root: inventory)
    monkeypatch.setattr(study, "_evaluate_source", lambda _root: records)
    output = tmp_path / "selection"
    study.build_study(source_root=tmp_path / "source", output_root=output)

    path = output / "datasets" / "btcusdt_1h" / "selection_snapshot.json"
    payload = study._load_json(path)
    payload["selection_snapshot"]["selection_policy_identity"] = _hash("forged-policy")
    path.write_bytes(study._canonical_bytes(payload))
    _rebind_manifest(output)

    with pytest.raises(study.SelectionStudyError, match="selection artifact mismatch"):
        study.verify_study_bundle(source_root=tmp_path / "source", output_root=output)


def test_source_mutation_during_verification_is_rejected(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for index in range(38):
        (source / f"source-{index:02d}.json").write_bytes(bytes([index]))
    monkeypatch.setattr(
        study,
        "SOURCE_INVENTORY_SHA256",
        study._inventory_sha256(study._inventory(source)),
    )

    def mutate_source(**kwargs: object) -> dict[str, str]:
        output_root = kwargs["output_root"]
        assert isinstance(output_root, Path)
        (output_root / "source-00.json").write_bytes(b"mutated")
        return {
            "decision_id": study.SOURCE_DECISION_ID,
            "manifest_id": study.SOURCE_MANIFEST_ID,
        }

    monkeypatch.setattr(study.phase9c2, "verify_study_bundle", mutate_source)
    with pytest.raises(study.SelectionStudyError, match="source changed"):
        study._verify_phase9c2_source(source)


def test_hermetic_study_executes_zero_provider_and_network_calls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    records = _records()
    inventory = _inventory()
    provider_calls: list[str] = []
    network_calls: list[str] = []

    def fail_provider(*_args: object, **_kwargs: object) -> object:
        provider_calls.append("provider")
        raise AssertionError("selection parity must not execute a provider")

    def fail_network(*_args: object, **_kwargs: object) -> object:
        network_calls.append("network")
        raise AssertionError("selection parity must not access the network")

    monkeypatch.setattr(study, "_verify_phase9c2_source", lambda _root: inventory)
    monkeypatch.setattr(study, "_evaluate_source", lambda _root: records)
    monkeypatch.setattr(study.phase9c2, "_execute_provider", fail_provider)
    monkeypatch.setattr(study.phase9c2, "discover_trendlines", fail_provider)
    monkeypatch.setattr(socket, "create_connection", fail_network)
    output = tmp_path / "selection"

    study.build_study(source_root=tmp_path / "source", output_root=output)

    assert provider_calls == []
    assert network_calls == []
    audit = study._load_json(output / "source_audit.json")
    assert audit["phase9d_provider_execution_count"] == 0
    assert audit["network_request_count"] == 0


@pytest.mark.skipif(
    os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1",
    reason="set TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE=1 for frozen Phase 9D evidence",
)
def test_verified_external_phase9d_bundle() -> None:
    result = study.verify_study_bundle()
    assert result["study_status"] == "SELECTION_LAYER_PARITY_VERIFIED"
    assert result["source_inventory_sha256"] == study.SOURCE_INVENTORY_SHA256
    assert result["membership_parity"] is True
    decision = study._load_json(study.OUTPUT_ROOT / "decision.json")
    assert decision["selection_policy_identity"] == study.EXPECTED_POLICY_IDENTITY
    assert decision["decision_id"] == (
        "c7daee89ffe745e12d4c8dcad65fc27a9c19f7da3b460acc32360af0f814b6cd"
    )
    assert decision["execution"] == {
        "historical_provider_execution_count": 6,
        "network_request_count": 0,
        "phase9d_provider_execution_count": 0,
        "selection_execution_count": 6,
    }
    for dataset_id, (source_id, selection_id) in EXPECTED_SNAPSHOT_IDS.items():
        dataset = decision["datasets"][study.DATASET_ORDER.index(dataset_id)]
        assert dataset["source_snapshot_id"] == source_id
        assert dataset["selection_snapshot_id"] == selection_id
        payload = study._load_json(
            study.OUTPUT_ROOT / "datasets" / dataset_id / "selection_snapshot.json"
        )
        assert payload["selection_snapshot"]["snapshot_id"] == selection_id
        assert payload["selection_snapshot"]["selection_policy_identity"] == study.EXPECTED_POLICY_IDENTITY
    assert result["decision_id"] == decision["decision_id"]
    assert result["manifest_id"] == (
        "51fb6ff236e8e6f94d47082c00fa27dc5692ab8e629e0a10959f35ccc2675585"
    )
    assert result["output_inventory_sha256"] == (
        "aca26bb086c3cd0b8ce04c152ab1b71fa240068c92c8f5691a7848fe3900ecb8"
    )
