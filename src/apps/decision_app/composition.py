"""Explicit production composition for the D9C decision service.

The service deliberately receives a small, closed catalog rather than using
import-time discovery.  D9C only enables the reviewed SR adapter and the
already-approved shared ATR feature; unfinished model integrations stay out of
the production graph.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from apps.decision_app.catalog import PluginCatalog
from apps.decision_app.contracts import ResolvedModelBinding
from apps.decision_app.data import DataPolicy, DataResolver, DataSourceCatalog
from apps.decision_app.features import FeatureCatalog, FeaturePolicy
from apps.decision_app.policy import (
    PASSTHROUGH_V1,
    PRIORITY_V1,
    DecisionPolicyCatalog,
)
from apps.decision_app.real_features import SR_ATR_DEFINITION
from apps.decision_app.runtime_plugins import (
    RuntimePluginCatalog,
    RuntimePluginDefinition,
    StateInitializationRequirement,
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
    source_catalog = DataSourceCatalog(())
    data_policy = DataPolicy(
        name=EMPTY_DATA_POLICY_NAME,
        version=EMPTY_DATA_POLICY_VERSION,
        concepts={},
    )
    return DecisionComposition(
        plugin_catalog=PluginCatalog((SR_MODEL_SPEC,)),
        runtime_plugin_catalog=RuntimePluginCatalog(
            (
                RuntimePluginDefinition(
                    plugin_name=SR_MODEL_SPEC.name,
                    plugin_version=SR_MODEL_SPEC.version,
                    factory=SRDecisionPlugin,
                    initialization_requirement=sr_initialization_requirement,
                ),
            )
        ),
        feature_catalog=FeatureCatalog((SR_ATR_DEFINITION,)),
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
