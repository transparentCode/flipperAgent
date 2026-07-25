import pandas as pd
import pytest

from libs.models.trendlines.fitting.least_squares import LeastSquaresFitter


def _make_least_squares_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [9.2, 10.1, 9.4, 11.0, 10.3, 12.0, 11.4, 13.0, 12.4],
            "high": [10.0, 11.2, 10.6, 12.4, 11.8, 13.6, 12.8, 14.7, 13.9],
            "low": [8.5, 9.1, 8.2, 9.8, 9.0, 10.5, 9.8, 11.2, 10.7],
            "close": [9.6, 10.4, 9.7, 11.3, 10.6, 12.3, 11.8, 13.4, 12.9],
        }
    )


def test_least_squares_fitter_returns_trendlines():
    fitter = LeastSquaresFitter(pivot_window=1)

    result = fitter.fit(_make_least_squares_frame())

    assert result.is_valid is True
    assert result.best_support is not None
    assert result.best_resistance is not None
    assert result.best_support.method == "least_squares"
    assert result.best_resistance.method == "least_squares"
    assert result.best_support.metadata["r_squared"] >= 0.0
    assert result.best_resistance.metadata["r_squared"] >= 0.0


def test_least_squares_fitter_rejects_missing_columns():
    fitter = LeastSquaresFitter(pivot_window=1)

    with pytest.raises(ValueError, match="requires columns"):
        fitter.fit(pd.DataFrame({"close": [1, 2, 3]}))