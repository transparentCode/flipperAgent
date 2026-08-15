"""Unified strategy-model manager for canonical and bridged legacy models."""

from __future__ import annotations

from typing import Any

from apps.strategy_app.feature_contracts import build_available_feature_contract
from apps.strategy_app.settings import (
    create_strategy_config_manager,
    resolve_asset_timeframe_node,
)
from libs.common.config import ConfigManager
from libs.common.enums import SystemComponent
from libs.common.exceptions import ConfigurationError
from libs.common.logging.logger_utils import bind_logger
from libs.contracts.signal import FeatureVector
from libs.contracts.strategy_model import (
    ModelDecision,
    ModelExecutionContext,
    ModelInputContract,
    ModelTriggerSpec,
)
from libs.models.base import BaseModel
from libs.models.legacy_bootstrap import bootstrap_legacy_model_registries
from libs.models.registry import ModelRegistry
from libs.models.scoring_base import ScoringModel
from libs.models.strategy_adapters import (
    LegacyBaseModelAdapter,
    LegacyScoringModelAdapter,
)
from libs.models.strategy_model_v2 import StrategyModelV2
from libs.models.strategy_registry import StrategyModelRegistry

logger = bind_logger(__name__, system_component=SystemComponent.MODEL_STRATEGY)

KEY_STRATEGY_MODELS = "strategy_models"
KEY_MODELS = "models"
KEY_SCORING_MODELS = "scoring_models"
KEY_FEATURES = "features"
KEY_ENGINEERED_FEATURES = "engineered_features"


