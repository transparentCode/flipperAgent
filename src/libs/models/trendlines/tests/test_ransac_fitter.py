import pandas as pd
import pytest

from app.trendlines.fitting.ransac import RansacFitter


def _make_ransac_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [10.0, 10.6, 10.4, 11.2, 11.0, 11.8, 11.6, 12.5, 12.2, 13.0, 12.8],
            "high": [10.8, 11.4, 11.0, 12.0, 11.7, 12.7, 12.1, 13.2, 12.9, 13.8, 13.4],
            "low": [9.4, 10.0, 9.8, 10.5, 10.2, 11.1, 10.9, 11.7, 11.4, 12.2, 12.0],
            "close": [10.5, 10.9, 10.7, 11.5, 11.3, 12.0, 11.9, 12.8, 12.5, 13.3, 13.1],
        }
    )


def test_ransac_fitter_returns_trendlines():
    fitter = RansacFitter(pivot_window=1, max_trials=100, seed=7)

    result = fitter.fit(_make_ransac_frame())

    assert result.is_valid is True
    assert result.best_support is not None
    assert result.best_resistance is not None
    assert result.best_support.method == "ransac"
    assert result.best_resistance.method == "ransac"
    assert result.best_support.metadata["r_squared"] >= 0.0
    assert result.best_resistance.metadata["r_squared"] >= 0.0


def test_ransac_fitter_rejects_missing_columns():
    fitter = RansacFitter(pivot_window=1)

    with pytest.raises(ValueError, match="requires columns"):
        fitter.fit(pd.DataFrame({"close": [1, 2, 3]}))