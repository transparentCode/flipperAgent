from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from libs.models.trendline_family.optimization.contracts import canonical_json, semantic_id
from scripts import analyze_trendline_family_candidate_density as study
from scripts.diagnose_trendline_family_candidate_rejection import validate_diagnosis_bundle


@pytest.fixture(scope="module")
def study_bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_root = tmp_path_factory.mktemp("candidate_density") / "study"
    study.build_candidate_density_study(output_root=output_root)
    return output_root


@pytest.fixture()
def copied_study_bundle(study_bundle: Path, tmp_path: Path) -> Path:
    copied = tmp_path / "study"
    shutil.copytree(study_bundle, copied)
    return copied


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json(value).encode("utf-8") + b"\n")


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _binding(bundle: Path) -> dict[str, object]:
    return _read_json(bundle / "source_binding.json")


def _rebind_study_source_binding(binding: dict[str, object]) -> None:
    inventory = binding["diagnosis_inventory"]
    assert isinstance(inventory, dict)
    inventory_semantic = {
        "source_name": inventory["source_name"],
        "root_name": inventory["root_name"],
        "files": inventory["files"],
    }
    inventory["inventory_sha256"] = sha256(canonical_json(inventory_semantic).encode("utf-8")).hexdigest()
    semantic = {
        "study_schema_version": binding["study_schema_version"],
        "diagnosis_id": binding["diagnosis_id"],
        "diagnosis_source_binding_id": binding["diagnosis_source_binding_id"],
        "diagnosis_inventory": inventory,
    }
    binding["study_source_binding_id"] = semantic_id("trendline-family-candidate-density-study-source-binding", semantic)


def _write_rebound_source_binding(bundle: Path, binding: dict[str, object]) -> None:
    source_path = bundle / "source_binding.json"
    manifest_path = bundle / "study_manifest.json"
    _write_json(source_path, binding)
    manifest = _read_json(manifest_path)
    manifest["study_source_binding_id"] = binding["study_source_binding_id"]
    manifest["source_binding_sha256"] = _sha256(source_path)
    _write_json(manifest_path, manifest)


def _rewrite_study_json(bundle: Path, payload: dict[str, object]) -> None:
    study_path = bundle / "candidate_density_study.json"
    manifest_path = bundle / "study_manifest.json"
    _write_json(study_path, payload)
    manifest = _read_json(manifest_path)
    identity = payload["study_identity"]
    assert isinstance(identity, dict)
    manifest["study_id"] = identity["study_id"]
    manifest["candidate_density_study_json_sha256"] = _sha256(study_path)
    _write_json(manifest_path, manifest)


def test_density_script_has_no_forbidden_execution_boundaries() -> None:
    source = Path(study.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "BinanceNativeAdapter",
        "get_historical_ohlcv",
        "NativeDeterministicLineProvider",
        "provider.generate",
        "run_phase_i_evaluation",
        "run_stage_grid",
        "run_validation_trial",
        "CandidateGeometryEvaluator",
        "evaluate_holdout_once",
        "TrendlineFamilyTracker",
        "advance_interaction_events",
        "RegimeV2",
    ):
        assert forbidden not in source


def test_approved_diagnosis_validates_before_density_analysis() -> None:
    bundle = validate_diagnosis_bundle(output_root=study.DIAGNOSIS_ROOT)
    assert bundle["rejection_diagnosis"]["diagnosis_identity"]["diagnosis_id"] == study.EXPECTED_DIAGNOSIS_ID


def test_fixed_source_identity_rejects_drift() -> None:
    diagnosis = deepcopy(validate_diagnosis_bundle(output_root=study.DIAGNOSIS_ROOT)["rejection_diagnosis"])
    identity = diagnosis["diagnosis_identity"]
    assert isinstance(identity, dict)
    identity["dataset_hash"] = "drift"
    with pytest.raises(study.CandidateDensityStudyError, match="fixed identity drift"):
        study._fixed_identity(diagnosis)


