from __future__ import annotations

import importlib.util
from pathlib import Path


_ROOT = Path(__file__).parents[3]
_REMOVED_MODULES = (
    ".".join(("libs", "integrations", "trendline_regime_v2")),
    ".".join(("libs", "integrations", "trendline_regime_v2", "ablation")),
    ".".join(("libs", "models", "trendline", "optimization", "ablation")),
    ".".join(("libs", "models", "trendline_family", "optimization", "ablation")),
)


def _find_spec_or_none(module_name: str):
    try:
        return importlib.util.find_spec(module_name)
    except ModuleNotFoundError:
        return None


def test_removed_ablation_modules_are_absent() -> None:
    removed_paths = (
        _ROOT / "src" / "libs" / "integrations" / "trendline_regime_v2",
        _ROOT / "src" / "libs" / "models" / "trendline" / "optimization" / "ablation.py",
        _ROOT / "src" / "libs" / "models" / "trendline_family" / "optimization" / "ablation.py",
    )

    assert all(_find_spec_or_none(module_name) is None for module_name in _REMOVED_MODULES)
    assert all(not path.exists() for path in removed_paths)


def test_optimization_exports_remain_core_only() -> None:
    from libs.models.trendline import optimization as canonical
    from libs.models.trendline_family import optimization as compatibility

    retired_names = (
        "FEATURE_GROUP_SPECS",
        "RegimeFeatureAblationEvaluator",
        "WeightedFeatureScorer",
        "evaluate_regime_feature_group_holdout",
        "run_regime_feature_ablation",
    )
    for name in retired_names:
        assert name not in canonical.__all__
        assert not hasattr(canonical, name)
        assert not hasattr(compatibility, name)

    assert canonical.CandidateGeometryEvaluator is compatibility.CandidateGeometryEvaluator
    assert canonical.FeatureGroup is compatibility.FeatureGroup
    assert callable(canonical.run_candidate_geometry_optimization)
