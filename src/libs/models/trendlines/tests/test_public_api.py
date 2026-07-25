from pathlib import Path

import numpy as np

import libs.models.trendlines as canonical

from libs.models.trendlines import (
    PivotSet,
    Trendline,
    TrendlineFitResult,
    TrendlinePipelineConfig,
    fit_trendlines,
    fit_trendlines_to_boundary,
    run_trendline_pipeline,
)
from libs.models.trendlines.pivots.rdp_zigzag import RDPZigZagPivotExtractor


def test_public_contract_exports_are_stable():
    pivots = PivotSet(
        high_indices=np.array([1, 4]),
        high_values=np.array([10.0, 12.0]),
        low_indices=np.array([2, 5]),
        low_values=np.array([8.0, 9.0]),
    )
    line = Trendline(
        start_index=1,
        end_index=4,
        start_value=10.0,
        end_value=12.0,
        slope=2.0 / 3.0,
        intercept=10.0 - (2.0 / 3.0),
        touch_count=2,
        is_support=False,
        method="seed",
        score=0.75,
    )
    result = TrendlineFitResult(resistance_lines=[line], is_valid=True)

    assert pivots.is_valid()
    assert result.best_resistance is line
    assert line.project(3) == line.value_at(7)
    assert RDPZigZagPivotExtractor.__name__ == "RDPZigZagPivotExtractor"
    assert callable(run_trendline_pipeline)
    package_root = Path(__file__).resolve().parents[1]

    assert Path(canonical.__file__).resolve().is_relative_to(package_root)

    for value in (
        TrendlinePipelineConfig,
        PivotSet,
        Trendline,
        TrendlineFitResult,
        RDPZigZagPivotExtractor,
        run_trendline_pipeline,
        fit_trendlines,
        fit_trendlines_to_boundary,
    ):
        module_name = value.__module__
        assert module_name == "libs.models.trendlines" or module_name.startswith(
            "libs.models.trendlines."
        ), (value, module_name)
