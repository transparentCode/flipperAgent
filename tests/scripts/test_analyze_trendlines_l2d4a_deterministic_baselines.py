"""Offline script contract tests for L2-D4A."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import analyze_trendlines_l2d4a_deterministic_baselines as d4_script


@pytest.fixture(scope="module")
def study_result(tmp_path_factory):
    root = tmp_path_factory.mktemp("l2d4a-script") / "output"
    return SimpleNamespace(
        **d4_script.run_study(
            output_root=root,
        )
    )


def test_script_loads_only_committed_source_and_prior_artifacts(study_result):
    manifest = json.loads(study_result.paths["run_manifest"].read_text())
    assert manifest["source_artifact_path"].endswith("normalized_ohlcv_v2.json")
    assert "trendlines_research_validation" in manifest["source_artifact_path"]
    assert "l2d2_structural_stability_v1" in manifest["d2_artifact_path"]
    assert "l2d3_interaction_utility_v1" in manifest["d3_artifact_path"]


def test_script_provider_budget_remains_zero(study_result):
    manifest = json.loads(study_result.paths["run_manifest"].read_text())
    assert manifest["provider_calls"] == 0
    assert manifest["provider_retries"] == 0


def test_script_identities_and_bundle_are_exact(study_result):
    manifest = json.loads(study_result.paths["run_manifest"].read_text())
    assert manifest["structural_stability_bundle_id"] == d4_script.d3_script.EXPECTED_D2_BUNDLE_ID
    assert manifest["interaction_utility_bundle_id"] == d4_script.EXPECTED_D3_BUNDLE_ID
    assert manifest["selection_attempts"] == 86
    assert manifest["model_event_count"] == 43
    assert manifest["outcome"] is None


def test_script_checksums_cover_canonical_outputs(study_result):
    root = study_result.paths["run_manifest"].parent
    checksums = json.loads((root / "checksums.json").read_text())
    for member in checksums["files"]:
        path = root / member["path"]
        data = path.read_bytes()
        assert len(data) == member["byte_length"]
        assert hashlib.sha256(data).hexdigest() == member["sha256"]
