from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from math import nan

import pytest

from apps.decision_app.observers.momentum_regression import (
    MOMENTUM_REGRESSION_OBSERVATION_ARTIFACT_TYPE,
    MOMENTUM_REGRESSION_OBSERVER_SPEC,
    MomentumRegressionObserver,
    momentum_regression_runtime_factory,
)
from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.planning.planner import (
    DecisionLaneSpec,
    ModelBindingSpec,
    PlannerError,
    compile_decision_plan,
)
from libs.contracts.decision import (
    CausalBarView,
    DecisionContext,
    FeatureSnapshot,
    ModelArtifact,
    ModelDependencyRequirement,
    ModelSpec,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)
LANE_ID = "BTCUSDT:regression_shadow_1h"
OBSERVER_BINDING_ID = "observer-binding"
MOMENTUM_BINDING_ID = "momentum-binding"


def _bar() -> CausalBarView:
    opened_at = BASE
    closed_at = opened_at + timedelta(hours=1)
    return CausalBarView(
        timeframe="1h",
        bar_open_at=opened_at,
        bar_close_at=closed_at,
        market_as_of=closed_at,
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal(100),
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )


def _regression_value(
    *,
    region: str = "INNER_CHANNEL",
    outer_position: float = 0.1,
) -> dict[str, object]:
    return {
        "context_id": "structural_channel_location_one_step_v1",
        "source_config_hash": "30d530f70382",
        "channel_config_hash": "550f7e645487cb2f04fb5994919452101113d6bdb3aef34fc58b2deb792d1fc2",
        "structural": {
            "slope_log_per_hour": 0.002,
            "fit_quality": 0.91,
            "estimator_id": "structural_log_price_theil_sen_v1",
        },
        "location": {
            "region": region,
            "outer_channel_position": outer_position,
            "outer_width_fraction": 0.4,
            "upper_outer_breach": False,
            "lower_outer_breach": False,
            "previous_region": "INNER_CHANNEL",
            "reentered_from_upper_outer": None,
            "reentered_from_lower_outer": None,
            "inner_width_fraction": 0.2,
        },
    }


def _momentum_artifact(
    *,
    direction: int = 1,
    score: float = 1.0,
    conviction: float = 1.0,
) -> ModelArtifact:
    cutoff = BASE + timedelta(hours=1)
    return ModelArtifact(
        binding_id=MOMENTUM_BINDING_ID,
        lane_id=LANE_ID,
        asset="BTCUSDT",
        decision_timeframe="1h",
        trigger_timeframe="1h",
        market_as_of=cutoff,
        artifact_type="momentum.signal.v1",
        value={
            "direction": direction,
            "score": score,
            "conviction": conviction,
        },
    )


def _context(
    *,
    regression_value: dict[str, object] | None = None,
    momentum_artifact: ModelArtifact | None = None,
    feature_version: str = "1",
) -> DecisionContext:
    cutoff = BASE + timedelta(hours=1)
    snapshot = FeatureSnapshot(
        name="REGRESSION_CONTEXT",
        version=feature_version,
        market_as_of=cutoff,
        value=regression_value or _regression_value(),
        provenance={"feature_config_fingerprint": "regression-feature-fingerprint"},
    )
    return DecisionContext(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        lane_id=LANE_ID,
        binding_id=OBSERVER_BINDING_ID,
        market_as_of=cutoff,
        trigger_timeframe="1h",
        decision_timeframe="1h",
        trigger_mode="on_bar_close",
        decision_bar=_bar(),
        decision_bar_closed=True,
        shared_features={"REGRESSION_CONTEXT": snapshot},
        upstream_artifacts={"momentum": momentum_artifact or _momentum_artifact()},
    )


def test_observer_is_analytical_stateless_and_decisionless() -> None:
    assert MOMENTUM_REGRESSION_OBSERVER_SPEC.output_kind == "analytical"
    assert MOMENTUM_REGRESSION_OBSERVER_SPEC.stateful is False
    assert MOMENTUM_REGRESSION_OBSERVER_SPEC.produces_artifact_type == (
        MOMENTUM_REGRESSION_OBSERVATION_ARTIFACT_TYPE
    )
    assert MOMENTUM_REGRESSION_OBSERVER_SPEC.intrinsic_data_requirements == ()
    assert MOMENTUM_REGRESSION_OBSERVER_SPEC.dependency_requirements == (
        ModelDependencyRequirement(
            slot_name="momentum", artifact_type="momentum.signal.v1"
        ),
    )
    outcome = MomentumRegressionObserver().evaluate(_context())
    assert outcome.decision is None
    assert (
        outcome.artifact.artifact_type == MOMENTUM_REGRESSION_OBSERVATION_ARTIFACT_TYPE
    )
    assert set(outcome.artifact.value) == {"momentum", "regression"}
    assert set(outcome.artifact.value["regression"]) == {
        "slope_log_per_hour",
        "fit_quality",
        "region",
        "outer_channel_position",
        "outer_width_fraction",
        "upper_outer_breach",
        "lower_outer_breach",
        "previous_region",
        "reentered_from_upper_outer",
        "reentered_from_lower_outer",
    }


