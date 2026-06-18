from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from libs.contracts.schemas import FeatureVector


@dataclass(frozen=True)
class StrategyDecisionView:
    feature_vector: FeatureVector
    runtime_metadata: dict[str, Any]


class StrategyDecisionViewAdapter:
    def __init__(
        self,
        *,
        decision_timeframe: str,
        trigger_timeframe: str,
        trigger_mode: str,
        base_timeframe: str,
    ) -> None:
        self.decision_timeframe = decision_timeframe
        self.trigger_timeframe = trigger_timeframe
        self.trigger_mode = trigger_mode
        self.base_timeframe = base_timeframe

    def adapt(self, feature_vec: FeatureVector) -> StrategyDecisionView:
        normalized = self._normalize_feature_vector_for_decision(feature_vec)
        return StrategyDecisionView(
            feature_vector=normalized,
            runtime_metadata=self._runtime_metadata_for_feature_vector(normalized),
        )

    def _runtime_metadata_for_feature_vector(self, feature_vec: FeatureVector) -> dict[str, Any]:
        transport = dict(feature_vec.features.get("ctx_transport", {}))
        source_feature_timeframe = str(
            transport.get("source_feature_timeframe")
            or transport.get("trigger_timeframe")
            or self.trigger_timeframe
            or feature_vec.timeframe
        )
        runtime_metadata: dict[str, Any] = {
            "decision_timeframe": str(
                transport.get("decision_timeframe") or self.decision_timeframe
            ),
            "trigger_timeframe": str(
                transport.get("trigger_timeframe") or self.trigger_timeframe
            ),
            "trigger_mode": str(transport.get("trigger_mode") or self.trigger_mode),
            "source_feature_timeframe": source_feature_timeframe,
            "base_timeframe": str(transport.get("base_timeframe") or self.base_timeframe),
        }
        if "decision_bar_closed" in transport:
            runtime_metadata["decision_bar_closed"] = transport["decision_bar_closed"]
        if "projection_mode" in transport:
            runtime_metadata["projection_mode"] = transport["projection_mode"]
        return runtime_metadata

    def _normalize_feature_vector_for_decision(self, feature_vec: FeatureVector) -> FeatureVector:
        if feature_vec.timeframe == self.decision_timeframe:
            return feature_vec.model_copy(update={"features": dict(feature_vec.features)})

        features = dict(feature_vec.features)
        transport = dict(features.get("ctx_transport", {}))
        transport.setdefault("base_timeframe", self.base_timeframe)
        transport["trigger_timeframe"] = self.trigger_timeframe
        transport["decision_timeframe"] = self.decision_timeframe
        transport["trigger_mode"] = self.trigger_mode
        transport["source_feature_timeframe"] = feature_vec.timeframe
        features["ctx_transport"] = transport
        return feature_vec.model_copy(
            update={
                "timeframe": self.decision_timeframe,
                "features": features,
            }
        )
