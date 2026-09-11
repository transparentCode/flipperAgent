import importlib
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from types import MappingProxyType

import pytest

from libs.analysis_capabilities import (
    get_analysis_invocation_spec,
    list_analysis_capabilities,
    list_analysis_invocation_specs,
)

ROOT = Path(__file__).resolve().parents[2]

_EXPECTED = {
    "model.regression": (
        "regression.context.v1",
        "libs.analysis_capabilities.execution.regression.RegressionExecutionRequest",
        "libs.regression.contracts.RegressionContextSnapshot",
        ("frame", "asset", "timeframe", "config", "channel_config"),
        ("channel_config_hash", "source_config_hash", "window_size"),
        "stateless",
        "native_result_observed_through",
        "native_partial",
        (),
    ),
    "model.sr": (
        "sr.engine.step.schema.1.0",
        "libs.analysis_capabilities.execution.sr.SRExecutionRequest",
        "libs.analysis_capabilities.execution.sr.SRExecutionResult",
        ("previous_state", "closed_bar", "resolved_config"),
        ("resolved_config_hash",),
        "caller_threaded",
        "last_closed_bar",
        "native_partial",
        (),
    ),
    "model.trendlines": (
        "trendlines.geometry.v2",
        "libs.analysis_capabilities.execution.trendlines.TrendlinesExecutionRequest",
        "libs.models.trendlines.TrendlineSnapshot",
        ("history",),
        ("history_capacity_bars", "pivot_window"),
        "stateless",
        "last_closed_bar",
        "source_attested",
        (),
    ),
    "ta.fibonacci_geometry": (
        "fibonacci.two_point_linear.v1",
        "libs.analysis_capabilities.ta.fibonacci_geometry.FibonacciGeometryRequest",
        "libs.analysis_capabilities.ta.fibonacci_geometry.FibonacciGeometrySnapshot",
        (
            "start_anchor",
            "end_anchor",
            "market_as_of",
            "retracement_ratios",
            "extension_ratios",
        ),
        ("retracement_ratios", "extension_ratios"),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        (),
    ),
    "ta.swing_anchors": (
        "swing_anchors.strict_confirmed.v1",
        "libs.analysis_capabilities.ta.swing_anchors.SwingAnchorRequest",
        "libs.analysis_capabilities.ta.swing_anchors.SwingAnchorSnapshot",
        ("bars", "span"),
        ("span",),
        "stateless",
        "last_closed_bar",
        "source_attested",
        (),
    ),
    "ta.traditional_pivot_geometry": (
        "pivot.traditional.v1",
        "libs.analysis_capabilities.ta.traditional_pivot_geometry.TraditionalPivotGeometryRequest",
        "libs.analysis_capabilities.ta.traditional_pivot_geometry.TraditionalPivotGeometrySnapshot",
        ("reference", "market_as_of"),
        (),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        (),
    ),
    "ta.vwap_geometry": (
        "vwap.explicit_range_hlc3.v1",
        "libs.analysis_capabilities.ta.vwap_geometry.VWAPGeometryRequest",
        "libs.analysis_capabilities.ta.vwap_geometry.VWAPGeometrySnapshot",
        ("bars", "market_as_of"),
        (),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        ("volume_unit",),
    ),
    "ta.anchored_vwap_path": (
        "vwap.anchored_path_hlc3.v1",
        "libs.analysis_capabilities.ta.anchored_vwap_path.AnchoredVWAPPathRequest",
        "libs.analysis_capabilities.ta.anchored_vwap_path.AnchoredVWAPPathSnapshot",
        ("bars", "market_as_of"),
        (),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        ("volume_unit",),
    ),
    "ta.fibonacci_trend_extension_geometry": (
        "fibonacci.three_point_trend_extension.v1",
        "libs.analysis_capabilities.ta.fibonacci_trend_extension_geometry.FibonacciTrendExtensionRequest",
        "libs.analysis_capabilities.ta.fibonacci_trend_extension_geometry.FibonacciTrendExtensionSnapshot",
        (
            "start_anchor",
            "impulse_end_anchor",
            "retracement_anchor",
            "market_as_of",
            "extension_ratios",
        ),
        ("extension_ratios",),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        (),
    ),
    "ta.parallel_channel_geometry": (
        "parallel_channel.swing_three_anchor.v1",
        "libs.analysis_capabilities.ta.parallel_channel_geometry.ParallelChannelGeometryRequest",
        "libs.analysis_capabilities.ta.parallel_channel_geometry.ParallelChannelGeometrySnapshot",
        (
            "bars",
            "start_anchor",
            "end_anchor",
            "offset_anchor",
            "market_as_of",
        ),
        (),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        (),
    ),
    "ta.gann_box_geometry": (
        "gann.box.bar_price_grid.v1",
        "libs.analysis_capabilities.ta.gann_box_geometry.GannBoxGeometryRequest",
        "libs.analysis_capabilities.ta.gann_box_geometry.GannBoxGeometrySnapshot",
        (
            "bars",
            "start",
            "end",
            "price_levels",
            "time_levels",
            "market_as_of",
        ),
        ("price_levels", "time_levels"),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        (),
    ),
    "ta.gann_fan_geometry": (
        "gann.fan.bar_scale.v1",
        "libs.analysis_capabilities.ta.gann_fan_geometry.GannFanGeometryRequest",
        "libs.analysis_capabilities.ta.gann_fan_geometry.GannFanGeometrySnapshot",
        (
            "bars",
            "anchor",
            "price_per_bar",
            "angle_ratios",
            "market_as_of",
        ),
        ("angle_ratios", "price_per_bar"),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        (),
    ),
    "ta.volume_profile_geometry": (
        "volume_profile.explicit_range_uniform_overlap.v1",
        "libs.analysis_capabilities.ta.volume_profile_geometry.VolumeProfileGeometryRequest",
        "libs.analysis_capabilities.ta.volume_profile_geometry.VolumeProfileGeometrySnapshot",
        ("bars", "market_as_of", "row_count", "value_area_fraction"),
        ("row_count", "value_area_fraction"),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        ("volume_unit",),
    ),
    "ta.abcd_pattern_geometry": (
        "pattern.abcd.explicit_four_anchor.v1",
        "libs.analysis_capabilities.ta.abcd_pattern_geometry.ABCDPatternGeometryRequest",
        "libs.analysis_capabilities.ta.abcd_pattern_geometry.ABCDPatternGeometrySnapshot",
        ("bars", "a", "b", "c", "d", "market_as_of"),
        (),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        (),
    ),
    "ta.xabcd_pattern_geometry": (
        "pattern.xabcd.explicit_five_anchor.v1",
        "libs.analysis_capabilities.ta.xabcd_pattern_geometry.XABCDPatternGeometryRequest",
        "libs.analysis_capabilities.ta.xabcd_pattern_geometry.XABCDPatternGeometrySnapshot",
        ("bars", "x", "a", "b", "c", "d", "market_as_of"),
        (),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        (),
    ),
    "ta.head_shoulders_pattern_geometry": (
        "pattern.head_shoulders.explicit_five_anchor_neckline.v1",
        "libs.analysis_capabilities.ta.head_shoulders_pattern_geometry.HeadShouldersPatternGeometryRequest",
        "libs.analysis_capabilities.ta.head_shoulders_pattern_geometry.HeadShouldersPatternGeometrySnapshot",
        (
            "bars",
            "left_shoulder",
            "neck_left",
            "head",
            "neck_right",
            "right_shoulder",
            "market_as_of",
        ),
        (),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        (),
    ),
    "ta.triangle_pattern_geometry": (
        "pattern.triangle.explicit_four_anchor_boundaries.v1",
        "libs.analysis_capabilities.ta.triangle_pattern_geometry.TrianglePatternGeometryRequest",
        "libs.analysis_capabilities.ta.triangle_pattern_geometry.TrianglePatternGeometrySnapshot",
        ("bars", "a", "b", "c", "d", "market_as_of"),
        (),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        (),
    ),
    "ta.cypher_pattern_geometry": (
        "pattern.cypher.explicit_five_anchor_measurements.v1",
        "libs.analysis_capabilities.ta.cypher_pattern_geometry.CypherPatternGeometryRequest",
        "libs.analysis_capabilities.ta.cypher_pattern_geometry.CypherPatternGeometrySnapshot",
        ("bars", "x", "a", "b", "c", "d", "market_as_of"),
        (),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        (),
    ),
    "ta.three_drives_pattern_geometry": (
        "pattern.three_drives.explicit_six_anchor.v1",
        "libs.analysis_capabilities.ta.three_drives_pattern_geometry.ThreeDrivesPatternGeometryRequest",
        "libs.analysis_capabilities.ta.three_drives_pattern_geometry.ThreeDrivesPatternGeometrySnapshot",
        (
            "bars",
            "start",
            "drive1",
            "retrace_a",
            "drive2",
            "retrace_c",
            "drive3",
            "market_as_of",
        ),
        (),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        (),
    ),
    "ta.elliott_impulse_wave_geometry": (
        "pattern.elliott_impulse.explicit_six_anchor.v1",
        "libs.analysis_capabilities.ta.elliott_impulse_wave_geometry.ElliottImpulseWaveGeometryRequest",
        "libs.analysis_capabilities.ta.elliott_impulse_wave_geometry.ElliottImpulseWaveGeometrySnapshot",
        (
            "bars",
            "start",
            "wave1",
            "wave2",
            "wave3",
            "wave4",
            "wave5",
            "market_as_of",
        ),
        (),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        (),
    ),
    "ta.elliott_correction_wave_geometry": (
        "pattern.elliott_correction.explicit_four_anchor.v1",
        "libs.analysis_capabilities.ta.elliott_correction_wave_geometry.ElliottCorrectionWaveGeometryRequest",
        "libs.analysis_capabilities.ta.elliott_correction_wave_geometry.ElliottCorrectionWaveGeometrySnapshot",
        (
            "bars",
            "start",
            "wave_a",
            "wave_b",
            "wave_c",
            "market_as_of",
        ),
        (),
        "stateless",
        "explicit_request_cutoff",
        "source_attested",
        (),
    ),
}


