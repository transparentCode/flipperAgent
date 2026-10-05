from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.domain.market_state import (
    BarStore,
    TimeframeGrid,
    compile_bar_store_capacities,
)
from apps.decision_app.domain.view import DecisionViewBuilder
from apps.decision_app.features.engine import FeatureEngine
from apps.decision_app.features.planning import (
    FeatureCatalog,
    FeaturePolicy,
    SharedFeatureDefinition,
    compile_feature_plan,
)
from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.planning.planner import (
    DecisionLaneSpec,
    ModelBindingSpec,
    compile_decision_plan,
)
from apps.decision_app.planning.readiness import compile_lane_market_requirements
from apps.decision_app.runtime.models import (
    BindingExecutionResult,
    ModelRuntime,
    PreparedLaneExecution,
)
from apps.decision_app.runtime.plugins import (
    RuntimePluginCatalog,
    RuntimePluginDefinition,
)
from libs.contracts.decision import (
    CausalBarView,
    DecisionContext,
    FeatureRequirement,
    ModelArtifact,
    ModelOutcome,
    ModelRequestContext,
    ModelSpec,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)
GRID = TimeframeGrid(
    alignment_origin=BASE,
    durations={"1h": timedelta(hours=1)},
)


def make_bar(index: int) -> CausalBarView:
    opened_at = BASE + timedelta(hours=index)
    closed_at = opened_at + timedelta(hours=1)
    return CausalBarView(
        timeframe="1h",
        bar_open_at=opened_at,
        bar_close_at=closed_at,
        market_as_of=closed_at,
        open=Decimal(100 + index),
        high=Decimal(102 + index),
        low=Decimal(99 + index),
        close=Decimal(101 + index),
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )


def make_spec(
    name: str,
    artifact_type: str,
    *,
    stateful: bool = False,
    feature_requirements: tuple[FeatureRequirement, ...] = (),
    dependencies=(),
) -> ModelSpec:
    from libs.contracts.decision import ModelDependencyRequirement

    return ModelSpec(
        name=name,
        version="1",
        stateful=stateful,
        output_kind="analytical",
        produces_artifact_type=artifact_type,
        intrinsic_feature_requirements=feature_requirements,
        dependency_requirements=tuple(
            ModelDependencyRequirement(
                slot_name=slot,
                artifact_type=artifact_type_for_dependency,
            )
            for slot, artifact_type_for_dependency in dependencies
        ),
    )


def make_lane(
    bindings: tuple[ModelBindingSpec, ...],
    *,
    policy_name: str = "default",
    policy_version: str = "1",
    policy_parameters: Mapping[str, object] | None = None,
    authority: str = "authoritative",
    risk_profile_key: str | None = "btc-default",
) -> DecisionLaneSpec:
    return DecisionLaneSpec(
        lane_id="BTCUSDT:1h",
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        decision_timeframe="1h",
        trigger_timeframe="1h",
        trigger_mode="on_bar_close",
        policy_name=policy_name,
        policy_version=policy_version,
        policy_parameters={} if policy_parameters is None else policy_parameters,
        authority=authority,
        risk_profile_key=risk_profile_key,
        bindings=bindings,
    )


@dataclass
class Bundle:
    runtime: ModelRuntime
    lane: object
    store: BarStore
    view_builder: DecisionViewBuilder

    def view(self, index: int):
        bar = make_bar(index)
        key = self.store.series_keys[0]
        if self.store.latest_at_or_before(key, bar.market_as_of) != bar:
            self.store.append(key, bar)
        lane = self.lane
        requirements = compile_lane_market_requirements(lane, GRID)
        return self.view_builder.build(lane, requirements, bar.market_as_of)


