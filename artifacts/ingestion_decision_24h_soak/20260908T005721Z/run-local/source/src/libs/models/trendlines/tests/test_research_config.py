"""L2-A1 research configuration contracts."""

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from libs.models.trendlines.config import (
    AssetConfig,
    AssetTimeframeConfig,
    load_trendlines_config,
    resolve_pipeline_config,
)
from libs.models.trendlines.contracts import TrendlineExecutionMode
from libs.models.trendlines.pivots.capabilities import ExtractorExecutionPolicyError
from libs.models.trendlines.workflows.research import (
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchPurpose,
    TrendlineResearchSpec,
    resolve_research_config,
)


def _spec(mode: TrendlineResearchDataMode = TrendlineResearchDataMode.SYNTHETIC) -> TrendlineResearchSpec:
    data = TrendlineResearchDataSpec(
        mode=mode,
        seed=7 if mode is TrendlineResearchDataMode.SYNTHETIC else None,
        start_time=(
            datetime(2025, 1, 1, tzinfo=timezone.utc)
            if mode is TrendlineResearchDataMode.SYNTHETIC
            else None
        ),
        bar_counts={"1h": 16} if mode is TrendlineResearchDataMode.SYNTHETIC else {},
        event_start=(
            datetime(2025, 1, 1, tzinfo=timezone.utc)
            if mode is TrendlineResearchDataMode.BINANCE
            else None
        ),
        knowledge_cutoff=(
            datetime(2025, 1, 2, tzinfo=timezone.utc)
            if mode is TrendlineResearchDataMode.BINANCE
            else None
        ),
    )
    return TrendlineResearchSpec(
        purpose=(
            TrendlineResearchPurpose.RESEARCH
            if mode is TrendlineResearchDataMode.BINANCE
            else TrendlineResearchPurpose.SMOKE
        ),
        data=data,
        asset="BTCUSDT",
        timeframes=("1h",),
        primary_timeframe="1h",
    )


def test_canonical_yaml_exposes_explicit_extractor_parameters():
    config = load_trendlines_config()

    assert config.extractor_params == {"window_left": 3, "window_right": 3}


def test_canonical_yaml_exposes_explicit_fitter_parameters():
    config = load_trendlines_config()

    assert config.fitter_params == {"pivot_window": 3, "line_fit_mode": "endpoint"}


def test_global_pipeline_configuration_resolves_without_constructor_defaults():
    config = load_trendlines_config()
    resolved = resolve_pipeline_config(
        config,
        "BTCUSDT",
        "1h",
        execution_mode=TrendlineExecutionMode.RESEARCH,
    )

    assert resolved.extractor_params == config.extractor_params
    assert resolved.fitter_params == config.fitter_params


def test_partial_asset_timeframe_parameter_overlay_preserves_global_values():
    config = load_trendlines_config()
    config = replace(
        config,
        assets={
            "BTCUSDT": AssetConfig(
                timeframes={"1h": AssetTimeframeConfig(extractor_params={"window_right": 5})}
            )
        },
    )
    resolved = resolve_pipeline_config(
        config,
        "BTCUSDT",
        "1h",
        execution_mode=TrendlineExecutionMode.RESEARCH,
    )

    assert resolved.extractor_params == {"window_left": 3, "window_right": 5}


def test_asset_timeframe_component_override_takes_precedence():
    config = load_trendlines_config()
    config = replace(
        config,
        assets={
            "BTCUSDT": AssetConfig(
                timeframes={
                    "1h": AssetTimeframeConfig(
                        extractor="rdp_zigzag",
                        extractor_params={"epsilon_atr": 0.5, "min_segment_bars": 1},
                    )
                }
            )
        },
    )
    resolved = resolve_pipeline_config(
        config,
        "BTCUSDT",
        "1h",
        execution_mode=TrendlineExecutionMode.RESEARCH,
    )

    assert resolved.extractor == "rdp_zigzag"
    assert resolved.extractor_params == {"epsilon_atr": 0.5, "min_segment_bars": 1}


def test_runtime_pipeline_resolution_rejects_research_only_rdp():
    config = load_trendlines_config()
    config = replace(
        config,
        extractor="rdp_zigzag",
        extractor_params={"epsilon_atr": 0.5, "min_segment_bars": 1},
    )

    with pytest.raises(ExtractorExecutionPolicyError):
        resolve_pipeline_config(
            config,
            "BTCUSDT",
            "1h",
            execution_mode=TrendlineExecutionMode.RUNTIME,
        )


def test_research_pipeline_resolution_accepts_explicitly_configured_rdp():
    config = load_trendlines_config()
    config = replace(
        config,
        extractor="rdp_zigzag",
        extractor_params={"epsilon_atr": 0.5, "min_segment_bars": 1},
    )

    resolved = resolve_pipeline_config(
        config,
        "BTCUSDT",
        "1h",
        execution_mode=TrendlineExecutionMode.RESEARCH,
    )

    assert resolved.extractor == "rdp_zigzag"


def test_research_configuration_identity_is_deterministic():
    config = load_trendlines_config()
    first = resolve_research_config(_spec(), config)
    second = resolve_research_config(_spec(), config)

    assert first.research_configuration_id == second.research_configuration_id
    assert first.to_dict() == second.to_dict()


def test_behaviour_affecting_resolved_parameter_changes_research_configuration_identity():
    config = load_trendlines_config()
    changed = replace(config, extractor_params={"window_left": 5, "window_right": 3})

    first = resolve_research_config(_spec(), config)
    second = resolve_research_config(_spec(), changed)

    assert first.research_configuration_id != second.research_configuration_id


def test_smoke_binance_is_rejected():
    with pytest.raises(ValueError, match="SMOKE.*BINANCE"):
        TrendlineResearchSpec(
            purpose=TrendlineResearchPurpose.SMOKE,
            data=TrendlineResearchDataSpec(
                mode=TrendlineResearchDataMode.BINANCE,
                event_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
                knowledge_cutoff=datetime(2025, 1, 2, tzinfo=timezone.utc),
            ),
            asset="BTCUSDT",
            timeframes=("1h",),
            primary_timeframe="1h",
        )