def _load_qualified(path: str) -> type:
    module_name, class_name = path.rsplit(".", 1)
    return getattr(importlib.import_module(module_name), class_name)


def test_specs_are_exactly_one_to_one_with_catalog_in_id_order() -> None:
    catalog_ids = tuple(entry.capability_id for entry in list_analysis_capabilities())
    specs = list_analysis_invocation_specs()

    assert catalog_ids == tuple(sorted(_EXPECTED))
    assert tuple(spec.capability_id for spec in specs) == catalog_ids
    assert set(_EXPECTED) == set(catalog_ids)


@pytest.mark.parametrize("capability_id", tuple(sorted(_EXPECTED)))
def test_spec_fields_and_versions_are_exact(capability_id: str) -> None:
    spec = get_analysis_invocation_spec(capability_id)
    expected = _EXPECTED[capability_id]

    assert (
        spec.method_version,
        spec.request_contract,
        spec.result_contract,
        spec.request_fields,
        spec.parameter_fields,
        spec.state_mode,
        spec.cutoff_mode,
        spec.identity_mode,
        spec.required_source_fields,
    ) == expected

    request_type = _load_qualified(spec.request_contract)
    assert tuple(field.name for field in fields(request_type)) == spec.request_fields
    assert hasattr(spec, "__slots__")
    with pytest.raises(FrozenInstanceError):
        spec.method_version = "changed"  # type: ignore[misc]


