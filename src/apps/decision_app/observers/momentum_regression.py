"""Decision-only shadow observation of the approved Momentum/regression context."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from math import isfinite
from typing import Any

from apps.decision_app.features.regression_context import (
    REGRESSION_CONTEXT_FEATURE_NAME,
    REGRESSION_CONTEXT_FEATURE_VERSION,
)
from libs.contracts.decision import (
    DataRequirement,
    DecisionContext,
    DecisionModelPlugin,
    FeatureRequirement,
    FeatureSnapshot,
    ModelArtifact,
    ModelDependencyRequirement,
    ModelOutcome,
    ModelRequestContext,
    ModelSpec,
)
from libs.regression.context_snapshot import REGRESSION_CONTEXT_ID
from libs.regression.contracts.context_snapshot import ResidualRegion

MOMENTUM_REGRESSION_OBSERVER_NAME = "momentum_regression_observer"
MOMENTUM_REGRESSION_OBSERVER_VERSION = "1"
MOMENTUM_REGRESSION_OBSERVATION_ARTIFACT_TYPE = "momentum.regression_observation.v1"

REGRESSION_WHITELIST = (
    "structural.slope_log_per_hour",
    "structural.fit_quality",
    "location.region",
    "location.outer_channel_position",
    "location.outer_width_fraction",
    "location.upper_outer_breach",
    "location.lower_outer_breach",
    "location.previous_region",
    "location.reentered_from_upper_outer",
    "location.reentered_from_lower_outer",
)

_REGION_VALUES = frozenset(region.value for region in ResidualRegion)
_MOMENTUM_VALUE_KEYS = frozenset({"direction", "score", "conviction"})
_FEATURE_VALUE_KEYS = frozenset(
    {
        "context_id",
        "source_config_hash",
        "channel_config_hash",
        "structural",
        "location",
    }
)
_STRUCTURAL_VALUE_KEYS = frozenset({"slope_log_per_hour", "fit_quality"})
_LOCATION_VALUE_KEYS = frozenset(
    {
        "region",
        "outer_channel_position",
        "outer_width_fraction",
        "upper_outer_breach",
        "lower_outer_breach",
        "previous_region",
        "reentered_from_upper_outer",
        "reentered_from_lower_outer",
    }
)


def _require_mapping(value: object, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    return value


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _finite_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _finite_unit(value: object, *, field_name: str) -> float:
    result = _finite_number(value, field_name=field_name)
    if not 0.0 <= result <= 1.0:
        raise ValueError(f"{field_name} must be between zero and one")
    return result


def _require_bool(value: object, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a bool")
    return value


def _require_bool_or_none(value: object, *, field_name: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise TypeError(f"{field_name} must be a bool or None")
    return value


def _require_region(value: object, *, field_name: str) -> str:
    region = _require_text(value, field_name=field_name)
    if region not in _REGION_VALUES:
        raise ValueError(f"{field_name} is not an approved residual region")
    return region


def _require_optional_region(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_region(value, field_name=field_name)


def _read_feature_snapshot(
    context: DecisionContext,
) -> tuple[FeatureSnapshot, Mapping[str, Any]]:
    if not context.decision_bar_closed:
        raise ValueError(
            "momentum regression observation requires a closed Decision bar"
        )
    snapshot = context.shared_features.get(REGRESSION_CONTEXT_FEATURE_NAME)
    if snapshot is None:
        raise ValueError("REGRESSION_CONTEXT feature is required")
    if snapshot.version != REGRESSION_CONTEXT_FEATURE_VERSION:
        raise ValueError("REGRESSION_CONTEXT feature version is unsupported")
    if snapshot.market_as_of != context.market_as_of:
        raise ValueError("REGRESSION_CONTEXT cutoff does not match the model context")
    value = _require_mapping(snapshot.value, field_name="REGRESSION_CONTEXT value")
    if not _FEATURE_VALUE_KEYS <= set(value):
        raise ValueError("REGRESSION_CONTEXT value is missing approved fields")
    if value["context_id"] != REGRESSION_CONTEXT_ID:
        raise ValueError("REGRESSION_CONTEXT identity is unsupported")
    _require_text(value["source_config_hash"], field_name="source_config_hash")
    _require_text(value["channel_config_hash"], field_name="channel_config_hash")
    structural = _require_mapping(value["structural"], field_name="structural")
    location = _require_mapping(value["location"], field_name="location")
    if not _STRUCTURAL_VALUE_KEYS <= set(structural):
        raise ValueError("REGRESSION_CONTEXT structural whitelist is incomplete")
    if not _LOCATION_VALUE_KEYS <= set(location):
        raise ValueError("REGRESSION_CONTEXT location whitelist is incomplete")
    _finite_number(
        structural["slope_log_per_hour"],
        field_name="structural.slope_log_per_hour",
    )
    _finite_unit(structural["fit_quality"], field_name="structural.fit_quality")
    _require_region(location["region"], field_name="location.region")
    _finite_number(
        location["outer_channel_position"],
        field_name="location.outer_channel_position",
    )
    outer_width_fraction = _finite_number(
        location["outer_width_fraction"],
        field_name="location.outer_width_fraction",
    )
    if outer_width_fraction < 0.0:
        raise ValueError("location.outer_width_fraction must be non-negative")
    _require_bool(
        location["upper_outer_breach"], field_name="location.upper_outer_breach"
    )
    _require_bool(
        location["lower_outer_breach"], field_name="location.lower_outer_breach"
    )
    _require_optional_region(
        location["previous_region"], field_name="location.previous_region"
    )
    _require_bool_or_none(
        location["reentered_from_upper_outer"],
        field_name="location.reentered_from_upper_outer",
    )
    _require_bool_or_none(
        location["reentered_from_lower_outer"],
        field_name="location.reentered_from_lower_outer",
    )
    _require_text(
        snapshot.provenance.get("feature_config_fingerprint"),
        field_name="feature_config_fingerprint",
    )
    return snapshot, value


def _read_momentum_artifact(context: DecisionContext) -> ModelArtifact:
    if set(context.upstream_artifacts) != {"momentum"}:
        raise ValueError("the real momentum upstream dependency is required")
    artifact = context.upstream_artifacts["momentum"]
    if artifact.artifact_type != "momentum.signal.v1":
        raise ValueError("momentum dependency must be momentum.signal.v1")
    value = _require_mapping(artifact.value, field_name="momentum artifact value")
    if set(value) != _MOMENTUM_VALUE_KEYS:
        raise ValueError("momentum artifact value has an unsupported shape")
    direction = value["direction"]
    if isinstance(direction, bool) or direction not in {-1, 0, 1}:
        raise ValueError("momentum direction must be -1, 0, or 1")
    _finite_number(value["score"], field_name="momentum.score")
    _finite_unit(value["conviction"], field_name="momentum.conviction")
    return artifact


def _project_regression(value: Mapping[str, Any]) -> Mapping[str, Any]:
    structural = _require_mapping(value["structural"], field_name="structural")
    location = _require_mapping(value["location"], field_name="location")
    return {
        "slope_log_per_hour": _finite_number(
            structural["slope_log_per_hour"],
            field_name="structural.slope_log_per_hour",
        ),
        "fit_quality": _finite_unit(
            structural["fit_quality"], field_name="structural.fit_quality"
        ),
        "region": _require_region(location["region"], field_name="location.region"),
        "outer_channel_position": _finite_number(
            location["outer_channel_position"],
            field_name="location.outer_channel_position",
        ),
        "outer_width_fraction": _finite_number(
            location["outer_width_fraction"],
            field_name="location.outer_width_fraction",
        ),
        "upper_outer_breach": _require_bool(
            location["upper_outer_breach"],
            field_name="location.upper_outer_breach",
        ),
        "lower_outer_breach": _require_bool(
            location["lower_outer_breach"],
            field_name="location.lower_outer_breach",
        ),
        "previous_region": _require_optional_region(
            location["previous_region"], field_name="location.previous_region"
        ),
        "reentered_from_upper_outer": _require_bool_or_none(
            location["reentered_from_upper_outer"],
            field_name="location.reentered_from_upper_outer",
        ),
        "reentered_from_lower_outer": _require_bool_or_none(
            location["reentered_from_lower_outer"],
            field_name="location.reentered_from_lower_outer",
        ),
    }


class MomentumRegressionObserver:
    """Stateless analytical observer; it has no authority to make decisions."""

    spec = ModelSpec(
        name=MOMENTUM_REGRESSION_OBSERVER_NAME,
        version=MOMENTUM_REGRESSION_OBSERVER_VERSION,
        stateful=False,
        output_kind="analytical",
        produces_artifact_type=MOMENTUM_REGRESSION_OBSERVATION_ARTIFACT_TYPE,
        supported_trigger_modes=("on_bar_close",),
        intrinsic_feature_requirements=(
            FeatureRequirement(name=REGRESSION_CONTEXT_FEATURE_NAME),
        ),
        dependency_requirements=(
            ModelDependencyRequirement(
                slot_name="momentum",
                artifact_type="momentum.signal.v1",
            ),
        ),
    )

    def data_requests(
        self,
        base_context: ModelRequestContext,
        state_snapshot: object | None = None,
    ) -> Sequence[DataRequirement]:
        if not isinstance(base_context, ModelRequestContext):
            raise TypeError("base_context must be a ModelRequestContext")
        if state_snapshot is not None:
            raise ValueError("momentum regression observer is stateless")
        return ()

    def evaluate(
        self,
        context: DecisionContext,
        state_snapshot: object | None = None,
    ) -> ModelOutcome:
        if not isinstance(context, DecisionContext):
            raise TypeError("context must be a DecisionContext")
        if state_snapshot is not None:
            raise ValueError("momentum regression observer is stateless")
        feature_snapshot, feature_value = _read_feature_snapshot(context)
        momentum_artifact = _read_momentum_artifact(context)
        momentum_value = _require_mapping(
            momentum_artifact.value, field_name="momentum artifact value"
        )
        source_config_hash = _require_text(
            feature_value["source_config_hash"], field_name="source_config_hash"
        )
        channel_config_hash = _require_text(
            feature_value["channel_config_hash"], field_name="channel_config_hash"
        )
        feature_fingerprint = _require_text(
            feature_snapshot.provenance["feature_config_fingerprint"],
            field_name="feature_config_fingerprint",
        )
        artifact = ModelArtifact(
            binding_id=context.binding_id,
            lane_id=context.lane_id,
            asset=context.asset,
            decision_timeframe=context.decision_timeframe,
            trigger_timeframe=context.trigger_timeframe,
            market_as_of=context.market_as_of,
            artifact_type=MOMENTUM_REGRESSION_OBSERVATION_ARTIFACT_TYPE,
            value={
                "momentum": {
                    "direction": momentum_value["direction"],
                    "score": _finite_number(
                        momentum_value["score"], field_name="momentum.score"
                    ),
                    "conviction": _finite_unit(
                        momentum_value["conviction"],
                        field_name="momentum.conviction",
                    ),
                },
                "regression": _project_regression(feature_value),
            },
            provenance={
                "observer": (
                    f"{MOMENTUM_REGRESSION_OBSERVER_NAME}"
                    f"@{MOMENTUM_REGRESSION_OBSERVER_VERSION}"
                ),
                "momentum_artifact_type": momentum_artifact.artifact_type,
                "momentum_binding_id": momentum_artifact.binding_id,
                "regression_feature_version": feature_snapshot.version,
                "regression_feature_config_fingerprint": feature_fingerprint,
                "regression_source_config_hash": source_config_hash,
                "regression_channel_config_hash": channel_config_hash,
                "regression_context_id": feature_value["context_id"],
            },
        )
        return ModelOutcome(artifact=artifact, decision=None)


def momentum_regression_runtime_factory(
    parameters: Mapping[str, object],
) -> DecisionModelPlugin:
    """Instantiate the observer only from its deliberately empty parameter set."""

    if not isinstance(parameters, Mapping):
        raise TypeError("momentum regression observer parameters must be a mapping")
    if parameters:
        raise ValueError("momentum regression observer accepts no parameters")
    return MomentumRegressionObserver()


MOMENTUM_REGRESSION_OBSERVER_SPEC = MomentumRegressionObserver.spec

__all__ = [
    "MOMENTUM_REGRESSION_OBSERVATION_ARTIFACT_TYPE",
    "MOMENTUM_REGRESSION_OBSERVER_NAME",
    "MOMENTUM_REGRESSION_OBSERVER_SPEC",
    "MOMENTUM_REGRESSION_OBSERVER_VERSION",
    "REGRESSION_WHITELIST",
    "MomentumRegressionObserver",
    "momentum_regression_runtime_factory",
]
