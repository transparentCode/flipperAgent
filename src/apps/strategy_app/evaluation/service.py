from __future__ import annotations

import types
from dataclasses import dataclass
from typing import Any

from apps.strategy_app.evaluation.migration import log_migration_comparison
from apps.strategy_app.model_manager import ModelManager
from apps.strategy_app.scoring_model_manager import ScoringModelManager
from libs.contracts.schemas import FeatureVector
from libs.contracts.signal import ScoringOutput
from libs.contracts.strategy_model import ModelDecision
from libs.models.blender.ensemble import RegimeEnsembleBlender
from libs.selection.selection_layer import SelectionLayer
from apps.strategy_app.models.unified_model_manager import UnifiedModelManager


@dataclass(frozen=True)
class StrategyEvaluationResult:
    feature_vector: FeatureVector
    selected: list[Any]


class StrategyEvaluationService:
    def __init__(
        self,
        *,
        asset: str,
        timeframe: str,
        model_manager: ModelManager,
        scoring_model_manager: ScoringModelManager,
        unified_model_manager: UnifiedModelManager | None = None,
        selection_layer: SelectionLayer,
        logger: Any,
        blender: RegimeEnsembleBlender | None = None,
    ) -> None:
        self.asset = asset
        self.timeframe = timeframe
        self.model_manager = model_manager
        self.scoring_model_manager = scoring_model_manager
        self.unified_model_manager = unified_model_manager
        self.selection_layer = selection_layer
        self.logger = logger
        self.blender = blender

    def validate_feature_coverage(self) -> None:
        self.model_manager.validate_feature_coverage()
        self.scoring_model_manager.validate_feature_coverage()
        if self.unified_model_manager is not None:
            self.unified_model_manager.validate_feature_coverage()

    def evaluate_feature_vector(self, feature_vec: FeatureVector) -> StrategyEvaluationResult:
        return self.evaluate_feature_vector_routed(feature_vec)

    def evaluate_feature_vector_routed(
        self,
        feature_vec: FeatureVector,
        *,
        allowed_model_names: set[str] | None = None,
        runtime_metadata: dict[str, Any] | None = None,
    ) -> StrategyEvaluationResult:
        outputs = self._filter_outputs(
            self.model_manager.evaluate(feature_vec),
            allowed_model_names,
        )
        scoring_outputs = self._filter_outputs(
            self.scoring_model_manager.evaluate(feature_vec),
            allowed_model_names,
        )

        adapted_outputs = self._filter_outputs(
            self.model_manager.evaluate_adapted(feature_vec),
            allowed_model_names,
        )
        scoring_outputs.extend(adapted_outputs)

        native_scoring_outputs = self._filter_outputs(
            self.model_manager.evaluate_scoring(feature_vec),
            allowed_model_names,
        )
        scoring_outputs.extend(native_scoring_outputs)
        unified_scoring_outputs = self._evaluate_unified_scoring_outputs(
            feature_vec,
            allowed_model_names=allowed_model_names,
            runtime_metadata=runtime_metadata,
        )
        scoring_outputs.extend(unified_scoring_outputs)

        shadow_outputs = self._filter_outputs(
            self.model_manager.evaluate_shadow(feature_vec),
            allowed_model_names,
        )
        log_migration_comparison(
            self.logger,
            asset=self.asset,
            timeframe=self.timeframe,
            adapted=adapted_outputs,
            shadow=shadow_outputs,
        )

        scoring_outputs = self._blend_outputs(feature_vec, scoring_outputs)
        selected = self.selection_layer.select(
            model_outputs=outputs,
            scoring_outputs=scoring_outputs,
            feature_vec=feature_vec,
        )
        if runtime_metadata:
            for result in selected:
                result.candidate.metadata.update(runtime_metadata)
        return StrategyEvaluationResult(feature_vector=feature_vec, selected=selected)

    def _evaluate_unified_scoring_outputs(
        self,
        feature_vec: FeatureVector,
        *,
        allowed_model_names: set[str] | None,
        runtime_metadata: dict[str, Any] | None,
    ) -> list[ScoringOutput]:
        if self.unified_model_manager is None:
            return []
        decisions = self.unified_model_manager.evaluate(
            feature_vec,
            runtime_metadata=runtime_metadata,
            allowed_model_names=allowed_model_names,
        )
        return [self._decision_to_scoring_output(decision) for decision in decisions]

    def _blend_outputs(
        self,
        feature_vec: FeatureVector,
        scoring_outputs: list[Any],
    ) -> list[Any]:
        if self.blender is None or not scoring_outputs:
            return scoring_outputs

        regime_snapshot = feature_vec.features.get("regime_snapshot")
        if regime_snapshot is None:
            return scoring_outputs

        regime_ns = types.SimpleNamespace(**regime_snapshot)
        blended = self.blender.blend(
            scoring_outputs=scoring_outputs,
            regime_features=regime_ns,
            mtf_agreement=feature_vec.features.get("mtf_agreement"),
        )
        if blended is None:
            return scoring_outputs
        return [blended]

    @staticmethod
    def _filter_outputs(outputs: list[Any], allowed_model_names: set[str] | None) -> list[Any]:
        if not allowed_model_names:
            return outputs
        return [
            output for output in outputs
            if getattr(output, "model_name", "") in allowed_model_names
        ]

    @staticmethod
    def _decision_to_scoring_output(decision: ModelDecision) -> ScoringOutput:
        return ScoringOutput(
            model_name=decision.model_name,
            asset=decision.asset,
            timeframe=decision.decision_timeframe,
            timestamp=decision.timestamp,
            edge_score=decision.score,
            conviction=decision.conviction,
            metadata={
                **decision.metadata,
                "_trigger_timeframe": decision.trigger_timeframe,
                "_direction_hint": decision.direction_hint,
            },
        )
