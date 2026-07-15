from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import canonical_json, deterministic_hash
from libs.models.sr.scripts.atr_calibration.artifacts import (
    find_development_bundle,
    publish_development,
    publish_holdout,
    selection_from_payload,
    validate_holdout_bundle,
)
from libs.models.sr.scripts.atr_calibration.candidates import replay_candidates
from libs.models.sr.scripts.atr_calibration.metrics import compute_window_metrics
from libs.models.sr.scripts.atr_calibration.selection import (
    DevelopmentDisposition,
    evaluate_holdout_metrics,
    select_development,
)


def test_development_artifact_round_trip_and_content_identity(tmp_path, calibration_config, source_capsules, development_metrics, resolved_sr_config):
    development, _ = source_capsules
    selection = select_development(
        development_metrics,
        config=calibration_config,
        development_source_id=development.capsule_id,
        implementation_commit=calibration_config.source_implementation_commit,
    )
    bundle_id, path = publish_development(
        selection,
        calibration_config,
        implementation_commit=calibration_config.source_implementation_commit,
        development_source_id=development.capsule_id,
        output_root=tmp_path,
        resolved_sr_config_hash=resolved_sr_config.resolved_config_hash,
        resolved_input_hash=calibration_config.expected_input_hash,
    )
    loaded, loaded_bundle_id, loaded_path = find_development_bundle(
        calibration_config,
        output_root=tmp_path,
        development_source_id=development.capsule_id,
        implementation_commit=calibration_config.source_implementation_commit,
        development=development,
        resolved_config=resolved_sr_config,
    )
    assert loaded.selection_id == selection.selection_id
    assert (bundle_id, path) == (loaded_bundle_id, loaded_path)
    assert selection_from_payload(json.loads((path / "selection.json").read_text())).selection_id == selection.selection_id


def test_duplicate_json_key_rejected_in_selection(tmp_path, calibration_config, source_capsules, development_metrics, resolved_sr_config):
    development, _ = source_capsules
    selection = select_development(
        development_metrics,
        config=calibration_config,
        development_source_id=development.capsule_id,
        implementation_commit=calibration_config.source_implementation_commit,
    )
    _, path = publish_development(
        selection,
        calibration_config,
        implementation_commit=calibration_config.source_implementation_commit,
        development_source_id=development.capsule_id,
        output_root=tmp_path,
        resolved_sr_config_hash=resolved_sr_config.resolved_config_hash,
        resolved_input_hash=calibration_config.expected_input_hash,
    )
    selection_path = path / "selection.json"
    selection_path.write_text('{"selection_id":"x","selection_id":"y"}', encoding="utf-8")
    with pytest.raises(ContractValidationError):
        find_development_bundle(
            calibration_config,
            output_root=tmp_path,
            development_source_id=development.capsule_id,
            implementation_commit=calibration_config.source_implementation_commit,
            development=development,
            resolved_config=resolved_sr_config,
        )


