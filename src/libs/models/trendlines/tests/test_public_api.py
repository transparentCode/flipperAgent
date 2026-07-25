from pathlib import Path

import numpy as np

import app.trendlines as compatibility
import libs.models.trendlines as canonical

from app.trendlines import PivotSet, Trendline, TrendlineFitResult, run_trendline_pipeline
from app.trendlines.pivots.rdp_zigzag import RDPZigZagPivotExtractor


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
    new_root = Path(canonical.__file__).resolve().parent

    assert new_root.name == "trendlines"
    assert new_root.parent.name == "models"

    for name in (
        "TrendlinePipelineConfig",
        "PivotSet",
        "Trendline",
        "TrendlineFitResult",
        "run_trendline_pipeline",
        "fit_trendlines",
        "fit_trendlines_to_boundary",
    ):
        assert getattr(canonical, name) is getattr(compatibility, name)
