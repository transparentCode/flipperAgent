"""Opt-in deterministic technical-analysis capabilities."""

__all__ = (
    "ABCDPatternGeometryRequest",
    "ABCDPatternGeometrySnapshot",
    "ABCDSequenceKind",
    "AnchoredVWAPPathRequest",
    "AnchoredVWAPPathSnapshot",
    "AnchoredVWAPPoint",
    "CypherPatternGeometryRequest",
    "CypherPatternGeometrySnapshot",
    "CypherSequenceKind",
    "ElliottCorrectionOrientation",
    "ElliottCorrectionWaveGeometryRequest",
    "ElliottCorrectionWaveGeometrySnapshot",
    "ElliottImpulseOrientation",
    "ElliottImpulseWaveGeometryRequest",
    "ElliottImpulseWaveGeometrySnapshot",
    "FibonacciTrendExtensionLevel",
    "FibonacciTrendExtensionRequest",
    "FibonacciTrendExtensionSnapshot",
    "GannAngleRatio",
    "GannBoxGeometryRequest",
    "GannBoxGeometrySnapshot",
    "GannBoxPriceLevel",
    "GannBoxTimeLevel",
    "GannCoordinate",
    "GannFanGeometryRequest",
    "GannFanGeometrySnapshot",
    "GannFanRay",
    "HeadShouldersOrientation",
    "HeadShouldersPatternGeometryRequest",
    "HeadShouldersPatternGeometrySnapshot",
    "ParallelChannelBar",
    "ParallelChannelGeometryRequest",
    "ParallelChannelGeometrySnapshot",
    "SwingAnchor",
    "SwingAnchorBar",
    "SwingAnchorRequest",
    "SwingAnchorSnapshot",
    "ThreeDrivesOrientation",
    "ThreeDrivesPatternGeometryRequest",
    "ThreeDrivesPatternGeometrySnapshot",
    "TriangleApexRelation",
    "TrianglePatternGeometryRequest",
    "TrianglePatternGeometrySnapshot",
    "VolumeProfileBar",
    "VolumeProfileGeometryRequest",
    "VolumeProfileGeometrySnapshot",
    "VolumeProfileRow",
    "XABCDPatternGeometryRequest",
    "XABCDPatternGeometrySnapshot",
    "XABCDSequenceKind",
    "compute_abcd_pattern_geometry",
    "compute_anchored_vwap_path",
    "compute_cypher_pattern_geometry",
    "compute_elliott_correction_wave_geometry",
    "compute_elliott_impulse_wave_geometry",
    "compute_fibonacci_trend_extension",
    "compute_gann_box_geometry",
    "compute_gann_fan_geometry",
    "compute_head_shoulders_pattern_geometry",
    "compute_parallel_channel_geometry",
    "compute_swing_anchors",
    "compute_three_drives_pattern_geometry",
    "compute_triangle_pattern_geometry",
    "compute_volume_profile_geometry",
    "compute_xabcd_pattern_geometry",
)


