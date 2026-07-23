from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path

import pytest

from libs.models.trendline_v2.domain.identity import deterministic_hash
from scripts import analyze_trendline_v2_candidate_eligibility_families as study


def _evaluation(*, available: bool = True, contact: bool = True) -> dict[str, object]:
    if not available:
        return {
            "evaluation_available": False,
            "future_contact_count": None,
            "future_body_violation_count": None,
            "has_exact_contact": None,
            "survives_exact_side": None,
            "contact_and_survives_exact_side": None,
        }
    return {
        "evaluation_available": True,
        "future_contact_count": 2 if contact else 0,
        "future_body_violation_count": 0 if contact else 2,
        "has_exact_contact": contact,
        "survives_exact_side": contact,
        "contact_and_survives_exact_side": contact,
    }


def _record(
    index: int,
    *,
    role: str,
    group: str,
    segment: str,
    first_time: str,
    skip: int,
    clearance: float,
    prominence: float,
) -> dict[str, object]:
    first_position = index + 1
    second_position = first_position + 2 + (index % 2)
    return {
        "candidate_id": f"candidate-{index}",
        "candidate_structure_id": f"structure-{index}",
        "role": role,
        "first_anchor_id": f"first-{index}",
        "second_anchor_id": group,
        "first_anchor_time": first_time,
        "second_anchor_time": f"2025-08-{10 + index:02d}T00:00:00Z",
        "candidate_available_at": f"2025-08-{12 + index:02d}T00:00:00Z",
        "anchor_source_positions": [first_position, second_position],
        "confirmation_positions": [first_position + 1, second_position + 1],
        "anchor_span_bars": second_position - first_position,
        "chronological_segment": segment,
        "same_role_extrema_skip_count": skip,
        "minimum_body_clearance_bps": clearance,
        "minimum_anchor_prominence_bps": prominence,
        "absolute_slope_bps_per_day": 1.0 + index,
        "evaluations": {
            str(horizon): _evaluation(contact=index % 2 == 0)
            for horizon in study.HORIZONS
        },
    }


def _records() -> list[dict[str, object]]:
    return [
        _record(0, role="support", group="support-1", segment="early", first_time="2025-08-01T00:00:00Z", skip=0, clearance=1.0, prominence=4.0),
        _record(1, role="support", group="support-1", segment="early", first_time="2025-08-02T00:00:00Z", skip=1, clearance=3.0, prominence=2.0),
        _record(2, role="support", group="support-1", segment="early", first_time="2025-08-03T00:00:00Z", skip=4, clearance=2.0, prominence=8.0),
        _record(3, role="support", group="support-2", segment="late", first_time="2025-08-04T00:00:00Z", skip=0, clearance=5.0, prominence=5.0),
        _record(4, role="resistance", group="resistance-1", segment="early", first_time="2025-08-05T00:00:00Z", skip=2, clearance=2.0, prominence=1.0),
        _record(5, role="resistance", group="resistance-1", segment="late", first_time="2025-08-06T00:00:00Z", skip=3, clearance=7.0, prominence=3.0),
        _record(6, role="resistance", group="resistance-2", segment="early", first_time="2025-08-07T00:00:00Z", skip=0, clearance=4.0, prominence=6.0),
        _record(7, role="resistance", group="resistance-2", segment="late", first_time="2025-08-08T00:00:00Z", skip=0, clearance=4.0, prominence=9.0),
    ]


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(study._canonical_bytes(value))


