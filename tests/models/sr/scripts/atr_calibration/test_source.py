from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from hashlib import sha256
from shutil import copytree

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.domain.identity import canonical_json, deterministic_hash
from libs.models.sr.scripts.atr_calibration.contracts import CapsuleStage
from libs.models.sr.scripts.atr_calibration.source import (
    build_source_capsules,
    load_capsule,
    load_frozen_source,
    publish_source_capsule,
)


def test_exact_frozen_source_identity(calibration_config):
    bars = load_frozen_source(calibration_config, repo_root=Path(__file__).resolve().parents[5])
    assert len(bars) == 811
    assert bars[0].open_time.isoformat() == "2024-04-11T00:00:00+00:00"
    assert bars[-1].closed_at.isoformat() == "2026-07-01T00:00:00+00:00"


def _copied_frozen_source_bundle(tmp_path, calibration_config):
    repository_root = Path(__file__).resolve().parents[5]
    source_bundle = repository_root / calibration_config.source_bundle_path
    copied_bundle = tmp_path / "bundle"
    copytree(source_bundle, copied_bundle)
    return (
        replace(calibration_config, source_bundle_path="bundle"),
        copied_bundle,
    )


def test_frozen_source_rejects_rehashed_member_metadata_tamper(
    tmp_path,
    calibration_config,
):
    copied_config, copied_bundle = _copied_frozen_source_bundle(
        tmp_path,
        calibration_config,
    )
    manifest_path = copied_bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_member = next(
        member for member in manifest["members"] if member["name"] == "source_bars.json"
    )
    source_member["byte_length"] += 1
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ContractValidationError):
        load_frozen_source(copied_config, repo_root=tmp_path)


def test_frozen_source_rejects_source_member_symlink(tmp_path, calibration_config):
    copied_config, copied_bundle = _copied_frozen_source_bundle(
        tmp_path,
        calibration_config,
    )
    source_path = copied_bundle / "source_bars.json"
    copied_member = tmp_path / "source_bars-copy.json"
    copied_member.write_bytes(source_path.read_bytes())
    source_path.unlink()
    source_path.symlink_to(copied_member)

    with pytest.raises(ContractValidationError):
        load_frozen_source(copied_config, repo_root=tmp_path)


def test_source_capsule_round_trip_and_member_tamper_rejection(tmp_path, calibration_config, source_capsules):
    development, _ = source_capsules
    output_root = tmp_path / "research"
    path = publish_source_capsule(development, output_root=output_root)
    loaded = load_capsule(path, expected_stage=CapsuleStage.DEVELOPMENT, expected_source=calibration_config, expected_implementation_commit=development.implementation_commit)
    assert loaded.capsule_id == development.capsule_id
    source_path = path / "source_bars.json"
    source_path.write_bytes(source_path.read_bytes() + b" ")
    with pytest.raises(ContractValidationError):
        load_capsule(path, expected_stage=CapsuleStage.DEVELOPMENT, expected_source=calibration_config, expected_implementation_commit=development.implementation_commit)


def test_development_prefix_identity_is_frozen_against_fully_rehashed_bar_tamper(
    tmp_path,
    calibration_config,
    source_capsules,
):
    development, _ = source_capsules
    path = publish_source_capsule(development, output_root=tmp_path)
    source_path = path / "source_bars.json"
    source_payload = json.loads(source_path.read_text(encoding="utf-8"))
    first_bar = source_payload["bars"][0]
    first_bar["open"] = (first_bar["low"] + first_bar["high"]) / 2.0
    source_bytes = (canonical_json(source_payload) + "\n").encode("utf-8")
    source_path.write_bytes(source_bytes)

    bars = source_payload["bars"]
    identity = {
        "schema_version": source_payload["schema_version"],
        "stage": source_payload["stage"],
        "source_bundle_id": source_payload["source_bundle_id"],
        "source_bars_sha256": source_payload["source_bars_sha256"],
        "source_row_count": source_payload["source_row_count"],
        "split_boundary": source_payload["split_boundary"],
        "implementation_commit": source_payload["implementation_commit"],
        "bars": bars,
    }
    capsule_id = deterministic_hash(identity)
    bars_sha256 = sha256(canonical_json(bars).encode("utf-8")).hexdigest()
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    semantic = manifest["capsule_id_semantic_payload"]
    for payload in (manifest, semantic):
        payload["capsule_id"] = capsule_id
        payload["bars_sha256"] = bars_sha256
        payload["member"] = {
            "name": "source_bars.json",
            "sha256": sha256(source_bytes).hexdigest(),
            "byte_length": len(source_bytes),
        }
    manifest["capsule_id_recomputed_from"] = identity
    manifest_bytes = (canonical_json(manifest) + "\n").encode("utf-8")
    (path / "manifest.json").write_bytes(manifest_bytes)
    tampered_path = path.parent / capsule_id
    path.rename(tampered_path)

    with pytest.raises(ContractValidationError):
        load_capsule(
            tampered_path,
            expected_stage=CapsuleStage.DEVELOPMENT,
            expected_source=calibration_config,
            expected_implementation_commit=development.implementation_commit,
        )


def test_retired_sealed_source_paths_fail_closed(tmp_path, calibration_config, sealed_test_capsule):
    with pytest.raises(ContractValidationError):
        build_source_capsules(
            calibration_config,
            repo_root=Path(__file__).resolve().parents[5],
            implementation_commit=calibration_config.source_implementation_commit,
        )
    with pytest.raises(ContractValidationError):
        publish_source_capsule(sealed_test_capsule, output_root=tmp_path)


def test_source_module_has_no_provider_adapter_or_network_dependency():
    source = Path(__file__).resolve().parents[5] / "src/libs/models/sr/scripts/atr_calibration/source.py"
    text = source.read_text(encoding="utf-8")
    assert "BinanceNativeAdapter" not in text
    assert "requests" not in text
    assert "httpx" not in text
    assert "research.studies.baseline_trial" not in text
