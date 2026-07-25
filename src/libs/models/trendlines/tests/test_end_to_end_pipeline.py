"""End-to-end integration test exercising Stages 1-5 of the trendlines pipeline.

Covers: Extract -> Fit -> Orchestrate -> Adapt -> Signal in a single chain.
"""

import numpy as np
import pandas as pd

from libs.models.trendlines import run_trendline_pipeline
from libs.models.trendlines.boundary.adapters import build_boundary_result_from_trendline_result
from libs.models.trendlines.boundary.contracts import BoundaryResult, Ray
from libs.models.trendlines.signals.orchestrator import TrendlineSignalOrchestrator


def _make_ohlcv_frame(n_bars: int = 60) -> pd.DataFrame:
    """Generate a synthetic OHLCV frame with a slight upward trend and noise."""

    rng = np.random.default_rng(42)
    base = 100.0 + np.linspace(0, 10, n_bars) + rng.normal(0, 1.5, n_bars)
    highs = base + rng.uniform(0.5, 2.0, n_bars)
    lows = base - rng.uniform(0.5, 2.0, n_bars)
    opens = base + rng.uniform(-0.5, 0.5, n_bars)
    closes = base + rng.uniform(-0.5, 0.5, n_bars)

    index = pd.date_range("2025-01-01", periods=n_bars, freq="1h")
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes},
        index=index,
    )


def test_full_pipeline_extract_to_signals():
    """Run all 5 stages and verify contract shapes at each boundary."""

    df = _make_ohlcv_frame()

    # Stage 1+2+3: Extract -> Fit -> Orchestrate
    result = run_trendline_pipeline(
        df,
        extractor="fractal",
        fitter="pathfinding",
        extractor_kwargs={"window_left": 3, "window_right": 3},
        fitter_kwargs={"pivot_window": 3},
    )

    assert result.is_valid is True
    assert "pipeline" in result.metadata
    assert result.metadata["pipeline"]["extractor"] == "fractal"
    assert result.metadata["pipeline"]["fitter"] == "pathfinding"
    assert len(result.support_lines) + len(result.resistance_lines) > 0

    # Stage 4: Adapt -> BoundaryResult
    boundary = build_boundary_result_from_trendline_result(
        df,
        asset="TEST",
        timeframe="1h",
        trendline_result=result,
    )

    assert isinstance(boundary, BoundaryResult)
    assert boundary.asset == "TEST"
    assert boundary.timeframe == "1h"
    assert boundary.is_valid is True
    assert boundary.quality_metrics is not None

    total_rays = len(boundary.active_support_rays) + len(boundary.active_resistance_rays)
    assert total_rays > 0
    for ray in boundary.active_support_rays + boundary.active_resistance_rays:
        assert isinstance(ray, Ray)
        assert ray.kernel.startswith("trendlines:")
        assert ray.touch_count >= 1

    assert boundary.interaction in (
        "NONE",
        "STRUCTURAL_BREAKOUT",
        "STRUCTURAL_BREAKDOWN",
        "GEOMETRIC_BOUNCE_SUPPORT",
        "GEOMETRIC_BOUNCE_RESISTANCE",
    )

    # Stage 5: Signal extraction
    orchestrator = TrendlineSignalOrchestrator()
    output = orchestrator.run(boundary)

    assert "signals" in output
    assert "composite_direction" in output
    assert "composite_confidence" in output
    assert "signal_count" in output
    assert isinstance(output["signals"], list)
    assert isinstance(output["composite_direction"], float)
    assert isinstance(output["composite_confidence"], float)
    assert -1.0 <= output["composite_direction"] <= 1.0
    assert 0.0 <= output["composite_confidence"] <= 1.0


def test_full_pipeline_with_all_fitters():
    """Verify all registered fitters produce valid results through the full chain."""

    df = _make_ohlcv_frame()

    for fitter_name in ("pathfinding", "least_squares", "ransac"):
        result = run_trendline_pipeline(
            df,
            extractor="fractal",
            fitter=fitter_name,
            extractor_kwargs={"window_left": 3, "window_right": 3},
        )

        assert isinstance(result.is_valid, bool), f"{fitter_name}: is_valid not bool"
        assert result.metadata["pipeline"]["fitter"] == fitter_name

        if not result.is_valid:
            continue

        boundary = build_boundary_result_from_trendline_result(
            df, asset="TEST", timeframe="1h", trendline_result=result,
        )
        output = TrendlineSignalOrchestrator().run(boundary)
        assert isinstance(output["signal_count"], int), f"{fitter_name}: bad signal_count"


def test_full_pipeline_with_all_extractors():
    """Verify all registered extractors produce valid results through the full chain."""

    df = _make_ohlcv_frame()

    for extractor_name in ("fractal", "rdp_zigzag"):
        result = run_trendline_pipeline(
            df,
            extractor=extractor_name,
            fitter="pathfinding",
        )

        assert isinstance(result.is_valid, bool), f"{extractor_name}: is_valid not bool"
        assert result.metadata["pipeline"]["extractor"] == extractor_name

        if not result.is_valid:
            continue

        boundary = build_boundary_result_from_trendline_result(
            df, asset="TEST", timeframe="1h", trendline_result=result,
        )
        output = TrendlineSignalOrchestrator().run(boundary)
        assert isinstance(output["signal_count"], int), f"{extractor_name}: bad signal_count"


def test_boundary_result_serializes():
    """BoundaryResult.to_dict() produces a valid JSON-serializable dict."""

    import json

    df = _make_ohlcv_frame()
    result = run_trendline_pipeline(df, extractor="fractal", fitter="pathfinding")
    boundary = build_boundary_result_from_trendline_result(
        df, asset="TEST", timeframe="1h", trendline_result=result,
    )

    payload = boundary.to_dict()
    serialized = json.dumps(payload)
    assert len(serialized) > 0
    roundtrip = json.loads(serialized)
    assert roundtrip["asset"] == "TEST"
    assert roundtrip["timeframe"] == "1h"
