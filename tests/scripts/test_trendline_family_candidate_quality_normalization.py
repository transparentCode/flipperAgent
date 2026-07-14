from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from libs.models.trendline_family.optimization.contracts import canonical_json, semantic_id
from scripts import analyze_trendline_family_candidate_quality_normalization as study
from scripts.analyze_trendline_family_candidate_density import validate_density_study_bundle
from scripts.diagnose_trendline_family_candidate_rejection import validate_diagnosis_bundle


@pytest.fixture(scope="module")
def study_bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_root = tmp_path_factory.mktemp("candidate_quality_normalization") / "study"
    study.build_candidate_quality_normalization_study(output_root=output_root)
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


def _rebind_inventory(entry: dict[str, object]) -> None:
    inventory = entry["inventory"]
    assert isinstance(inventory, dict)
    semantic = {
        "source_name": inventory["source_name"],
        "root_name": inventory["root_name"],
        "files": inventory["files"],
    }
    inventory["inventory_sha256"] = sha256(canonical_json(semantic).encode("utf-8")).hexdigest()


def _rebind_quality_source_binding(binding: dict[str, object]) -> None:
    diagnosis = binding["diagnosis_bundle"]
    density = binding["density_bundle"]
    assert isinstance(diagnosis, dict)
    assert isinstance(density, dict)
    _rebind_inventory(diagnosis)
    _rebind_inventory(density)
    semantic = {
        "quality_study_schema_version": binding["quality_study_schema_version"],
        "diagnosis_bundle": diagnosis,
        "density_bundle": density,
    }
    binding["quality_source_binding_id"] = semantic_id(
        "trendline-family-candidate-quality-normalization-source-binding",
        semantic,
    )


def _write_rebound_source_binding(bundle: Path, binding: dict[str, object]) -> None:
    source_path = bundle / "source_binding.json"
    manifest_path = bundle / "study_manifest.json"
    _write_json(source_path, binding)
    manifest = _read_json(manifest_path)
    manifest["quality_source_binding_id"] = binding.get("quality_source_binding_id")
    manifest["source_binding_sha256"] = _sha256(source_path)
    _write_json(manifest_path, manifest)


def _rewrite_study_json(bundle: Path, payload: dict[str, object]) -> None:
    study_path = bundle / "quality_normalization_study.json"
    manifest_path = bundle / "study_manifest.json"
    _write_json(study_path, payload)
    manifest = _read_json(manifest_path)
    identity = payload["study_identity"]
    assert isinstance(identity, dict)
    manifest["study_id"] = identity["study_id"]
    manifest["quality_normalization_study_json_sha256"] = _sha256(study_path)
    _write_json(manifest_path, manifest)


def _source_entry(binding: dict[str, object], label: str) -> dict[str, object]:
    entry = binding[f"{label}_bundle"]
    assert isinstance(entry, dict)
    return entry


