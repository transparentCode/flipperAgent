"""Offline contract tests for the bounded L2-D2 analysis script."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import analyze_trendlines_l2d2_structural_stability as subject


SOURCE_ROOT = Path.cwd() / subject.SOURCE_ROOT
EXPECTED_SOURCE = "d3cba96f006b5f7e05a38d888b60b799f128f41567030f0663da908e005f0331"
EXPECTED_AVAILABILITY = "9b3e8f49e408d7781b89a686787e989888d25638683e1a8ab921c1043d4f8bd1"
EXPECTED_DATASET = "6464eede955ccfcf0ac023b7b96d026235e6763cbc4eb10470f9c31ee9b0002c"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_script_is_pinned_to_committed_v2_artifact_and_has_no_provider_path():
    source = Path(subject.__file__).read_text(encoding="utf-8")
    assert subject.SOURCE_ARTIFACT_NAME == "normalized_ohlcv_v2.json"
    assert subject.SOURCE_ROOT.name == "20260726_btcusdt_1h_single_call_v1"
    assert "BinanceNativeAdapter" not in source
    assert "get_historical_ohlcv" not in source
    assert "TrendlineResearchDataMode.BINANCE" in source


def test_offline_run_reuses_exact_identities_and_writes_checksums(tmp_path):
    before_yaml = _sha256(Path("src/libs/models/trendlines/config/trendlines.yaml"))
    result = subject.run_study(source_root=SOURCE_ROOT, output_root=tmp_path)
    after_yaml = _sha256(Path("src/libs/models/trendlines/config/trendlines.yaml"))
    manifest = _json(tmp_path / "run_manifest.json")
    checksums = _json(tmp_path / "checksums.json")

    assert before_yaml == after_yaml
    assert manifest["provider_calls"] == 0
    assert manifest["provider_retries"] == 0
    assert manifest["implementation_base_commit"] == (
        "b839f5d593d47df186814563fe6fcd38984c85a6"
    )
    assert "implementation_commit" not in manifest
    assert manifest["test_disposition"]["status"] == "PASSED"
    assert manifest["test_disposition"]["provider_calls"] == 0
    assert manifest["source_id"] == EXPECTED_SOURCE
    assert manifest["availability_id"] == EXPECTED_AVAILABILITY
    assert manifest["dataset_id"] == EXPECTED_DATASET
    assert manifest["rows"] == 312
    assert manifest["executed_positions"] == 293
    assert manifest["recorded_positions"] == 248
    assert manifest["outcome"] is None
    assert result["bundle"].structural_stability_bundle_id == manifest[
        "structural_stability_bundle_id"
    ]
    for member in checksums["files"]:
        path = tmp_path / member["path"]
        assert path.is_file()
        assert path.stat().st_size == member["byte_length"]
        assert _sha256(path) == member["sha256"]


def test_identical_offline_runs_reproduce_bundle_and_manifest(tmp_path):
    first = subject.run_study(
        source_root=SOURCE_ROOT,
        output_root=tmp_path / "first",
    )
    second = subject.run_study(
        source_root=SOURCE_ROOT,
        output_root=tmp_path / "second",
    )
    assert first["bundle"].structural_stability_bundle_id == second[
        "bundle"
    ].structural_stability_bundle_id
    assert (tmp_path / "first" / "structural_stability_bundle.json").read_bytes() == (
        tmp_path / "second" / "structural_stability_bundle.json"
    ).read_bytes()


def test_changed_horizon_changes_spec_and_bundle_identity(tmp_path):
    default = subject.run_study(
        source_root=SOURCE_ROOT,
        output_root=tmp_path / "default",
    )
    changed = subject.run_study(
        source_root=SOURCE_ROOT,
        output_root=tmp_path / "changed",
        survival_horizons_bars=(1, 3),
    )
    assert default["stability_spec"].stability_spec_id != changed[
        "stability_spec"
    ].stability_spec_id
    assert default["bundle"].structural_stability_bundle_id != changed[
        "bundle"
    ].structural_stability_bundle_id
    assert _json(tmp_path / "changed" / "run_manifest.json")["outcome"] is None
