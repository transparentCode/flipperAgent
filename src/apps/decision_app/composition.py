"""Explicit production composition for the D9C decision service.

The service deliberately receives a small, closed catalog rather than using
import-time discovery.  D9C only enables the reviewed SR adapter and the
already-approved shared ATR feature; unfinished model integrations stay out of
the production graph.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from apps.decision_app.data.resolver import DataPolicy, DataResolver, DataSourceCatalog
from apps.decision_app.domain.contracts import ResolvedModelBinding
from apps.decision_app.features.definitions import SR_ATR_DEFINITION
from apps.decision_app.features.momentum_integration import (
    MomentumBindingEnvelope,
    build_momentum_feature_definitions,
    momentum_runtime_factory,
    parse_momentum_binding_parameters,
)
from apps.decision_app.features.planning import FeatureCatalog, FeaturePolicy
from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.runtime.plugins import (
    RuntimePluginCatalog,
    RuntimePluginDefinition,
    StateInitializationRequirement,
)
from apps.decision_app.runtime.policy import (
    PASSTHROUGH_V1,
    PRIORITY_V1,
    DecisionPolicyCatalog,
)
from apps.decision_app.settings import DecisionConfig
from libs.models.sr.adapters.decision_plugin import SR_MODEL_SPEC, SRDecisionPlugin
from libs.models.sr.config import SRConfigResolver

EMPTY_FEATURE_POLICY_NAME = "decision-empty"
EMPTY_FEATURE_POLICY_VERSION = "1"
EMPTY_DATA_POLICY_NAME = "decision-empty"
EMPTY_DATA_POLICY_VERSION = "1"


def sr_initialization_requirement(
    binding: ResolvedModelBinding,
) -> StateInitializationRequirement:
    """Resolve the reviewed SR adapter's bounded first-inception horizon."""

    asset, separator, _ = binding.lane_id.partition(":")
    if not separator or not asset:
        raise ValueError(
            "SR initialization requires the canonical '<asset>:<lane>' lane_id"
        )
    parameters = binding.parameters
    raw_config = parameters.get("sr_config")
    if not isinstance(raw_config, Mapping):
        raise TypeError("SR plugin parameters require an sr_config mapping")
    resolved = SRConfigResolver(raw_config).resolve(
        asset=asset,
        timeframe=binding.decision_timeframe,
    )
    return StateInitializationRequirement(
        trigger_steps=max(
            resolved.lifecycle.max_age_bars,
            2 * resolved.detection.pivot_span_bars + 1,
        )
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class DecisionComposition:
    """All explicit catalogs/policies needed to build one D9A generation."""

    plugin_catalog: PluginCatalog
    runtime_plugin_catalog: RuntimePluginCatalog
    feature_catalog: FeatureCatalog
    feature_policy: FeaturePolicy
    policy_catalog: DecisionPolicyCatalog
    data_source_catalog: DataSourceCatalog
    data_policy: DataPolicy
    data_resolver: DataResolver


def _configured_momentum_profiles(
    config: DecisionConfig,
) -> dict[str, MomentumBindingEnvelope]:
    """Validate the explicit Momentum route envelopes in active config."""

    profiles: dict[str, MomentumBindingEnvelope] = {}
    for lane in config.lane_specs():
        for binding in lane.bindings:
            if binding.plugin_name != "momentum":
                continue
            if binding.plugin_version != "1":
                raise ValueError(
                    f"unsupported Momentum plugin version: {binding.plugin_version}"
                )
            profile = parse_momentum_binding_parameters(
                binding.parameters,
                expected_asset=lane.asset,
                expected_decision_timeframe=lane.decision_timeframe,
            )
            if profile.route_key in profiles:
                raise ValueError(
                    f"duplicate Momentum route profile: {profile.route_key}"
                )
            profiles[profile.route_key] = profile
    return profiles


def _validate_regression_observer_configuration(config: DecisionConfig) -> bool:
    """Validate the observer's dedicated shadow-lane graph invariants."""

    enabled = False
    for lane in config.lane_specs():
        bindings_by_slot = {binding.slot_name: binding for binding in lane.bindings}
        for binding in lane.bindings:
            if binding.plugin_name != "momentum_regression_observer":
                continue
            if binding.plugin_version != "1":
                raise ValueError(
                    "unsupported Momentum regression observer version: "
                    f"{binding.plugin_version}"
                )
            if lane.authority != "shadow":
                raise ValueError(
                    "momentum_regression_observer@1 requires a shadow lane: "
                    f"{lane.lane_id}"
                )
            if "momentum" not in binding.dependencies:
                raise ValueError(
                    "momentum_regression_observer@1 requires a momentum dependency: "
                    f"{lane.lane_id}:{binding.slot_name}"
                )
            provider_slot = binding.dependencies["momentum"]
            provider = bindings_by_slot.get(provider_slot)
            if provider is None:
                raise ValueError(
                    "momentum_regression_observer@1 momentum dependency must resolve "
                    "to a same-lane binding: "
                    f"{lane.lane_id}:{provider_slot}"
                )
            if (provider.plugin_name, provider.plugin_version) != ("momentum", "1"):
                raise ValueError(
                    "momentum_regression_observer@1 momentum dependency must resolve "
                    "to momentum@1: "
                    f"{lane.lane_id}:{provider_slot}"
                )
            if (lane.policy_name, lane.policy_version) != ("passthrough", "1"):
                raise ValueError(
                    "momentum_regression_observer@1 requires passthrough@1 policy: "
                    f"{lane.lane_id}"
                )
            if lane.policy_parameters.get("source_slot") != provider_slot:
                raise ValueError(
                    "momentum_regression_observer@1 requires passthrough source_slot "
                    "to equal its Momentum provider slot: "
                    f"{lane.lane_id}:{provider_slot}"
                )
            enabled = True
    return enabled


def build_production_composition(config: DecisionConfig) -> DecisionComposition:
    """Build the reviewed, non-discovering D9C production composition."""

    if not isinstance(config, DecisionConfig):
        raise TypeError("config must be DecisionConfig")

    configured_policy = config.global_settings.feature_policy
    feature_policy = (
        FeaturePolicy(
            name=configured_policy.name,
            version=configured_policy.version,
            allowed_features=configured_policy.allowed_features,
        )
        if configured_policy is not None
        else FeaturePolicy(
            name=EMPTY_FEATURE_POLICY_NAME,
            version=EMPTY_FEATURE_POLICY_VERSION,
            allowed_features=(),
        )
    )
    momentum_profiles = _configured_momentum_profiles(config)
    momentum_enabled = bool(momentum_profiles)
    observer_enabled = _validate_regression_observer_configuration(config)
    source_catalog = DataSourceCatalog(())
    data_policy = DataPolicy(
        name=EMPTY_DATA_POLICY_NAME,
        version=EMPTY_DATA_POLICY_VERSION,
        concepts={},
    )
    plugin_specs = [SR_MODEL_SPEC]
    runtime_definitions = [
        RuntimePluginDefinition(
            plugin_name=SR_MODEL_SPEC.name,
            plugin_version=SR_MODEL_SPEC.version,
            factory=SRDecisionPlugin,
            initialization_requirement=sr_initialization_requirement,
        )
    ]
    feature_definitions = [SR_ATR_DEFINITION]
    if momentum_enabled:
        from libs.models.momentum.adapters.decision_plugin import MOMENTUM_MODEL_SPEC

        plugin_specs.append(MOMENTUM_MODEL_SPEC)
        runtime_definitions.append(
            RuntimePluginDefinition(
                plugin_name=MOMENTUM_MODEL_SPEC.name,
                plugin_version=MOMENTUM_MODEL_SPEC.version,
                factory=momentum_runtime_factory,
            )
        )
        feature_definitions.extend(
            build_momentum_feature_definitions(momentum_profiles)
        )
    if observer_enabled:
        from apps.decision_app.features.regression_context import (
            build_regression_context_feature_definition,
        )
        from apps.decision_app.observers.momentum_regression import (
            MOMENTUM_REGRESSION_OBSERVER_SPEC,
            momentum_regression_runtime_factory,
        )
        from libs.regression.config.resolver import ConfigResolver

        regression_config_path = (
            Path(__file__).resolve().parents[3]
            / "src"
            / "libs"
            / "regression"
            / "config"
            / "regression.yaml"
        )
        regression_resolver = ConfigResolver.from_yaml(str(regression_config_path))
        plugin_specs.append(MOMENTUM_REGRESSION_OBSERVER_SPEC)
        runtime_definitions.append(
            RuntimePluginDefinition(
                plugin_name=MOMENTUM_REGRESSION_OBSERVER_SPEC.name,
                plugin_version=MOMENTUM_REGRESSION_OBSERVER_SPEC.version,
                factory=momentum_regression_runtime_factory,
            )
        )
        feature_definitions.append(
            build_regression_context_feature_definition(regression_resolver)
        )

    return DecisionComposition(
        plugin_catalog=PluginCatalog(plugin_specs),
        runtime_plugin_catalog=RuntimePluginCatalog(runtime_definitions),
        feature_catalog=FeatureCatalog(feature_definitions),
        feature_policy=feature_policy,
        policy_catalog=DecisionPolicyCatalog((PASSTHROUGH_V1, PRIORITY_V1)),
        data_source_catalog=source_catalog,
        data_policy=data_policy,
        data_resolver=DataResolver(source_catalog),
    )


__all__ = [
    "EMPTY_DATA_POLICY_NAME",
    "EMPTY_DATA_POLICY_VERSION",
    "EMPTY_FEATURE_POLICY_NAME",
    "EMPTY_FEATURE_POLICY_VERSION",
    "DecisionComposition",
    "build_production_composition",
    "sr_initialization_requirement",
]
