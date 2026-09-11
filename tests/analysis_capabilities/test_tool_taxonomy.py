from pathlib import Path

import yaml

from libs.analysis_capabilities import get_analysis_capability

ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_PATH = (
    ROOT / "docs" / "architecture" / "analysis_capabilities" / "tool-taxonomy.yaml"
)
ALLOWED_FAMILIES = {
    "trend",
    "fibonacci",
    "gann",
    "pattern",
    "volume",
    "reference",
    "model",
    "viewer_shape",
}
ALLOWED_KINDS = {"quant_kernel", "viewer_primitive", "manual_only"}
ALLOWED_STATUSES = {"available", "planned", "deferred"}
EXPECTED_TOOL_IDS = (
    "abcd_pattern",
    "anchored_volume_profile",
    "anchored_vwap_path",
    "arc",
    "arrow",
    "brush_highlighter",
    "cypher_pattern",
    "elliott_correction_wave",
    "elliott_double_combo_wave",
    "elliott_impulse_wave",
    "elliott_triangle_wave",
    "elliott_triple_combo_wave",
    "ellipse",
    "fib_three_point_extension",
    "fib_two_point",
    "fixed_range_volume_profile",
    "flag_pennant_pattern",
    "gann_box",
    "gann_fan",
    "gann_square",
    "head_shoulders_pattern",
    "parallel_channel",
    "polyline",
    "rectangle",
    "regression",
    "support_resistance",
    "swing_anchors",
    "three_drives_pattern",
    "traditional_pivots",
    "trendlines",
    "triangle_pattern",
    "vwap_final",
    "wedge_pattern",
    "xabcd_harmonic_pattern",
)


def _taxonomy() -> dict:
    return yaml.safe_load(TAXONOMY_PATH.read_text(encoding="utf-8"))


def test_taxonomy_has_deterministic_unique_schema() -> None:
    document = _taxonomy()
    assert document["schema"] == "analysis-tool-taxonomy.v1"
    tools = document["tools"]
    ids = [tool["tool_id"] for tool in tools]
    assert ids == sorted(ids)
    assert tuple(ids) == EXPECTED_TOOL_IDS
    assert len(ids) == 34
    assert len(ids) == len(set(ids))
    assert all(
        set(tool)
        == {
            "tool_id",
            "family",
            "kind",
            "status",
            "capability_id",
        }
        for tool in tools
    )
    assert all(tool["family"] in ALLOWED_FAMILIES for tool in tools)
    assert all(tool["kind"] in ALLOWED_KINDS for tool in tools)
    assert all(tool["status"] in ALLOWED_STATUSES for tool in tools)


def test_available_quant_kernels_resolve_and_deferred_shapes_do_not() -> None:
    tools = _taxonomy()["tools"]
    callable_ids = {entry.capability_id for entry in _catalog_entries()}
    for tool in tools:
        capability_id = tool["capability_id"]
        if tool["status"] == "available":
            assert tool["kind"] == "quant_kernel"
            assert capability_id in callable_ids
            assert get_analysis_capability(capability_id).capability_id == capability_id
        else:
            assert capability_id is None
        if tool["kind"] == "viewer_primitive":
            assert tool["status"] == "deferred"
            assert capability_id is None


def test_gann_entries_split_available_fan_box_from_planned_square() -> None:
    gann = {
        tool["tool_id"]: tool
        for tool in _taxonomy()["tools"]
        if tool["tool_id"].startswith("gann_")
    }

    assert set(gann) == {"gann_fan", "gann_box", "gann_square"}
    assert all(tool["family"] == "gann" for tool in gann.values())
    assert all(tool["kind"] == "quant_kernel" for tool in gann.values())
    assert gann["gann_fan"]["status"] == "available"
    assert gann["gann_fan"]["capability_id"] == "ta.gann_fan_geometry"
    assert gann["gann_box"]["status"] == "available"
    assert gann["gann_box"]["capability_id"] == "ta.gann_box_geometry"
    assert gann["gann_square"]["status"] == "planned"
    assert gann["gann_square"]["capability_id"] is None


def test_volume_profile_tools_share_one_callable_kernel() -> None:
    tools = {
        tool["tool_id"]: tool
        for tool in _taxonomy()["tools"]
        if tool["tool_id"]
        in {
            "anchored_volume_profile",
            "fixed_range_volume_profile",
        }
    }
    assert set(tools) == {"anchored_volume_profile", "fixed_range_volume_profile"}
    assert all(tool["status"] == "available" for tool in tools.values())
    assert {tool["capability_id"] for tool in tools.values()} == {
        "ta.volume_profile_geometry"
    }


def test_pattern_tools_are_available_without_pattern_classifiers() -> None:
    tools = {
        tool["tool_id"]: tool
        for tool in _taxonomy()["tools"]
        if tool["tool_id"]
        in {
            "abcd_pattern",
            "head_shoulders_pattern",
            "triangle_pattern",
            "xabcd_harmonic_pattern",
            "cypher_pattern",
            "three_drives_pattern",
            "elliott_correction_wave",
            "elliott_impulse_wave",
            "elliott_triangle_wave",
            "elliott_double_combo_wave",
            "elliott_triple_combo_wave",
        }
    }
    assert tools["abcd_pattern"]["capability_id"] == ("ta.abcd_pattern_geometry")
    assert tools["head_shoulders_pattern"]["capability_id"] == (
        "ta.head_shoulders_pattern_geometry"
    )
    assert tools["triangle_pattern"]["capability_id"] == (
        "ta.triangle_pattern_geometry"
    )
    assert tools["xabcd_harmonic_pattern"]["capability_id"] == (
        "ta.xabcd_pattern_geometry"
    )
    assert tools["cypher_pattern"]["capability_id"] == ("ta.cypher_pattern_geometry")
    assert tools["three_drives_pattern"]["capability_id"] == (
        "ta.three_drives_pattern_geometry"
    )
    assert all(
        tools[tool_id]["status"] == "available"
        for tool_id in (
            "abcd_pattern",
            "head_shoulders_pattern",
            "triangle_pattern",
            "xabcd_harmonic_pattern",
            "cypher_pattern",
            "three_drives_pattern",
        )
    )
    assert all(
        tools[tool_id]["status"] == "planned"
        and tools[tool_id]["kind"] == "quant_kernel"
        and tools[tool_id]["capability_id"] is None
        for tool_id in (
            "elliott_triangle_wave",
            "elliott_double_combo_wave",
            "elliott_triple_combo_wave",
        )
    )
    assert all(
        tools[tool_id]["status"] == "available"
        and tools[tool_id]["capability_id"] == f"ta.{tool_id}_geometry"
        for tool_id in ("elliott_correction_wave", "elliott_impulse_wave")
    )
    assert "elliott_wave_pattern" not in tools


def _catalog_entries():
    from libs.analysis_capabilities import list_analysis_capabilities

    return list_analysis_capabilities()