def test_canonical_exposure_balance_and_existing_threshold_reconciliation(study_bundle: Path) -> None:
    payload = study.validate_density_study_bundle(output_root=study_bundle)["candidate_density_study"]
    for lookback in study.LOOKBACKS:
        exposure = payload["canonical_exposure"][str(lookback)]
        assert exposure == {
            "validation_bar_count": 288,
            "exposed_candidate_count": 576,
            "support_candidate_count": 288,
            "resistance_candidate_count": 288,
            "quality_method": "anchor_span_coverage_v1",
            "source_threshold_bps": 4000,
            "source_threshold": "0.40",
        }
    actual = {
        (row["lookback_bars"], row["threshold_bps"]): row["accepted_candidate_count"]
        for row in payload["existing_threshold_reconciliation"]
    }
    assert actual == study.EXPECTED_ACCEPTED_COUNTS
    assert all(row["reconciled"] for row in payload["existing_threshold_reconciliation"])


def test_threshold_grid_is_exact_deterministic_and_monotonic(study_bundle: Path) -> None:
    payload = study.validate_density_study_bundle(output_root=study_bundle)["candidate_density_study"]
    for lookback in study.LOOKBACKS:
        entries = payload["threshold_support_curves"][str(lookback)]
        assert [entry["threshold_bps"] for entry in entries] == list(range(0, 4001, 100))
        assert [entry["threshold"] for entry in entries] == [study._threshold_text(bps) for bps in study.THRESHOLD_BPS]
        accepted = [entry["aggregate"]["accepted_candidate_count"] for entry in entries]
        producing = [entry["aggregate"]["producing_bar_count"] for entry in entries]
        assert accepted == sorted(accepted, reverse=True)
        assert producing == sorted(producing, reverse=True)
        assert study._threshold_decimal(3000) == study.Decimal("0.30")


def test_support_frontier_is_descriptive_only(study_bundle: Path) -> None:
    payload = study.validate_density_study_bundle(output_root=study_bundle)["candidate_density_study"]
    frontier = payload["minimum_sample_support_frontier"]
    assert all(item["descriptive_only"] is True for item in frontier.values())
    assert "recommend" not in canonical_json(frontier).lower()
    for values in frontier.values():
        assert set(values["current_threshold_deficits"]) == {"3000", "3500", "4000"}


def test_validation_universe_and_holdout_boundary_are_sealed(study_bundle: Path) -> None:
    payload = study.validate_density_study_bundle(output_root=study_bundle)["candidate_density_study"]
    identity = payload["source_and_bias_identity"]
    assert identity["holdout_accessed"] is False
    assert identity["planned_holdout_start_position"] == 636
    assert [(item["fold_index"], item["start_position"], item["end_position"]) for item in identity["validation_windows"]] == list(
        study.EXPECTED_VALIDATION_WINDOWS
    )


def test_quality_coverage_distributions_and_anchor_persistence_are_deterministic(study_bundle: Path) -> None:
    first = study.validate_density_study_bundle(output_root=study_bundle)["candidate_density_study"]
    second = study.build_density_study_payload(
        diagnosis_bundle=validate_diagnosis_bundle(output_root=study.DIAGNOSIS_ROOT),
        source_binding=study.capture_study_source_binding(diagnosis_root=study.DIAGNOSIS_ROOT),
    )
    assert first["quality_and_structure_distributions"] == second["quality_and_structure_distributions"]
    assert first["anchor_pair_persistence"] == second["anchor_pair_persistence"]
    for distributions in first["quality_and_structure_distributions"].values():
        for item in distributions:
            assert item["normalized_quality"] == item["coverage"]
            assert set(item["normalized_quality"]["quantiles"]) == {"0.1", "0.25", "0.5", "0.75", "0.9"}
    for persistence in first["anchor_pair_persistence"].values():
        for item in persistence:
            assert len(item["top_repeated_keys"]) <= 20
            assert item["maximum_consecutive_run_length"] >= item["median_consecutive_run_length"]


