from __future__ import annotations

from dataclasses import replace
import json
import shutil
from pathlib import Path

import pytest

from libs.models.trendline_family.contracts import canonical_json
from scripts import build_trendline_family_candidate_evidence_report as report


@pytest.fixture()
def copied_sources(tmp_path: Path) -> tuple[Path, Path]:
    source_root = tmp_path / "sources"
    v1 = source_root / report.V1_TRIAL_NAME
    v2 = source_root / report.TRIAL_NAME
    shutil.copytree(report.V1_TRIAL_ROOT, v1)
    shutil.copytree(report.V2_TRIAL_ROOT, v2)
    return v1, v2


@pytest.fixture()
def copied_report_bundle(tmp_path: Path) -> Path:
    output_root = tmp_path / "report"
    shutil.copytree(report.REPORT_ROOT, output_root)
    return output_root


def _build(tmp_path: Path, sources: tuple[Path, Path]):
    return report.build_candidate_evidence_report(
        v1_root=sources[0],
        v2_root=sources[1],
        output_root=tmp_path / "report",
    )


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_canonical_json(path: Path, payload: object) -> None:
    path.write_bytes(canonical_json(payload).encode("utf-8") + b"\n")


def _update_outer_source_inventory_hash(output_root: Path) -> None:
    source_path = output_root / "source_inventory.json"
    manifest_path = output_root / "report_manifest.json"
    manifest = _read_json(manifest_path)
    manifest["source_inventory_sha256"] = report._sha256_bytes(source_path.read_bytes())
    _write_canonical_json(manifest_path, manifest)


def test_report_script_is_read_only_and_has_no_network_or_runner_boundary() -> None:
    source = Path(report.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "BinanceNativeAdapter",
        "get_historical_ohlcv",
        "run_phase_i_evaluation",
        "CandidateGeometryEvaluator",
        "run_stage_grid",
        "evaluate_holdout_once",
    ):
        assert forbidden not in source


