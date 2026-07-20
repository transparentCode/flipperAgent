"""Neutral Trendline and RegimeV2 composition implementations."""

from .ablation import (
    FEATURE_GROUP_SPECS,
    FeatureGroupSpec,
    RegimeFeatureAblationEvaluator,
    WeightedFeatureScorer,
    evaluate_regime_feature_group_holdout,
    run_regime_feature_ablation,
)
from .shadow import (
    FailedTrendlineFamilyShadowProducer,
    TrendlineFamilyFeatureProducer,
    TrendlineFamilyShadowConfig,
    build_trendline_family_shadow_failure_payload,
    summarize_trendline_family_shadow_artifacts,
)

__all__ = [
    "FEATURE_GROUP_SPECS",
    "FailedTrendlineFamilyShadowProducer",
    "FeatureGroupSpec",
    "RegimeFeatureAblationEvaluator",
    "TrendlineFamilyFeatureProducer",
    "TrendlineFamilyShadowConfig",
    "WeightedFeatureScorer",
    "build_trendline_family_shadow_failure_payload",
    "evaluate_regime_feature_group_holdout",
    "run_regime_feature_ablation",
    "summarize_trendline_family_shadow_artifacts",
]
