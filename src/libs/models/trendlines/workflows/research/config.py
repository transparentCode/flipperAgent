"""Deterministic YAML-resolved research configuration bundle."""

from __future__ import annotations

from libs.models.trendlines.config import TrendlinesConfig
from libs.models.trendlines.config.resolve import resolve_pipeline_config
from libs.models.trendlines.contracts.identity import (
    TrendlineExecutionMode,
    canonical_hash,
)
from libs.models.trendlines.workflows.research.contracts import (
    PreparedTrendlineResearchConfig,
    RESEARCH_CONFIG_SEMANTICS_VERSION,
    TrendlineResearchSpec,
)


def resolve_research_config(
    spec: TrendlineResearchSpec,
    trendlines_config: TrendlinesConfig,
) -> PreparedTrendlineResearchConfig:
    """Resolve every requested timeframe without using constructor defaults."""

    if not isinstance(spec, TrendlineResearchSpec):
        raise TypeError("spec must be a TrendlineResearchSpec")
    if not isinstance(trendlines_config, TrendlinesConfig):
        raise TypeError("trendlines_config must be a TrendlinesConfig")

    pipeline_configs = {
        timeframe: resolve_pipeline_config(
            trendlines_config,
            spec.asset,
            timeframe,
            execution_mode=TrendlineExecutionMode.RESEARCH,
        )
        for timeframe in spec.timeframes
    }
    root_configuration_id = canonical_hash(
        trendlines_config,
        semantics_version=f"{RESEARCH_CONFIG_SEMANTICS_VERSION}.root",
    )
    search_grid_identity = canonical_hash(
        trendlines_config.search_grids,
        semantics_version=f"{RESEARCH_CONFIG_SEMANTICS_VERSION}.search-grid",
    )
    payload = {
        "asset": spec.asset,
        "timeframes": list(spec.timeframes),
        "primary_timeframe": spec.primary_timeframe,
        "execution_mode": TrendlineExecutionMode.RESEARCH.value,
        "pipelines": {
            timeframe: config.to_dict()
            for timeframe, config in pipeline_configs.items()
        },
        "root_configuration_id": root_configuration_id,
        "search_grid_identity": search_grid_identity,
    }
    research_configuration_id = canonical_hash(
        payload,
        semantics_version=RESEARCH_CONFIG_SEMANTICS_VERSION,
    )
    return PreparedTrendlineResearchConfig(
        asset=spec.asset,
        timeframes=spec.timeframes,
        primary_timeframe=spec.primary_timeframe,
        pipeline_configs=pipeline_configs,
        root_configuration_id=root_configuration_id,
        search_grid_identity=search_grid_identity,
        research_configuration_id=research_configuration_id,
    )


__all__ = ["resolve_research_config"]
