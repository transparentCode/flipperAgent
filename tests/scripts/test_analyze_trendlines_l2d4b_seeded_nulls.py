"""Offline script contract tests for L2-D4B."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import analyze_trendlines_l2d4b_seeded_nulls as d4b_script


@pytest.fixture(scope="module")
def study_result(tmp_path_factory):
    output_root = tmp_path_factory.mktemp("l2d4b-script") / "output"
    return SimpleNamespace(
        **d4b_script.run_study(output_root=output_root),
    )


def test_script_loads_only_committed_prior_artifacts(study_result):
    manifest = json.loads(study_result.paths["run_manifest"].read_text())
    assert manifest["source_artifact_path"].endswith("normalized_ohlcv_v2.json")
    assert "trendlines_research_validation" in manifest["source_artifact_path"]
    assert "l2d2_structural_stability_v1" in manifest["d2_artifact_path"]
    assert "l2d3_interaction_utility_v1" in manifest["d3_artifact_path"]
    assert "l2d4a_deterministic_naive_baselines_v1" in manifest["d4a_artifact_path"]


def test_script_provider_budget_and_attempt_inventory_remain_zero(study_result):
    manifest = json.loads(study_result.paths["run_manifest"].read_text())
    assert manifest["provider_calls"] == 0
    assert manifest["provider_retries"] == 0
    assert manifest["selection_attempts"] == 2752
    assert manifest["expected_selection_attempts"] == 2752
    assert manifest["selection_attempts"] == (
        manifest["model_event_count"] * 2 * 32
    )


def test_script_preserves_prior_identities_and_outcome_null(study_result):
    manifest = json.loads(study_result.paths["run_manifest"].read_text())
    assert manifest["structural_stability_bundle_id"] == d4b_script.EXPECTED_D2_BUNDLE_ID
    assert manifest["interaction_utility_bundle_id"] == d4b_script.EXPECTED_D3_BUNDLE_ID
    assert manifest["baseline_comparison_bundle_id"] == d4b_script.EXPECTED_D4A_BUNDLE_ID
    assert manifest["stochastic_null_comparison_bundle_id"] == study_result.bundle.stochastic_null_comparison_bundle_id
    assert manifest["outcome"] is None


def test_script_selection_inventory_and_distribution_rows_are_complete(study_result):
    manifest = json.loads(study_result.paths["run_manifest"].read_text())
    assert manifest["null_outcome_count"] == len(study_result.bundle.null_outcomes)
    assert manifest["repetition_comparison_count"] == 2 * 32 * 2 * 4
    assert manifest["distribution_summary_count"] == 2 * 1 * 2 * 4 * 7
    assert set(manifest["selection_inventory"]) == {
        "random-valid-pivot-pair-v1",
        "causal-density-matched-null-v1",
    }
    assert manifest["selection_inventory"]["random-valid-pivot-pair-v1"]["attempts"] == 1376
    assert manifest["selection_inventory"]["causal-density-matched-null-v1"]["attempts"] == 1376


def test_script_checksums_cover_canonical_outputs(study_result):
    root = study_result.paths["run_manifest"].parent
    checksums = json.loads((root / "checksums.json").read_text())
    for member in checksums["files"]:
        path = root / member["path"]
        data = path.read_bytes()
        assert len(data) == member["byte_length"]
        assert hashlib.sha256(data).hexdigest() == member["sha256"]


def test_script_has_no_provider_or_network_construction():
    source = Path("scripts/analyze_trendlines_l2d4b_seeded_nulls.py").read_text(
        encoding="utf-8"
    )
    assert "BinanceNativeAdapter" not in source
    assert "get_historical_ohlcv" not in source
    assert "http://" not in source
