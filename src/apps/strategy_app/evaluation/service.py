from __future__ import annotations

import types
from dataclasses import dataclass
from typing import Any

from apps.strategy_app.evaluation.migration import log_migration_comparison
from apps.strategy_app.model_manager import ModelManager
from apps.strategy_app.scoring_model_manager import ScoringModelManager
from libs.contracts.schemas import FeatureVector
from libs.models.blender.ensemble import RegimeEnsembleBlender
from libs.selection.selection_layer import SelectionLayer


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
        selection_layer: SelectionLayer,
        logger: Any,
        blender: RegimeEnsembleBlender | None = None,
    ) -> None:
        self.asset = asset
        self.timeframe = timeframe
        self.model_manager = model_manager
        self.scoring_model_manager = scoring_model_manager
        self.selection_layer = selection_layer
        self.logger = logger
        self.blender = blender

    def validate_feature_coverage(self) -> None:
        self.model_manager.validate_feature_coverage()
        self.scoring_model_manager.validate_feature_coverage()

    def evaluate_feature_vector(self, feature_vec: FeatureVector) -> StrategyEvaluationResult:
        outputs = self.model_manager.evaluate(feature_vec)
        scoring_outputs = self.scoring_model_manager.evaluate(feature_vec)

        adapted_outputs = self.model_manager.evaluate_adapted(feature_vec)
        scoring_outputs.extend(adapted_outputs)

        native_scoring_outputs = self.model_manager.evaluate_scoring(feature_vec)
        scoring_outputs.extend(native_scoring_outputs)

        shadow_outputs = self.model_manager.evaluate_shadow(feature_vec)
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
        return StrategyEvaluationResult(feature_vector=feature_vec, selected=selected)

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
