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
from .derived import DerivedTrendlineConfig, derive_configuration
from .field_policy import ConfigClassification, ConfigFieldPolicy, ConfigScope, FIELD_POLICIES
from .loader import load_trendline_family_config

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
    "ConfigClassification",
    "ConfigFieldPolicy",
    "ConfigScope",
    "DerivedTrendlineConfig",
    "FIELD_POLICIES",
    "canonical_mtf_source_timeframes",
    "canonical_timeframe_duration_seconds",
    "configuration_manifest",
    "configuration_sources",
    "derive_configuration",
    "legacy_v1_profile",
    "load_trendline_family_config",
]