def test_rehashed_semantic_selection_tampering_is_rejected(tmp_path, calibration_config, source_capsules, development_metrics, resolved_sr_config):
    development, _ = source_capsules
    selection = select_development(
        development_metrics,
        config=calibration_config,
        development_source_id=development.capsule_id,
        implementation_commit=calibration_config.source_implementation_commit,
    )
    _, path = publish_development(
        selection,
        calibration_config,
        implementation_commit=calibration_config.source_implementation_commit,
        development_source_id=development.capsule_id,
        output_root=tmp_path,
        resolved_sr_config_hash=resolved_sr_config.resolved_config_hash,
        resolved_input_hash=calibration_config.expected_input_hash,
    )
    payload = json.loads((path / "selection.json").read_text(encoding="utf-8"))
    payload["selected_period"] = 7
    payload["disposition"] = "SELECTED_CHALLENGER"
    identity = dict(payload)
    identity.pop("selection_id", None)
    payload["selection_id"] = deterministic_hash(identity)
    selection_bytes = (canonical_json(payload) + "\n").encode("utf-8")
    (path / "selection.json").write_bytes(selection_bytes)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    semantic = manifest["bundle_id_semantic_payload"]
    for member in semantic["members"]:
        if member["name"] == "selection.json":
            member["sha256"] = sha256(selection_bytes).hexdigest()
            member["byte_length"] = len(selection_bytes)
    manifest["selection_id"] = payload["selection_id"]
    semantic["selection_id"] = payload["selection_id"]
    manifest["bundle_id"] = deterministic_hash(semantic)
    manifest["bundle_id_semantic_payload"] = semantic
    (path / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    tampered_path = path.parent / manifest["bundle_id"]
    path.rename(tampered_path)
    with pytest.raises(ContractValidationError):
        find_development_bundle(
            calibration_config,
            output_root=tmp_path,
            development_source_id=development.capsule_id,
            implementation_commit=calibration_config.source_implementation_commit,
            development=development,
            resolved_config=resolved_sr_config,
        )


def test_rehashed_protocol_mutation_is_rejected(tmp_path, calibration_config, source_capsules, development_metrics, resolved_sr_config):
    development, _ = source_capsules
    selection = select_development(
        development_metrics,
        config=calibration_config,
        development_source_id=development.capsule_id,
        implementation_commit=calibration_config.source_implementation_commit,
    )
    _, path = publish_development(
        selection,
        calibration_config,
        implementation_commit=calibration_config.source_implementation_commit,
        development_source_id=development.capsule_id,
        output_root=tmp_path,
        resolved_sr_config_hash=resolved_sr_config.resolved_config_hash,
        resolved_input_hash=calibration_config.expected_input_hash,
    )
    protocol_path = path / "protocol.json"
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    protocol["protocol"]["candidate_periods"] = [7, 10, 14, 20, 21]
    protocol_bytes = (json.dumps(protocol, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    protocol_path.write_bytes(protocol_bytes)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    semantic = manifest["bundle_id_semantic_payload"]
    for member in semantic["members"]:
        if member["name"] == "protocol.json":
            member["sha256"] = sha256(protocol_bytes).hexdigest()
            member["byte_length"] = len(protocol_bytes)
    manifest["bundle_id"] = deterministic_hash(semantic)
    manifest["bundle_id_semantic_payload"] = semantic
    (path / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    tampered_path = path.parent / manifest["bundle_id"]
    path.rename(tampered_path)
    with pytest.raises(ContractValidationError):
        find_development_bundle(
            calibration_config,
            output_root=tmp_path,
            development_source_id=development.capsule_id,
            implementation_commit=calibration_config.source_implementation_commit,
            development=development,
            resolved_config=resolved_sr_config,
        )


def test_selected_holdout_bundle_is_recomputed_from_sealed_capsule(tmp_path, calibration_config, source_capsules, development_metrics, resolved_sr_config):
    development, sealed = source_capsules
    base_selection = select_development(
        development_metrics,
        config=calibration_config,
        development_source_id=development.capsule_id,
        implementation_commit=calibration_config.source_implementation_commit,
    )
    selection = replace(
        base_selection,
        selected_period=7,
        disposition=DevelopmentDisposition.SELECTED_CHALLENGER,
    )
    replays = replay_candidates(
        sealed,
        (calibration_config.baseline_period, selection.selected_period),
        config=calibration_config,
        resolved_config=resolved_sr_config,
    )
    metrics = {
        replay.period: compute_window_metrics(
            replay,
            sealed,
            config=calibration_config,
            name="holdout",
            start=calibration_config.holdout_start,
            end=calibration_config.holdout_end,
        )
        for replay in replays
    }
    evaluation = evaluate_holdout_metrics(selection, metrics, config=calibration_config)
    development_bundle_id = "a" * 64
    bundle_id, path = publish_holdout(
        selection,
        evaluation,
        calibration_config,
        implementation_commit=calibration_config.source_implementation_commit,
        sealed_source_id=sealed.capsule_id,
        development_bundle_id=development_bundle_id,
        output_root=tmp_path,
        resolved_sr_config_hash=resolved_sr_config.resolved_config_hash,
        resolved_input_hash=calibration_config.expected_input_hash,
    )
    loaded = validate_holdout_bundle(
        path,
        config=calibration_config,
        selection=selection,
        implementation_commit=calibration_config.source_implementation_commit,
        sealed_source_id=sealed.capsule_id,
        development_bundle_id=development_bundle_id,
        sealed=sealed,
        resolved_config=resolved_sr_config,
    )
    assert loaded.holdout_id == evaluation.holdout_id
    assert path.name == bundle_id

    mutated_baseline = replace(
        evaluation.baseline_metrics,
        median_quality_reference_atr=evaluation.baseline_metrics.median_quality_reference_atr + 1.0,
    )
    mutated_evaluation = replace(evaluation, baseline_metrics=mutated_baseline)
    metrics_path = path / "holdout_metrics.json"
    metrics_payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics_payload["baseline"]["median_quality_reference_atr"] = mutated_baseline.median_quality_reference_atr
    metrics_bytes = (canonical_json(metrics_payload) + "\n").encode("utf-8")
    metrics_path.write_bytes(metrics_bytes)
    recommendation_path = path / "recommendation.json"
    recommendation_payload = json.loads(recommendation_path.read_text(encoding="utf-8"))
    recommendation_payload["holdout_id"] = mutated_evaluation.holdout_id
    recommendation_bytes = (canonical_json(recommendation_payload) + "\n").encode("utf-8")
    recommendation_path.write_bytes(recommendation_bytes)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    semantic = manifest["bundle_id_semantic_payload"]
    for member in semantic["members"]:
        member_path = path / member["name"]
        data = member_path.read_bytes()
        member["sha256"] = sha256(data).hexdigest()
        member["byte_length"] = len(data)
    manifest["holdout_id"] = mutated_evaluation.holdout_id
    semantic["holdout_id"] = mutated_evaluation.holdout_id
    manifest["bundle_id"] = deterministic_hash(semantic)
    manifest["bundle_id_semantic_payload"] = semantic
    (path / "manifest.json").write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    tampered_path = path.parent / manifest["bundle_id"]
    path.rename(tampered_path)
    with pytest.raises(ContractValidationError):
        validate_holdout_bundle(
            tampered_path,
            config=calibration_config,
            selection=selection,
            implementation_commit=calibration_config.source_implementation_commit,
            sealed_source_id=sealed.capsule_id,
            development_bundle_id=development_bundle_id,
            sealed=sealed,
            resolved_config=resolved_sr_config,
        )
