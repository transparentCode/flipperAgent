import numpy as np
import pandas as pd
import pytest

from libs.models.trendlines import (
    ExtractorCapabilities,
    ExtractorExecutionPolicyError,
    PivotFinality,
    PivotSet,
    TrendlineExecutionMode,
    TrendlinePipelineConfig,
    build_extractor,
    fit_trendlines,
    list_extractors_for_mode,
    run_trendline_pipeline,
    run_trendline_pipeline_from_config,
)
from libs.models.trendlines.pivots.fractal import FractalPivotExtractor
from libs.models.trendlines.pivots.rdp_zigzag import RDPZigZagPivotExtractor


def _make_frame(n_bars: int = 120) -> pd.DataFrame:
    index = np.arange(n_bars, dtype=float)
    close = 100.0 + 0.25 * index + 3.0 * np.sin(index / 4.0)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.6,
            "low": close - 0.6,
            "close": close,
        }
    )


def _rdp_kwargs() -> dict[str, float | int]:
    return {"epsilon_atr": 0.1, "min_segment_bars": 1}


def _pivot_set() -> PivotSet:
    return PivotSet(
        high_indices=np.array([10, 30]),
        high_values=np.array([105.0, 110.0]),
        low_indices=np.array([20, 40]),
        low_values=np.array([95.0, 100.0]),
    )


def test_fractal_declares_runtime_and_research_support():
    capabilities = FractalPivotExtractor.CAPABILITIES

    assert capabilities.supported_modes == frozenset(
        {TrendlineExecutionMode.RUNTIME, TrendlineExecutionMode.RESEARCH}
    )


def test_fractal_declares_append_only_confirmed_finality():
    assert (
        FractalPivotExtractor.CAPABILITIES.finality
        is PivotFinality.CONFIRMED_APPEND_ONLY
    )


def test_rdp_declares_research_only_support():
    assert RDPZigZagPivotExtractor.CAPABILITIES.supported_modes == frozenset(
        {TrendlineExecutionMode.RESEARCH}
    )


def test_rdp_declares_retrospective_prefix_revising_finality():
    assert (
        RDPZigZagPivotExtractor.CAPABILITIES.finality
        is PivotFinality.RETROSPECTIVE_PREFIX_REVISING
    )


def test_runtime_extractor_listing_excludes_rdp():
    assert list_extractors_for_mode(TrendlineExecutionMode.RUNTIME) == ("fractal",)


def test_research_extractor_listing_includes_fractal_and_rdp():
    assert list_extractors_for_mode(TrendlineExecutionMode.RESEARCH) == (
        "fractal",
        "rdp_zigzag",
    )


def test_building_fractal_in_runtime_succeeds():
    extractor = build_extractor(
        "fractal",
        execution_mode=TrendlineExecutionMode.RUNTIME,
        window_left=1,
        window_right=1,
    )

    assert isinstance(extractor, FractalPivotExtractor)


def test_building_rdp_in_runtime_fails_closed():
    with pytest.raises(ExtractorExecutionPolicyError, match="rdp_zigzag.*runtime"):
        build_extractor("rdp_zigzag", **_rdp_kwargs())


def test_building_deprecated_rdp_alias_in_runtime_fails_closed():
    with pytest.raises(ExtractorExecutionPolicyError, match="rdp_zigzag.*runtime"):
        build_extractor("rdp-zigzag", **_rdp_kwargs())


def test_building_rdp_in_research_succeeds():
    extractor = build_extractor(
        "rdp_zigzag",
        execution_mode=TrendlineExecutionMode.RESEARCH,
        **_rdp_kwargs(),
    )

    assert isinstance(extractor, RDPZigZagPivotExtractor)


def test_runtime_pipeline_rejects_rdp_registry_name():
    with pytest.raises(ExtractorExecutionPolicyError, match="rdp_zigzag.*runtime"):
        run_trendline_pipeline(
            _make_frame(),
            extractor="rdp_zigzag",
            fitter="least_squares",
            extractor_kwargs=_rdp_kwargs(),
        )


def test_research_pipeline_accepts_rdp_registry_name():
    result = run_trendline_pipeline(
        _make_frame(),
        extractor="rdp_zigzag",
        fitter="least_squares",
        extractor_kwargs=_rdp_kwargs(),
        execution_mode=TrendlineExecutionMode.RESEARCH,
    )

    assert result.metadata["pipeline"]["execution_mode"] == "research"
    assert (
        result.metadata["pipeline"]["extractor_finality"]
        == "retrospective_prefix_revising"
    )


