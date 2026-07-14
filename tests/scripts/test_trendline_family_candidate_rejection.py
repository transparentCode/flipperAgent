from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from libs.models.trendline_family.optimization.contracts import canonical_json, semantic_id
from scripts import diagnose_trendline_family_candidate_rejection as diagnosis


@pytest.fixture()
def copied_sources(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    source_root = tmp_path / "sources"
    v1 = source_root / diagnosis.V1_TRIAL_NAME
    v2 = source_root / diagnosis.TRIAL_NAME
    report = tmp_path / "report"
    config = tmp_path / "trendline_family.yaml"
    shutil.copytree(diagnosis.V1_TRIAL_ROOT, v1)
    shutil.copytree(diagnosis.V2_TRIAL_ROOT, v2)
    shutil.copytree(diagnosis.REPORT_ROOT, report)
    shutil.copy2(diagnosis.CONFIG_PATH, config)
    return v1, v2, report, config


@pytest.fixture()
def copied_diagnosis_bundle(tmp_path: Path) -> Path:
    output_root = tmp_path / "diagnosis"
    shutil.copytree(diagnosis.OUTPUT_ROOT, output_root)
    return output_root


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.write_bytes(canonical_json(payload).encode("utf-8") + b"\n")


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _rebind_trial_inventory(binding: dict[str, object], source_key: str) -> None:
    inventories = binding["trial_inventories"]
    assert isinstance(inventories, dict)
    sources = inventories["sources"]
    assert isinstance(sources, dict)
    entry = sources[source_key]
    assert isinstance(entry, dict)
    semantic = {
        "source_name": entry["source_name"],
        "trial_name": entry["trial_name"],
        "files": entry["files"],
    }
    entry["inventory_sha256"] = sha256(canonical_json(semantic).encode("utf-8")).hexdigest()
    inventory_semantic = {
        "report_schema_version": inventories["report_schema_version"],
        "sources": inventories["sources"],
    }
    inventories["source_inventory_id"] = semantic_id("trendline-family-candidate-source-inventory", inventory_semantic)


def _rebind_report_inventory(binding: dict[str, object]) -> None:
    inventory = binding["approved_report_inventory"]
    assert isinstance(inventory, dict)
    semantic = {
        "source_name": inventory["source_name"],
        "root_name": inventory["root_name"],
        "files": inventory["files"],
    }
    inventory["inventory_sha256"] = sha256(canonical_json(semantic).encode("utf-8")).hexdigest()


def _rebind_source_binding_id(binding: dict[str, object]) -> None:
    semantic = {
        "diagnosis_schema_version": binding["diagnosis_schema_version"],
        "trial_inventories": binding["trial_inventories"],
        "approved_report_inventory": binding["approved_report_inventory"],
        "config_inventory": binding["config_inventory"],
    }
    binding["source_binding_id"] = semantic_id("trendline-family-candidate-rejection-source-binding", semantic)


def _write_rebound_source_binding(bundle: Path, binding: dict[str, object]) -> None:
    source_path = bundle / "source_binding.json"
    manifest_path = bundle / "diagnosis_manifest.json"
    _write_json(source_path, binding)
    manifest = _read_json(manifest_path)
    manifest["source_binding_id"] = binding["source_binding_id"]
    manifest["source_binding_sha256"] = _sha256(source_path)
    _write_json(manifest_path, manifest)


def _rewrite_diagnosis_json(bundle: Path, payload: dict[str, object]) -> None:
    diagnosis_path = bundle / "rejection_diagnosis.json"
    manifest_path = bundle / "diagnosis_manifest.json"
    _write_json(diagnosis_path, payload)
    manifest = _read_json(manifest_path)
    identity = payload["diagnosis_identity"]
    assert isinstance(identity, dict)
    manifest["diagnosis_id"] = identity["diagnosis_id"]
    manifest["rejection_diagnosis_json_sha256"] = _sha256(diagnosis_path)
    _write_json(manifest_path, manifest)


def _binding(bundle: Path) -> dict[str, object]:
    return _read_json(bundle / "source_binding.json")


def _v2_files(binding: dict[str, object]) -> list[dict[str, object]]:
    inventories = binding["trial_inventories"]
    assert isinstance(inventories, dict)
    sources = inventories["sources"]
    assert isinstance(sources, dict)
    entry = sources["v2"]
    assert isinstance(entry, dict)
    files = entry["files"]
    assert isinstance(files, list)
    return files


def _protected_inventory() -> dict[str, dict[str, str]]:
    roots = {
        "v1": diagnosis.V1_TRIAL_ROOT,
        "v2": diagnosis.V2_TRIAL_ROOT,
        "report": diagnosis.REPORT_ROOT,
        "diagnosis": diagnosis.OUTPUT_ROOT,
    }
    result = {
        name: {
            path.relative_to(root).as_posix(): _sha256(path)
            for path in sorted(root.rglob("*"))
            if path.is_file()
        }
        for name, root in roots.items()
    }
    result["config"] = {"configs/trendline_family.yaml": _sha256(diagnosis.CONFIG_PATH)}
    return result


def test_diagnosis_script_has_no_network_evaluation_holdout_or_tracker_boundary() -> None:
    source = Path(diagnosis.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "BinanceNativeAdapter",
        "get_historical_ohlcv",
        "run_phase_i_evaluation",
        "run_stage_grid",
        "run_validation_trial",
        "CandidateGeometryEvaluator",
        "evaluate_holdout_once",
    ):
        assert forbidden not in source


def test_sources_validate_configuration_matrix_is_fixed_and_reordered_trials_are_invariant(copied_sources) -> None:
    before, _, _, browser, _, configurations = diagnosis.load_diagnosis_sources(
        v1_root=copied_sources[0], v2_root=copied_sources[1], report_root=copied_sources[2], config_path=copied_sources[3]
    )
    baseline = diagnosis.TrendlineFamilyConfigResolver.from_path(copied_sources[3]).resolve(asset="BTCUSDT", timeframe="4h")
    reordered = replace(browser, trials=tuple(reversed(browser.trials)))
    assert diagnosis._configuration_matrix(baseline_config=baseline, browser=browser) == diagnosis._configuration_matrix(
        baseline_config=baseline,
        browser=reordered,
    )
    assert len(configurations) == 7
    assert before["source_binding_id"]


def test_quantiles_are_order_invariant() -> None:
    assert diagnosis._summary([0.1, 0.2, 0.3]) == diagnosis._summary([0.3, 0.1, 0.2])
    assert diagnosis._summary([0.1, 0.2, 0.3])["quantiles"]["0.5"] == 0.2


def test_source_report_tampering_and_nonidentical_output_reject(copied_sources, tmp_path: Path) -> None:
    report = copied_sources[2]
    report_path = report / "evidence_report.md"
    report_path.write_bytes(report_path.read_bytes() + b"tampered")
    with pytest.raises(diagnosis.RejectionDiagnosisError, match="approved source validation failed"):
        diagnosis.load_diagnosis_sources(
            v1_root=copied_sources[0],
            v2_root=copied_sources[1],
            report_root=report,
            config_path=copied_sources[3],
        )
    path = tmp_path / "bundle" / "rejection_diagnosis.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"different")
    with pytest.raises(diagnosis.RejectionDiagnosisError, match="non-identical diagnosis overwrite"):
        diagnosis._atomic_write_if_identical(path, b"expected")


def test_existing_diagnosis_bundle_validates_and_all_protected_bytes_stay_unchanged() -> None:
    before = _protected_inventory()
    bundle = diagnosis.validate_diagnosis_bundle(output_root=diagnosis.OUTPUT_ROOT)
    after = _protected_inventory()
    assert bundle["source_binding"]["source_binding_id"] == (
        "trendline-family-candidate-rejection-source-binding_06a563f43accc93acd9e3df59ff8d78174b861debe483446073b4c7b42e6500a"
    )
    assert before == after
    assert {name: len(files) for name, files in before.items() if name != "config"} == {
        "v1": 1,
        "v2": 30,
        "report": 4,
        "diagnosis": 4,
    }


def test_persisted_source_binding_canonically_matches_fresh_source_bytes() -> None:
    persisted = _binding(diagnosis.OUTPUT_ROOT)
    fresh = diagnosis.capture_source_binding(
        v1_root=diagnosis.V1_TRIAL_ROOT,
        v2_root=diagnosis.V2_TRIAL_ROOT,
        report_root=diagnosis.REPORT_ROOT,
        config_path=diagnosis.CONFIG_PATH,
    )
    assert canonical_json(persisted) == canonical_json(fresh)


def test_fully_rebound_nested_v2_sha_rejects_against_embedded_binding(copied_diagnosis_bundle: Path) -> None:
    binding = _binding(copied_diagnosis_bundle)
    _v2_files(binding)[0]["sha256"] = "0" * 64
    _rebind_trial_inventory(binding, "v2")
    _rebind_source_binding_id(binding)
    _write_rebound_source_binding(copied_diagnosis_bundle, binding)
    with pytest.raises(diagnosis.RejectionDiagnosisError, match="diagnosis identity source binding mismatch"):
        diagnosis.validate_diagnosis_bundle(output_root=copied_diagnosis_bundle)


def test_nested_v2_sha_with_only_outer_manifest_rebound_rejects_trial_inventory(copied_diagnosis_bundle: Path) -> None:
    binding = _binding(copied_diagnosis_bundle)
    _v2_files(binding)[0]["sha256"] = "0" * 64
    _write_rebound_source_binding(copied_diagnosis_bundle, binding)
    with pytest.raises(diagnosis.RejectionDiagnosisError, match="trial inventories are invalid.*inventory_sha256 mismatch"):
        diagnosis.validate_diagnosis_bundle(output_root=copied_diagnosis_bundle)


@pytest.mark.parametrize("fully_rebound", (False, True))
def test_forged_approved_report_inventory_rejects(copied_diagnosis_bundle: Path, fully_rebound: bool) -> None:
    binding = _binding(copied_diagnosis_bundle)
    report = binding["approved_report_inventory"]
    assert isinstance(report, dict)
    files = report["files"]
    assert isinstance(files, list)
    files[0]["sha256"] = "0" * 64
    if fully_rebound:
        _rebind_report_inventory(binding)
        _rebind_source_binding_id(binding)
    _write_rebound_source_binding(copied_diagnosis_bundle, binding)
    expected = "diagnosis identity source binding mismatch" if fully_rebound else "approved report inventory_sha256 mismatch"
    with pytest.raises(diagnosis.RejectionDiagnosisError, match=expected):
        diagnosis.validate_diagnosis_bundle(output_root=copied_diagnosis_bundle)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("sha256", "0" * 64, "config inventory sha256 differs"),
        ("relative_path", "configs/other.yaml", "config inventory relative_path differs"),
    ),
)
def test_forged_config_inventory_rejects_even_when_rebound(
    copied_diagnosis_bundle: Path,
    field: str,
    value: str,
    match: str,
) -> None:
    binding = _binding(copied_diagnosis_bundle)
    config = binding["config_inventory"]
    assert isinstance(config, dict)
    config[field] = value
    _rebind_source_binding_id(binding)
    _write_rebound_source_binding(copied_diagnosis_bundle, binding)
    with pytest.raises(diagnosis.RejectionDiagnosisError, match=match):
        diagnosis.validate_diagnosis_bundle(output_root=copied_diagnosis_bundle)


