import numpy as np
import pandas as pd

from libs.models.trendlines import TrendlinePipelineConfig, execute_trendline_pipeline, run_trendline_pipeline, run_trendline_pipeline_from_config
from libs.models.trendlines.contracts import PivotSet, TrendlineFitResult
from libs.models.trendlines.pivots.capabilities import (
    ExtractorCapabilities,
    PivotFinality,
    TrendlineExecutionMode,
)


def _make_pipeline_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [9.2, 10.1, 9.4, 11.0, 10.3, 12.0, 11.4, 13.0, 12.4],
            "high": [10.0, 11.2, 10.6, 12.4, 11.8, 13.6, 12.8, 14.7, 13.9],
            "low": [8.5, 9.1, 8.2, 9.8, 9.0, 10.5, 9.8, 11.2, 10.7],
            "close": [9.6, 10.4, 9.7, 11.3, 10.6, 12.3, 11.8, 13.4, 12.9],
        }
    )


def test_run_trendline_pipeline_with_registered_components():
    result = run_trendline_pipeline(
        _make_pipeline_frame(),
        extractor="fractal",
        fitter="pathfinding",
        extractor_kwargs={"window_left": 1, "window_right": 1},
        fitter_kwargs={"pivot_window": 1},
    )

    assert result.is_valid is True
    assert result.metadata["pipeline"]["extractor"] == "fractal"
    assert result.metadata["pipeline"]["fitter"] == "pathfinding"
    assert result.metadata["pipeline"]["n_high_pivots"] >= 1
    assert result.metadata["pipeline"]["n_low_pivots"] >= 1


def test_run_trendline_pipeline_accepts_custom_components():
    class StubExtractor:
        CAPABILITIES = ExtractorCapabilities(
            supported_modes=frozenset(
                {TrendlineExecutionMode.RUNTIME, TrendlineExecutionMode.RESEARCH}
            ),
            finality=PivotFinality.CONFIRMED_APPEND_ONLY,
        )

        def extract(self, df: pd.DataFrame) -> PivotSet:
            return PivotSet(
                high_indices=np.array([1, 3]),
                high_values=np.array([11.2, 12.4]),
                low_indices=np.array([2, 4]),
                low_values=np.array([8.2, 9.0]),
            )

    class RecordingFitter:
        def __init__(self):
            self.seen_pivots = None

        def fit(self, df: pd.DataFrame, pivots: PivotSet | None = None) -> TrendlineFitResult:
            self.seen_pivots = pivots
            return TrendlineFitResult(is_valid=pivots is not None, metadata={"source": "recording"})

    fitter = RecordingFitter()
    result = run_trendline_pipeline(
        _make_pipeline_frame(),
        extractor=StubExtractor(),
        fitter=fitter,
    )

    assert fitter.seen_pivots is not None
    assert result.is_valid is True
    assert result.metadata["pipeline"]["extractor"] == "StubExtractor"
    assert result.metadata["pipeline"]["fitter"] == "RecordingFitter"


def test_run_trendline_pipeline_from_config():
    config = TrendlinePipelineConfig(
        extractor="fractal",
        fitter="least_squares",
        extractor_params={"window_left": 1, "window_right": 1},
        fitter_params={"pivot_window": 1},
    )

    result = run_trendline_pipeline_from_config(_make_pipeline_frame(), config)

    assert result.is_valid is True
    assert result.metadata["pipeline"]["extractor"] == "fractal"
    assert result.metadata["pipeline"]["fitter"] == "least_squares"


def test_execute_trendline_pipeline_normalizes_mapping_config():
    result, resolved_config = execute_trendline_pipeline(
        _make_pipeline_frame(),
        config={
            "extractor": "fractal",
            "fitter": "least_squares",
            "extractor_params": {"window_left": 1, "window_right": 1},
            "fitter_params": {"pivot_window": 1},
            "boundary_params": {"atr_window": 5, "interaction_tolerance_atr": 0.2},
            "signal_params": {"weights": {"structural": 1.2}},
        },
    )

    assert result.is_valid is True
    assert resolved_config is not None
    assert isinstance(resolved_config, TrendlinePipelineConfig)
    assert resolved_config.fitter == "least_squares"
    assert resolved_config.boundary_params == {"atr_window": 5, "interaction_tolerance_atr": 0.2}
    assert resolved_config.signal_params == {"weights": {"structural": 1.2}}


def test_run_trendline_pipeline_with_rdp_zigzag_extractor():
    result = run_trendline_pipeline(
        _make_pipeline_frame(),
        extractor="rdp_zigzag",
        fitter="least_squares",
        extractor_kwargs={"epsilon_atr": 0.1, "min_segment_bars": 1},
        execution_mode=TrendlineExecutionMode.RESEARCH,
    )

    assert result.is_valid is True
    assert result.metadata["pipeline"]["extractor"] == "rdp_zigzag"
    assert result.metadata["pipeline"]["fitter"] == "least_squares"