def test_quality_script_has_no_forbidden_execution_boundaries() -> None:
    source = Path(study.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "BinanceNativeAdapter",
        "get_historical_ohlcv",
        "NativeDeterministicLineProvider",
        "provider.generate",
        "PathfindingLineFitter",
        "CausalFractalPivotProvider",
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


def test_approved_bundles_validate_before_quality_analysis() -> None:
    diagnosis = validate_diagnosis_bundle(output_root=study.DIAGNOSIS_ROOT)
    density = validate_density_study_bundle(output_root=study.DENSITY_ROOT, diagnosis_root=study.DIAGNOSIS_ROOT)
    study._require_identity_sources(diagnosis, density)


@pytest.mark.parametrize(
    ("bundle_name", "field_name"),
    (("diagnosis_identity", "dataset_hash"), ("diagnosis_identity", "phase_i_run_id"), ("study_identity", "study_id")),
)
def test_fixed_source_identity_rejects_drift(bundle_name: str, field_name: str) -> None:
    diagnosis = deepcopy(validate_diagnosis_bundle(output_root=study.DIAGNOSIS_ROOT))
    density = deepcopy(validate_density_study_bundle(output_root=study.DENSITY_ROOT, diagnosis_root=study.DIAGNOSIS_ROOT))
    if bundle_name == "study_identity":
        target = density["candidate_density_study"][bundle_name]
    else:
        target = diagnosis["rejection_diagnosis"][bundle_name]
    assert isinstance(target, dict)
    target[field_name] = "drift"
    with pytest.raises(study.QualityNormalizationStudyError, match="fixed identity drift"):
        study._require_identity_sources(diagnosis, density)


def test_exact_matched_triplet_population_and_raw_span_evidence() -> None:
    diagnosis = validate_diagnosis_bundle(output_root=study.DIAGNOSIS_ROOT)
    triplets = study.reconstruct_matched_triplets(diagnosis_bundle=diagnosis)
    assert len(triplets) == 576
    assert sum(item["role"] == "SUPPORT" for item in triplets) == 288
    assert sum(item["role"] == "RESISTANCE" for item in triplets) == 288
    assert all(item["anchor_span_bars"] > 0 for item in triplets)
    assert all(item["position"] < study.PLANNED_HOLDOUT_START for item in triplets)
    assert {item["candidate_id"] for item in triplets}
    assert all(len(item["anchor_ids"]) == 2 and len(item["anchor_timestamps"]) == 2 for item in triplets)
    assert all(set(item["path_lengths_by_lookback"]) == {"120", "180", "240"} for item in triplets)


def test_path_length_remains_audit_only() -> None:
    triplets = study.reconstruct_matched_triplets(diagnosis_bundle=validate_diagnosis_bundle(output_root=study.DIAGNOSIS_ROOT))
    catalog = study.formula_catalog()
    before = study._formula_scores(catalog[1], triplets)
    changed = [dict(item) for item in triplets]
    changed[0]["path_lengths_by_lookback"] = {"120": 2, "180": 999, "240": 3}
    changed[0]["path_length_deltas"] = {"180_minus_120": 997, "240_minus_120": 1, "240_minus_180": -996}
    assert study._formula_scores(catalog[1], changed) == before
    assert all(item["uses_path_length"] is False for item in catalog)


def test_current_formula_reconstructs_all_persisted_scores_and_exact_ratios() -> None:
    triplets = study.reconstruct_matched_triplets(diagnosis_bundle=validate_diagnosis_bundle(output_root=study.DIAGNOSIS_ROOT))
    errors = [
        Decimal(error)
        for triplet in triplets
        for error in triplet["current_formula_absolute_errors"].values()
    ]
    assert len(errors) == 1728
    assert max(errors) <= Decimal("1e-12")
    audit = study.build_current_method_audit(triplets=triplets)
    ratios = audit["cross_lookback_score_ratios"]
    with localcontext() as context:
        context.prec = 50
        expected_ratios = [
            study._decimal_text(Decimal(179) / Decimal(119)),
            study._decimal_text(Decimal(239) / Decimal(119)),
            study._decimal_text(Decimal(239) / Decimal(179)),
        ]
    assert [item["expected_score_ratio"] for item in ratios] == expected_ratios
    assert all(item["rank_order_equal"] is True for item in ratios)
    assert all(item["absolute_score_scaling_only"] is True for item in audit["threshold_support_differences_inherited_from_score_scaling"])


def test_formula_catalog_is_exact_and_fixed_horizon_scores_are_invariant() -> None:
    catalog = study.formula_catalog()
    assert [item["formula_id"] for item in catalog] == [
        "lookback_relative_anchor_span_coverage_v1",
        "fixed_horizon_linear_v1_h12",
        "fixed_horizon_linear_v1_h24",
        "fixed_horizon_linear_v1_h48",
        "fixed_horizon_linear_v1_h96",
        "fixed_horizon_saturating_v1_h12",
        "fixed_horizon_saturating_v1_h24",
        "fixed_horizon_saturating_v1_h48",
        "fixed_horizon_saturating_v1_h96",
    ]
    assert {item["horizon_bars"] for item in catalog[1:]} == {12, 24, 48, 96}
    triplets = study.reconstruct_matched_triplets(diagnosis_bundle=validate_diagnosis_bundle(output_root=study.DIAGNOSIS_ROOT))
    invariance = study.build_invariance_audit(catalog=catalog, triplets=triplets)
    assert invariance[0]["exact_lookback_invariance"] is False
    assert all(item["exact_lookback_invariance"] is True for item in invariance[1:])
    assert all(item["unequal_score_triplet_count"] == 0 for item in invariance[1:])
    assert all(item["rank_order_equality"]["120_vs_240"] is True for item in invariance)


def test_formula_scores_are_bounded_monotonic_and_decimal_exact() -> None:
    for horizon in study.HORIZONS:
        linear = [study.fixed_linear_score(anchor_span_bars=span, horizon_bars=horizon) for span in range(1, 512)]
        saturating = [study.fixed_saturating_score(anchor_span_bars=span, horizon_bars=horizon) for span in range(1, 512)]
        assert all(Decimal(0) <= score <= Decimal(1) for score in linear + saturating)
        assert linear == sorted(linear)
        assert saturating == sorted(saturating)
        assert study.fixed_linear_score(anchor_span_bars=horizon, horizon_bars=horizon) == Decimal(1)
        assert study.fixed_saturating_score(anchor_span_bars=horizon, horizon_bars=horizon) == Decimal(1) / Decimal(2)


def test_distribution_tie_saturation_and_support_evidence_is_deterministic(study_bundle: Path) -> None:
    payload = study.validate_quality_study_bundle(output_root=study_bundle)["quality_normalization_study"]
    distributions = payload["score_distributions"]
    support = payload["descriptive_support_curves"]
    for formula_id, lookbacks in distributions.items():
        assert set(lookbacks) == {"120", "180", "240"}
        for rows in lookbacks.values():
            assert {row["scope"] for row in rows} == {"aggregate", "fold_0", "fold_1", "fold_2", "role_SUPPORT", "role_RESISTANCE"}
            for row in rows:
                summary = row["score_distribution"]
                assert set(summary["quantiles"]) == {"0.10", "0.25", "0.50", "0.75", "0.90"}
                assert Decimal("0") <= Decimal(summary["one_score_saturation_fraction"]) <= Decimal("1")
        for lookback, curve in support[formula_id].items():
            rows = curve["curve"]
            assert [row["threshold_bps"] for row in rows] == list(range(0, 10_001, 100))
            accepted = [row["aggregate"]["accepted_candidate_count"] for row in rows]
            produced = [row["aggregate"]["producing_bar_count"] for row in rows]
            assert accepted == sorted(accepted, reverse=True)
            assert produced == sorted(produced, reverse=True)
            assert all(len(row["folds"]) == 3 and len(row["roles"]) == 2 and len(row["fold_roles"]) == 6 for row in rows)
            assert lookback in {"120", "180", "240"}


def test_eligibility_is_architecture_only_without_selection_semantics(study_bundle: Path) -> None:
    payload = study.validate_quality_study_bundle(output_root=study_bundle)["quality_normalization_study"]
    eligibility = payload["structural_eligibility"]
    assert eligibility[0]["eligible_for_fresh_unseen_research"] is False
    assert all(item["eligible_for_fresh_unseen_research"] is True for item in eligibility[1:])
    assert eligibility[0]["failed_architecture_gates"] == ["exact_lookback_invariance_for_matched_geometry"]
    assert all(item["classification_scope"] == "architecture_only_not_selection_or_promotion" for item in eligibility)
    assert payload["source_and_bias_identity"]["holdout_accessed"] is False
    assert payload["source_and_bias_identity"]["provider_calls"] == 0
    assert payload["source_and_bias_identity"]["evaluator_calls"] == 0


def test_rerender_is_idempotent_and_nonidentical_overwrite_rejects(study_bundle: Path, tmp_path: Path) -> None:
    before = {path.name: path.read_bytes() for path in study_bundle.iterdir()}
    study.build_candidate_quality_normalization_study(output_root=study_bundle)
    assert {path.name: path.read_bytes() for path in study_bundle.iterdir()} == before
    copied = tmp_path / "study"
    shutil.copytree(study_bundle, copied)
    binding = _binding(copied)
    payload = _read_json(copied / "quality_normalization_study.json")
    (copied / "quality_normalization_study.md").write_bytes(b"different")
    with pytest.raises(study.QualityNormalizationStudyError, match="non-identical quality-study overwrite"):
        study.write_quality_study_bundle(output_root=copied, source_binding=binding, payload=payload)


def test_protected_source_bytes_remain_unchanged_after_read_only_study(tmp_path: Path) -> None:
    before = study.capture_protected_source_inventories()
    study.build_candidate_quality_normalization_study(output_root=tmp_path / "study")
    assert study.capture_protected_source_inventories() == before


def test_quality_bundle_validates_unchanged(study_bundle: Path) -> None:
    bundle = study.validate_quality_study_bundle(output_root=study_bundle)
    assert bundle["study_manifest"]["study_id"] == bundle["quality_normalization_study"]["study_identity"]["study_id"]


@pytest.mark.parametrize("label", ("diagnosis", "density"))
def test_fully_rebound_source_inventory_rejects_against_live_sources(copied_study_bundle: Path, label: str) -> None:
    binding = _binding(copied_study_bundle)
    entry = _source_entry(binding, label)
    inventory = entry["inventory"]
    assert isinstance(inventory, dict)
    files = inventory["files"]
    assert isinstance(files, list)
    files[0]["sha256"] = "0" * 64
    _rebind_quality_source_binding(binding)
    _write_rebound_source_binding(copied_study_bundle, binding)
    with pytest.raises(study.QualityNormalizationStudyError, match="differs from approved live source bytes"):
        study.validate_quality_study_bundle(output_root=copied_study_bundle)


def test_forged_quality_source_binding_id_rejects(copied_study_bundle: Path) -> None:
    binding = _binding(copied_study_bundle)
    binding["quality_source_binding_id"] = "trendline-family-candidate-quality-normalization-source-binding_" + "0" * 64
    _write_rebound_source_binding(copied_study_bundle, binding)
    with pytest.raises(study.QualityNormalizationStudyError, match="quality source binding ID mismatch"):
        study.validate_quality_study_bundle(output_root=copied_study_bundle)


def test_external_and_embedded_source_binding_mismatch_rejects(copied_study_bundle: Path) -> None:
    payload = _read_json(copied_study_bundle / "quality_normalization_study.json")
    source_identity = payload["source_and_bias_identity"]
    assert isinstance(source_identity, dict)
    embedded = source_identity["source_binding"]
    assert isinstance(embedded, dict)
    diagnosis = _source_entry(embedded, "diagnosis")
    inventory = diagnosis["inventory"]
    assert isinstance(inventory, dict)
    files = inventory["files"]
    assert isinstance(files, list)
    files[0]["size_bytes"] += 1
    identity = payload["study_identity"]
    assert isinstance(identity, dict)
    identity["study_id"] = study._quality_study_id(payload)
    _rewrite_study_json(copied_study_bundle, payload)
    with pytest.raises(study.QualityNormalizationStudyError, match="embedded source binding"):
        study.validate_quality_study_bundle(output_root=copied_study_bundle)


def test_rebound_study_claim_rejects_against_independently_rederived_analysis(copied_study_bundle: Path) -> None:
    payload = _read_json(copied_study_bundle / "quality_normalization_study.json")
    observations = payload["observations"]
    assert isinstance(observations, list)
    observations[0] = "forged"
    identity = payload["study_identity"]
    assert isinstance(identity, dict)
    identity["study_id"] = study._quality_study_id(payload)
    _rewrite_study_json(copied_study_bundle, payload)
    with pytest.raises(study.QualityNormalizationStudyError, match="independently rederived source analysis"):
        study.validate_quality_study_bundle(output_root=copied_study_bundle)


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (lambda binding: binding.pop("diagnosis_bundle"), "top-level fields"),
        (lambda binding: binding.update({"unexpected": True}), "top-level fields"),
        (lambda binding: _source_entry(binding, "diagnosis").pop("inventory"), "fields are invalid"),
        (lambda binding: _source_entry(binding, "density").update({"unexpected": True}), "fields are invalid"),
    ),
)
def test_missing_or_extra_source_binding_fields_reject(copied_study_bundle: Path, mutation, match: str) -> None:
    binding = _binding(copied_study_bundle)
    mutation(binding)
    _write_json(copied_study_bundle / "source_binding.json", binding)
    with pytest.raises(study.QualityNormalizationStudyError, match=match):
        study.validate_quality_study_bundle(output_root=copied_study_bundle)


