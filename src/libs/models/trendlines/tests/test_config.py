from app.trendlines import TrendlinePipelineConfig


def test_trendline_pipeline_config_round_trips():
    config = TrendlinePipelineConfig(
        extractor="fractal",
        fitter="least_squares",
        extractor_params={"window_left": 1, "window_right": 2},
        fitter_params={"pivot_window": 2},
        boundary_params={"atr_window": 7, "interaction_tolerance_atr": 0.15},
        signal_params={"weights": {"structural": 1.5, "pattern": 0.7}},
    )

    restored = TrendlinePipelineConfig.from_dict(config.to_dict())

    assert restored == config


def test_trendline_pipeline_config_defaults_when_empty():
    config = TrendlinePipelineConfig.from_dict({})

    assert config.extractor == "fractal"
    assert config.fitter == "pathfinding"
    assert config.extractor_params == {}
    assert config.fitter_params == {}
    assert config.boundary_params == {}
    assert config.signal_params == {}


def test_trendline_pipeline_config_omits_empty_optional_sections_from_dict():
    config = TrendlinePipelineConfig()

    assert config.to_dict() == {
        "extractor": "fractal",
        "fitter": "pathfinding",
        "extractor_params": {},
        "fitter_params": {},
    }
