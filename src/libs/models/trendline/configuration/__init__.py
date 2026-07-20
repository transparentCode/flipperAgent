"""Canonical immutable Trendline configuration schema and resolution boundary."""

from .contracts import (
    CandidateConfig,
    EventsConfig,
    InteractionConfig,
    LifecycleConfig,
    MatchingConfig,
    MTFConfig,
    ModelConfig,
    RailsConfig,
    RankingConfig,
    RepositoryConfig,
    ResolvedTrendlineFamilyConfig,
    RuntimeConfig,
    TrendlineFamilyConfig,
    canonical_mtf_source_timeframes,
    canonical_timeframe_duration_seconds,
)
from .profiles import LEGACY_V1_PROFILE_ID, LEGACY_V1_PROFILE_VERSION, legacy_v1_profile
from .provenance import ConfigSource, configuration_manifest, configuration_sources
from .resolver import UNSET, TrendlineConfigPatch, TrendlineConfigScope, TrendlineFamilyConfigResolver

__all__ = [
    "CandidateConfig",
    "ConfigSource",
    "EventsConfig",
    "InteractionConfig",
    "LEGACY_V1_PROFILE_ID",
    "LEGACY_V1_PROFILE_VERSION",
    "LifecycleConfig",
    "MatchingConfig",
    "MTFConfig",
    "ModelConfig",
    "RailsConfig",
    "RankingConfig",
    "RepositoryConfig",
    "ResolvedTrendlineFamilyConfig",
    "RuntimeConfig",
    "TrendlineConfigPatch",
    "TrendlineConfigScope",
    "TrendlineFamilyConfig",
    "TrendlineFamilyConfigResolver",
    "UNSET",
    "canonical_mtf_source_timeframes",
    "canonical_timeframe_duration_seconds",
    "configuration_manifest",
    "configuration_sources",
    "legacy_v1_profile",
]
