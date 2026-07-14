from __future__ import annotations

import pandas as pd

from libs.models.trendline_family.optimization.ablation import FEATURE_GROUP_SPECS, RegimeFeatureAblationEvaluator, WeightedFeatureScorer, run_regime_feature_ablation
from libs.models.trendline_family.optimization.contracts import FeatureGroup, ObjectiveSpec
from libs.models.trendline_family.optimization.folds import build_walk_forward_fold_plan

from .support import dataset, resolved_config


def test_shadow_feature_ablation_uses_declared_groups_without_active_mutation() -> None:
    source = dataset(rows=64)
    base = pd.DataFrame({"base_signal": [0.0] * source.row_count}, index=source.to_frame().index)
    shadow_columns = {
        field: [0.5] * source.row_count
        for field in FEATURE_GROUP_SPECS[FeatureGroup.BASE_GEOMETRY].fields
    }
    shadow_columns["distance_to_support_line_atr"] = [1.0 if index % 5 == 0 else -1.0 for index in range(source.row_count)]
    shadow = pd.DataFrame(shadow_columns, index=source.to_frame().index)
    base_before = base.copy(deep=True)
    evaluator = RegimeFeatureAblationEvaluator(
        dataset=source,
        active_baseline_features=base,
        shadow_features=shadow,
        label_column="event_label",
        scorer=WeightedFeatureScorer({"distance_to_support_line_atr": 2.0}),
    )
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=3, holdout_bars=8, warmup_bars=4)
    results = run_regime_feature_ablation(
        dataset=source,
        fold_plan=plan,
        baseline_config=resolved_config(),
        objective=ObjectiveSpec("ablation-v1", "balanced_accuracy"),
        evaluator=evaluator,
        groups=(FeatureGroup.BASELINE, FeatureGroup.BASE_GEOMETRY),
    )

    assert base.equals(base_before)
    assert results[FeatureGroup.BASELINE].trial.evaluation_context["feature_group"] == "baseline"
    audit = results[FeatureGroup.BASE_GEOMETRY].parameter_effect_audits[0]
    assert audit.effect_detected and not audit.leakage_detected
    assert set(FEATURE_GROUP_SPECS[FeatureGroup.ALL_TRENDLINE_FAMILY].fields).issuperset(
        FEATURE_GROUP_SPECS[FeatureGroup.BASE_GEOMETRY].fields
    )


def test_missing_shadow_fields_have_typed_exclusion_evidence() -> None:
    source = dataset(rows=56)
    base = pd.DataFrame({"base_signal": [0.0] * source.row_count}, index=source.to_frame().index)
    evaluator = RegimeFeatureAblationEvaluator(
        dataset=source,
        active_baseline_features=base,
        shadow_features=pd.DataFrame(index=base.index),
        label_column="event_label",
        scorer=WeightedFeatureScorer({}),
    )
    plan = build_walk_forward_fold_plan(source, initial_train_bars=18, validation_bars=8, fold_count=2, holdout_bars=8, warmup_bars=4)
    result = run_regime_feature_ablation(
        dataset=source,
        fold_plan=plan,
        baseline_config=resolved_config(),
        objective=ObjectiveSpec("ablation-v1", "balanced_accuracy"),
        evaluator=evaluator,
        groups=(FeatureGroup.MTF,),
    )[FeatureGroup.MTF]
    assert any("missing_shadow_field" in key for window in result.window_results for key in window.excluded_reasons)