class RecordingPlugin:
    def __init__(self, spec: ModelSpec, events: list[tuple[str, str, tuple[str, ...]]]):
        self.spec = spec
        self.events = events
        self.request_count = 0
        self.evaluate_count = 0

    def data_requests(
        self,
        base_context: ModelRequestContext,
        state_snapshot: object | None = None,
    ) -> tuple[()]:
        del base_context, state_snapshot
        self.request_count += 1
        return ()

    def evaluate(
        self,
        context: DecisionContext,
        state_snapshot: object | None = None,
    ) -> ModelOutcome:
        self.evaluate_count += 1
        self.events.append(
            ("evaluate", context.binding_id, tuple(context.upstream_artifacts))
        )
        return ModelOutcome(
            artifact=ModelArtifact(
                binding_id=context.binding_id,
                lane_id=context.lane_id,
                asset=context.asset,
                decision_timeframe=context.decision_timeframe,
                trigger_timeframe=context.trigger_timeframe,
                market_as_of=context.market_as_of,
                artifact_type=self.spec.produces_artifact_type,
            )
        )


def make_bundle(
    specs: list[ModelSpec],
    bindings: tuple[ModelBindingSpec, ...],
    *,
    definitions: tuple[SharedFeatureDefinition, ...] = (),
    allowed_features: tuple[str, ...] = (),
    plugin_overrides: Mapping[str, object] | None = None,
    policy_name: str = "default",
    policy_version: str = "1",
    policy_parameters: Mapping[str, object] | None = None,
    authority: str = "authoritative",
    risk_profile_key: str | None = "btc-default",
) -> tuple[Bundle, dict[str, object]]:
    lane_spec = make_lane(
        bindings,
        policy_name=policy_name,
        policy_version=policy_version,
        policy_parameters=policy_parameters,
        authority=authority,
        risk_profile_key=risk_profile_key,
    )
    lane = compile_decision_plan(PluginCatalog(specs), [lane_spec]).lanes[0]
    feature_catalog = FeatureCatalog(definitions)
    feature_plan = compile_feature_plan(
        lane,
        feature_catalog,
        FeaturePolicy(name="operator", version="1", allowed_features=allowed_features),
        GRID,
    )
    feature_capacities = {}
    from apps.decision_app.features.planning import (
        compile_feature_bar_store_capacities,
        merge_bar_store_capacities,
    )

    feature_capacities = compile_feature_bar_store_capacities(
        compile_decision_plan(PluginCatalog(specs), [lane_spec]),
        [feature_plan],
        feature_catalog,
        GRID,
    )
    plan = compile_decision_plan(PluginCatalog(specs), [lane_spec])
    capacities = merge_bar_store_capacities(
        compile_bar_store_capacities(plan, GRID),
        feature_capacities,
    )
    store = BarStore(capacities)
    view_builder = DecisionViewBuilder(store, GRID)
    events: list[tuple[str, str, tuple[str, ...]]] = []
    plugins: dict[str, RecordingPlugin] = {}
    runtime_definitions = []
    for spec in specs:
        plugin = (
            plugin_overrides[spec.name]
            if plugin_overrides is not None and spec.name in plugin_overrides
            else RecordingPlugin(spec, events)
        )
        plugins[spec.name] = plugin
        runtime_definitions.append(
            RuntimePluginDefinition(
                plugin_name=spec.name,
                plugin_version=spec.version,
                factory=lambda parameters, plugin=plugin: plugin,
            )
        )
    runtime_catalog = RuntimePluginCatalog(runtime_definitions)
    runtime = ModelRuntime(
        lane,
        feature_plan,
        FeatureEngine(feature_catalog, store, GRID),
        runtime_catalog,
        GRID,
    )
    return Bundle(runtime, lane, store, view_builder), plugins


