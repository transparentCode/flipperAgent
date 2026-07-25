import pytest

from libs.models.trendlines import build_extractor, build_fitter, list_extractors, list_fitters
from libs.models.trendlines.fitting.least_squares import LeastSquaresFitter
from libs.models.trendlines.fitting.pathfinding import PathfindingFitter
from libs.models.trendlines.fitting.ransac import RansacFitter
from libs.models.trendlines.pivots.rdp_zigzag import RDPZigZagPivotExtractor


def test_build_fitter_returns_registered_fitter():
    fitter = build_fitter("pathfinding", pivot_window=2)
    assert isinstance(fitter, PathfindingFitter)
    assert fitter.pivot_window == 2


def test_list_fitters_reports_registered_names():
    assert "least_squares" in list_fitters()
    assert "pathfinding" in list_fitters()
    assert "ransac" in list_fitters()


def test_list_extractors_reports_registered_names():
    assert "fractal" in list_extractors()
    assert "rdp_zigzag" in list_extractors()


def test_build_fitter_returns_least_squares_fitter():
    fitter = build_fitter("least_squares", pivot_window=2)
    assert isinstance(fitter, LeastSquaresFitter)
    assert fitter.pivot_window == 2


def test_build_fitter_supports_deprecated_alias(caplog):
    fitter = build_fitter("ols", pivot_window=2)
    assert isinstance(fitter, LeastSquaresFitter)
    assert "deprecated" in caplog.text.lower()


def test_build_fitter_returns_ransac_fitter():
    fitter = build_fitter("ransac", pivot_window=2, max_trials=10, seed=3)
    assert isinstance(fitter, RansacFitter)
    assert fitter.pivot_window == 2


def test_build_extractor_supports_deprecated_alias(caplog):
    extractor = build_extractor("fractals", window_left=1, window_right=1)
    assert extractor.__class__.__name__ == "FractalPivotExtractor"
    assert "deprecated" in caplog.text.lower()


def test_build_extractor_returns_rdp_zigzag_extractor():
    extractor = build_extractor("rdp_zigzag", epsilon_atr=0.1, min_segment_bars=1)
    assert isinstance(extractor, RDPZigZagPivotExtractor)


def test_build_extractor_supports_hyphenated_rdp_alias(caplog):
    extractor = build_extractor("rdp-zigzag", epsilon_atr=0.1, min_segment_bars=1)
    assert isinstance(extractor, RDPZigZagPivotExtractor)
    assert "deprecated" in caplog.text.lower()


def test_build_fitter_raises_for_unknown_name():
    with pytest.raises(ValueError, match="Unknown trendline fitter"):
        build_fitter("missing")