@pytest.mark.parametrize("parameters", [None, {"unexpected": True}, {"x": 1}])
def test_observer_factory_rejects_non_empty_or_non_mapping_parameters(
    parameters,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        momentum_regression_runtime_factory(parameters)


def test_observer_factory_accepts_only_empty_parameters() -> None:
    plugin = momentum_regression_runtime_factory({})
    assert isinstance(plugin, MomentumRegressionObserver)
    assert plugin.spec == MOMENTUM_REGRESSION_OBSERVER_SPEC


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("location"),
        lambda value: value["structural"].update(fit_quality=nan),
        lambda value: value["location"].update(region="not-a-region"),
        lambda value: value["location"].update(outer_width_fraction=-0.1),
        lambda value: value["location"].update(upper_outer_breach=1),
        lambda value: value["location"].update(previous_region="not-a-region"),
    ],
)
def test_observer_rejects_malformed_regression_whitelist(mutation) -> None:
    value = deepcopy(_regression_value())
    mutation(value)
    with pytest.raises((TypeError, ValueError)):
        MomentumRegressionObserver().evaluate(_context(regression_value=value))


@pytest.mark.parametrize(
    "artifact_type,value",
    [
        ("other.v1", {"direction": 1, "score": 1.0, "conviction": 1.0}),
        ("momentum.signal.v1", {"direction": 2, "score": 1.0, "conviction": 1.0}),
        ("momentum.signal.v1", {"direction": 1, "score": 1.0, "conviction": 2.0}),
    ],
)
def test_observer_requires_real_well_formed_momentum_artifact(
    artifact_type, value
) -> None:
    artifact = replace(_momentum_artifact(), artifact_type=artifact_type, value=value)
    with pytest.raises((TypeError, ValueError)):
        MomentumRegressionObserver().evaluate(_context(momentum_artifact=artifact))


def test_model_artifact_rejects_nonfinite_momentum_value_before_observer() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        _momentum_artifact(score=nan)


def test_observer_isolation_keeps_momentum_and_tracks_regression() -> None:
    observer = MomentumRegressionObserver()
    first = observer.evaluate(_context()).artifact.value
    second = observer.evaluate(
        _context(
            regression_value=_regression_value(region="ABOVE_OUTER", outer_position=1.2)
        )
    ).artifact.value
    assert first["momentum"] == second["momentum"]
    assert first["regression"] != second["regression"]


def test_observer_isolation_keeps_regression_and_tracks_momentum() -> None:
    observer = MomentumRegressionObserver()
    first = observer.evaluate(_context()).artifact.value
    second = observer.evaluate(
        _context(momentum_artifact=_momentum_artifact(direction=-1, score=-1.0))
    ).artifact.value
    assert first["regression"] == second["regression"]
    assert second["momentum"] == {
        "direction": -1,
        "score": -1.0,
        "conviction": 1.0,
    }


def _observer_lane(*, dependencies: dict[str, str]) -> DecisionLaneSpec:
    return DecisionLaneSpec(
        lane_id=LANE_ID,
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        decision_timeframe="1h",
        trigger_timeframe="1h",
        trigger_mode="on_bar_close",
        policy_name="passthrough",
        policy_version="1",
        policy_parameters={"source_slot": "observer"},
        authority="shadow",
        bindings=(
            ModelBindingSpec(
                slot_name="observer",
                plugin_name="momentum_regression_observer",
                plugin_version="1",
                parameters={},
                dependencies=dependencies,
            ),
        ),
    )


def test_planner_rejects_missing_observer_dependency_provider() -> None:
    with pytest.raises(PlannerError, match="missing dependency"):
        compile_decision_plan(
            PluginCatalog((MOMENTUM_REGRESSION_OBSERVER_SPEC,)),
            (_observer_lane(dependencies={}),),
        )


def test_planner_rejects_incompatible_observer_dependency_provider() -> None:
    provider = ModelSpec(
        name="provider",
        version="1",
        stateful=False,
        output_kind="analytical",
        produces_artifact_type="wrong.v1",
    )
    lane = replace(
        _observer_lane(dependencies={"momentum": "provider"}),
        bindings=(
            ModelBindingSpec(
                slot_name="provider",
                plugin_name="provider",
                plugin_version="1",
            ),
            lane_binding := ModelBindingSpec(
                slot_name="observer",
                plugin_name="momentum_regression_observer",
                plugin_version="1",
                parameters={},
                dependencies={"momentum": "provider"},
            ),
        ),
    )
    assert lane.bindings[-1] == lane_binding
    with pytest.raises(PlannerError, match="requires momentum.signal.v1"):
        compile_decision_plan(
            PluginCatalog((provider, MOMENTUM_REGRESSION_OBSERVER_SPEC)),
            (lane,),
        )
