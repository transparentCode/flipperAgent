from __future__ import annotations

from libs.integrations.trendline_regime_v2 import ablation as owner
from libs.models.trendline import optimization as canonical_package
from libs.models.trendline.optimization import ablation as canonical_module
from libs.models.trendline_family import optimization as family_package
from libs.models.trendline_family.optimization import ablation as family_module


_HISTORICAL_EXPORTS = (
    "FEATURE_GROUP_SPECS",
    "RegimeFeatureAblationEvaluator",
    "WeightedFeatureScorer",
    "evaluate_regime_feature_group_holdout",
    "run_regime_feature_ablation",
)


def test_historical_ablation_imports_preserve_integration_owned_identity() -> None:
    for name in _HISTORICAL_EXPORTS:
        expected = getattr(owner, name)
        assert getattr(canonical_package, name) is expected
        assert getattr(canonical_module, name) is expected
        assert getattr(family_package, name) is expected
        assert getattr(family_module, name) is expected