@pytest.mark.parametrize("relative_path", ("../escape", "/absolute", "folder\\file", "./file", "folder/../file"))
def test_unsafe_source_binding_paths_reject(copied_study_bundle: Path, relative_path: str) -> None:
    binding = _binding(copied_study_bundle)
    inventory = _source_entry(binding, "diagnosis")["inventory"]
    assert isinstance(inventory, dict)
    files = inventory["files"]
    assert isinstance(files, list)
    files[0]["relative_path"] = relative_path
    _write_json(copied_study_bundle / "source_binding.json", binding)
    with pytest.raises(study.QualityNormalizationStudyError, match="safe canonical POSIX relative path"):
        study.validate_quality_study_bundle(output_root=copied_study_bundle)


@pytest.mark.parametrize("mode", ("duplicate", "unsorted"))
def test_duplicate_and_unsorted_source_binding_paths_reject(copied_study_bundle: Path, mode: str) -> None:
    binding = _binding(copied_study_bundle)
    inventory = _source_entry(binding, "density")["inventory"]
    assert isinstance(inventory, dict)
    files = inventory["files"]
    assert isinstance(files, list)
    if mode == "duplicate":
        files[1]["relative_path"] = files[0]["relative_path"]
        match = "paths must be unique"
    else:
        files.reverse()
        match = "paths must be strictly sorted"
    _write_json(copied_study_bundle / "source_binding.json", binding)
    with pytest.raises(study.QualityNormalizationStudyError, match=match):
        study.validate_quality_study_bundle(output_root=copied_study_bundle)


