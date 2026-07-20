"""Compatibility exports for neutral Trendline/RegimeV2 shadow composition."""

from libs.integrations.trendline_regime_v2.shadow import (
    FailedTrendlineFamilyShadowProducer,
    TrendlineFamilyFeatureProducer,
    TrendlineFamilyShadowConfig,
    build_trendline_family_shadow_failure_payload,
    summarize_trendline_family_shadow_artifacts,
)

__all__ = [
    "FailedTrendlineFamilyShadowProducer",
    "TrendlineFamilyFeatureProducer",
    "TrendlineFamilyShadowConfig",
    "build_trendline_family_shadow_failure_payload",
    "summarize_trendline_family_shadow_artifacts",
]
