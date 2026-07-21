"""Shadow-only RegimeV2 feature-group ablation over immutable aligned frames."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from statistics import mean
from typing import Any, Mapping, Protocol, Sequence

import pandas as pd

from libs.models.trendline.configuration.contracts import ResolvedTrendlineFamilyConfig
from libs.models.trendline.contracts import ContractValidationError
from libs.models.trendline.optimization.contracts import (
    FeatureGroup,
    FinalistFreeze,
    HoldoutOpenAudit,
    MetricRecord,
    ObjectiveSpec,
    OptimizationStage,
    ParameterEffectAudit,
    PromotionDecision,
    StageEvaluationSpec,
    TrialConfig,
    TrialResult,
    TrialStatus,
    WindowResult,
    semantic_id,
)
from libs.models.trendline.optimization.contracts import _number, _text
from libs.models.trendline.optimization.evaluator import (
    HoldoutOpenRegistry,
    evaluate_holdout_once,
    run_validation_trial,
)
from libs.models.trendline.optimization.folds import (
    FoldPlan,
    HoldoutPlan,
    ImmutableHistoricalFrame,
    WalkForwardFold,
)
from libs.models.trendline.optimization.metrics import binary_classification_metrics, ratio_metric


@dataclass(frozen=True)
class FeatureGroupSpec:
    group: FeatureGroup
    fields: tuple[str, ...]

    def __post_init__(self) -> None:
        fields = tuple(self.fields)
        if len(fields) != len(set(fields)) or any(not isinstance(field, str) or not field for field in fields):
            raise ContractValidationError("feature group fields must be unique non-empty strings")
        object.__setattr__(self, "fields", tuple(sorted(fields)))


@dataclass(frozen=True)
class RegimeAblationEvaluationSpec:
    scorer_identity: str
    scorer_state_hash: str
    threshold: float
    label_column: str
    baseline_feature_hash: str
    shadow_feature_hash: str
    spec_version: str = "regime_ablation_evaluation_v1"

    def to_stage_spec(self) -> StageEvaluationSpec:
        return StageEvaluationSpec(
            stage=OptimizationStage.FEATURE_ABLATION,
            spec_type="regime_ablation_evaluation",
            semantic_inputs={
                "scorer_identity": _text(self.scorer_identity, field_name="scorer_identity"),
                "scorer_state_hash": _text(self.scorer_state_hash, field_name="scorer_state_hash"),
                "threshold": _number(self.threshold, field_name="ablation threshold", minimum=0.0),
                "label_column": _text(self.label_column, field_name="label_column"),
                "baseline_feature_hash": _text(self.baseline_feature_hash, field_name="baseline_feature_hash"),
                "shadow_feature_hash": _text(self.shadow_feature_hash, field_name="shadow_feature_hash"),
            },
            spec_version=self.spec_version,
        )


_BASE_GEOMETRY = (
    "trendline_family_valid",
    "trendline_family_coverage",
    "nearest_support_family_id",
    "nearest_resistance_family_id",
    "distance_to_support_line_atr",
    "distance_to_resistance_line_atr",
    "distance_to_support_zone_atr",
    "distance_to_resistance_zone_atr",
)
_FAMILY_IDENTITY = (
    "trendline_family_count_active",
    "trendline_family_count_dormant",
    "trendline_family_births",
    "trendline_family_updates",
    "trendline_family_dormancies",
    "trendline_family_reactivations",
    "trendline_family_expiries",
    "trendline_family_churn_count",
    "trendline_family_churn_rate",
    "trendline_family_generated_candidate_count",
    "trendline_family_matched_count",
    "trendline_family_rejected_birth_count",
)
_INTERACTIONS = (
    "support_interaction_state",
    "resistance_interaction_state",
    "support_wick_penetration_atr",
    "resistance_wick_penetration_atr",
    "support_body_penetration_atr",
    "resistance_body_penetration_atr",
    "support_close_penetration_atr",
    "resistance_close_penetration_atr",
)
_EVENTS = (
    "trendline_family_event_count",
    "trendline_family_event_transition_count",
    "trendline_family_break_pending_count",
    "trendline_family_break_confirmed_count",
    "trendline_family_retest_pending_count",
    "trendline_family_retest_success_count",
    "trendline_family_failed_break_count",
    "trendline_family_role_reversal_count",
    "support_event_state",
    "resistance_event_state",
    "support_event_age_bars",
    "resistance_event_age_bars",
    "support_pressure_bars",
    "resistance_pressure_bars",
    "support_close_beyond_streak",
    "resistance_close_beyond_streak",
)
_MULTI_RAIL = (
    "trendline_family_corridor_count",
    "trendline_family_singleton_count",
    "trendline_family_multi_rail_count",
    "trendline_family_total_rail_count",
    "support_rail_count",
    "resistance_rail_count",
    "support_corridor_width_atr",
    "resistance_corridor_width_atr",
    "support_spacing_stability",
    "resistance_spacing_stability",
    "support_nearest_rail_distance_atr",
    "resistance_nearest_rail_distance_atr",
)
_MTF = (
    "mtf.enabled",
    "mtf.source_timeframe_count",
    "mtf.fresh_source_count",
    "mtf.stale_included_source_count",
    "mtf.stale_excluded_source_count",
    "mtf.projected_family_count",
    "mtf.confluence_cluster_count",
    "mtf.conflict_relation_count",
    "mtf.agreement_relation_count",
    "mtf.intersection_relation_count",
    "mtf.support_confluence_strength",
    "mtf.resistance_confluence_strength",
)

FEATURE_GROUP_SPECS: Mapping[FeatureGroup, FeatureGroupSpec] = {
    FeatureGroup.BASELINE: FeatureGroupSpec(FeatureGroup.BASELINE, ()),
    FeatureGroup.BASE_GEOMETRY: FeatureGroupSpec(FeatureGroup.BASE_GEOMETRY, _BASE_GEOMETRY),
    FeatureGroup.FAMILY_IDENTITY_LIFECYCLE: FeatureGroupSpec(FeatureGroup.FAMILY_IDENTITY_LIFECYCLE, _FAMILY_IDENTITY),
    FeatureGroup.INTERACTION_OBSERVATIONS: FeatureGroupSpec(FeatureGroup.INTERACTION_OBSERVATIONS, _INTERACTIONS),
    FeatureGroup.FULL_EVENTS: FeatureGroupSpec(FeatureGroup.FULL_EVENTS, _EVENTS),
    FeatureGroup.MULTI_RAIL: FeatureGroupSpec(FeatureGroup.MULTI_RAIL, _MULTI_RAIL),
    FeatureGroup.MTF: FeatureGroupSpec(FeatureGroup.MTF, _MTF),
}
FEATURE_GROUP_SPECS = {
    **FEATURE_GROUP_SPECS,
    FeatureGroup.ALL_TRENDLINE_FAMILY: FeatureGroupSpec(
        FeatureGroup.ALL_TRENDLINE_FAMILY,
        tuple(
            sorted(
                set().union(
                    *(
                        spec.fields
                        for group, spec in FEATURE_GROUP_SPECS.items()
                        if group is not FeatureGroup.BASELINE
                    )
                )
            )
        ),
    ),
}


class OfflineAblationScorer(Protocol):
    """Caller-supplied offline scorer. It must not mutate or call active runtime objects."""

    def score(self, features: pd.DataFrame, *, feature_columns: tuple[str, ...]) -> Sequence[float]: ...


@dataclass(frozen=True)
class WeightedFeatureScorer:
    """Deterministic test/research probe, not a trained or active RegimeV2 model."""

    weights: Mapping[str, float]
    intercept: float = 0.0

    def __post_init__(self) -> None:
        if any(not isinstance(key, str) or not key for key in self.weights):
            raise ContractValidationError("ablation scorer weights require non-empty string fields")
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) for value in self.weights.values()):
            raise ContractValidationError("ablation scorer weights must be finite numeric")
        if not isinstance(self.intercept, (int, float)) or isinstance(self.intercept, bool) or not math.isfinite(float(self.intercept)):
            raise ContractValidationError("ablation scorer intercept must be finite numeric")

    def score(self, features: pd.DataFrame, *, feature_columns: tuple[str, ...]) -> Sequence[float]:
        raw = pd.Series(float(self.intercept), index=features.index, dtype=float)
        for column in feature_columns:
            weight = float(self.weights.get(column, 0.0))
            if weight == 0.0:
                continue
            raw += pd.to_numeric(features[column], errors="coerce").fillna(0.0).astype(float) * weight
        return (1.0 / (1.0 + (-raw.clip(-30.0, 30.0)).map(math.exp))).to_list()


def scorer_identity(scorer: OfflineAblationScorer) -> str:
    """Return persisted scorer identity without invalidating prior ablation artifacts."""

    if isinstance(scorer, WeightedFeatureScorer):
        return "libs.models.trendline_family.optimization.ablation.WeightedFeatureScorer"
    return f"{scorer.__class__.__module__}.{scorer.__class__.__qualname__}"


class RegimeFeatureAblationEvaluator:
    """Aligned, immutable feature evaluation; active RegimeV2 remains unmodified."""

    def __init__(
        self,
        *,
        dataset: ImmutableHistoricalFrame,
        active_baseline_features: pd.DataFrame,
        shadow_features: pd.DataFrame,
        label_column: str,
        scorer: OfflineAblationScorer,
        threshold: float = 0.5,
    ) -> None:
        # Protocol runtime checks are not reliable for data callables.
        if not callable(getattr(scorer, "score", None)):
            raise ContractValidationError("ablation scorer must expose score")
        if not isinstance(label_column, str) or not label_column or label_column not in dataset.to_frame().columns:
            raise ContractValidationError("ablation label_column must exist in immutable dataset")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0.0 <= float(threshold) <= 1.0:
            raise ContractValidationError("ablation threshold must be in [0, 1]")
        self.dataset = dataset
        self.baseline = _aligned_frame(active_baseline_features, dataset, owner="active baseline features")
        self.shadow = _aligned_frame(shadow_features, dataset, owner="shadow features")
        declared = set().union(*(spec.fields for spec in FEATURE_GROUP_SPECS.values()))
        leaked = declared & set(self.baseline.columns)
        if leaked:
            raise ContractValidationError("approved active baseline input must not contain trendline-family shadow fields")
        self.label_column = label_column
        self.scorer = scorer
        self.threshold = float(threshold)

    def evaluation_spec(self) -> StageEvaluationSpec:
        scorer_identity_value = scorer_identity(self.scorer)
        scorer_state = getattr(self.scorer, "__dict__", None)
        if not isinstance(scorer_state, Mapping):
            raise ContractValidationError("offline ablation scorer must expose immutable semantic state")
        return RegimeAblationEvaluationSpec(
            scorer_identity=scorer_identity_value,
            scorer_state_hash=semantic_id("ablation-scorer-state", scorer_state),
            threshold=self.threshold,
            label_column=self.label_column,
            baseline_feature_hash=_feature_frame_hash(self.baseline),
            shadow_feature_hash=_feature_frame_hash(self.shadow),
        ).to_stage_spec()

    def __call__(
        self,
        trial: TrialConfig,
        config: ResolvedTrendlineFamilyConfig,
        window: WalkForwardFold | HoldoutPlan,
        window_kind: str,
    ) -> WindowResult:
        del config
        if trial.stage is not OptimizationStage.FEATURE_ABLATION:
            raise ContractValidationError("ablation evaluator only accepts regime_ablation trials")
        context_group = trial.evaluation_context.get("feature_group")
        try:
            group = FeatureGroup(context_group)
        except (TypeError, ValueError) as exc:
            raise ContractValidationError("ablation trial must bind typed feature_group") from exc
        bounds = window.validation if isinstance(window, WalkForwardFold) else window.window
        positions = range(bounds.start_position, bounds.end_position + 1)
        index = self.dataset.to_frame().index[list(positions)]
        spec = FEATURE_GROUP_SPECS[group]
        missing_fields = tuple(field for field in spec.fields if field not in self.shadow.columns)
        labels = self.dataset.to_frame().loc[index, self.label_column]
        valid_labels = labels.notna()
        if missing_fields:
            return _missing_group_window(
                trial=trial,
                window=window,
                window_kind=window_kind,
                group=group,
                missing_fields=missing_fields,
                evaluated_bar_count=len(index),
                source_fingerprint=self.dataset.dataset_hash,
            )
        selected_shadow = self.shadow.loc[index, list(spec.fields)].copy(deep=True)
        valid_features = selected_shadow.notna().all(axis=1) if spec.fields else pd.Series(True, index=index)
        mask = valid_labels & valid_features
        base = self.baseline.loc[index].copy(deep=True)
        joined = base.join(selected_shadow)
        columns = tuple(base.columns) + spec.fields
        scores = pd.Series(self.scorer.score(joined.loc[mask, list(columns)], feature_columns=columns), index=joined.index[mask], dtype=float)
        if len(scores) != int(mask.sum()) or not scores.map(math.isfinite).all() or ((scores < 0.0) | (scores > 1.0)).any():
            raise ContractValidationError("offline ablation scorer must return finite scores in [0, 1]")
        raw_truth = labels.loc[mask]
        if not raw_truth.isin((True, False, 0, 1, 0.0, 1.0)).all():
            raise ContractValidationError("ablation labels must be boolean or binary")
        truth = raw_truth.astype(bool).to_list()
        predictions = (scores >= self.threshold).to_list()
        metrics = _ablation_metrics(truth=truth, scores=scores.to_list(), predictions=predictions, total_rows=len(index), excluded=int((~mask).sum()))
        evaluated_index_hash = semantic_id("ablation-sample-population", tuple(timestamp.to_pydatetime() for timestamp in joined.index[mask]))
        return WindowResult(
            trial_id=trial.trial_id,
            fold_id=window.fold_id if isinstance(window, WalkForwardFold) else window.holdout_plan_id,
            window_kind=window_kind,
            metrics=metrics,
            evaluated_bar_count=len(index),
            excluded_reasons={"missing_label_or_feature": int((~mask).sum())},
            diagnostics={
                "feature_group": group.value,
                "declared_feature_fields": spec.fields,
                "stage_output_fingerprint": semantic_id("ablation-stage-output", {"scores": scores.to_list(), "group": group.value}),
                "forbidden_output_fingerprint": self.dataset.dataset_hash,
                "evaluated_index_hash": evaluated_index_hash,
                "missingness": {column: int(selected_shadow[column].isna().sum()) for column in spec.fields},
            },
        )


def run_regime_feature_ablation(
    *,
    dataset: ImmutableHistoricalFrame,
    fold_plan: FoldPlan,
    baseline_config: ResolvedTrendlineFamilyConfig,
    objective: ObjectiveSpec,
    evaluator: RegimeFeatureAblationEvaluator,
    groups: Sequence[FeatureGroup | str] = tuple(FeatureGroup),
    seed: int = 0,
) -> Mapping[FeatureGroup, TrialResult]:
    """Run independent shadow groups. No group modifies active RegimeV2 inputs or config."""

    requested = {FeatureGroup(group) for group in groups}
    normalized = (FeatureGroup.BASELINE,) + tuple(
        sorted((group for group in requested if group is not FeatureGroup.BASELINE), key=lambda group: group.value)
    )
    results: dict[FeatureGroup, TrialResult] = {}
    baseline: TrialResult | None = None
    for group in normalized:
        trial = TrialConfig(
            stage=OptimizationStage.FEATURE_ABLATION,
            asset=dataset.asset,
            timeframe=dataset.timeframe,
            parameter_overrides={},
            baseline_config_hash=baseline_config.resolved_config_hash,
            dataset_hash=dataset.dataset_hash,
            fold_plan_id=fold_plan.fold_plan_id,
            objective=objective,
            model_version=baseline_config.model_version,
            config_version=baseline_config.config_version,
            seed=seed,
            evaluation_context={"feature_group": group.value, "feature_group_fields": FEATURE_GROUP_SPECS[group].fields},
            evaluation_spec=evaluator.evaluation_spec(),
        )
        result = run_validation_trial(trial=trial, config=baseline_config, fold_plan=fold_plan, evaluator=evaluator)
        if group is FeatureGroup.BASELINE:
            baseline = result
        elif baseline is not None and result.status is TrialStatus.COMPLETED:
            counter_trial = replace(
                result.trial,
                evaluation_context={
                    "feature_group": FeatureGroup.BASELINE.value,
                    "feature_group_fields": FEATURE_GROUP_SPECS[FeatureGroup.BASELINE].fields,
                },
                trial_kind="counterfactual",
                counterfactual_of_trial_id=result.trial.trial_id,
                reverted_parameter="feature_group",
                trial_config_hash=None,
                trial_id=None,
            )
            counterfactual = run_validation_trial(
                trial=counter_trial, config=baseline_config, fold_plan=fold_plan, evaluator=evaluator
            )
            result = _attach_feature_group_audit(
                result=result, group=group, counterfactual=counterfactual
            )
        results[group] = result
    return results


def evaluate_regime_feature_group_holdout(
    *,
    validation_result: TrialResult,
    baseline_config: ResolvedTrendlineFamilyConfig,
    fold_plan: FoldPlan,
    evaluator: RegimeFeatureAblationEvaluator,
    finalist_freeze: FinalistFreeze,
    holdout_open_audit: HoldoutOpenAudit,
    holdout_open_registry: HoldoutOpenRegistry,
) -> TrialResult:
    """Open one frozen group on holdout without changing validation selection."""

    if validation_result.trial.stage is not OptimizationStage.FEATURE_ABLATION:
        raise ContractValidationError("holdout result must be regime_ablation")
    return evaluate_holdout_once(
        validation_finalist=validation_result,
        baseline_config=baseline_config,
        fold_plan=fold_plan,
        evaluator=evaluator,
        finalist_freeze=finalist_freeze,
        holdout_open_audit=holdout_open_audit,
        holdout_open_registry=holdout_open_registry,
    )


def _attach_feature_group_audit(*, result: TrialResult, group: FeatureGroup, counterfactual: TrialResult) -> TrialResult:
    baseline_fingerprint = _result_diagnostic(counterfactual, "stage_output_fingerprint")
    result_fingerprint = _result_diagnostic(result, "stage_output_fingerprint")
    baseline_source = _result_diagnostic(counterfactual, "forbidden_output_fingerprint")
    result_source = _result_diagnostic(result, "forbidden_output_fingerprint")
    audit = ParameterEffectAudit(
        parameter_name="feature_group",
        owning_stage=OptimizationStage.FEATURE_ABLATION,
        baseline_value=FeatureGroup.BASELINE.value,
        trial_value=group.value,
        expected_affected_outputs=("stage_output_fingerprint",),
        observed_changed_outputs=("stage_output_fingerprint",) if baseline_fingerprint != result_fingerprint else (),
        forbidden_outputs_checked=("forbidden_output_fingerprint",),
        effect_detected=baseline_fingerprint != result_fingerprint,
        leakage_detected=baseline_source != result_source,
        decision=(PromotionDecision.PROMOTE if baseline_fingerprint != result_fingerprint and baseline_source == result_source else PromotionDecision.REJECT),
        counterfactual_trial_id=counterfactual.trial.trial_id,
        counterfactual_result_id=counterfactual.result_id,
    )
    return TrialResult(
        trial=result.trial,
        status=result.status,
        window_results=result.window_results,
        aggregate_metrics=result.aggregate_metrics,
        parameter_effect_audits=(audit,),
        failure_code=result.failure_code,
        failure_reason=result.failure_reason,
        runtime_diagnostics=result.runtime_diagnostics,
        objective_gate=result.objective_gate,
        counterfactual_results=(counterfactual,),
    )


def _missing_group_window(*, trial, window, window_kind, group, missing_fields, evaluated_bar_count, source_fingerprint):
    metrics = (
        MetricRecord("balanced_accuracy", value=None, undefined_reason="required_shadow_fields_missing"),
        MetricRecord("macro_f1", value=None, undefined_reason="required_shadow_fields_missing"),
        MetricRecord("brier_score", value=None, undefined_reason="required_shadow_fields_missing"),
        MetricRecord("log_loss", value=None, undefined_reason="required_shadow_fields_missing"),
        MetricRecord("expected_calibration_error", value=None, undefined_reason="required_shadow_fields_missing"),
    )
    return WindowResult(
        trial_id=trial.trial_id,
        fold_id=window.fold_id if isinstance(window, WalkForwardFold) else window.holdout_plan_id,
        window_kind=window_kind,
        metrics=metrics,
        evaluated_bar_count=evaluated_bar_count,
        excluded_reasons={f"missing_shadow_field:{field}": evaluated_bar_count for field in missing_fields},
        diagnostics={
            "feature_group": group.value,
            "declared_feature_fields": FEATURE_GROUP_SPECS[group].fields,
            "missing_shadow_fields": missing_fields,
            "stage_output_fingerprint": semantic_id("ablation-missing-group", {"group": group.value, "fields": missing_fields}),
            "forbidden_output_fingerprint": source_fingerprint,
        },
    )


def _aligned_frame(frame: pd.DataFrame, dataset: ImmutableHistoricalFrame, *, owner: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise ContractValidationError(f"{owner} must be a DataFrame")
    expected = dataset.to_frame().index
    if not frame.index.equals(expected) or frame.index.has_duplicates:
        raise ContractValidationError(f"{owner} must exactly align to immutable dataset timestamps")
    return frame.copy(deep=True)


def _ablation_metrics(*, truth: list[bool], scores: list[float], predictions: list[bool], total_rows: int, excluded: int) -> tuple[MetricRecord, ...]:
    if not truth:
        return (
            MetricRecord("balanced_accuracy", value=None, sample_count=total_rows, excluded_row_count=excluded, undefined_reason="no_evaluated_rows"),
            MetricRecord("macro_f1", value=None, sample_count=total_rows, excluded_row_count=excluded, undefined_reason="no_evaluated_rows"),
            MetricRecord("brier_score", value=None, sample_count=total_rows, excluded_row_count=excluded, undefined_reason="no_evaluated_rows"),
            MetricRecord("log_loss", value=None, sample_count=total_rows, excluded_row_count=excluded, undefined_reason="no_evaluated_rows"),
            MetricRecord("expected_calibration_error", value=None, sample_count=total_rows, excluded_row_count=excluded, undefined_reason="no_evaluated_rows"),
        )
    classification = binary_classification_metrics(labels=truth, predictions=predictions)
    positive = sum(truth)
    negative = len(truth) - positive
    sensitivity = next(metric.value for metric in classification if metric.name == "recall")
    specificity = next(metric.value for metric in classification if metric.name == "specificity")
    balanced = None if sensitivity is None or specificity is None else (sensitivity + specificity) / 2.0
    macro_f1 = next(metric.value for metric in classification if metric.name == "macro_f1")
    brier = mean((score - float(label)) ** 2 for score, label in zip(scores, truth, strict=True))
    log_loss = -mean(
        float(label) * math.log(max(score, 1e-12)) + (1.0 - float(label)) * math.log(max(1.0 - score, 1e-12))
        for score, label in zip(scores, truth, strict=True)
    )
    ece = _ece(scores, truth)
    return (
        MetricRecord("balanced_accuracy", value=balanced, sample_count=total_rows, valid_row_count=len(truth), excluded_row_count=excluded, undefined_reason=None if balanced is not None else "one_class_sample"),
        MetricRecord("macro_f1", value=macro_f1, sample_count=total_rows, valid_row_count=len(truth), excluded_row_count=excluded, undefined_reason=None if macro_f1 is not None else "undefined_class_f1"),
        MetricRecord("brier_score", value=brier, sample_count=total_rows, valid_row_count=len(truth), excluded_row_count=excluded),
        MetricRecord("log_loss", value=log_loss, sample_count=total_rows, valid_row_count=len(truth), excluded_row_count=excluded),
        MetricRecord("expected_calibration_error", value=ece, sample_count=total_rows, valid_row_count=len(truth), excluded_row_count=excluded),
        ratio_metric("positive_label_rate", numerator=positive, denominator=len(truth), sample_count=total_rows, valid_row_count=len(truth), excluded_row_count=excluded),
        ratio_metric("negative_label_rate", numerator=negative, denominator=len(truth), sample_count=total_rows, valid_row_count=len(truth), excluded_row_count=excluded),
    )


def _ece(scores: list[float], labels: list[bool], bins: int = 10) -> float:
    total = len(scores)
    error = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        values = [
            (score, label)
            for score, label in zip(scores, labels, strict=True)
            if low <= score and (score <= high if index == bins - 1 else score < high)
        ]
        if not values:
            continue
        confidence = mean(score for score, _ in values)
        accuracy = mean(float(label) for _, label in values)
        error += len(values) / total * abs(confidence - accuracy)
    return error


def _result_diagnostic(result: TrialResult, key: str) -> str:
    return semantic_id("ablation-audit-diagnostic", [window.diagnostics.get(key) for window in result.window_results])


def _feature_frame_hash(frame: pd.DataFrame) -> str:
    """Bind feature values and index exactly without retaining caller-owned frames."""

    return semantic_id(
        "ablation-feature-frame",
        {
            "columns": tuple(str(column) for column in frame.columns),
            "index": tuple(timestamp.to_pydatetime() for timestamp in frame.index),
            "rows": tuple(
                tuple(None if pd.isna(value) else _feature_scalar(value) for value in row)
                for row in frame.itertuples(index=False, name=None)
            ),
        },
    )


def _feature_scalar(value: Any) -> Any:
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    return str(value)


__all__ = [
    "FEATURE_GROUP_SPECS",
    "FeatureGroupSpec",
    "OfflineAblationScorer",
    "RegimeFeatureAblationEvaluator",
    "WeightedFeatureScorer",
    "evaluate_regime_feature_group_holdout",
    "run_regime_feature_ablation",
]
