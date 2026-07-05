from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.trendlines import TrendlinePipelineConfig
from app.trendlines.boundary import (
    BoundaryResult,
    TouchDeclusterConfig,
    build_boundary_result_from_trendline_result,
    decluster_touch_indices,
    trendline_to_boundary_ray,
)
from app.trendlines.contracts import Trendline, TrendlineFitResult


def _make_boundary_frame() -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=6, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
            "high": [101.0, 102.5, 103.5, 104.5, 105.0, 106.0],
            "low": [99.0, 100.5, 101.0, 102.0, 103.0, 104.0],
            "close": [100.5, 101.5, 102.8, 103.7, 104.4, 105.4],
        },
        index=index,
    )


def test_boundary_adapter_exports_are_stable():
    frame = _make_boundary_frame()
    support = Trendline(
        start_index=0,
        end_index=4,
        start_value=99.0,
        end_value=103.0,
        slope=1.0,
        intercept=99.0,
        touch_count=3,
        is_support=True,
        method="pathfinding",
        score=0.8,
        metadata={"r_squared": 0.9},
    )
    resistance = Trendline(
        start_index=1,
        end_index=5,
        start_value=102.5,
        end_value=106.0,
        slope=0.875,
        intercept=101.625,
        touch_count=2,
        is_support=False,
        method="pathfinding",
        score=0.7,
        metadata={"r_squared": 0.85},
    )
    fit_result = TrendlineFitResult(
        support_lines=[support],
        resistance_lines=[resistance],
        is_valid=True,
        metadata={
            "created_at": datetime.now(timezone.utc).isoformat(),
            "pipeline": {"extractor": "fractal", "fitter": "pathfinding"},
        },
    )

    support_ray = trendline_to_boundary_ray(support, index=frame.index, extractor_name="fractal")
    boundary_result = build_boundary_result_from_trendline_result(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        trendline_result=fit_result,
    )
    diagnostics = decluster_touch_indices([1, 2, 4], TouchDeclusterConfig(min_bars_between_touches=2))

    assert support_ray.is_support is True
    assert support_ray.metadata["extractor"] == "fractal"
    assert isinstance(boundary_result, BoundaryResult)
    assert boundary_result.best_support is not None
    assert boundary_result.best_resistance is not None
    assert boundary_result.quality_metrics is not None
    assert boundary_result.best_support.metadata["extractor"] == "fractal"
    assert diagnostics.raw_touch_count == 3
    assert diagnostics.effective_touch_indices == (1, 4)


def test_boundary_adapter_reads_boundary_params_from_config():
    frame = _make_boundary_frame()
    support = Trendline(
        start_index=0,
        end_index=4,
        start_value=99.0,
        end_value=103.0,
        slope=1.0,
        intercept=99.0,
        touch_count=3,
        is_support=True,
        method="pathfinding",
        score=0.8,
        metadata={"r_squared": 0.9},
    )
    resistance = Trendline(
        start_index=1,
        end_index=5,
        start_value=102.5,
        end_value=106.0,
        slope=0.875,
        intercept=101.625,
        touch_count=2,
        is_support=False,
        method="pathfinding",
        score=0.7,
        metadata={"r_squared": 0.85},
    )
    fit_result = TrendlineFitResult(
        support_lines=[support],
        resistance_lines=[resistance],
        is_valid=True,
        metadata={"pipeline": {"extractor": "fractal", "fitter": "pathfinding"}},
    )
    config = TrendlinePipelineConfig(
        boundary_params={"atr_window": 5, "interaction_tolerance_atr": 0.2}
    )

    boundary_result = build_boundary_result_from_trendline_result(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        trendline_result=fit_result,
        trendline_config=config,
    )

    assert boundary_result.metadata["trendlines"]["adapter"] == {
        "atr_window": 5,
        "interaction_tolerance_atr": 0.2,
    }
    assert boundary_result.metadata["trendlines"]["config"]["boundary_params"] == {
        "atr_window": 5,
        "interaction_tolerance_atr": 0.2,
    }