def test_rerender_is_idempotent_and_nonidentical_overwrite_rejects(study_bundle: Path, tmp_path: Path) -> None:
    before = {path.name: path.read_bytes() for path in study_bundle.iterdir()}
    study.build_candidate_density_study(output_root=study_bundle)
    assert {path.name: path.read_bytes() for path in study_bundle.iterdir()} == before
    copied = tmp_path / "study"
    shutil.copytree(study_bundle, copied)
    binding = _binding(copied)
    payload = _read_json(copied / "candidate_density_study.json")
    (copied / "candidate_density_study.md").write_bytes(b"different")
    with pytest.raises(study.CandidateDensityStudyError, match="non-identical study overwrite"):
        study.write_density_study_bundle(output_root=copied, source_binding=binding, payload=payload)


def test_protected_source_bytes_remain_unchanged_after_read_only_study(tmp_path: Path) -> None:
    before = study.capture_protected_source_inventories()
    study.build_candidate_density_study(output_root=tmp_path / "study")
    assert study.capture_protected_source_inventories() == before


def test_existing_study_bundle_validates_unchanged(study_bundle: Path) -> None:
    bundle = study.validate_density_study_bundle(output_root=study_bundle)
    assert bundle["study_manifest"]["study_id"] == bundle["candidate_density_study"]["study_identity"]["study_id"]


def test_fully_rebound_diagnosis_inventory_rejects(copied_study_bundle: Path) -> None:
    binding = _binding(copied_study_bundle)
    inventory = binding["diagnosis_inventory"]
    assert isinstance(inventory, dict)
    files = inventory["files"]
    assert isinstance(files, list)
    files[0]["sha256"] = "0" * 64
    _rebind_study_source_binding(binding)
    _write_rebound_source_binding(copied_study_bundle, binding)
    with pytest.raises(study.CandidateDensityStudyError, match="differs from approved diagnosis source bytes"):
        study.validate_density_study_bundle(output_root=copied_study_bundle)


def test_stale_diagnosis_inventory_hash_rejects_before_manifest_rebinding(copied_study_bundle: Path) -> None:
    binding = _binding(copied_study_bundle)
    inventory = binding["diagnosis_inventory"]
    assert isinstance(inventory, dict)
    files = inventory["files"]
    assert isinstance(files, list)
    files[0]["sha256"] = "0" * 64
    _write_rebound_source_binding(copied_study_bundle, binding)
    with pytest.raises(study.CandidateDensityStudyError, match="inventory_sha256 mismatch"):
        study.validate_density_study_bundle(output_root=copied_study_bundle)


def test_forged_study_source_binding_id_rejects(copied_study_bundle: Path) -> None:
    binding = _binding(copied_study_bundle)
    binding["study_source_binding_id"] = "trendline-family-candidate-density-study-source-binding_" + "0" * 64
    _write_rebound_source_binding(copied_study_bundle, binding)
    with pytest.raises(study.CandidateDensityStudyError, match="study source binding ID mismatch"):
        study.validate_density_study_bundle(output_root=copied_study_bundle)


