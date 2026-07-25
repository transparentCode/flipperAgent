from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.trendlines import run_trendline_pipeline
from app.trendlines.boundary import Ray, build_boundary_result_from_trendline_result
from app.trendlines.boundary.adapters import _detect_boundary_interaction


def _make_ray(level: float, *, is_support: bool, score: float) -> Ray:
    start_time = pd.Timestamp("2026-01-01T00:00:00Z")
    end_time = pd.Timestamp("2026-01-01T04:00:00Z")
    return Ray(
        start_time=start_time,
        end_time=end_time,
        start_price=level,
        end_price=level,
        slope=0.0,
        intercept=level,
        touch_count=3,
        is_support=is_support,
        kernel="trendlines:pathfinding",
        score=score,
        r_squared=0.9,
        metadata={"source": "trendlines"},
    )


def _make_indexed_pipeline_frame() -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=9, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "open": [9.2, 10.1, 9.4, 11.0, 10.3, 12.0, 11.4, 13.0, 12.4],
            "high": [10.0, 11.2, 10.6, 12.4, 11.8, 13.6, 12.8, 14.7, 13.9],
            "low": [8.5, 9.1, 8.2, 9.8, 9.0, 10.5, 9.8, 11.2, 10.7],
            "close": [9.6, 10.4, 9.7, 11.3, 10.6, 12.3, 11.8, 13.4, 12.9],
        },
        index=index,
    )


@pytest.mark.parametrize(
    ("price", "support_rays", "resistance_rays", "hull_floor", "hull_ceiling", "expected"),
    [
        (99.0, [], [], 100.0, np.nan, "STRUCTURAL_BREAKDOWN"),
        (111.0, [], [], np.nan, 110.0, "STRUCTURAL_BREAKOUT"),
        (
            100.1,
            [_make_ray(99.4, is_support=True, score=0.4), _make_ray(100.0, is_support=True, score=0.9)],
            [],
            95.0,
            120.0,
            "GEOMETRIC_BOUNCE_SUPPORT",
        ),
        (
            109.9,
            [],
            [_make_ray(110.6, is_support=False, score=0.4), _make_ray(110.0, is_support=False, score=0.9)],
            90.0,
            120.0,
            "GEOMETRIC_BOUNCE_RESISTANCE",
        ),
        (
            105.0,
            [_make_ray(100.0, is_support=True, score=0.9)],
            [_make_ray(110.0, is_support=False, score=0.9)],
            95.0,
            115.0,
            "NONE",
        ),
    ],
)
def test_detect_boundary_interaction_classifies_all_outcomes(
    price: float,
    support_rays: list[Ray],
    resistance_rays: list[Ray],
    hull_floor: float,
    hull_ceiling: float,
    expected: str,
):
    interaction = _detect_boundary_interaction(
        price,
        support_rays,
        resistance_rays,
        hull_floor,
        hull_ceiling,
        np.ones(5, dtype=float),
        interaction_tolerance_atr=0.25,
    )

    assert interaction == expected


def test_build_boundary_result_from_fractal_pathfinding_pipeline():
    frame = _make_indexed_pipeline_frame()
    trendline_result = run_trendline_pipeline(
        frame,
        extractor="fractal",
        fitter="pathfinding",
        extractor_kwargs={"window_left": 1, "window_right": 1},
        fitter_kwargs={"pivot_window": 1},
    )

    boundary_result = build_boundary_result_from_trendline_result(
        frame,
        asset="BTCUSDT",
        timeframe="1h",
        trendline_result=trendline_result,
    )

    assert trendline_result.is_valid is True
    assert boundary_result.is_valid is True
    assert boundary_result.interaction == "NONE"
    assert boundary_result.best_support is not None
    assert boundary_result.best_resistance is not None
    assert boundary_result.best_support.metadata["extractor"] == "fractal"
    assert boundary_result.best_resistance.metadata["extractor"] == "fractal"
    assert boundary_result.metadata["trendlines"]["pipeline"]["extractor"] == "fractal"
    assert boundary_result.metadata["trendlines"]["pipeline"]["fitter"] == "pathfinding"
