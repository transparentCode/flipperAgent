import numpy as np
import pandas as pd
import pytest

from app.trendlines.pivots import FractalPivotExtractor, RDPZigZagPivotExtractor
from app.trendlines import build_extractor, list_extractors


def _make_fractal_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "high": [10.0, 12.0, 11.0, 14.0, 13.0, 15.0, 12.0],
            "low": [7.0, 8.0, 6.0, 9.0, 7.0, 10.0, 8.0],
        }
    )


def _make_rdp_frame() -> pd.DataFrame:
    close = [10.0, 12.0, 9.5, 13.5, 8.8, 14.2, 9.4, 15.0, 10.1]
    return pd.DataFrame(
        {
            "open": [value - 0.2 for value in close],
            "high": [value + 0.9 for value in close],
            "low": [value - 0.9 for value in close],
            "close": close,
        }
    )


def test_build_extractor_returns_registered_extractor():
    extractor = build_extractor("fractal", window_left=1, window_right=1)
    assert isinstance(extractor, FractalPivotExtractor)
    assert extractor.window_left == 1
    assert extractor.window_right == 1


def test_list_extractors_reports_registered_names():
    assert "fractal" in list_extractors()
    assert "rdp_zigzag" in list_extractors()


def test_fractal_extractor_returns_pivot_set():
    extractor = FractalPivotExtractor(window_left=1, window_right=1)
    pivots = extractor.extract(_make_fractal_frame())

    assert isinstance(pivots.high_indices, np.ndarray)
    assert isinstance(pivots.low_indices, np.ndarray)
    assert pivots.n_highs >= 1
    assert pivots.n_lows >= 1


def test_fractal_extractor_rejects_missing_columns():
    extractor = FractalPivotExtractor(window_left=1, window_right=1)

    with pytest.raises(ValueError, match="requires columns"):
        extractor.extract(pd.DataFrame({"close": [1, 2, 3]}))


def test_rdp_zigzag_extractor_returns_pivot_set():
    extractor = RDPZigZagPivotExtractor(epsilon_atr=0.1, min_segment_bars=1)
    pivots = extractor.extract(_make_rdp_frame())

    assert isinstance(pivots.high_indices, np.ndarray)
    assert isinstance(pivots.low_indices, np.ndarray)
    assert pivots.n_highs >= 1
    assert pivots.n_lows >= 1


def test_rdp_zigzag_extractor_returns_empty_set_for_short_frame():
    extractor = RDPZigZagPivotExtractor(epsilon_atr=0.1, min_segment_bars=1)
    pivots = extractor.extract(_make_rdp_frame().iloc[:3])

    assert pivots.total_pivots == 0


def test_rdp_zigzag_extractor_rejects_missing_columns():
    extractor = RDPZigZagPivotExtractor(epsilon_atr=0.1, min_segment_bars=1)

    with pytest.raises(ValueError, match="requires columns"):
        extractor.extract(pd.DataFrame({"high": [1, 2, 3], "low": [0, 1, 2]}))