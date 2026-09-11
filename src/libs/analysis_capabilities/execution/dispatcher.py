"""Explicit capability dispatch without dynamic model loading."""

from typing import Any

from ..catalog import get_analysis_capability


def execute_analysis_capability(capability_id: str, request: object) -> Any:
    """Execute one known capability through its native adapter contract."""

    get_analysis_capability(capability_id)

    if capability_id == "model.trendlines":
        from .trendlines import execute_trendlines

        return execute_trendlines(request)
    if capability_id == "model.sr":
        from .sr import execute_sr

        return execute_sr(request)
    if capability_id == "model.regression":
        from .regression import execute_regression

        return execute_regression(request)
    if capability_id == "ta.swing_anchors":
        from ..ta.swing_anchors import compute_swing_anchors

        return compute_swing_anchors(request)
    if capability_id == "ta.fibonacci_geometry":
        from ..ta.fibonacci_geometry import compute_fibonacci_geometry

        return compute_fibonacci_geometry(request)
    if capability_id == "ta.fibonacci_trend_extension_geometry":
        from ..ta.fibonacci_trend_extension_geometry import (
            compute_fibonacci_trend_extension,
        )

        return compute_fibonacci_trend_extension(request)
    if capability_id == "ta.parallel_channel_geometry":
        from ..ta.parallel_channel_geometry import compute_parallel_channel_geometry

        return compute_parallel_channel_geometry(request)
    if capability_id == "ta.traditional_pivot_geometry":
        from ..ta.traditional_pivot_geometry import compute_traditional_pivot_geometry

        return compute_traditional_pivot_geometry(request)
    if capability_id == "ta.vwap_geometry":
        from ..ta.vwap_geometry import compute_vwap_geometry

        return compute_vwap_geometry(request)
    if capability_id == "ta.anchored_vwap_path":
        from ..ta.anchored_vwap_path import compute_anchored_vwap_path

        return compute_anchored_vwap_path(request)
    if capability_id == "ta.gann_fan_geometry":
        from ..ta.gann_fan_geometry import compute_gann_fan_geometry

        return compute_gann_fan_geometry(request)
    if capability_id == "ta.gann_box_geometry":
        from ..ta.gann_box_geometry import compute_gann_box_geometry

        return compute_gann_box_geometry(request)
    if capability_id == "ta.volume_profile_geometry":
        from ..ta.volume_profile_geometry import compute_volume_profile_geometry

        return compute_volume_profile_geometry(request)
    if capability_id == "ta.abcd_pattern_geometry":
        from ..ta.abcd_pattern_geometry import compute_abcd_pattern_geometry

        return compute_abcd_pattern_geometry(request)
    if capability_id == "ta.xabcd_pattern_geometry":
        from ..ta.xabcd_pattern_geometry import compute_xabcd_pattern_geometry

        return compute_xabcd_pattern_geometry(request)
    if capability_id == "ta.head_shoulders_pattern_geometry":
        from ..ta.head_shoulders_pattern_geometry import (
            compute_head_shoulders_pattern_geometry,
        )

        return compute_head_shoulders_pattern_geometry(request)
    if capability_id == "ta.triangle_pattern_geometry":
        from ..ta.triangle_pattern_geometry import compute_triangle_pattern_geometry

        return compute_triangle_pattern_geometry(request)
    if capability_id == "ta.cypher_pattern_geometry":
        from ..ta.cypher_pattern_geometry import compute_cypher_pattern_geometry

        return compute_cypher_pattern_geometry(request)
    if capability_id == "ta.three_drives_pattern_geometry":
        from ..ta.three_drives_pattern_geometry import (
            compute_three_drives_pattern_geometry,
        )

        return compute_three_drives_pattern_geometry(request)
    if capability_id == "ta.elliott_impulse_wave_geometry":
        from ..ta.elliott_impulse_wave_geometry import (
            compute_elliott_impulse_wave_geometry,
        )

        return compute_elliott_impulse_wave_geometry(request)
    if capability_id == "ta.elliott_correction_wave_geometry":
        from ..ta.elliott_correction_wave_geometry import (
            compute_elliott_correction_wave_geometry,
        )

        return compute_elliott_correction_wave_geometry(request)

    raise RuntimeError(f"catalog capability has no V0B adapter: {capability_id!r}")


__all__ = ("execute_analysis_capability",)
