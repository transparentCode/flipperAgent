from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from app.trendlines.boundary import BoundaryResult, Ray
from app.trendlines.boundary.adapters import build_boundary_result_from_trendline_result
from app.trendlines.contracts import Trendline, TrendlineFitResult


def _line(*, is_support: bool = True) -> Trendline:
    return Trendline(
        start_index=0,
        end_index=9,
        start_value=100.0,
        end_value=101.0,
        slope=1.0 / 9.0,
        intercept=100.0,
        touch_count=2,
        is_support=is_support,
        method="test",
        score=0.5,
    )


def _flat_line(level: float, *, is_support: bool) -> Trendline:
    return Trendline(
        start_index=0,
        end_index=9,
        start_value=level,
        end_value=level,
        slope=0.0,
        intercept=level,
        touch_count=3,
        is_support=is_support,
        method="test",
        score=0.8,
    )


def _ray(*, is_support: bool = True) -> Ray:
    return Ray(
        start_time=pd.Timestamp("2026-01-01T00:00:00Z"),
        end_time=pd.Timestamp("2026-01-01T09:00:00Z"),
        start_price=100.0,
        end_price=101.0,
        slope=1.0 / 9.0,
        intercept=100.0,
        touch_count=2,
        is_support=is_support,
        score=0.5,
    )


def _frame() -> pd.DataFrame:
    close = np.linspace(100.0, 101.0, 10)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
        },
        index=pd.date_range("2026-01-01", periods=10, freq="h"),
    )


def _constant_channel_frame(close: float) -> pd.DataFrame:
    closes = np.full(10, close, dtype=float)
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes + 1.0,
            "low": closes - 1.0,
            "close": closes,
        },
        index=pd.date_range("2026-01-01", periods=10, freq="h"),
    )


def test_fit_result_exposes_one_sided_structure_without_changing_is_valid():
    result = TrendlineFitResult(
        support_lines=[_line(is_support=True)],
        resistance_lines=[],
        is_valid=True,
    )

    assert result.is_valid is True
    assert result.has_support is True
    assert result.has_resistance is False
    assert result.has_both_sides is False
    assert result.has_closed_channel is False
    assert result.is_one_sided_structure is True
    assert result.structure_state == "support_only"
    assert result.metadata["structure"]["structure_state"] == "support_only"
    assert result.to_dict()["structure_state"] == "support_only"


def test_fit_result_exposes_closed_channel_structure():
    result = TrendlineFitResult(
        support_lines=[_line(is_support=True)],
        resistance_lines=[_line(is_support=False)],
        is_valid=True,
    )

    assert result.has_both_sides is True
    assert result.has_closed_channel is True
    assert result.is_one_sided_structure is False
    assert result.structure_state == "closed_channel"


def test_boundary_result_exposes_structure_state_in_dict_and_metadata():
    support = _ray(is_support=True)
    resistance = _ray(is_support=False)
    result = BoundaryResult(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        active_support_rays=[support],
        active_resistance_rays=[resistance],
        convex_hull_floor=100.0,
        convex_hull_ceiling=102.0,
        is_valid=True,
    )

    as_dict = result.to_dict()

    assert result.has_closed_channel is True
    assert result.structure_state == "closed_channel"
    assert as_dict["has_both_sides"] is True
    assert as_dict["structure_state"] == "closed_channel"


def test_boundary_adapter_exposes_mid_channel_context():
    fit_result = TrendlineFitResult(
        support_lines=[_flat_line(100.0, is_support=True)],
        resistance_lines=[_flat_line(110.0, is_support=False)],
        is_valid=True,
    )

    boundary = build_boundary_result_from_trendline_result(
        _constant_channel_frame(105.0),
        asset="BTCUSDT",
        timeframe="1h",
        trendline_result=fit_result,
        interaction_tolerance_atr=0.25,
        atr_window=1,
    )
    as_dict = boundary.to_dict()

    assert boundary.market_position_state == "mid_channel_noise"
    assert boundary.is_inside_channel is True
    assert boundary.is_mid_channel_noise is True
    assert boundary.is_near_support is False
    assert boundary.is_near_resistance is False
    assert boundary.hull_position == 0.5
    assert boundary.best_support_quality == 0.8975
    assert boundary.best_resistance_quality == 0.8975
    assert boundary.mean_normalized_quality == 0.8975
    assert as_dict["market_position_state"] == "mid_channel_noise"
    assert as_dict["boundary_context"]["support_distance_atr"] == 2.5
    assert as_dict["support_rays"][0]["normalized_quality_score"] == 0.8975
    assert as_dict["quality_metrics"]["mean_normalized_quality"] == 0.8975
    assert boundary.metadata["normalized_quality"]["mean_normalized_quality"] == 0.8975


def test_boundary_adapter_exposes_near_support_and_channel_pressure_context():
    fit_result = TrendlineFitResult(
        support_lines=[_flat_line(100.0, is_support=True)],
        resistance_lines=[_flat_line(110.0, is_support=False)],
        is_valid=True,
    )

    boundary = build_boundary_result_from_trendline_result(
        _constant_channel_frame(100.25),
        asset="BTCUSDT",
        timeframe="1h",
        trendline_result=fit_result,
        interaction_tolerance_atr=0.25,
        atr_window=1,
    )

    assert boundary.market_position_state == "near_support"
    assert boundary.is_near_support is True
    assert boundary.has_lower_channel_pressure is True
    assert boundary.is_inside_channel is True
    assert boundary.boundary_context["support_distance_atr"] == 0.125
    assert boundary.best_support.quality_components["coverage_score"] == 1.0
    assert boundary.best_support.quality_components["touch_score"] == 0.75


def test_boundary_adapter_exposes_above_channel_context():
    fit_result = TrendlineFitResult(
        support_lines=[_flat_line(100.0, is_support=True)],
        resistance_lines=[_flat_line(110.0, is_support=False)],
        is_valid=True,
    )

    boundary = build_boundary_result_from_trendline_result(
        _constant_channel_frame(111.0),
        asset="BTCUSDT",
        timeframe="1h",
        trendline_result=fit_result,
        interaction_tolerance_atr=0.25,
        atr_window=1,
    )

    assert boundary.market_position_state == "above_channel"
    assert boundary.is_above_channel is True
    assert boundary.is_inside_channel is False
    assert boundary.interaction == "STRUCTURAL_BREAKOUT"


def test_boundary_adapter_preserves_fit_validity_but_marks_one_sided_structure():
    fit_result = TrendlineFitResult(
        support_lines=[_line(is_support=True)],
        resistance_lines=[],
        is_valid=True,
    )

    boundary = build_boundary_result_from_trendline_result(
        _frame(),
        asset="BTCUSDT",
        timeframe="1h",
        trendline_result=fit_result,
    )

    assert boundary.is_valid is True
    assert boundary.has_support is True
    assert boundary.has_resistance is False
    assert boundary.has_closed_channel is False
    assert boundary.structure_state == "support_only"
    assert boundary.metadata["structure"]["structure_state"] == "support_only"
    assert boundary.metadata["trendlines"]["structure"]["structure_state"] == "support_only"
