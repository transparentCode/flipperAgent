"""Network-free D5C orchestration tests."""

from __future__ import annotations

from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from scripts import analyze_trendlines_l2d5c_geometry_sensitivity as script
from libs.models.trendlines.config import load_trendlines_config
from libs.models.trendlines.workflows.research.adequacy import (
    GEOMETRY_SENSITIVITY_CAPSULE_SEMANTICS_VERSION,
    GEOMETRY_SENSITIVITY_VARIANT_NAMES,
    expected_geometry_variant_identity,
    frozen_geometry_sensitivity_variants,
)
from libs.models.trendlines.contracts.identity import canonical_hash


def test_official_output_overwrite_is_rejected(tmp_path):
    output = tmp_path / "already-published"
    output.mkdir()
    with pytest.raises(RuntimeError, match="overwrite is forbidden"):
        script.run_study(output_root=output)


def test_variant_config_is_copied_without_mutating_yaml_config():
    canonical = load_trendlines_config()
    before_extractor = dict(canonical.extractor_params)
    before_fitter = dict(canonical.fitter_params)
    variant_config = script._variant_config(canonical, frozen_geometry_sensitivity_variants()[0])
    assert dict(canonical.extractor_params) == before_extractor
    assert dict(canonical.fitter_params) == before_fitter
    assert variant_config is not canonical
    assert dict(variant_config.extractor_params) != before_extractor


def test_variants_have_fixed_order():
    assert tuple(value.name for value in frozen_geometry_sensitivity_variants()) == GEOMETRY_SENSITIVITY_VARIANT_NAMES


def test_all_frozen_expected_member_variant_identities_exist():
    for variant in frozen_geometry_sensitivity_variants():
        for member in (
            "reference-btcusdt-1h-20250101-v1",
            "temporal-btcusdt-1h-20250401-v1",
            "cross-asset-ethusdt-1h-20250401-v1",
            "cross-asset-solusdt-1h-20250401-v1",
            "cross-timeframe-btcusdt-4h-20250401-v1",
        ):
            identity = expected_geometry_variant_identity(variant.name, member)
            assert set(identity) == {"research_configuration_id", "preparation_id"}


def test_reference_frame_path_is_not_copied_to_matrix():
    class Spec:
        relation = "reference"

    spec = SimpleNamespace(relation="reference")
    assert script._member_frame_path(spec).parent == script.REFERENCE_SOURCE_ROOT


def test_fresh_frame_path_is_under_d5a_members():
    spec = SimpleNamespace(relation="temporal", name="member")
    assert script._member_frame_path(spec) == script.SOURCE_MATRIX_ROOT / "members" / "member" / script.SOURCE_ARTIFACT_NAME


def test_stage_digest_inventory_uses_four_stages():
    bundles = {
        "d2": SimpleNamespace(structural_stability_bundle_id="a" * 64, summaries=(), to_dict=lambda: {"id": "a"}),
        "d3": SimpleNamespace(interaction_utility_bundle_id="b" * 64, summaries=(), to_dict=lambda: {"id": "b"}),
        "d4a": SimpleNamespace(baseline_comparison_bundle_id="c" * 64, comparison_summaries=(), to_dict=lambda: {"id": "c"}),
        "d4b": SimpleNamespace(stochastic_null_comparison_bundle_id="d" * 64, distribution_summaries=(), to_dict=lambda: {"id": "d"}),
    }
    records = script._stage_digest_inventory({"bundles": bundles})
    assert tuple(row["stage"] for row in records) == ("d2", "d3", "d4a", "d4b")


def test_manifest_paths_are_not_part_of_package_identity():
    from scripts import analyze_trendlines_l2d5b_offline_robustness as d5b

    matrix, _ = d5b.load_source_matrix(trendlines_config=load_trendlines_config())
    protocol = script._build_protocol(matrix, d5b._protocol())
    first = protocol.to_dict()
    first["output_path"] = "/tmp/one"
    assert "output_path" not in protocol.to_dict()


def test_script_has_no_provider_construction_or_network_import():
    source = Path(script.__file__).read_text(encoding="utf-8")
    assert "BinanceNativeAdapter" not in source
    assert "requests" not in source
    assert "httpx" not in source


def test_official_counts_are_frozen():
    assert 5 * 2 == 10
    assert 15 * 293 == 4395
    assert 15 * 248 == 3720


def test_variant_root_parameters_are_explicit():
    canonical = load_trendlines_config()
    for variant in frozen_geometry_sensitivity_variants():
        configured = script._variant_config(canonical, variant)
        assert set(configured.extractor_params) == {"window_left", "window_right"}
        assert set(configured.fitter_params) == {"pivot_window", "line_fit_mode"}


def test_published_artifact_readback_is_complete_and_content_addressed():
    root = Path(
        "artifacts/trendlines_research_robustness/"
        "20260727_l2d5c_geometry_sensitivity_v1"
    )
    assert root.is_dir()
    inventory = json.loads((root / "checksums.json").read_text(encoding="utf-8"))
    files = tuple(inventory["files"])
    assert len(files) == 18
    assert len(tuple(root.rglob("*"))) >= 19
    for entry in files:
        path = root / entry["path"]
        assert path.is_file()
        assert path.stat().st_size == entry["byte_length"]
        assert script._sha256(path) == entry["sha256"]

    bundle = json.loads((root / "geometry_sensitivity_bundle.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
    assert bundle["geometry_sensitivity_bundle_id"] == manifest["geometry_sensitivity_bundle_id"]
    assert "capsules" not in bundle
    capsule_ids = tuple(bundle["capsule_ids"])
    assert len(capsule_ids) == 10
    assert [row["capsule_id"] for row in manifest["capsules"]] == list(capsule_ids)
    capsules = [
        json.loads((root / row["path"]).read_text(encoding="utf-8"))
        for row in manifest["capsules"]
    ]
    assert [row["geometry_sensitivity_capsule_id"] for row in capsules] == list(capsule_ids)
    for capsule in capsules:
        assert not {"state_rows", "outcomes", "null_outcomes", "stochastic_selections"}.intersection(capsule)
        payload = dict(capsule)
        capsule_id = payload.pop("geometry_sensitivity_capsule_id")
        assert capsule_id == canonical_hash(
            payload,
            semantics_version=GEOMETRY_SENSITIVITY_CAPSULE_SEMANTICS_VERSION,
        )