@pytest.mark.asyncio
async def test_model_bindings_evaluate_in_dependency_order_without_data_resolution():
    specs = [
        make_spec("Boundary", "boundary.v1"),
        make_spec(
            "Regression",
            "regression.v1",
            dependencies=(("boundary", "boundary.v1"),),
        ),
        make_spec("Independent", "independent.v1"),
    ]
    bindings = (
        ModelBindingSpec(
            slot_name="boundary", plugin_name="Boundary", plugin_version="1"
        ),
        ModelBindingSpec(
            slot_name="regression",
            plugin_name="Regression",
            plugin_version="1",
            dependencies={"boundary": "boundary"},
        ),
        ModelBindingSpec(
            slot_name="independent",
            plugin_name="Independent",
            plugin_version="1",
        ),
    )
    bundle, plugins = make_bundle(specs, bindings)
    prepared = await bundle.runtime.prepare_live(bundle.view(0))

    assert all(plugin.request_count == 0 for plugin in plugins.values())
    events = plugins["Boundary"].events
    assert prepared.binding_results
    assert all(
        result.status == "EXECUTED" for result in prepared.binding_results.values()
    )
    regression_id = next(
        binding.binding_id
        for binding in bundle.lane.bindings.values()
        if binding.slot_name == "regression"
    )
    regression_event = next(
        item for item in events if item[0] == "evaluate" and item[1] == regression_id
    )
    assert len(regression_event[2]) == 1
    boundary_id = next(
        binding.binding_id
        for binding in bundle.lane.bindings.values()
        if binding.slot_name == "boundary"
    )
    evaluation_order = [item[1] for item in events]
    assert evaluation_order.index(boundary_id) < evaluation_order.index(regression_id)


@pytest.mark.asyncio
async def test_binding_feature_visibility_is_isolated():
    specs = [
        make_spec(
            "A",
            "a.v1",
            feature_requirements=(FeatureRequirement(name="FEATURE_A"),),
        ),
        make_spec(
            "B",
            "b.v1",
            feature_requirements=(FeatureRequirement(name="FEATURE_B"),),
        ),
    ]
    definitions = tuple(
        SharedFeatureDefinition(
            name=name,
            version="1",
            calculator=lambda context, name=name: name,
        )
        for name in ("FEATURE_A", "FEATURE_B")
    )
    bindings = (
        ModelBindingSpec(slot_name="a", plugin_name="A", plugin_version="1"),
        ModelBindingSpec(slot_name="b", plugin_name="B", plugin_version="1"),
    )
    bundle, plugins = make_bundle(
        specs,
        bindings,
        definitions=definitions,
        allowed_features=("FEATURE_A", "FEATURE_B"),
    )
    prepared = await bundle.runtime.prepare_live(bundle.view(0))

    assert all(
        result.status == "EXECUTED" for result in prepared.binding_results.values()
    )
    assert set(plugins["A"].events[0][2]) == set()
    assert set(
        prepared.feature_resolution.bindings[
            next(key for key in prepared.feature_resolution.bindings if ":a:" in key)
        ].features
    ) == {"FEATURE_A"}


