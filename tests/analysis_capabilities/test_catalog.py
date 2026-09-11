import importlib.util

import pytest

from libs.analysis_capabilities import (
    get_analysis_capability,
    list_analysis_capabilities,
)

EXPECTED = {
    "model.regression": ("Regression", "libs.regression.api"),
    "model.sr": ("Support / Resistance", "libs.models.sr"),
    "model.trendlines": ("Trendlines", "libs.models.trendlines"),
    "ta.swing_anchors": (
        "Causal Swing Anchors",
        "libs.analysis_capabilities.ta.swing_anchors",
    ),
    "ta.fibonacci_geometry": (
        "Two-Point Fibonacci Geometry",
        "libs.analysis_capabilities.ta.fibonacci_geometry",
    ),
    "ta.traditional_pivot_geometry": (
        "Traditional Pivot Geometry",
        "libs.analysis_capabilities.ta.traditional_pivot_geometry",
    ),
    "ta.vwap_geometry": (
        "VWAP Geometry",
        "libs.analysis_capabilities.ta.vwap_geometry",
    ),
    "ta.anchored_vwap_path": (
        "Anchored VWAP Path",
        "libs.analysis_capabilities.ta.anchored_vwap_path",
    ),
    "ta.fibonacci_trend_extension_geometry": (
        "Three-Point Fibonacci Trend Extension",
        "libs.analysis_capabilities.ta.fibonacci_trend_extension_geometry",
    ),
    "ta.parallel_channel_geometry": (
        "Parallel Channel Geometry",
        "libs.analysis_capabilities.ta.parallel_channel_geometry",
    ),
    "ta.gann_box_geometry": (
        "Gann Box Geometry",
        "libs.analysis_capabilities.ta.gann_box_geometry",
    ),
    "ta.gann_fan_geometry": (
        "Gann Fan Geometry",
        "libs.analysis_capabilities.ta.gann_fan_geometry",
    ),
    "ta.volume_profile_geometry": (
        "Volume Profile Geometry",
        "libs.analysis_capabilities.ta.volume_profile_geometry",
    ),
    "ta.abcd_pattern_geometry": (
        "ABCD Pattern Geometry",
        "libs.analysis_capabilities.ta.abcd_pattern_geometry",
    ),
    "ta.xabcd_pattern_geometry": (
        "XABCD Pattern Geometry",
        "libs.analysis_capabilities.ta.xabcd_pattern_geometry",
    ),
    "ta.head_shoulders_pattern_geometry": (
        "Head & Shoulders Pattern Geometry",
        "libs.analysis_capabilities.ta.head_shoulders_pattern_geometry",
    ),
    "ta.triangle_pattern_geometry": (
        "Triangle Pattern Geometry",
        "libs.analysis_capabilities.ta.triangle_pattern_geometry",
    ),
    "ta.cypher_pattern_geometry": (
        "Cypher Pattern Geometry",
        "libs.analysis_capabilities.ta.cypher_pattern_geometry",
    ),
    "ta.three_drives_pattern_geometry": (
        "Three Drives Pattern Geometry",
        "libs.analysis_capabilities.ta.three_drives_pattern_geometry",
    ),
    "ta.elliott_impulse_wave_geometry": (
        "Elliott Impulse Wave Geometry",
        "libs.analysis_capabilities.ta.elliott_impulse_wave_geometry",
    ),
    "ta.elliott_correction_wave_geometry": (
        "Elliott Correction Wave Geometry",
        "libs.analysis_capabilities.ta.elliott_correction_wave_geometry",
    ),
}


def test_catalog_has_exact_ids_and_deterministic_order() -> None:
    entries = list_analysis_capabilities()

    assert isinstance(entries, tuple)
    assert tuple(entry.capability_id for entry in entries) == tuple(sorted(EXPECTED))
    assert {entry.capability_id for entry in entries} == set(EXPECTED)


@pytest.mark.parametrize("capability_id", tuple(sorted(EXPECTED)))
def test_catalog_metadata_and_lookup(capability_id: str) -> None:
    entry = get_analysis_capability(capability_id)
    expected_display_name, expected_module = EXPECTED[capability_id]

    assert entry.display_name == expected_display_name
    assert entry.canonical_module == expected_module
    assert entry.description.strip()
    assert "alpha" not in entry.description.lower()
    assert "promotion" not in entry.description.lower()
    assert importlib.util.find_spec(entry.canonical_module) is not None


def test_catalog_lookup_returns_the_catalog_entry() -> None:
    entries = {entry.capability_id: entry for entry in list_analysis_capabilities()}

    for capability_id, entry in entries.items():
        assert get_analysis_capability(capability_id) is entry

    with pytest.raises(KeyError):
        get_analysis_capability("model.unknown")


def test_fibonacci_catalog_declares_only_two_point_linear_geometry() -> None:
    entry = get_analysis_capability("ta.fibonacci_geometry")

    assert entry.description == (
        "Linear two-anchor retracement and extension geometry from explicit causal "
        "anchors."
    )
    assert "three" not in entry.description.lower()
    assert "log" not in entry.description.lower()