def test_forged_source_binding_id_rejects(copied_diagnosis_bundle: Path) -> None:
    binding = _binding(copied_diagnosis_bundle)
    binding["source_binding_id"] = "trendline-family-candidate-rejection-source-binding_" + "0" * 64
    _write_rebound_source_binding(copied_diagnosis_bundle, binding)
    with pytest.raises(diagnosis.RejectionDiagnosisError, match="source binding ID mismatch"):
        diagnosis.validate_diagnosis_bundle(output_root=copied_diagnosis_bundle)


def test_external_binding_must_equal_embedded_source_inventories(copied_diagnosis_bundle: Path) -> None:
    payload = _read_json(copied_diagnosis_bundle / "rejection_diagnosis.json")
    execution_identity = payload["source_and_execution_identity"]
    assert isinstance(execution_identity, dict)
    embedded = execution_identity["source_inventories"]
    assert isinstance(embedded, dict)
    embedded["config_inventory"]["size_bytes"] += 1
    identity = payload["diagnosis_identity"]
    assert isinstance(identity, dict)
    identity["diagnosis_id"] = diagnosis._diagnosis_id(payload)
    _rewrite_diagnosis_json(copied_diagnosis_bundle, payload)
    with pytest.raises(diagnosis.RejectionDiagnosisError, match="embedded source inventories"):
        diagnosis.validate_diagnosis_bundle(output_root=copied_diagnosis_bundle)


