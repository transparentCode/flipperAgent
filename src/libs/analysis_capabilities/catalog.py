"""The fixed V0A analysis capability catalog."""

from .descriptor import AnalysisCapabilityDescriptor
from .registry import AnalysisCapabilityRegistry

_REGISTRY = AnalysisCapabilityRegistry(
    (
        AnalysisCapabilityDescriptor(
            capability_id="model.trendlines",
            display_name="Trendlines",
            description="Structural trendline geometry analysis.",
            canonical_module="libs.models.trendlines",
        ),
        AnalysisCapabilityDescriptor(
            capability_id="model.sr",
            display_name="Support / Resistance",
            description="Support and resistance structure analysis.",
            canonical_module="libs.models.sr",
        ),
        AnalysisCapabilityDescriptor(
            capability_id="model.regression",
            display_name="Regression",
            description="Regression-based market structure analysis.",
            canonical_module="libs.regression.api",
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.swing_anchors",
            display_name="Causal Swing Anchors",
            description=(
                "Strict confirmed swing anchors with formation and availability times."
            ),
            canonical_module="libs.analysis_capabilities.ta.swing_anchors",
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.fibonacci_geometry",
            display_name="Two-Point Fibonacci Geometry",
            description=(
                "Linear two-anchor retracement and extension geometry from "
                "explicit causal anchors."
            ),
            canonical_module="libs.analysis_capabilities.ta.fibonacci_geometry",
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.vwap_geometry",
            display_name="VWAP Geometry",
            description=(
                "Explicit-range HLC3 volume-weighted average price at a "
                "closed-bar cutoff."
            ),
            canonical_module="libs.analysis_capabilities.ta.vwap_geometry",
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.parallel_channel_geometry",
            display_name="Parallel Channel Geometry",
            description=(
                "Explicit three-anchor parallel channel geometry using ordered "
                "bar-index coordinates."
            ),
            canonical_module=(
                "libs.analysis_capabilities.ta.parallel_channel_geometry"
            ),
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.fibonacci_trend_extension_geometry",
            display_name="Three-Point Fibonacci Trend Extension",
            description=(
                "Explicit three-point Fibonacci extension levels from causal "
                "anchors and caller-selected ratios."
            ),
            canonical_module=(
                "libs.analysis_capabilities.ta.fibonacci_trend_extension_geometry"
            ),
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.anchored_vwap_path",
            display_name="Anchored VWAP Path",
            description=("Explicit-range cumulative HLC3 VWAP path over closed bars."),
            canonical_module="libs.analysis_capabilities.ta.anchored_vwap_path",
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.traditional_pivot_geometry",
            display_name="Traditional Pivot Geometry",
            description=(
                "Traditional pivot-point horizontal levels from an explicit "
                "completed reference range."
            ),
            canonical_module="libs.analysis_capabilities.ta.traditional_pivot_geometry",
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.gann_fan_geometry",
            display_name="Gann Fan Geometry",
            description=(
                "Explicit bar-coordinate Gann fan rays with a caller-supplied "
                "price-per-bar scale."
            ),
            canonical_module="libs.analysis_capabilities.ta.gann_fan_geometry",
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.gann_box_geometry",
            display_name="Gann Box Geometry",
            description=(
                "Explicit price and bar-coordinate Gann box partition levels."
            ),
            canonical_module="libs.analysis_capabilities.ta.gann_box_geometry",
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.volume_profile_geometry",
            display_name="Volume Profile Geometry",
            description=(
                "Explicit-range volume histogram using deterministic uniform "
                "price-overlap allocation."
            ),
            canonical_module="libs.analysis_capabilities.ta.volume_profile_geometry",
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.abcd_pattern_geometry",
            display_name="ABCD Pattern Geometry",
            description=(
                "Explicit four-anchor ABCD price and bar-coordinate geometry "
                "without pattern classification."
            ),
            canonical_module="libs.analysis_capabilities.ta.abcd_pattern_geometry",
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.xabcd_pattern_geometry",
            display_name="XABCD Pattern Geometry",
            description=(
                "Explicit five-anchor XABCD geometry and factual harmonic "
                "ratios without named-family classification."
            ),
            canonical_module="libs.analysis_capabilities.ta.xabcd_pattern_geometry",
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.head_shoulders_pattern_geometry",
            display_name="Head & Shoulders Pattern Geometry",
            description=(
                "Explicit regular or inverse Head & Shoulders neckline and "
                "prominence geometry."
            ),
            canonical_module=(
                "libs.analysis_capabilities.ta.head_shoulders_pattern_geometry"
            ),
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.triangle_pattern_geometry",
            display_name="Triangle Pattern Geometry",
            description=(
                "Explicit four-anchor triangle boundary, gap, and apex "
                "geometry without subtype classification."
            ),
            canonical_module="libs.analysis_capabilities.ta.triangle_pattern_geometry",
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.cypher_pattern_geometry",
            display_name="Cypher Pattern Geometry",
            description=(
                "Explicit five-anchor Cypher measurements without ratio classification."
            ),
            canonical_module="libs.analysis_capabilities.ta.cypher_pattern_geometry",
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.three_drives_pattern_geometry",
            display_name="Three Drives Pattern Geometry",
            description=(
                "Explicit six-anchor Three Drives measurements without "
                "symmetry classification."
            ),
            canonical_module=(
                "libs.analysis_capabilities.ta.three_drives_pattern_geometry"
            ),
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.elliott_impulse_wave_geometry",
            display_name="Elliott Impulse Wave Geometry",
            description=(
                "Explicit six-anchor Elliott impulse price and bar-coordinate "
                "geometry without theory-rule validation."
            ),
            canonical_module=(
                "libs.analysis_capabilities.ta.elliott_impulse_wave_geometry"
            ),
        ),
        AnalysisCapabilityDescriptor(
            capability_id="ta.elliott_correction_wave_geometry",
            display_name="Elliott Correction Wave Geometry",
            description=(
                "Explicit four-anchor Elliott correction geometry without "
                "subtype classification."
            ),
            canonical_module=(
                "libs.analysis_capabilities.ta.elliott_correction_wave_geometry"
            ),
        ),
    )
)


def get_analysis_capability(capability_id: str) -> AnalysisCapabilityDescriptor:
    """Return one catalog entry by its exact stable identifier."""

    return _REGISTRY.get(capability_id)


def list_analysis_capabilities() -> tuple[AnalysisCapabilityDescriptor, ...]:
    """Return all catalog entries in deterministic ID order."""

    return _REGISTRY.descriptors


__all__ = ("get_analysis_capability", "list_analysis_capabilities")