def __getattr__(name: str) -> object:
    """Load the historical V1A facade only when one of its names is requested."""

    if name in {
        "ABCDPatternGeometryRequest",
        "ABCDPatternGeometrySnapshot",
        "ABCDSequenceKind",
        "compute_abcd_pattern_geometry",
    }:
        from .abcd_pattern_geometry import (
            ABCDPatternGeometryRequest,
            ABCDPatternGeometrySnapshot,
            ABCDSequenceKind,
            compute_abcd_pattern_geometry,
        )

        return {
            "ABCDPatternGeometryRequest": ABCDPatternGeometryRequest,
            "ABCDPatternGeometrySnapshot": ABCDPatternGeometrySnapshot,
            "ABCDSequenceKind": ABCDSequenceKind,
            "compute_abcd_pattern_geometry": compute_abcd_pattern_geometry,
        }[name]
    if name in {
        "XABCDPatternGeometryRequest",
        "XABCDPatternGeometrySnapshot",
        "XABCDSequenceKind",
        "compute_xabcd_pattern_geometry",
    }:
        from .xabcd_pattern_geometry import (
            XABCDPatternGeometryRequest,
            XABCDPatternGeometrySnapshot,
            XABCDSequenceKind,
            compute_xabcd_pattern_geometry,
        )

        return {
            "XABCDPatternGeometryRequest": XABCDPatternGeometryRequest,
            "XABCDPatternGeometrySnapshot": XABCDPatternGeometrySnapshot,
            "XABCDSequenceKind": XABCDSequenceKind,
            "compute_xabcd_pattern_geometry": compute_xabcd_pattern_geometry,
        }[name]
    if name in {
        "CypherPatternGeometryRequest",
        "CypherPatternGeometrySnapshot",
        "CypherSequenceKind",
        "compute_cypher_pattern_geometry",
    }:
        from .cypher_pattern_geometry import (
            CypherPatternGeometryRequest,
            CypherPatternGeometrySnapshot,
            CypherSequenceKind,
            compute_cypher_pattern_geometry,
        )

        return {
            "CypherPatternGeometryRequest": CypherPatternGeometryRequest,
            "CypherPatternGeometrySnapshot": CypherPatternGeometrySnapshot,
            "CypherSequenceKind": CypherSequenceKind,
            "compute_cypher_pattern_geometry": compute_cypher_pattern_geometry,
        }[name]
    if name in {
        "ThreeDrivesOrientation",
        "ThreeDrivesPatternGeometryRequest",
        "ThreeDrivesPatternGeometrySnapshot",
        "compute_three_drives_pattern_geometry",
    }:
        from .three_drives_pattern_geometry import (
            ThreeDrivesOrientation,
            ThreeDrivesPatternGeometryRequest,
            ThreeDrivesPatternGeometrySnapshot,
            compute_three_drives_pattern_geometry,
        )

        return {
            "ThreeDrivesOrientation": ThreeDrivesOrientation,
            "ThreeDrivesPatternGeometryRequest": ThreeDrivesPatternGeometryRequest,
            "ThreeDrivesPatternGeometrySnapshot": ThreeDrivesPatternGeometrySnapshot,
            "compute_three_drives_pattern_geometry": compute_three_drives_pattern_geometry,
        }[name]
    if name in {
        "ElliottImpulseOrientation",
        "ElliottImpulseWaveGeometryRequest",
        "ElliottImpulseWaveGeometrySnapshot",
        "compute_elliott_impulse_wave_geometry",
    }:
        from .elliott_impulse_wave_geometry import (
            ElliottImpulseOrientation,
            ElliottImpulseWaveGeometryRequest,
            ElliottImpulseWaveGeometrySnapshot,
            compute_elliott_impulse_wave_geometry,
        )

        return {
            "ElliottImpulseOrientation": ElliottImpulseOrientation,
            "ElliottImpulseWaveGeometryRequest": ElliottImpulseWaveGeometryRequest,
            "ElliottImpulseWaveGeometrySnapshot": ElliottImpulseWaveGeometrySnapshot,
            "compute_elliott_impulse_wave_geometry": compute_elliott_impulse_wave_geometry,
        }[name]
    if name in {
        "ElliottCorrectionOrientation",
        "ElliottCorrectionWaveGeometryRequest",
        "ElliottCorrectionWaveGeometrySnapshot",
        "compute_elliott_correction_wave_geometry",
    }:
        from .elliott_correction_wave_geometry import (
            ElliottCorrectionOrientation,
            ElliottCorrectionWaveGeometryRequest,
            ElliottCorrectionWaveGeometrySnapshot,
            compute_elliott_correction_wave_geometry,
        )

        return {
            "ElliottCorrectionOrientation": ElliottCorrectionOrientation,
            "ElliottCorrectionWaveGeometryRequest": ElliottCorrectionWaveGeometryRequest,
            "ElliottCorrectionWaveGeometrySnapshot": ElliottCorrectionWaveGeometrySnapshot,
            "compute_elliott_correction_wave_geometry": compute_elliott_correction_wave_geometry,
        }[name]
    if name in {
        "HeadShouldersOrientation",
        "HeadShouldersPatternGeometryRequest",
        "HeadShouldersPatternGeometrySnapshot",
        "compute_head_shoulders_pattern_geometry",
    }:
        from .head_shoulders_pattern_geometry import (
            HeadShouldersOrientation,
            HeadShouldersPatternGeometryRequest,
            HeadShouldersPatternGeometrySnapshot,
            compute_head_shoulders_pattern_geometry,
        )

        return {
            "HeadShouldersOrientation": HeadShouldersOrientation,
            "HeadShouldersPatternGeometryRequest": HeadShouldersPatternGeometryRequest,
            "HeadShouldersPatternGeometrySnapshot": HeadShouldersPatternGeometrySnapshot,
            "compute_head_shoulders_pattern_geometry": compute_head_shoulders_pattern_geometry,
        }[name]
    if name in {
        "TriangleApexRelation",
        "TrianglePatternGeometryRequest",
        "TrianglePatternGeometrySnapshot",
        "compute_triangle_pattern_geometry",
    }:
        from .triangle_pattern_geometry import (
            TriangleApexRelation,
            TrianglePatternGeometryRequest,
            TrianglePatternGeometrySnapshot,
            compute_triangle_pattern_geometry,
        )

        return {
            "TriangleApexRelation": TriangleApexRelation,
            "TrianglePatternGeometryRequest": TrianglePatternGeometryRequest,
            "TrianglePatternGeometrySnapshot": TrianglePatternGeometrySnapshot,
            "compute_triangle_pattern_geometry": compute_triangle_pattern_geometry,
        }[name]
    if name in {
        "SwingAnchor",
        "SwingAnchorBar",
        "SwingAnchorRequest",
        "SwingAnchorSnapshot",
        "compute_swing_anchors",
    }:
        from .swing_anchors import (
            SwingAnchor,
            SwingAnchorBar,
            SwingAnchorRequest,
            SwingAnchorSnapshot,
            compute_swing_anchors,
        )

        return {
            "SwingAnchor": SwingAnchor,
            "SwingAnchorBar": SwingAnchorBar,
            "SwingAnchorRequest": SwingAnchorRequest,
            "SwingAnchorSnapshot": SwingAnchorSnapshot,
            "compute_swing_anchors": compute_swing_anchors,
        }[name]
    if name in {
        "GannAngleRatio",
        "GannFanGeometryRequest",
        "GannFanGeometrySnapshot",
        "GannFanRay",
        "compute_gann_fan_geometry",
    }:
        from .gann_fan_geometry import (
            GannAngleRatio,
            GannFanGeometryRequest,
            GannFanGeometrySnapshot,
            GannFanRay,
            compute_gann_fan_geometry,
        )

        return {
            "GannAngleRatio": GannAngleRatio,
            "GannFanGeometryRequest": GannFanGeometryRequest,
            "GannFanGeometrySnapshot": GannFanGeometrySnapshot,
            "GannFanRay": GannFanRay,
            "compute_gann_fan_geometry": compute_gann_fan_geometry,
        }[name]
    if name in {
        "GannBoxGeometryRequest",
        "GannBoxGeometrySnapshot",
        "GannBoxPriceLevel",
        "GannBoxTimeLevel",
        "GannCoordinate",
        "compute_gann_box_geometry",
    }:
        from .gann_box_geometry import (
            GannBoxGeometryRequest,
            GannBoxGeometrySnapshot,
            GannBoxPriceLevel,
            GannBoxTimeLevel,
            GannCoordinate,
            compute_gann_box_geometry,
        )

        return {
            "GannBoxGeometryRequest": GannBoxGeometryRequest,
            "GannBoxGeometrySnapshot": GannBoxGeometrySnapshot,
            "GannBoxPriceLevel": GannBoxPriceLevel,
            "GannBoxTimeLevel": GannBoxTimeLevel,
            "GannCoordinate": GannCoordinate,
            "compute_gann_box_geometry": compute_gann_box_geometry,
        }[name]
    if name in {
        "VolumeProfileBar",
        "VolumeProfileGeometryRequest",
        "VolumeProfileGeometrySnapshot",
        "VolumeProfileRow",
        "compute_volume_profile_geometry",
    }:
        from .volume_profile_geometry import (
            VolumeProfileBar,
            VolumeProfileGeometryRequest,
            VolumeProfileGeometrySnapshot,
            VolumeProfileRow,
            compute_volume_profile_geometry,
        )

        return {
            "VolumeProfileBar": VolumeProfileBar,
            "VolumeProfileGeometryRequest": VolumeProfileGeometryRequest,
            "VolumeProfileGeometrySnapshot": VolumeProfileGeometrySnapshot,
            "VolumeProfileRow": VolumeProfileRow,
            "compute_volume_profile_geometry": compute_volume_profile_geometry,
        }[name]
    if name in {
        "FibonacciTrendExtensionLevel",
        "FibonacciTrendExtensionRequest",
        "FibonacciTrendExtensionSnapshot",
        "compute_fibonacci_trend_extension",
    }:
        from .fibonacci_trend_extension_geometry import (
            FibonacciTrendExtensionLevel,
            FibonacciTrendExtensionRequest,
            FibonacciTrendExtensionSnapshot,
            compute_fibonacci_trend_extension,
        )

        return {
            "FibonacciTrendExtensionLevel": FibonacciTrendExtensionLevel,
            "FibonacciTrendExtensionRequest": FibonacciTrendExtensionRequest,
            "FibonacciTrendExtensionSnapshot": FibonacciTrendExtensionSnapshot,
            "compute_fibonacci_trend_extension": compute_fibonacci_trend_extension,
        }[name]
    if name in {
        "ParallelChannelBar",
        "ParallelChannelGeometryRequest",
        "ParallelChannelGeometrySnapshot",
        "compute_parallel_channel_geometry",
    }:
        from .parallel_channel_geometry import (
            ParallelChannelBar,
            ParallelChannelGeometryRequest,
            ParallelChannelGeometrySnapshot,
            compute_parallel_channel_geometry,
        )

        return {
            "ParallelChannelBar": ParallelChannelBar,
            "ParallelChannelGeometryRequest": ParallelChannelGeometryRequest,
            "ParallelChannelGeometrySnapshot": ParallelChannelGeometrySnapshot,
            "compute_parallel_channel_geometry": compute_parallel_channel_geometry,
        }[name]
    if name in {
        "AnchoredVWAPPathRequest",
        "AnchoredVWAPPathSnapshot",
        "AnchoredVWAPPoint",
        "compute_anchored_vwap_path",
    }:
        from .anchored_vwap_path import (
            AnchoredVWAPPathRequest,
            AnchoredVWAPPathSnapshot,
            AnchoredVWAPPoint,
            compute_anchored_vwap_path,
        )

        return {
            "AnchoredVWAPPathRequest": AnchoredVWAPPathRequest,
            "AnchoredVWAPPathSnapshot": AnchoredVWAPPathSnapshot,
            "AnchoredVWAPPoint": AnchoredVWAPPoint,
            "compute_anchored_vwap_path": compute_anchored_vwap_path,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