def test_only_sr_threads_state_and_volume_paths_require_volume_unit() -> None:
    specs = list_analysis_invocation_specs()
    assert tuple(
        spec.capability_id for spec in specs if spec.state_mode == "caller_threaded"
    ) == ("model.sr",)
    assert tuple(
        spec.capability_id for spec in specs if spec.required_source_fields
    ) == (
        "ta.anchored_vwap_path",
        "ta.volume_profile_geometry",
        "ta.vwap_geometry",
    )


def test_specs_are_immutable_and_executor_has_no_mutable_callable_registry() -> None:
    from libs.analysis_capabilities import invocation_spec
    from libs.analysis_capabilities.invocation import executor

    assert isinstance(invocation_spec._SPECS_BY_ID, MappingProxyType)
    with pytest.raises(TypeError):
        invocation_spec._SPECS_BY_ID["model.fake"] = object()  # type: ignore[index]
    assert not hasattr(executor, "_EXECUTORS")


def test_metadata_root_and_specs_are_fresh_process_import_isolated() -> None:
    script = """
import sys
from libs.analysis_capabilities import list_analysis_invocation_specs

assert len(list_analysis_invocation_specs()) == 21
assert 'libs.analysis_capabilities.execution' not in sys.modules
assert not any(
    name.startswith((
        'libs.models.',
        'libs.regression.',
        'libs.analysis_capabilities.ta',
        'numpy',
        'pandas',
        'apps.',
    ))
    for name in sys.modules
)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
