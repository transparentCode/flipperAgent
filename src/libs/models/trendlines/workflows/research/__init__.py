"""Canonical, source-agnostic trendline research preparation foundation."""

from libs.models.trendlines.workflows.research.config import resolve_research_config
from libs.models.trendlines.workflows.research.contracts import (
    BarAvailabilitySource,
    BarTimestampSemantics,
    PreparedTrendlineResearchConfig,
    PreparedTrendlineResearchDataset,
    PreparedTrendlineResearchRun,
    RESEARCH_AVAILABILITY_ID_SEMANTICS_VERSION,
    RESEARCH_CONFIG_SEMANTICS_VERSION,
    RESEARCH_DATA_SEMANTICS_VERSION,
    RESEARCH_PREPARATION_SEMANTICS_VERSION,
    SYNTHETIC_GENERATOR_SEMANTICS_VERSION,
    TrendlineResearchDataMode,
    TrendlineResearchDataSpec,
    TrendlineResearchDatasetIdentity,
    TrendlineResearchPurpose,
    TrendlineResearchSpec,
    build_research_availability_id,
)
from libs.models.trendlines.workflows.research.data import (
    TrendlineResearchLoader,
    prepare_research_dataset,
    prepare_trendline_research,
    validate_research_frame,
)
from libs.models.trendlines.workflows.research.synthetic import (
    generate_synthetic_frames,
    strict_timeframe_seconds,
)

__all__ = [
    "BarAvailabilitySource",
    "BarTimestampSemantics",
    "PreparedTrendlineResearchConfig",
    "PreparedTrendlineResearchDataset",
    "PreparedTrendlineResearchRun",
    "RESEARCH_AVAILABILITY_ID_SEMANTICS_VERSION",
    "RESEARCH_CONFIG_SEMANTICS_VERSION",
    "RESEARCH_DATA_SEMANTICS_VERSION",
    "RESEARCH_PREPARATION_SEMANTICS_VERSION",
    "SYNTHETIC_GENERATOR_SEMANTICS_VERSION",
    "TrendlineResearchDataMode",
    "TrendlineResearchDataSpec",
    "TrendlineResearchDatasetIdentity",
    "TrendlineResearchLoader",
    "TrendlineResearchPurpose",
    "TrendlineResearchSpec",
    "build_research_availability_id",
    "generate_synthetic_frames",
    "prepare_research_dataset",
    "prepare_trendline_research",
    "resolve_research_config",
    "strict_timeframe_seconds",
    "validate_research_frame",
]