@pytest.mark.parametrize("size_bytes", (-1, True, "1"))
def test_invalid_source_binding_sizes_reject(copied_study_bundle: Path, size_bytes: object) -> None:
    binding = _binding(copied_study_bundle)
    inventory = _source_entry(binding, "diagnosis")["inventory"]
    assert isinstance(inventory, dict)
    files = inventory["files"]
    assert isinstance(files, list)
    files[0]["size_bytes"] = size_bytes
    _write_json(copied_study_bundle / "source_binding.json", binding)
    with pytest.raises(study.QualityNormalizationStudyError, match="size_bytes is invalid"):
        study.validate_quality_study_bundle(output_root=copied_study_bundle)


@pytest.mark.parametrize("file_hash", ("A" * 64, "0" * 63, "z" * 64, 0))
def test_invalid_source_binding_hashes_reject(copied_study_bundle: Path, file_hash: object) -> None:
    binding = _binding(copied_study_bundle)
    inventory = _source_entry(binding, "density")["inventory"]
    assert isinstance(inventory, dict)
    files = inventory["files"]
    assert isinstance(files, list)
    files[0]["sha256"] = file_hash
    _write_json(copied_study_bundle / "source_binding.json", binding)
    with pytest.raises(study.QualityNormalizationStudyError, match="lowercase 64-character SHA-256"):
        study.validate_quality_study_bundle(output_root=copied_study_bundle)