@pytest.mark.asyncio
async def test_prepared_execution_requires_complete_binding_evidence_and_identity():
    specs = [make_spec("A", "a.v1"), make_spec("B", "b.v1")]
    bundle, _ = make_bundle(
        specs,
        (
            ModelBindingSpec(slot_name="a", plugin_name="A", plugin_version="1"),
            ModelBindingSpec(slot_name="b", plugin_name="B", plugin_version="1"),
        ),
    )
    prepared = await bundle.runtime.prepare_live(bundle.view(0))
    assert isinstance(prepared, PreparedLaneExecution)
    binding_ids = {
        binding.slot_name: binding.binding_id
        for binding in bundle.lane.bindings.values()
    }
    a_id = binding_ids["a"]
    b_id = binding_ids["b"]
    a_result = prepared.binding_results[a_id]
    b_result = prepared.binding_results[b_id]

    with pytest.raises(ValueError, match="exactly match"):
        replace(prepared, binding_results={a_id: a_result})

    foreign_artifact = replace(
        a_result.outcome.artifact,
        binding_id="foreign-binding",
    )
    foreign_result = BindingExecutionResult(
        binding_id="foreign-binding",
        status="EXECUTED",
        outcome=replace(a_result.outcome, artifact=foreign_artifact),
    )
    with pytest.raises(ValueError, match="exactly match"):
        replace(
            prepared,
            binding_results={
                a_id: a_result,
                b_id: b_result,
                "foreign-binding": foreign_result,
            },
        )

    swapped_artifact = replace(a_result.outcome.artifact, binding_id=b_id)
    with pytest.raises(ValueError, match="artifact binding_id"):
        replace(
            prepared,
            binding_results={
                a_id: replace(
                    a_result,
                    outcome=replace(a_result.outcome, artifact=swapped_artifact),
                ),
                b_id: b_result,
            },
        )

    foreign_lane_artifact = replace(
        a_result.outcome.artifact,
        lane_id="foreign-lane",
    )
    with pytest.raises(ValueError, match="artifact lane_id"):
        replace(
            prepared,
            binding_results={
                a_id: replace(
                    a_result,
                    outcome=replace(
                        a_result.outcome,
                        artifact=foreign_lane_artifact,
                    ),
                ),
                b_id: b_result,
            },
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("blocker_id", "message"),
    (
        ("foreign-binding", "unknown dependency"),
        ("self", "itself"),
        ("executed", "executed dependency"),
    ),
)
async def test_prepared_execution_rejects_invalid_blocker_evidence(
    blocker_id: str,
    message: str,
):
    specs = [make_spec("A", "a.v1"), make_spec("B", "b.v1")]
    bundle, _ = make_bundle(
        specs,
        (
            ModelBindingSpec(slot_name="a", plugin_name="A", plugin_version="1"),
            ModelBindingSpec(slot_name="b", plugin_name="B", plugin_version="1"),
        ),
    )
    prepared = await bundle.runtime.prepare_live(bundle.view(0))
    binding_ids = {
        binding.slot_name: binding.binding_id
        for binding in bundle.lane.bindings.values()
    }
    a_id = binding_ids["a"]
    b_id = binding_ids["b"]
    actual_blocker = {
        "foreign-binding": "foreign-binding",
        "self": b_id,
        "executed": a_id,
    }[blocker_id]
    blocked = BindingExecutionResult(
        binding_id=b_id,
        status="BLOCKED",
        reason="dependency_unavailable",
        blocked_dependency_ids=(actual_blocker,),
    )
    with pytest.raises(ValueError, match=message):
        replace(
            prepared,
            binding_results={
                a_id: prepared.binding_results[a_id],
                b_id: blocked,
            },
        )


class RaisingPlugin(RecordingPlugin):
    def evaluate(
        self,
        context: DecisionContext,
        state_snapshot: object | None = None,
    ) -> ModelOutcome:
        del context, state_snapshot
        raise ValueError("boom-from-plugin")


@pytest.mark.asyncio
async def test_plugin_exception_is_invalid_and_logged_with_traceback(caplog):
    spec = make_spec("Raiser", "raiser.v1")
    bundle, _ = make_bundle(
        [spec],
        (
            ModelBindingSpec(
                slot_name="raiser", plugin_name="Raiser", plugin_version="1"
            ),
        ),
        plugin_overrides={"Raiser": RaisingPlugin(spec, [])},
    )
    caplog.set_level(logging.ERROR)

    prepared = await bundle.runtime.prepare_live(bundle.view(0))

    result = next(iter(prepared.binding_results.values()))
    assert result.status == "INVALID"
    assert result.reason == "evaluate_invalid"
    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "decision.plugin.evaluate_failed"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.ERROR
    assert "ValueError" in record.getMessage()
    assert "boom-from-plugin" in record.getMessage()
    assert record.exception_type == "ValueError"
    assert record.exception_message == "boom-from-plugin"
    assert record.rewarm is False
    assert record.lane_id == bundle.lane.lane_id
    assert record.binding_id == result.binding_id
    assert record.market_cutoff == bundle.view(0).market_as_of
    assert record.exc_info is not None
