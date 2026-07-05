"""Adapters for integrating RegimeV2 with application pipelines."""

from libs.models.regime_v2.adapters.feature_producer import (
    RegimeV2FeatureProducer,
    regime_v2_output_to_dict,
)
from libs.models.regime_v2.adapters.trendline_feature_producer import (
    TrendlineFeatureConfig,
    TrendlineFeatureProducer,
    compute_trendline_context_features,
)

__all__ = [
    "RegimeV2FeatureProducer",
    "TrendlineFeatureConfig",
    "TrendlineFeatureProducer",
    "compute_trendline_context_features",
    "regime_v2_output_to_dict",
]