@pytest.mark.parametrize("location", ("diagnosis_identity", "source_and_execution_identity"))
def test_diagnosis_source_binding_claim_locations_must_match(copied_diagnosis_bundle: Path, location: str) -> None:
    payload = _read_json(copied_diagnosis_bundle / "rejection_diagnosis.json")
    claim = payload[location]
    assert isinstance(claim, dict)
    claim["source_binding_id"] = "forged"
    identity = payload["diagnosis_identity"]
    assert isinstance(identity, dict)
    identity["diagnosis_id"] = diagnosis._diagnosis_id(payload)
    _rewrite_diagnosis_json(copied_diagnosis_bundle, payload)
    with pytest.raises(diagnosis.RejectionDiagnosisError, match="source binding mismatch"):
        diagnosis.validate_diagnosis_bundle(output_root=copied_diagnosis_bundle)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (lambda binding: binding.pop("config_inventory"), "source binding top-level fields"),
        (lambda binding: binding.update({"unexpected": True}), "source binding top-level fields"),
        (lambda binding: binding["trial_inventories"].pop("sources"), "trial inventories are invalid"),
        (lambda binding: binding["approved_report_inventory"].update({"unexpected": True}), "approved report inventory fields"),
        (lambda binding: binding["config_inventory"].pop("sha256"), "config inventory fields"),
    ),
)
def test_missing_or_extra_binding_inventory_fields_reject(copied_diagnosis_bundle: Path, mutation, match: str) -> None:
    binding = _binding(copied_diagnosis_bundle)
    mutation(binding)
    _write_rebound_source_binding(copied_diagnosis_bundle, binding)
    with pytest.raises(diagnosis.RejectionDiagnosisError, match=match):
        diagnosis.validate_diagnosis_bundle(output_root=copied_diagnosis_bundle)