def test_external_and_embedded_source_bindings_must_match(copied_study_bundle: Path) -> None:
    payload = _read_json(copied_study_bundle / "candidate_density_study.json")
    source_identity = payload["source_and_bias_identity"]
    assert isinstance(source_identity, dict)
    embedded = source_identity["source_binding"]
    assert isinstance(embedded, dict)
    inventory = embedded["diagnosis_inventory"]
    assert isinstance(inventory, dict)
    inventory["size_bytes"] = inventory.get("size_bytes", 0) + 1
    identity = payload["study_identity"]
    assert isinstance(identity, dict)
    identity["study_id"] = study._study_id(payload)
    _rewrite_study_json(copied_study_bundle, payload)
    with pytest.raises(study.CandidateDensityStudyError, match="embedded source binding"):
        study.validate_density_study_bundle(output_root=copied_study_bundle)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (lambda binding: binding.pop("diagnosis_inventory"), "top-level fields"),
        (lambda binding: binding.update({"unexpected": True}), "top-level fields"),
        (lambda binding: binding["diagnosis_inventory"].pop("files"), "inventory fields"),
        (lambda binding: binding["diagnosis_inventory"].update({"unexpected": True}), "inventory fields"),
    ),
)
def test_missing_or_extra_source_binding_fields_reject(copied_study_bundle: Path, mutation, match: str) -> None:
    binding = _binding(copied_study_bundle)
    mutation(binding)
    _write_rebound_source_binding(copied_study_bundle, binding)
    with pytest.raises(study.CandidateDensityStudyError, match=match):
        study.validate_density_study_bundle(output_root=copied_study_bundle)


@pytest.mark.parametrize("relative_path", ("../escape", "/absolute", "folder\\file", "./file", "folder/../file"))
def test_unsafe_source_binding_paths_reject(copied_study_bundle: Path, relative_path: str) -> None:
    binding = _binding(copied_study_bundle)
    inventory = binding["diagnosis_inventory"]
    assert isinstance(inventory, dict)
    files = inventory["files"]
    assert isinstance(files, list)
    files[0]["relative_path"] = relative_path
    _write_rebound_source_binding(copied_study_bundle, binding)
    with pytest.raises(study.CandidateDensityStudyError, match="safe canonical POSIX relative path"):
        study.validate_density_study_bundle(output_root=copied_study_bundle)


@pytest.mark.parametrize("mode", ("duplicate", "unsorted"))
def test_duplicate_and_unsorted_source_binding_paths_reject(copied_study_bundle: Path, mode: str) -> None:
    binding = _binding(copied_study_bundle)
    inventory = binding["diagnosis_inventory"]
    assert isinstance(inventory, dict)
    files = inventory["files"]
    assert isinstance(files, list)
    if mode == "duplicate":
        files[1]["relative_path"] = files[0]["relative_path"]
        match = "paths must be unique"
    else:
        files.reverse()
        match = "paths must be strictly sorted"
    _write_rebound_source_binding(copied_study_bundle, binding)
    with pytest.raises(study.CandidateDensityStudyError, match=match):
        study.validate_density_study_bundle(output_root=copied_study_bundle)


@pytest.mark.parametrize("size_bytes", (-1, True, "1"))
def test_invalid_source_binding_sizes_reject(copied_study_bundle: Path, size_bytes: object) -> None:
    binding = _binding(copied_study_bundle)
    inventory = binding["diagnosis_inventory"]
    assert isinstance(inventory, dict)
    files = inventory["files"]
    assert isinstance(files, list)
    files[0]["size_bytes"] = size_bytes
    _write_rebound_source_binding(copied_study_bundle, binding)
    with pytest.raises(study.CandidateDensityStudyError, match="size_bytes is invalid"):
        study.validate_density_study_bundle(output_root=copied_study_bundle)


@pytest.mark.parametrize("file_hash", ("A" * 64, "0" * 63, "z" * 64, 0))
def test_invalid_source_binding_hashes_reject(copied_study_bundle: Path, file_hash: object) -> None:
    binding = _binding(copied_study_bundle)
    inventory = binding["diagnosis_inventory"]
    assert isinstance(inventory, dict)
    files = inventory["files"]
    assert isinstance(files, list)
    files[0]["sha256"] = file_hash
    _write_rebound_source_binding(copied_study_bundle, binding)
    with pytest.raises(study.CandidateDensityStudyError, match="lowercase 64-character SHA-256"):
        study.validate_density_study_bundle(output_root=copied_study_bundle)
