import pandas as pd
import pytest
import numpy as np

from app.trendlines.fitting.pathfinding import PathfindingFitter
from app.trendlines.contracts import PivotSet


def _make_pathfinding_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [9.2, 10.1, 9.4, 11.0, 10.3, 12.0, 11.4, 13.0, 12.4],
            "high": [10.0, 11.2, 10.6, 12.4, 11.8, 13.6, 12.8, 14.7, 13.9],
            "low": [8.5, 9.1, 8.2, 9.8, 9.0, 10.5, 9.8, 11.2, 10.7],
            "close": [9.6, 10.4, 9.7, 11.3, 10.6, 12.3, 11.8, 13.4, 12.9],
        }
    )


def test_pathfinding_fitter_returns_support_and_resistance_lines():
    fitter = PathfindingFitter(pivot_window=1)

    result = fitter.fit(_make_pathfinding_frame())

    assert result.is_valid is True
    assert result.best_support is not None
    assert result.best_resistance is not None
    assert result.best_support.method == "pathfinding"
    assert result.best_resistance.method == "pathfinding"
    assert result.best_support.touch_count >= 2
    assert result.best_resistance.touch_count >= 2
    assert result.best_support.value_at(result.best_support.end_index) == pytest.approx(result.best_support.end_value)
    assert result.best_resistance.value_at(result.best_resistance.end_index) == pytest.approx(result.best_resistance.end_value)


def test_pathfinding_fitter_rejects_missing_columns():
    fitter = PathfindingFitter(pivot_window=1)

    with pytest.raises(ValueError, match="requires columns"):
        fitter.fit(pd.DataFrame({"close": [1, 2, 3]}))


def test_pathfinding_fitter_uses_injected_pivot_extractor():
    class StubExtractor:
        def extract(self, df: pd.DataFrame) -> PivotSet:
            return PivotSet(
                high_indices=np.array([1, 3]),
                high_values=np.array([11.2, 12.4]),
                low_indices=np.array([2, 4]),
                low_values=np.array([8.2, 9.0]),
            )

    fitter = PathfindingFitter(pivot_window=1, pivot_extractor=StubExtractor())

    result = fitter.fit(_make_pathfinding_frame())

    assert result.is_valid is True
    assert result.metadata["extractor"] == "StubExtractor"
