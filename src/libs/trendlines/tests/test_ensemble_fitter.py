"""Tests for EnsembleFitter."""

import pandas as pd
import pytest

from app.trendlines.fitting.ensemble import EnsembleFitter, _deduplicate
from app.trendlines.contracts import Trendline
from app.trendlines.registry import build_fitter, list_fitters


def _make_ohlc_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [10.0, 10.6, 10.4, 11.2, 11.0, 11.8, 11.6, 12.5, 12.2, 13.0, 12.8],
            "high": [10.8, 11.4, 11.0, 12.0, 11.7, 12.7, 12.1, 13.2, 12.9, 13.8, 13.4],
            "low": [9.4, 10.0, 9.8, 10.5, 10.2, 11.1, 10.9, 11.7, 11.4, 12.2, 12.0],
            "close": [10.5, 10.9, 10.7, 11.5, 11.3, 12.0, 11.9, 12.8, 12.5, 13.3, 13.1],
        }
    )


def test_ensemble_registered():
    assert "ensemble" in list_fitters()


def test_ensemble_build_from_registry():
    fitter = build_fitter("ensemble", pivot_window=1)
    assert isinstance(fitter, EnsembleFitter)


def test_ensemble_returns_multiple_lines():
    fitter = EnsembleFitter(pivot_window=1)
    result = fitter.fit(_make_ohlc_frame())

    assert result.is_valid is True
    total = len(result.support_lines) + len(result.resistance_lines)
    assert total >= 2  # at least 1 support + 1 resistance
    assert result.metadata["method"] == "ensemble"
    assert "sub_fitters" in result.metadata


def test_ensemble_metadata_tracks_sub_fitters():
    fitter = EnsembleFitter(pivot_window=1)
    result = fitter.fit(_make_ohlc_frame())

    sub = result.metadata["sub_fitters"]
    for name in ("pathfinding", "least_squares", "ransac"):
        assert name in sub


def test_ensemble_rejects_missing_columns():
    fitter = EnsembleFitter(pivot_window=1)
    with pytest.raises(ValueError, match="requires columns"):
        fitter.fit(pd.DataFrame({"close": [1, 2, 3]}))


def test_ensemble_passes_pathfinding_refit_mode():
    fitter = EnsembleFitter(pivot_window=1, pathfinding_line_fit_mode="ols_on_path")
    result = fitter.fit(_make_ohlc_frame())

    assert result.metadata["pathfinding_line_fit_mode"] == "ols_on_path"
    assert result.metadata["sub_fitters"]["pathfinding"]["n_support"] >= 0


def test_ensemble_rejects_unknown_pathfinding_refit_mode():
    fitter = EnsembleFitter(pivot_window=1, pathfinding_line_fit_mode="bad_mode")

    with pytest.raises(ValueError, match="pathfinding_line_fit_mode"):
        fitter.fit(_make_ohlc_frame())


def test_deduplicate_removes_near_identical():
    base = Trendline(
        start_index=0, end_index=10, start_value=100.0, end_value=101.0,
        slope=0.1, intercept=100.0, touch_count=5, is_support=True,
        method="a", score=0.9,
    )
    duplicate = Trendline(
        start_index=0, end_index=10, start_value=100.0, end_value=101.0,
        slope=0.1001, intercept=100.01, touch_count=3, is_support=True,
        method="b", score=0.7,
    )
    result = _deduplicate([base, duplicate], slope_atol=0.001, intercept_atol=0.1)
    assert len(result) == 1
    assert result[0].score == 0.9  # keeps higher score


def test_deduplicate_keeps_distinct():
    line_a = Trendline(
        start_index=0, end_index=10, start_value=100.0, end_value=101.0,
        slope=0.1, intercept=100.0, touch_count=5, is_support=True,
        method="a", score=0.9,
    )
    line_b = Trendline(
        start_index=0, end_index=10, start_value=90.0, end_value=95.0,
        slope=0.5, intercept=90.0, touch_count=3, is_support=True,
        method="b", score=0.7,
    )
    result = _deduplicate([line_a, line_b], slope_atol=0.001, intercept_atol=0.1)
    assert len(result) == 2