def test_report_generation_is_deterministic_complete_and_preserves_sources(
    copied_sources: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    before = report.capture_source_inventories(v1_root=copied_sources[0], v2_root=copied_sources[1])
    paths = _build(tmp_path, copied_sources)
    verified = report.validate_report_bundle(output_root=tmp_path / "report")
    after = report.capture_source_inventories(v1_root=copied_sources[0], v2_root=copied_sources[1])
    evidence = verified["evidence_report"]

    assert set(paths) == {"source_inventory", "evidence_report", "evidence_markdown", "report_manifest"}
    assert before == after
    assert len(evidence["primary_trial_evidence"]) == 6
    expected_trial_ids = tuple(
        trial["trial_id"]
        for trial in sorted(
            (item["trial"] for item in evidence["primary_trial_evidence"]),
            key=lambda item: (canonical_json(item["parameter_overrides"]), item["trial_id"]),
        )
    )
    assert tuple(item["trial"]["trial_id"] for item in evidence["primary_trial_evidence"]) == expected_trial_ids
    assert evidence["finalist_and_holdout_evidence"] == {
        "validation_finalist": None,
        "finalist_freeze": "absent",
        "holdout_open_audits": "absent",
        "baseline_holdout_result": "absent",
        "finalist_holdout_result": "absent",
    }
    assert evidence["recommendation"]["decision"] == "reject"
    assert evidence["recommendation"]["rationale"] == ["no_validation_trial_passed_stage_owned_gates"]
    assert "holdout_metrics" not in str(evidence["finalist_and_holdout_evidence"])
    assert _build(tmp_path, copied_sources) == paths


def test_existing_report_bundle_validates_source_inventory_semantics() -> None:
    verified = report.validate_report_bundle(output_root=report.REPORT_ROOT)
    derived_hashes = report.validate_source_inventory_payload(verified["source_inventory"])

    assert derived_hashes == verified["evidence_report"]["report_identity"]["source_inventory_hashes"]
    assert derived_hashes == verified["report_manifest"]["source_inventory_hashes"]


def test_input_manifest_and_normalized_csv_tampering_rejects(
    copied_sources: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    normalized = copied_sources[1] / "input" / "normalized_ohlcv.csv"
    normalized.write_bytes(normalized.read_bytes() + b"\n")
    with pytest.raises(report.EvidenceReportError, match="SHA-256"):
        _build(tmp_path, copied_sources)

    copied_sources = (
        copied_sources[0],
        tmp_path / "v2-dataset-tampered",
    )
    shutil.copytree(report.V2_TRIAL_ROOT, copied_sources[1])
    manifest = copied_sources[1] / "input" / "input_manifest.json"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace("dataset_ccaf", "dataset_dead", 1), encoding="utf-8")
    with pytest.raises(report.EvidenceReportError, match="source identity mismatch for dataset_hash"):
        _build(tmp_path, copied_sources)


def test_phase_i_and_recommendation_identity_tampering_rejects(
    copied_sources: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    recommendation = copied_sources[1] / "phase_i" / "candidate_geometry" / "recommendation.json"
    recommendation.write_text(recommendation.read_text(encoding="utf-8").replace("\"reject\"", "\"hold\"", 1), encoding="utf-8")
    with pytest.raises(report.EvidenceReportError, match="Phase-I artifact verification failed"):
        _build(tmp_path, copied_sources)
    assert not (tmp_path / "report").exists()


def test_report_manifest_rejects_markdown_tampering(
    copied_sources: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    _build(tmp_path, copied_sources)
    markdown = tmp_path / "report" / "evidence_report.md"
    markdown.write_bytes(markdown.read_bytes() + b"tampered")
    with pytest.raises(report.EvidenceReportError, match="Markdown hash mismatch"):
        report.validate_report_bundle(output_root=tmp_path / "report")


def test_forged_nested_source_hash_rejects_even_with_rebound_outer_manifest(
    copied_report_bundle: Path,
) -> None:
    source_path = copied_report_bundle / "source_inventory.json"
    source = _read_json(source_path)
    source["sources"]["v2"]["files"][0]["sha256"] = "0" * 64
    _write_canonical_json(source_path, source)
    _update_outer_source_inventory_hash(copied_report_bundle)

    with pytest.raises(report.EvidenceReportError, match="v2 inventory_sha256 mismatch"):
        report.validate_report_bundle(output_root=copied_report_bundle)


def test_forged_per_source_hash_and_inventory_id_reject(
    copied_report_bundle: Path,
) -> None:
    source_path = copied_report_bundle / "source_inventory.json"
    source = _read_json(source_path)
    source["sources"]["v1"]["inventory_sha256"] = "0" * 64
    _write_canonical_json(source_path, source)
    _update_outer_source_inventory_hash(copied_report_bundle)
    with pytest.raises(report.EvidenceReportError, match="v1 inventory_sha256 mismatch"):
        report.validate_report_bundle(output_root=copied_report_bundle)

    shutil.rmtree(copied_report_bundle)
    shutil.copytree(report.REPORT_ROOT, copied_report_bundle)
    source = _read_json(source_path)
    source["source_inventory_id"] = "forged"
    _write_canonical_json(source_path, source)
    _update_outer_source_inventory_hash(copied_report_bundle)
    with pytest.raises(report.EvidenceReportError, match="source inventory ID mismatch"):
        report.validate_report_bundle(output_root=copied_report_bundle)


def test_source_inventory_duplicate_and_unsorted_paths_reject(
    copied_report_bundle: Path,
) -> None:
    source_path = copied_report_bundle / "source_inventory.json"
    source = _read_json(source_path)
    files = source["sources"]["v2"]["files"]
    files[1]["relative_path"] = files[0]["relative_path"]
    _write_canonical_json(source_path, source)
    _update_outer_source_inventory_hash(copied_report_bundle)
    with pytest.raises(report.EvidenceReportError, match="file paths must be unique"):
        report.validate_report_bundle(output_root=copied_report_bundle)

    shutil.rmtree(copied_report_bundle)
    shutil.copytree(report.REPORT_ROOT, copied_report_bundle)
    source = _read_json(source_path)
    files = source["sources"]["v2"]["files"]
    files[0], files[1] = files[1], files[0]
    _write_canonical_json(source_path, source)
    _update_outer_source_inventory_hash(copied_report_bundle)
    with pytest.raises(report.EvidenceReportError, match="file paths must be strictly sorted"):
        report.validate_report_bundle(output_root=copied_report_bundle)


@pytest.mark.parametrize("unsafe_path", ("../escape", "/absolute", "a\\b", "a/./b"))
def test_source_inventory_unsafe_paths_reject(
    copied_report_bundle: Path,
    unsafe_path: str,
) -> None:
    source_path = copied_report_bundle / "source_inventory.json"
    source = _read_json(source_path)
    source["sources"]["v2"]["files"][0]["relative_path"] = unsafe_path
    _write_canonical_json(source_path, source)
    _update_outer_source_inventory_hash(copied_report_bundle)

    with pytest.raises(report.EvidenceReportError, match="relative_path"):
        report.validate_report_bundle(output_root=copied_report_bundle)


@pytest.mark.parametrize(
    ("source_key", "field", "value", "match"),
    (
        ("v1", "source_name", "v2", "source_name mismatch"),
        ("v1", "trial_name", report.TRIAL_NAME, "trial_name mismatch"),
    ),
)
def test_source_inventory_source_identity_mismatches_reject(
    copied_report_bundle: Path,
    source_key: str,
    field: str,
    value: str,
    match: str,
) -> None:
    source_path = copied_report_bundle / "source_inventory.json"
    source = _read_json(source_path)
    source["sources"][source_key][field] = value
    _write_canonical_json(source_path, source)
    _update_outer_source_inventory_hash(copied_report_bundle)

    with pytest.raises(report.EvidenceReportError, match=match):
        report.validate_report_bundle(output_root=copied_report_bundle)


@pytest.mark.parametrize("mutation", ("missing", "extra", "top_level_extra"))
def test_source_inventory_source_key_shape_rejects(
    copied_report_bundle: Path,
    mutation: str,
) -> None:
    source_path = copied_report_bundle / "source_inventory.json"
    source = _read_json(source_path)
    if mutation == "missing":
        source["sources"].pop("v2")
    elif mutation == "extra":
        source["sources"]["v3"] = source["sources"]["v2"]
    else:
        source["unexpected"] = True
    _write_canonical_json(source_path, source)
    _update_outer_source_inventory_hash(copied_report_bundle)

    with pytest.raises(report.EvidenceReportError, match="source inventory (sources|top-level fields)"):
        report.validate_report_bundle(output_root=copied_report_bundle)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("size_bytes", -1, "size_bytes"),
        ("size_bytes", True, "size_bytes"),
        ("size_bytes", "1", "size_bytes"),
        ("sha256", "A" * 64, "sha256"),
        ("sha256", "0" * 63, "sha256"),
        ("sha256", "g" * 64, "sha256"),
    ),
)
def test_source_inventory_invalid_file_fields_reject(
    copied_report_bundle: Path,
    field: str,
    value: object,
    match: str,
) -> None:
    source_path = copied_report_bundle / "source_inventory.json"
    source = _read_json(source_path)
    source["sources"]["v2"]["files"][0][field] = value
    _write_canonical_json(source_path, source)
    _update_outer_source_inventory_hash(copied_report_bundle)

    with pytest.raises(report.EvidenceReportError, match=match):
        report.validate_report_bundle(output_root=copied_report_bundle)


def test_payload_uses_canonical_trial_order_and_non_identical_overwrite_rejects(
    copied_sources: tuple[Path, Path],
    tmp_path: Path,
) -> None:
    input_evidence, scope, dataset = report.verify_input_evidence(v2_root=copied_sources[1])
    browser = report.verify_phase_i_evidence(v2_root=copied_sources[1], dataset=dataset)
    inventories = report.capture_source_inventories(v1_root=copied_sources[0], v2_root=copied_sources[1])
    first = report.build_evidence_payload(
        source_inventories=inventories,
        input_evidence=input_evidence,
        execution_scope=scope,
        dataset=dataset,
        browser=browser,
    )
    reordered = replace(browser, trials=tuple(reversed(browser.trials)))
    second = report.build_evidence_payload(
        source_inventories=inventories,
        input_evidence=input_evidence,
        execution_scope=scope,
        dataset=dataset,
        browser=reordered,
    )
    assert first == second
    report.write_report_bundle(output_root=tmp_path / "report", source_inventories=inventories, evidence_payload=first)
    with pytest.raises(report.EvidenceReportError, match="non-identical report overwrite"):
        report._atomic_write_if_identical(tmp_path / "report" / "evidence_report.json", b"tampered")