def test_runtime_pipeline_rejects_direct_rdp_instance():
    with pytest.raises(ExtractorExecutionPolicyError, match="RDPZigZagPivotExtractor"):
        run_trendline_pipeline(
            _make_frame(),
            extractor=RDPZigZagPivotExtractor(**_rdp_kwargs()),
            fitter="least_squares",
        )


def test_research_pipeline_accepts_direct_rdp_instance():
    result = run_trendline_pipeline(
        _make_frame(),
        extractor=RDPZigZagPivotExtractor(**_rdp_kwargs()),
        fitter="least_squares",
        execution_mode=TrendlineExecutionMode.RESEARCH,
    )

    assert result.metadata["pipeline"]["extractor"] == "RDPZigZagPivotExtractor"


def test_runtime_pipeline_rejects_unclassified_custom_extractor():
    class UnclassifiedExtractor:
        def extract(self, df: pd.DataFrame):
            del df
            return _pivot_set()

    with pytest.raises(ExtractorExecutionPolicyError, match="no typed capability"):
        run_trendline_pipeline(
            _make_frame(),
            extractor=UnclassifiedExtractor(),
            fitter="least_squares",
        )


def test_custom_extractor_modes_are_enforced():
    class ClassifiedRuntimeExtractor:
        CAPABILITIES = ExtractorCapabilities(
            supported_modes=frozenset({TrendlineExecutionMode.RUNTIME}),
            finality=PivotFinality.CONFIRMED_APPEND_ONLY,
        )

        def extract(self, df: pd.DataFrame):
            del df
            return _pivot_set()

        def trendline_identity_payload(self):
            return {"fixture": "classified-runtime-extractor"}

    class ResearchOnlyExtractor:
        CAPABILITIES = ExtractorCapabilities(
            supported_modes=frozenset({TrendlineExecutionMode.RESEARCH}),
            finality=PivotFinality.RETROSPECTIVE_PREFIX_REVISING,
        )

        def extract(self, df: pd.DataFrame):
            del df
            return _pivot_set()

        def trendline_identity_payload(self):
            return {"fixture": "research-only-extractor"}

    runtime_result = run_trendline_pipeline(
        _make_frame(),
        extractor=ClassifiedRuntimeExtractor(),
        fitter="least_squares",
    )
    assert runtime_result.metadata["pipeline"]["execution_mode"] == "runtime"

    with pytest.raises(ExtractorExecutionPolicyError, match="runtime"):
        run_trendline_pipeline(
            _make_frame(),
            extractor=ResearchOnlyExtractor(),
            fitter="least_squares",
        )

    research_result = run_trendline_pipeline(
        _make_frame(),
        extractor=ResearchOnlyExtractor(),
        fitter="least_squares",
        execution_mode=TrendlineExecutionMode.RESEARCH,
    )
    assert research_result.metadata["pipeline"]["execution_mode"] == "research"


def test_config_selected_rdp_fails_runtime_and_succeeds_in_research():
    config = TrendlinePipelineConfig(
        extractor="rdp_zigzag",
        fitter="least_squares",
        extractor_params=_rdp_kwargs(),
    )

    with pytest.raises(ExtractorExecutionPolicyError, match="rdp_zigzag.*runtime"):
        run_trendline_pipeline_from_config(_make_frame(), config)

    result = run_trendline_pipeline_from_config(
        _make_frame(),
        config,
        execution_mode=TrendlineExecutionMode.RESEARCH,
    )
    assert result.metadata["pipeline"]["extractor_finality"] == (
        "retrospective_prefix_revising"
    )


def test_public_facade_research_execution_records_mode_and_finality():
    with pytest.raises(ExtractorExecutionPolicyError, match="rdp_zigzag.*runtime"):
        fit_trendlines(
            _make_frame(),
            extractor="rdp_zigzag",
            fitter="least_squares",
            extractor_kwargs=_rdp_kwargs(),
        )

    output = fit_trendlines(
        _make_frame(),
        extractor="rdp_zigzag",
        fitter="least_squares",
        extractor_kwargs=_rdp_kwargs(),
        execution_mode=TrendlineExecutionMode.RESEARCH,
    )
    pipeline_metadata = output.fit_result.metadata["pipeline"]
    assert pipeline_metadata["execution_mode"] == "research"
    assert pipeline_metadata["extractor_finality"] == (
        "retrospective_prefix_revising"
    )
