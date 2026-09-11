import pytest

from libs.analysis_capabilities.execution import execute_analysis_capability


def test_unknown_capability_fails_before_execution() -> None:
    with pytest.raises(KeyError):
        execute_analysis_capability("model.unknown", object())


@pytest.mark.parametrize(
    "capability_id",
    (
        "model.trendlines",
        "model.sr",
        "model.regression",
        "ta.swing_anchors",
        "ta.fibonacci_geometry",
        "ta.fibonacci_trend_extension_geometry",
        "ta.parallel_channel_geometry",
        "ta.traditional_pivot_geometry",
        "ta.vwap_geometry",
        "ta.anchored_vwap_path",
        "ta.gann_box_geometry",
        "ta.gann_fan_geometry",
        "ta.volume_profile_geometry",
        "ta.abcd_pattern_geometry",
        "ta.xabcd_pattern_geometry",
        "ta.head_shoulders_pattern_geometry",
        "ta.triangle_pattern_geometry",
        "ta.cypher_pattern_geometry",
        "ta.three_drives_pattern_geometry",
        "ta.elliott_impulse_wave_geometry",
        "ta.elliott_correction_wave_geometry",
    ),
)
def test_known_capability_rejects_the_wrong_request_type(capability_id: str) -> None:
    with pytest.raises(TypeError):
        execute_analysis_capability(capability_id, object())