@pytest.mark.parametrize(
    "relative_path",
    ("../escape", "/absolute", "folder\\file", "./file", "folder/../file"),
)
def test_unsafe_trial_inventory_paths_reject(copied_diagnosis_bundle: Path, relative_path: str) -> None:
    binding = _binding(copied_diagnosis_bundle)
    _v2_files(binding)[0]["relative_path"] = relative_path
    _write_rebound_source_binding(copied_diagnosis_bundle, binding)
    with pytest.raises(diagnosis.RejectionDiagnosisError, match="trial inventories are invalid.*relative_path"):
        diagnosis.validate_diagnosis_bundle(output_root=copied_diagnosis_bundle)


@pytest.mark.parametrize("mode", ("duplicate", "unsorted"))
def test_duplicate_and_unsorted_trial_inventory_paths_reject(copied_diagnosis_bundle: Path, mode: str) -> None:
    binding = _binding(copied_diagnosis_bundle)
    files = _v2_files(binding)
    if mode == "duplicate":
        files[1]["relative_path"] = files[0]["relative_path"]
        match = "paths must be unique"
    else:
        files.reverse()
        match = "paths must be strictly sorted"
    _write_rebound_source_binding(copied_diagnosis_bundle, binding)
    with pytest.raises(diagnosis.RejectionDiagnosisError, match=f"trial inventories are invalid.*{match}"):
        diagnosis.validate_diagnosis_bundle(output_root=copied_diagnosis_bundle)


@pytest.mark.parametrize("size_bytes", (-1, True, "1"))
def test_invalid_trial_inventory_sizes_reject(copied_diagnosis_bundle: Path, size_bytes: object) -> None:
    binding = _binding(copied_diagnosis_bundle)
    _v2_files(binding)[0]["size_bytes"] = size_bytes
    _write_rebound_source_binding(copied_diagnosis_bundle, binding)
    with pytest.raises(diagnosis.RejectionDiagnosisError, match="trial inventories are invalid.*size_bytes is invalid"):
        diagnosis.validate_diagnosis_bundle(output_root=copied_diagnosis_bundle)


@pytest.mark.parametrize("file_hash", ("A" * 64, "0" * 63, "z" * 64, 0))
def test_invalid_trial_inventory_hashes_reject(copied_diagnosis_bundle: Path, file_hash: object) -> None:
    binding = _binding(copied_diagnosis_bundle)
    _v2_files(binding)[0]["sha256"] = file_hash
    _write_rebound_source_binding(copied_diagnosis_bundle, binding)
    with pytest.raises(diagnosis.RejectionDiagnosisError, match="trial inventories are invalid.*SHA-256"):
        diagnosis.validate_diagnosis_bundle(output_root=copied_diagnosis_bundle)


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("source_name", "wrong", "source_name mismatch"),
        ("root_name", "wrong", "root_name mismatch"),
    ),
)
def test_report_inventory_identity_fields_reject(copied_diagnosis_bundle: Path, field: str, value: str, match: str) -> None:
    binding = _binding(copied_diagnosis_bundle)
    report = binding["approved_report_inventory"]
    assert isinstance(report, dict)
    report[field] = value
    _write_rebound_source_binding(copied_diagnosis_bundle, binding)
    with pytest.raises(diagnosis.RejectionDiagnosisError, match=match):
        diagnosis.validate_diagnosis_bundle(output_root=copied_diagnosis_bundle)


@pytest.mark.parametrize("mode", ("missing", "order"))
def test_report_inventory_file_membership_and_order_reject(copied_diagnosis_bundle: Path, mode: str) -> None:
    binding = _binding(copied_diagnosis_bundle)
    report = binding["approved_report_inventory"]
    assert isinstance(report, dict)
    files = report["files"]
    assert isinstance(files, list)
    if mode == "missing":
        files.pop()
    else:
        files.reverse()
    _write_rebound_source_binding(copied_diagnosis_bundle, binding)
    with pytest.raises(diagnosis.RejectionDiagnosisError, match="approved report inventory files"):
        diagnosis.validate_diagnosis_bundle(output_root=copied_diagnosis_bundle)
