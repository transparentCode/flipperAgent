"""Compatibility exports for moved RegimeV2/Trendline research composition."""

from libs.integrations.trendline_regime_v2.ablation import (
    FEATURE_GROUP_SPECS,
    FeatureGroupSpec,
    OfflineAblationScorer,
    RegimeFeatureAblationEvaluator,
    WeightedFeatureScorer,
    evaluate_regime_feature_group_holdout,
    run_regime_feature_ablation,
    scorer_identity,
)


__all__ = [
    "FEATURE_GROUP_SPECS",
    "FeatureGroupSpec",
    "OfflineAblationScorer",
    "RegimeFeatureAblationEvaluator",
    "WeightedFeatureScorer",
    "evaluate_regime_feature_group_holdout",
    "run_regime_feature_ablation",
    "scorer_identity",
]