class UnifiedModelManager:
    """Loads canonical strategy models and optionally bridges legacy ones."""

    def __init__(
        self,
        asset: str,
        timeframe: str,
        *,
        config_manager: ConfigManager | None = None,
        bridge_legacy_roots: bool = True,
    ) -> None:
        self.asset = asset
        self.timeframe = timeframe
        bootstrap_legacy_model_registries()
        self.config_mgr = create_strategy_config_manager(config_manager or ConfigManager())
        self.bridge_legacy_roots = bridge_legacy_roots
        self.models: list[StrategyModelV2] = []
        self.runtime_specs: dict[str, ModelTriggerSpec] = {}
        self._load_models()

    def _resolve_config_node(self, root_key: str) -> dict[str, Any]:
        return resolve_asset_timeframe_node(
            self.config_mgr,
            root_key,
            self.asset,
            self.timeframe,
        )

    def _load_models(self) -> None:
        self._load_canonical_models()
        if self.bridge_legacy_roots:
            self._load_legacy_scoring_models()
            self._load_legacy_direction_models()

    def _load_canonical_models(self) -> None:
        models_node = self._resolve_config_node(KEY_STRATEGY_MODELS)
        for model_name, model_cfg in models_node.items():
            if not isinstance(model_cfg, dict) or not model_cfg.get("enabled", True):
                continue
            try:
                model_cls = StrategyModelRegistry.get(model_name)
            except KeyError:
                logger.warning("Strategy model '%s' not found in canonical registry, skipping.", model_name)
                continue
            instance = model_cls(model_cfg.get("params", {}) or {})
            if not isinstance(instance, StrategyModelV2):
                raise ConfigurationError(
                    f"Strategy model '{model_name}' for {self.asset}/{self.timeframe} "
                    f"must extend StrategyModelV2, got {type(instance).__name__}"
                )
            instance.trigger = _resolve_trigger(model_cfg, instance.trigger, default_timeframe=self.timeframe)
            self.runtime_specs[model_name] = instance.trigger
            self.models.append(instance)
            logger.info("Loaded canonical strategy model %s for %s/%s", model_name, self.asset, self.timeframe)

    def _load_legacy_scoring_models(self) -> None:
        models_node = self._resolve_config_node(KEY_SCORING_MODELS)
        for model_name, model_cfg in models_node.items():
            if not isinstance(model_cfg, dict) or not model_cfg.get("enabled", True):
                continue
            try:
                model_cls = ModelRegistry.get(model_name)
            except KeyError:
                logger.warning("Legacy scoring model '%s' not found in registry, skipping.", model_name)
                continue
            wrapped = model_cls(model_cfg.get("params", {}) or {})
            if not isinstance(wrapped, ScoringModel):
                raise ConfigurationError(
                    f"Legacy scoring model '{model_name}' for {self.asset}/{self.timeframe} "
                    f"must extend ScoringModel, got {type(wrapped).__name__}"
                )
            trigger = _resolve_trigger(model_cfg, _default_trigger(self.timeframe), default_timeframe=self.timeframe)
            adapter = LegacyScoringModelAdapter(
                wrapped,
                trigger=trigger,
                inputs=_inputs_from_legacy_meta(wrapped),
            )
            self.runtime_specs[model_name] = adapter.trigger
            self.models.append(adapter)

    def _load_legacy_direction_models(self) -> None:
        models_node = self._resolve_config_node(KEY_MODELS)
        for model_name, model_cfg in models_node.items():
            if not isinstance(model_cfg, dict) or not model_cfg.get("enabled", True):
                continue
            migration_mode = str(model_cfg.get("migration_mode", "legacy"))
            if migration_mode == "native_scoring":
                continue
            try:
                model_cls = ModelRegistry.get(model_name)
            except KeyError:
                logger.warning("Legacy model '%s' not found in registry, skipping.", model_name)
                continue
            wrapped = model_cls(model_cfg.get("params", {}) or {})
            trigger = _resolve_trigger(model_cfg, _default_trigger(self.timeframe), default_timeframe=self.timeframe)
            if isinstance(wrapped, ScoringModel) and migration_mode == "scoring":
                adapter = LegacyScoringModelAdapter(
                    wrapped,
                    trigger=trigger,
                    inputs=_inputs_from_legacy_meta(wrapped),
                )
            elif isinstance(wrapped, BaseModel):
                adapter = LegacyBaseModelAdapter(
                    wrapped,
                    trigger=trigger,
                    inputs=_inputs_from_legacy_meta(wrapped),
                )
            else:
                raise ConfigurationError(
                    f"Legacy model '{model_name}' for {self.asset}/{self.timeframe} "
                    f"must extend BaseModel, got {type(wrapped).__name__}"
                )
            self.runtime_specs[model_name] = adapter.trigger
            self.models.append(adapter)

    def validate_feature_coverage(self, available_features: set[str] | None = None) -> None:
        if available_features is None:
            available_features = self._available_features_from_config()

        for model in self.models:
            missing = model.validate_feature_coverage(available_features)
            if missing:
                raise ConfigurationError(
                    f"Strategy model '{model.spec.name}' for {self.asset}/{self.timeframe} requires "
                    f"{missing} but features.yaml only provides {sorted(available_features)}"
                )
            missing_fields = model.validate_required_fields(available_features)
            missing_engineered_fields = sorted(
                field_name for field_name in missing_fields if field_name.startswith("eng_")
            )
            if missing_engineered_fields:
                raise ConfigurationError(
                    f"Strategy model '{model.spec.name}' for {self.asset}/{self.timeframe} requires "
                    f"engineered fields {missing_engineered_fields} but engineered features are not configured"
                )

    def _available_features_from_config(self) -> set[str]:
        features_node = self._resolve_config_node(KEY_FEATURES)
        engineered_node = self._resolve_config_node(KEY_ENGINEERED_FEATURES)
        return build_available_feature_contract(features_node, engineered_node)

    def evaluate(
        self,
        feature_vector: FeatureVector,
        *,
        runtime_metadata: dict[str, Any] | None = None,
        context_views: dict[str, Any] | None = None,
        bar_views: dict[str, Any] | None = None,
        allowed_model_names: set[str] | None = None,
    ) -> list[ModelDecision]:
        context = ModelExecutionContext(
            feature_vector=feature_vector,
            runtime_metadata=runtime_metadata or {},
            context_views=context_views or {},
            bar_views=bar_views or {},
        )
        outputs: list[ModelDecision] = []
        for model in self.models:
            if allowed_model_names and model.spec.name not in allowed_model_names:
                continue
            try:
                outputs.append(model.evaluate(context))
            except Exception as exc:
                logger.error("Strategy model %s failed: %s", model.spec.name, exc, exc_info=True)
        return outputs


def _default_trigger(timeframe: str) -> ModelTriggerSpec:
    return ModelTriggerSpec(decision_timeframe=timeframe, base_timeframe="1m")


def _resolve_trigger(
    model_cfg: dict[str, Any],
    default_trigger: ModelTriggerSpec,
    *,
    default_timeframe: str,
) -> ModelTriggerSpec:
    runtime_cfg = model_cfg.get("runtime", {}) if isinstance(model_cfg, dict) else {}
    return ModelTriggerSpec(
        decision_timeframe=str(runtime_cfg.get("decision_timeframe", default_trigger.decision_timeframe or default_timeframe)),
        base_timeframe=str(runtime_cfg.get("base_timeframe", default_trigger.base_timeframe or "1m")),
        trigger_mode=runtime_cfg.get("trigger_mode", default_trigger.trigger_mode),
        trigger_timeframe=runtime_cfg.get("trigger_timeframe", default_trigger.trigger_timeframe),
    )


def _inputs_from_legacy_meta(wrapped: BaseModel) -> ModelInputContract:
    return ModelInputContract(
        required_indicators=list(getattr(wrapped.meta, "required_indicators", [])),
        required_fields=list(getattr(wrapped.meta, "required_fields", [])),
        external_data_sources=list(getattr(wrapped.meta, "external_data_sources", [])),
        warmup_bars=int(getattr(wrapped.meta, "min_history_bars", 0)),
    )


__all__ = ["UnifiedModelManager"]