def _synthetic_source(tmp_path: Path) -> tuple[Path, study.StudyBinding, list[dict[str, object]]]:
    root = tmp_path / "source"
    root.mkdir()
    records = _records()
    source_identity = "source-identity"
    study_id = "study-id"
    phase9a_id = "phase9a-id"
    candidate_payload = {
        "schema_version": "trendline_v2_phase_9b1_candidate_records_v1",
        "source_identity": source_identity,
        "phase9a_study_id": phase9a_id,
        "candidate_count": len(records),
        "records": records,
    }
    source_audit = {
        "schema_version": "trendline_v2_phase_9b1_source_audit_v1",
        "source_identity": source_identity,
        "source_inventory_sha256": "upstream-source-digest",
        "post_run_source_inventory_sha256": "upstream-source-digest",
        "source_immutability_verified": True,
        "provider_execution_count": 0,
        "network_request_count": 0,
    }
    decision = {
        "schema_version": "trendline_v2_phase_9b1_decision_v1",
        "study_id": study_id,
        "study_status": "DESCRIPTIVE_EVIDENCE_ONLY",
        "candidate_count": len(records),
        "support_count": 4,
        "resistance_count": 4,
        "QUALITY_SCORE_SELECTION": "NOT_AUTHORIZED",
        "ELIGIBILITY_RULE_SELECTION": "NOT_AUTHORIZED",
        "PARAMETER_PROMOTION": "NOT_AUTHORIZED",
        "TRACKER_START": "NOT_AUTHORIZED",
    }
    _write_json(root / "candidate_records.json", candidate_payload)
    root.joinpath("cohort_summary.csv").write_text("cohort\n", encoding="utf-8")
    _write_json(root / "decision.json", decision)
    _write_json(root / "feature_associations.json", {"schema_version": "associations-v1"})
    _write_json(root / "feature_contract.json", {"schema_version": "contract-v1"})
    _write_json(root / "source_audit.json", source_audit)

    members = []
    for name in sorted(study.SOURCE_DATA_MEMBERS):
        path = root / name
        members.append({
            "path": name,
            "byte_length": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    manifest_without_id = {
        "schema_version": "trendline_v2_phase_9b1_manifest_v1",
        "study_id": study_id,
        "source_identity": source_identity,
        "candidate_count": len(records),
        "provider_execution_count": 0,
        "network_request_count": 0,
        "members": members,
    }
    manifest = {
        **manifest_without_id,
        "manifest_id": deterministic_hash(
            "trendline_v2_phase_9b1_manifest", manifest_without_id
        ),
    }
    _write_json(root / "manifest.json", manifest)
    inventory = study._artifact_inventory(root)
    binding = study.StudyBinding(
        study_id=study_id,
        manifest_id=manifest["manifest_id"],
        inventory_sha256=study._inventory_digest(inventory),
        source_identity=source_identity,
        phase9a_study_id=phase9a_id,
        candidate_count=len(records),
        support_count=4,
        resistance_count=4,
        second_anchor_group_count=4,
        row_count=20,
        member_hashes={item["path"]: item["sha256"] for item in members},
    )
    return root, binding, records


def _family_ids(families: dict[str, tuple[dict[str, object], ...]]) -> dict[str, tuple[str, ...]]:
    return {
        family_id: tuple(record["candidate_id"] for record in records)
        for family_id, records in families.items()
    }


def test_exact_eight_family_contract_and_selector_hash() -> None:
    assert study.FAMILY_IDS == (
        "all_candidates_control_v1",
        "adjacent_extrema_only_v1",
        "skip_le_1_v1",
        "skip_le_3_v1",
        "latest_valid_predecessor_v1",
        "earliest_valid_predecessor_v1",
        "max_minimum_body_clearance_v1",
        "max_minimum_anchor_prominence_v1",
    )
    assert len(study.SELECTOR_FIELDS) == 10
    assert set(study.FORBIDDEN_SELECTOR_FIELDS).isdisjoint(study.SELECTOR_FIELDS)
    assert len(study.FAMILY_DEFINITIONS) == 8


def test_control_nested_membership_and_role_segment_coverage() -> None:
    families = study._select_families(_records())
    control = {record["candidate_id"] for record in families[study.FAMILY_IDS[0]]}
    assert len(control) == 8
    assert set(record["candidate_id"] for record in families["adjacent_extrema_only_v1"]) <= set(
        record["candidate_id"] for record in families["skip_le_1_v1"]
    )
    assert set(record["candidate_id"] for record in families["skip_le_1_v1"]) <= set(
        record["candidate_id"] for record in families["skip_le_3_v1"]
    )
    for records in families.values():
        assert {record["role"] for record in records} == {"support", "resistance"}
        assert {record["chronological_segment"] for record in records} == {"early", "late"}
        assert {record["candidate_id"] for record in records} <= control


def test_latest_and_earliest_predecessor_semantics() -> None:
    families = study._select_families(_records())
    latest = {record["second_anchor_id"]: record for record in families["latest_valid_predecessor_v1"]}
    earliest = {record["second_anchor_id"]: record for record in families["earliest_valid_predecessor_v1"]}
    assert latest["support-1"]["candidate_id"] == "candidate-2"
    assert earliest["support-1"]["candidate_id"] == "candidate-0"
    assert latest["resistance-1"]["candidate_id"] == "candidate-5"
    assert earliest["resistance-1"]["candidate_id"] == "candidate-4"


def test_max_clearance_and_prominence_use_stable_ties() -> None:
    families = study._select_families(_records())
    clearance = {record["second_anchor_id"]: record for record in families["max_minimum_body_clearance_v1"]}
    prominence = {record["second_anchor_id"]: record for record in families["max_minimum_anchor_prominence_v1"]}
    assert clearance["support-1"]["candidate_id"] == "candidate-1"
    assert clearance["resistance-2"]["candidate_id"] == "candidate-6"
    assert prominence["support-1"]["candidate_id"] == "candidate-2"
    assert prominence["resistance-2"]["candidate_id"] == "candidate-7"


def test_membership_is_input_order_independent_and_repeated() -> None:
    records = _records()
    first = _family_ids(study._select_families(records))
    second = _family_ids(study._select_families(list(reversed(records))))
    third = _family_ids(study._select_families(records))
    assert first == second == third


def test_future_label_mutation_does_not_change_membership() -> None:
    original = _family_ids(study._select_families(_records()))
    mutated = _records()
    for record in mutated:
        for evaluation in record["evaluations"].values():
            evaluation["future_contact_count"] = 999
            evaluation["future_body_violation_count"] = 999
            evaluation["has_exact_contact"] = not evaluation["has_exact_contact"]
            evaluation["survives_exact_side"] = not evaluation["survives_exact_side"]
            evaluation["contact_and_survives_exact_side"] = not evaluation["contact_and_survives_exact_side"]
    assert _family_ids(study._select_families(mutated)) == original


def test_selector_owned_mutations_are_stage_local() -> None:
    baseline = _family_ids(study._select_families(_records()))
    skip_mutated = _records()
    skip_mutated[0]["same_role_extrema_skip_count"] = 9
    skip_result = _family_ids(study._select_families(skip_mutated))
    for family_id in study.FAMILY_IDS[4:]:
        assert skip_result[family_id] == baseline[family_id]
    clearance_mutated = _records()
    clearance_mutated[0]["minimum_body_clearance_bps"] = 99.0
    clearance_result = _family_ids(study._select_families(clearance_mutated))
    assert clearance_result["max_minimum_body_clearance_v1"] != baseline[
        "max_minimum_body_clearance_v1"
    ]
    for family_id in (
        "adjacent_extrema_only_v1",
        "skip_le_1_v1",
        "skip_le_3_v1",
        "latest_valid_predecessor_v1",
        "earliest_valid_predecessor_v1",
        "max_minimum_anchor_prominence_v1",
    ):
        assert clearance_result[family_id] == baseline[family_id]


def test_one_per_anchor_and_support_resistance_isolation() -> None:
    families = study._select_families(_records())
    for family_id in study.FAMILY_IDS[4:]:
        records = families[family_id]
        groups = [(record["role"], record["second_anchor_id"]) for record in records]
        assert len(groups) == len(set(groups)) == 4
        assert {record["role"] for record in records} == {"support", "resistance"}


def test_metric_arithmetic_and_empty_cohort() -> None:
    records = _records()
    assert study._metric_summary([], 6)["evaluation_available_count"] == 0
    metric = study._metric_summary(records, 6)
    assert metric["evaluation_available_count"] == 8
    assert metric["contact_rate"] == 0.5
    group_metric = study._group_weighted_metric(records, 6)
    assert group_metric["weighted_group_count"] == 4
    assert group_metric["contact_rate"] == pytest.approx(5 / 12)
    assert group_metric["mean_of_group_mean_future_contact_count"] == pytest.approx(5 / 6)
    assert group_metric["mean_of_group_mean_future_body_violation_count"] == pytest.approx(7 / 6)
    assert "median_future_contact_count" not in group_metric
    assert "median_future_body_violation_count" not in group_metric
    outcome = study._outcome_summary(records)["6"]
    support_delta = outcome["early_to_late"]["support"]["candidate_weighted_descriptive"]
    assert support_delta["candidate_count_delta"] == -2
    assert support_delta["contact_rate_delta"] == pytest.approx(-2 / 3)
    overlap = study._overlap_matrix(study._select_families(records))
    pair = overlap["pairwise_membership"]["adjacent_extrema_only_v1|skip_le_1_v1"]
    assert pair["intersection_count"] == 4
    assert pair["union_count"] == 5
    assert pair["jaccard_membership_ratio"] == pytest.approx(0.8)


def test_source_binding_and_artifact_bundle_are_hermetic(tmp_path: Path) -> None:
    source, binding, records = _synthetic_source(tmp_path)
    output = tmp_path / "output"
    paths = study.run_study(source_root=source, output_root=output, _binding=binding)
    assert set(paths) == {
        "source_audit",
        "family_contract",
        "family_membership",
        "family_summary",
        "outcome_summary",
        "overlap_matrix",
        "decision",
        "manifest",
    }
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["selector_contract_id"] == study.SELECTOR_CONTRACT_ID
    assert manifest["candidate_count_control"] == len(records)
    assert tuple(item["path"] for item in manifest["members"]) == tuple(
        sorted(item["path"] for item in manifest["members"])
    )
    for item in manifest["members"]:
        path = output / item["path"]
        assert item["byte_length"] == path.stat().st_size
        assert item["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    audit = json.loads((output / "source_audit.json").read_text())
    assert audit["source_immutability_verified"] is True
    assert audit["pre_run_inventory_sha256"] == binding.inventory_sha256
    assert audit["post_run_inventory_sha256"] == binding.inventory_sha256
    decision = json.loads((output / "decision.json").read_text())
    assert all(
        value == "ARCHITECTURALLY_VALID_FOR_FRESH_SCOPE_STUDY"
        for value in decision["family_architecture_classification"].values()
    )
    assert decision["ELIGIBILITY_FAMILY_SELECTION"] == "NOT_AUTHORIZED"


def test_existing_output_refused(tmp_path: Path) -> None:
    source, binding, _ = _synthetic_source(tmp_path)
    output = tmp_path / "output"
    study.run_study(source_root=source, output_root=output, _binding=binding)
    with pytest.raises(FileExistsError):
        study.run_study(source_root=source, output_root=output, _binding=binding)


def test_source_mutation_before_execution_rejected(tmp_path: Path) -> None:
    source, binding, _ = _synthetic_source(tmp_path)
    source.joinpath("cohort_summary.csv").write_text("changed\n", encoding="utf-8")
    with pytest.raises(study.StudyArtifactError):
        study.run_study(source_root=source, output_root=tmp_path / "output", _binding=binding)


def test_source_mutation_during_execution_rejected(tmp_path: Path) -> None:
    source, binding, _ = _synthetic_source(tmp_path)

    def mutate(path: Path) -> None:
        path.joinpath("cohort_summary.csv").write_text("changed\n", encoding="utf-8")

    with pytest.raises(study.StudyArtifactError):
        study.run_study(
            source_root=source,
            output_root=tmp_path / "output",
            _binding=binding,
            _before_post_run_check=mutate,
        )


def test_source_mutation_during_manifest_write_rejected(tmp_path: Path) -> None:
    source, binding, _ = _synthetic_source(tmp_path)

    def mutate(path: Path) -> None:
        path.joinpath("cohort_summary.csv").write_text("changed\n", encoding="utf-8")

    with pytest.raises(study.StudyArtifactError):
        study.run_study(
            source_root=source,
            output_root=tmp_path / "output",
            _binding=binding,
            _during_manifest_write=mutate,
        )


def test_no_provider_network_viewer_or_legacy_dependencies() -> None:
    source = Path(study.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]
    assert all("trendline_family" not in value for value in imports)
    assert all("regime" not in value.lower() for value in imports)
    forbidden = (
        "discover_trendlines",
        "BinanceNativeAdapter",
        "plotly",
        "matplotlib",
        "webbrowser",
        "browser",
        "libs.trendlines",
        "trendlines_old",
    )
    assert not any(value in source for value in forbidden)


def test_decision_has_no_selection_claim() -> None:
    source = Path(study.__file__).read_text(encoding="utf-8").lower()
    assert "winner" not in source
    assert "optimal" not in source
    assert "recommended selector" not in source
    assert "statistical significance" not in source
    assert "trading improvement" not in source


def test_opt_in_external_evidence(tmp_path: Path) -> None:
    if os.environ.get("TRENDLINE_V2_VERIFY_EXTERNAL_EVIDENCE") != "1":
        pytest.skip("external evidence verification disabled")
    source = study.SOURCE_ROOT
    expected_counts = {
        "all_candidates_control_v1": 2697,
        "adjacent_extrema_only_v1": 303,
        "skip_le_1_v1": 527,
        "skip_le_3_v1": 827,
        "latest_valid_predecessor_v1": 321,
        "earliest_valid_predecessor_v1": 321,
        "max_minimum_body_clearance_v1": 321,
        "max_minimum_anchor_prominence_v1": 321,
    }

    recomputed_manifests = []
    recomputed_decisions = []
    for index in (1, 2):
        output = tmp_path / f"external-recomputed-{index}"
        paths = study.run_study(source_root=source, output_root=output)
        decision = json.loads(paths["decision"].read_text())
        manifest = json.loads(paths["manifest"].read_text())
        assert decision["family_candidate_counts"] == expected_counts
        recomputed_manifests.append(manifest)
        recomputed_decisions.append(decision)
    assert all(
        value == "ARCHITECTURALLY_VALID_FOR_FRESH_SCOPE_STUDY"
        for value in recomputed_decisions[0]["family_architecture_classification"].values()
    )
    assert recomputed_manifests[0] == recomputed_manifests[1]
    assert recomputed_decisions[0]["decision_id"] == recomputed_decisions[1]["decision_id"]

    if study.OUTPUT_ROOT.exists():
        canonical_manifest = study._load_json(study.OUTPUT_ROOT / "manifest.json")
        canonical_decision = study._load_json(study.OUTPUT_ROOT / "decision.json")
        assert canonical_manifest["manifest_id"] == recomputed_manifests[0]["manifest_id"]
        assert canonical_manifest["members"] == recomputed_manifests[0]["members"]
        assert canonical_decision["decision_id"] == recomputed_decisions[0]["decision_id"]
        assert study._sha256_file(study.OUTPUT_ROOT / "decision.json") == study._sha256_file(
            tmp_path / "external-recomputed-1" / "decision.json"
        )
