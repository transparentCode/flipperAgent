from __future__ import annotations

import json

import pytest

from libs.models.sr.domain.contracts import ContractValidationError
from libs.models.sr.scripts.atr_calibration.artifacts import (
    find_development_bundle,
    publish_development,
    selection_from_payload,
)
from libs.models.sr.scripts.atr_calibration.selection import select_development


def test_development_artifact_round_trip_and_content_identity(tmp_path, calibration_config, source_capsules, development_metrics):
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
    )
    loaded, loaded_bundle_id, loaded_path = find_development_bundle(
        calibration_config,
        output_root=tmp_path,
        development_source_id=development.capsule_id,
        implementation_commit=calibration_config.source_implementation_commit,
    )
    assert loaded.selection_id == selection.selection_id
    assert (bundle_id, path) == (loaded_bundle_id, loaded_path)
    assert selection_from_payload(json.loads((path / "selection.json").read_text())).selection_id == selection.selection_id


def test_duplicate_json_key_rejected_in_selection(tmp_path, calibration_config, source_capsules, development_metrics):
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
    )
    selection_path = path / "selection.json"
    selection_path.write_text('{"selection_id":"x","selection_id":"y"}', encoding="utf-8")
    with pytest.raises(ContractValidationError):
        find_development_bundle(
            calibration_config,
            output_root=tmp_path,
            development_source_id=development.capsule_id,
            implementation_commit=calibration_config.source_implementation_commit,
        )
