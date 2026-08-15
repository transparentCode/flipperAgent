from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.planning.planner import (
    DecisionLaneSpec,
    ModelBindingSpec,
    PlannerError,
    StaticCompositionPlanner,
    compile_decision_plan,
)
from libs.contracts.decision import (
    DataRequirement,
    ModelDependencyRequirement,
    ModelSpec,
)


def make_spec(
    name: str,
    artifact_type: str,
    *,
    dependencies: tuple[ModelDependencyRequirement, ...] = (),
    stateful: bool = False,
    decision_timeframes: tuple[str, ...] = (),
    trigger_timeframes: tuple[str, ...] = (),
    trigger_modes: tuple[str, ...] = (),
    data_requirements: tuple[DataRequirement, ...] = (),
) -> ModelSpec:
    return ModelSpec(
        name=name,
        version="1",
        stateful=stateful,
        output_kind="analytical",
        produces_artifact_type=artifact_type,
        supported_timeframes=decision_timeframes,
        supported_trigger_timeframes=trigger_timeframes,
        supported_trigger_modes=trigger_modes,
        intrinsic_data_requirements=data_requirements,
        dependency_requirements=dependencies,
    )


def make_binding(
    slot_name: str,
    plugin_name: str,
    *,
    parameters: dict[str, object] | None = None,
    dependencies: dict[str, str] | None = None,
) -> ModelBindingSpec:
    return ModelBindingSpec(
        slot_name=slot_name,
        plugin_name=plugin_name,
        plugin_version="1",
        parameters=parameters or {},
        dependencies=dependencies or {},
    )


def make_lane(
    bindings: tuple[ModelBindingSpec, ...],
    *,
    lane_id: str = "BTCUSDT:1h",
    asset: str = "BTCUSDT",
    decision_timeframe: str = "1h",
    trigger_timeframe: str = "1h",
    trigger_mode: str = "on_bar_close",
    authority: str = "authoritative",
    risk_profile_key: str | None = "btc-default",
    policy_name: str = "default",
    policy_version: str = "1",
    policy_parameters: dict[str, object] | None = None,
) -> DecisionLaneSpec:
    return DecisionLaneSpec(
        lane_id=lane_id,
        asset=asset,
        venue="binance",
        instrument_id=f"{asset[:-4]}-USDT-PERP",
        decision_timeframe=decision_timeframe,
        trigger_timeframe=trigger_timeframe,
        trigger_mode=trigger_mode,
        authority=authority,  # type: ignore[arg-type]
        risk_profile_key=risk_profile_key,
        policy_name=policy_name,
        policy_version=policy_version,
        policy_parameters=policy_parameters or {},
        bindings=bindings,
    )


def graph_catalog() -> PluginCatalog:
    return PluginCatalog(
        [
            make_spec("BoundaryModel", "boundary.v1"),
            make_spec(
                "RegressionModel",
                "regression.v1",
                dependencies=(
                    ModelDependencyRequirement(
                        slot_name="boundary",
                        artifact_type="boundary.v1",
                    ),
                ),
            ),
            make_spec(
                "BreakoutContextModel",
                "breakout_context.v1",
                dependencies=(
                    ModelDependencyRequirement(
                        slot_name="boundary",
                        artifact_type="boundary.v1",
                    ),
                ),
            ),
        ]
    )


def graph_lane(*, reverse: bool = False) -> DecisionLaneSpec:
    bindings = (
        make_binding("boundary", "BoundaryModel"),
        make_binding(
            "regression",
            "RegressionModel",
            dependencies={"boundary": "boundary"},
        ),
        make_binding(
            "breakout",
            "BreakoutContextModel",
            dependencies={"boundary": "boundary"},
        ),
    )
    return make_lane(tuple(reversed(bindings)) if reverse else bindings)


def test_shared_dependency_is_resolved_once_and_topologically_ordered() -> None:
    plan = compile_decision_plan(graph_catalog(), [graph_lane()])
    lane = plan.lanes[0]
    by_slot = lane.bindings

    assert len(lane.execution_order) == 3
    assert lane.execution_order[0] == by_slot["boundary"].binding_id
    assert lane.execution_order[1:] == (
        by_slot["breakout"].binding_id,
        by_slot["regression"].binding_id,
    )
    assert by_slot["regression"].dependencies == {
        "boundary": by_slot["boundary"].binding_id
    }
    assert by_slot["breakout"].dependencies == {
        "boundary": by_slot["boundary"].binding_id
    }
    assert len(set(lane.execution_order)) == 3


def test_input_order_does_not_change_plan_identity_or_order() -> None:
    first = StaticCompositionPlanner(graph_catalog()).compile([graph_lane()])
    second = StaticCompositionPlanner(graph_catalog()).compile(
        [graph_lane(reverse=True)]
    )

    first_lane = first.lanes[0]
    second_lane = second.lanes[0]
    assert first_lane.effective_lane_revision == second_lane.effective_lane_revision
    assert first_lane.execution_order == second_lane.execution_order
    assert {
        slot: binding.binding_id for slot, binding in first_lane.bindings.items()
    } == {slot: binding.binding_id for slot, binding in second_lane.bindings.items()}
    assert {
        slot: binding.binding_config_fingerprint
        for slot, binding in first_lane.bindings.items()
    } == {
        slot: binding.binding_config_fingerprint
        for slot, binding in second_lane.bindings.items()
    }


@pytest.mark.parametrize(
    ("decision_timeframe", "trigger_timeframe", "trigger_mode", "message"),
    [
        ("4h", "1h", "on_bar_close", "decision timeframe"),
        ("1h", "4h", "on_bar_close", "trigger timeframe"),
        ("1h", "1h", "projected", "trigger mode"),
    ],
)
def test_capability_validation_rejects_unsupported_values(
    decision_timeframe: str,
    trigger_timeframe: str,
    trigger_mode: str,
    message: str,
) -> None:
    spec = make_spec(
        "BoundaryModel",
        "boundary.v1",
        decision_timeframes=("1h",),
        trigger_timeframes=("1h",),
        trigger_modes=("on_bar_close",),
    )
    lane = make_lane(
        (make_binding("boundary", "BoundaryModel"),),
        decision_timeframe=decision_timeframe,
        trigger_timeframe=trigger_timeframe,
        trigger_mode=trigger_mode,
    )
    with pytest.raises(PlannerError, match=message):
        compile_decision_plan(PluginCatalog([spec]), [lane])


def test_empty_capabilities_are_unrestricted() -> None:
    plan = compile_decision_plan(
        PluginCatalog([make_spec("BoundaryModel", "boundary.v1")]),
        [make_lane((make_binding("boundary", "BoundaryModel"),))],
    )
    assert len(plan.lanes) == 1


def test_unknown_plugin_and_stateful_replay_safety_fail_closed() -> None:
    unknown_lane = make_lane((make_binding("unknown", "UnknownModel"),))
    with pytest.raises(PlannerError, match="unknown plugin"):
        compile_decision_plan(PluginCatalog([]), [unknown_lane])

    stateful = make_spec("StatefulModel", "stateful.v1", stateful=False)
    object.__setattr__(stateful, "stateful", True)
    object.__setattr__(
        stateful,
        "intrinsic_data_requirements",
        (DataRequirement(concept="LIVE_ONLY", replay_support_required=False),),
    )
    with pytest.raises(PlannerError, match="not replay-safe"):
        compile_decision_plan(
            PluginCatalog([stateful]),
            [make_lane((make_binding("state", "StatefulModel"),))],
        )


def test_stateful_replay_safety_covers_direct_and_transitive_ancestors() -> None:
    live_only = DataRequirement(
        concept="LIVE_ONLY_SENTIMENT",
        required=False,
        replay_support_required=False,
    )
    direct_catalog = PluginCatalog(
        [
            make_spec("LiveProvider", "provider.v1", data_requirements=(live_only,)),
            make_spec(
                "StatefulConsumer",
                "consumer.v1",
                stateful=True,
                dependencies=(
                    ModelDependencyRequirement(
                        slot_name="provider",
                        artifact_type="provider.v1",
                    ),
                ),
            ),
        ]
    )
    direct_lane = make_lane(
        (
            make_binding("provider", "LiveProvider"),
            make_binding(
                "consumer",
                "StatefulConsumer",
                dependencies={"provider": "provider"},
            ),
        )
    )
    with pytest.raises(
        PlannerError,
        match="consumer.*provider.*LIVE_ONLY_SENTIMENT",
    ):
        compile_decision_plan(direct_catalog, [direct_lane])

    transitive_catalog = PluginCatalog(
        [
            make_spec("LiveLeaf", "leaf.v1", data_requirements=(live_only,)),
            make_spec(
                "MiddleModel",
                "middle.v1",
                dependencies=(
                    ModelDependencyRequirement(
                        slot_name="leaf",
                        artifact_type="leaf.v1",
                    ),
                ),
            ),
            make_spec(
                "StatefulRoot",
                "root.v1",
                stateful=True,
                dependencies=(
                    ModelDependencyRequirement(
                        slot_name="middle",
                        artifact_type="middle.v1",
                    ),
                ),
            ),
        ]
    )
    transitive_lane = make_lane(
        (
            make_binding("leaf", "LiveLeaf"),
            make_binding(
                "middle",
                "MiddleModel",
                dependencies={"leaf": "leaf"},
            ),
            make_binding(
                "root",
                "StatefulRoot",
                dependencies={"middle": "middle"},
            ),
        )
    )
    with pytest.raises(
        PlannerError,
        match="root.*leaf.*LIVE_ONLY_SENTIMENT",
    ):
        compile_decision_plan(transitive_catalog, [transitive_lane])


def test_stateful_replay_safe_dependency_closure_is_accepted() -> None:
    replay_safe = DataRequirement(
        concept="OPEN_INTEREST",
        required=False,
        replay_support_required=True,
    )
    catalog = PluginCatalog(
        [
            make_spec("ReplayLeaf", "leaf.v1", data_requirements=(replay_safe,)),
            make_spec(
                "MiddleModel",
                "middle.v1",
                dependencies=(
                    ModelDependencyRequirement(
                        slot_name="leaf", artifact_type="leaf.v1"
                    ),
                ),
            ),
            make_spec(
                "StatefulRoot",
                "root.v1",
                stateful=True,
                dependencies=(
                    ModelDependencyRequirement(
                        slot_name="middle", artifact_type="middle.v1"
                    ),
                ),
            ),
        ]
    )
    lane = make_lane(
        (
            make_binding("leaf", "ReplayLeaf"),
            make_binding("middle", "MiddleModel", dependencies={"leaf": "leaf"}),
            make_binding("root", "StatefulRoot", dependencies={"middle": "middle"}),
        )
    )
    plan = compile_decision_plan(catalog, [lane])
    assert plan.lanes[0].bindings["root"].model_spec.stateful is True


@pytest.mark.parametrize(
    ("binding_dependencies", "message"),
    [
        ({}, "missing dependency slots"),
        (
            {"boundary": "boundary", "extra": "boundary"},
            "undeclared dependency slots",
        ),
        ({"boundary": "missing"}, "missing provider"),
        ({"boundary": "regression"}, "cannot depend on itself"),
    ],
)
def test_dependency_wiring_failures(
    binding_dependencies: dict[str, str], message: str
) -> None:
    catalog = PluginCatalog(
        [
            make_spec("BoundaryModel", "boundary.v1"),
            make_spec(
                "RegressionModel",
                "regression.v1",
                dependencies=(
                    ModelDependencyRequirement(
                        slot_name="boundary", artifact_type="boundary.v1"
                    ),
                ),
            ),
        ]
    )
    lane = make_lane(
        (
            make_binding("boundary", "BoundaryModel"),
            make_binding(
                "regression",
                "RegressionModel",
                dependencies=binding_dependencies,
            ),
        )
    )
    with pytest.raises(PlannerError, match=message):
        compile_decision_plan(catalog, [lane])


def test_dependency_artifact_mismatch_and_cycle_fail_closed() -> None:
    mismatch_catalog = PluginCatalog(
        [
            make_spec("BoundaryModel", "other.v1"),
            make_spec(
                "RegressionModel",
                "regression.v1",
                dependencies=(
                    ModelDependencyRequirement(
                        slot_name="boundary", artifact_type="boundary.v1"
                    ),
                ),
            ),
        ]
    )
    mismatch_lane = make_lane(
        (
            make_binding("boundary", "BoundaryModel"),
            make_binding(
                "regression",
                "RegressionModel",
                dependencies={"boundary": "boundary"},
            ),
        )
    )
    with pytest.raises(PlannerError, match="requires boundary.v1"):
        compile_decision_plan(mismatch_catalog, [mismatch_lane])

    cycle_catalog = PluginCatalog(
        [
            make_spec(
                "AModel",
                "a.v1",
                dependencies=(
                    ModelDependencyRequirement(slot_name="b", artifact_type="b.v1"),
                ),
            ),
            make_spec(
                "BModel",
                "b.v1",
                dependencies=(
                    ModelDependencyRequirement(slot_name="a", artifact_type="a.v1"),
                ),
            ),
        ]
    )
    cycle_lane = make_lane(
        (
            make_binding("a", "AModel", dependencies={"b": "b"}),
            make_binding("b", "BModel", dependencies={"a": "a"}),
        )
    )
    with pytest.raises(PlannerError, match="dependency cycle"):
        compile_decision_plan(cycle_catalog, [cycle_lane])


def test_authority_routes_allow_shadows_but_reject_two_authoritative_lanes() -> None:
    catalog = PluginCatalog([make_spec("BoundaryModel", "boundary.v1")])
    authoritative = make_lane((make_binding("boundary", "BoundaryModel"),))
    shadow = make_lane(
        (make_binding("boundary", "BoundaryModel"),),
        lane_id="BTCUSDT:1h-shadow",
        authority="shadow",
        risk_profile_key=None,
    )
    plan = compile_decision_plan(catalog, [shadow, authoritative])
    assert plan.authoritative_routes[("BTCUSDT", "1h")] == authoritative.lane_id

    second_authoritative = replace(
        shadow,
        lane_id="BTCUSDT:1h-other",
        authority="authoritative",
        risk_profile_key="btc-other",
    )
    with pytest.raises(PlannerError, match="multiple authoritative"):
        compile_decision_plan(catalog, [authoritative, second_authoritative])


def test_authoritative_lane_requires_risk_key_and_dependencies_stay_same_lane() -> None:
    with pytest.raises(ValueError, match="require risk_profile_key"):
        make_lane(
            (make_binding("boundary", "BoundaryModel"),),
            risk_profile_key=None,
        )

    catalog = graph_catalog()
    consumer = make_lane(
        (
            make_binding(
                "regression",
                "RegressionModel",
                dependencies={"boundary": "boundary"},
            ),
        ),
        lane_id="BTCUSDT:1h-consumer",
    )
    provider = make_lane(
        (make_binding("boundary", "BoundaryModel"),),
        lane_id="BTCUSDT:1h-provider",
        authority="shadow",
        risk_profile_key=None,
    )
    with pytest.raises(PlannerError, match="missing provider"):
        compile_decision_plan(catalog, [consumer, provider])


def test_resolved_lane_freezes_policy_and_validates_binding_invariants() -> None:
    plan = compile_decision_plan(graph_catalog(), [graph_lane()])
    lane = plan.lanes[0]
    frozen = replace(lane, policy_parameters={"x": {"y": [1]}})
    with pytest.raises((TypeError, AttributeError)):
        frozen.policy_parameters["x"]["y"].append(2)  # type: ignore[index]

    boundary = lane.bindings["boundary"]
    regression = lane.bindings["regression"]
    breakout = lane.bindings["breakout"]
    bindings = {
        "boundary": boundary,
        "regression": regression,
        "breakout": breakout,
    }

    with pytest.raises(ValueError, match="map key"):
        replace(
            lane,
            bindings={
                "wrong": boundary,
                "regression": regression,
                "breakout": breakout,
            },
        )

    with pytest.raises(ValueError, match="lane_id"):
        replace(
            lane,
            bindings={
                **bindings,
                "boundary": replace(boundary, lane_id="OTHER:1h"),
            },
        )
    with pytest.raises(ValueError, match="effective_lane_revision"):
        replace(
            lane,
            bindings={
                **bindings,
                "boundary": replace(boundary, effective_lane_revision="other"),
            },
        )

    for field_name, value, message in (
        ("decision_timeframe", "4h", "decision_timeframe"),
        ("trigger_timeframe", "4h", "trigger_timeframe"),
        ("trigger_mode", "projected", "trigger_mode"),
        ("publication_authority", "shadow", "publication_authority"),
        ("risk_profile_key", "other-risk", "risk_profile_key"),
    ):
        with pytest.raises(ValueError, match=message):
            replace(
                lane,
                bindings={
                    **bindings,
                    "boundary": replace(boundary, **{field_name: value}),
                },
            )

    foreign_dependency = replace(
        regression,
        dependencies={"boundary": "foreign-binding-id"},
    )
    with pytest.raises(ValueError, match="foreign binding ID"):
        replace(
            lane,
            bindings={**bindings, "regression": foreign_dependency},
        )


def test_resolved_lane_requires_unique_topological_execution_order() -> None:
    lane = compile_decision_plan(graph_catalog(), [graph_lane()]).lanes[0]
    ids = {slot: binding.binding_id for slot, binding in lane.bindings.items()}

    with pytest.raises(ValueError, match="dependency .* after consumer"):
        replace(
            lane,
            execution_order=(ids["breakout"], ids["boundary"], ids["regression"]),
        )
    with pytest.raises(ValueError, match="duplicate binding IDs"):
        replace(
            lane,
            execution_order=(ids["boundary"], ids["regression"], ids["regression"]),
        )


def test_resolved_decision_plan_authority_routes_match_lanes() -> None:
    plan = compile_decision_plan(
        graph_catalog(),
        [graph_lane()],
    )
    with pytest.raises(ValueError, match="exactly match authoritative lanes"):
        replace(
            plan,
            authoritative_routes={("BTCUSDT", "1h"): "nonexistent"},
        )
    with pytest.raises(ValueError, match="exactly match authoritative lanes"):
        replace(
            plan,
            authoritative_routes={
                ("BTCUSDT", "1h"): plan.lanes[0].lane_id,
                ("BTCUSDT", "1h-shadow"): "shadow-lane",
            },
        )
    with pytest.raises(ValueError, match="lane IDs must be unique"):
        replace(plan, lanes=(plan.lanes[0], plan.lanes[0]))


def test_route_collisions_are_scoped_by_asset_and_decision_timeframe() -> None:
    catalog = PluginCatalog([make_spec("BoundaryModel", "boundary.v1")])
    base_binding = make_binding("boundary", "BoundaryModel")
    plan = compile_decision_plan(
        catalog,
        [
            make_lane((base_binding,), lane_id="BTCUSDT:1h"),
            make_lane(
                (base_binding,),
                lane_id="ETHUSDT:1h",
                asset="ETHUSDT",
                risk_profile_key="eth-default",
            ),
            make_lane(
                (base_binding,),
                lane_id="BTCUSDT:4h",
                decision_timeframe="4h",
            ),
        ],
    )
    assert len(plan.authoritative_routes) == 3


def test_identity_changes_for_material_binding_and_lane_changes() -> None:
    catalog = PluginCatalog(
        [
            make_spec("BoundaryModel", "boundary.v1"),
            make_spec("OtherBoundaryModel", "boundary.v1"),
            make_spec(
                "RegressionModel",
                "regression.v1",
                dependencies=(
                    ModelDependencyRequirement(
                        slot_name="boundary", artifact_type="boundary.v1"
                    ),
                ),
            ),
        ]
    )
    base = make_lane(
        (
            make_binding("boundary", "BoundaryModel"),
            make_binding(
                "regression",
                "RegressionModel",
                dependencies={"boundary": "boundary"},
            ),
        )
    )
    base_plan = compile_decision_plan(catalog, [base]).lanes[0]
    parameter_plan = compile_decision_plan(
        catalog,
        [
            replace(
                base,
                bindings=(
                    make_binding(
                        "boundary", "BoundaryModel", parameters={"threshold": 2}
                    ),
                    base.bindings[1],
                ),
            )
        ],
    ).lanes[0]
    assert (
        parameter_plan.bindings["boundary"].binding_config_fingerprint
        != base_plan.bindings["boundary"].binding_config_fingerprint
    )
    assert parameter_plan.effective_lane_revision != base_plan.effective_lane_revision

    rewired = replace(
        base,
        bindings=(
            make_binding("boundary", "BoundaryModel"),
            make_binding("alternate", "OtherBoundaryModel"),
            make_binding(
                "regression",
                "RegressionModel",
                dependencies={"boundary": "alternate"},
            ),
        ),
    )
    rewired_plan = compile_decision_plan(catalog, [rewired]).lanes[0]
    assert (
        rewired_plan.bindings["regression"].binding_config_fingerprint
        != base_plan.bindings["regression"].binding_config_fingerprint
    )
    assert rewired_plan.effective_lane_revision != base_plan.effective_lane_revision

    for changed in (
        replace(base, trigger_timeframe="4h"),
        replace(base, decision_timeframe="4h", lane_id="BTCUSDT:4h"),
        replace(base, policy_version="2"),
        replace(base, policy_parameters={"threshold": 2}),
        replace(base, risk_profile_key="btc-other"),
    ):
        changed_plan = compile_decision_plan(catalog, [changed]).lanes[0]
        assert changed_plan.effective_lane_revision != base_plan.effective_lane_revision


def test_duplicate_dependency_slots_and_parameters_fail_closed() -> None:
    with pytest.raises(ValueError, match="slot names must be unique"):
        ModelSpec(
            name="BadModel",
            version="1",
            stateful=False,
            output_kind="analytical",
            produces_artifact_type="bad.v1",
            dependency_requirements=(
                ModelDependencyRequirement(slot_name="x", artifact_type="x.v1"),
                ModelDependencyRequirement(slot_name="x", artifact_type="x.v1"),
            ),
        )
    with pytest.raises(TypeError, match="unsupported mutable"):
        ModelBindingSpec(
            slot_name="bad",
            plugin_name="BoundaryModel",
            plugin_version="1",
            parameters={"object": object()},
        )


def test_duplicate_lane_and_binding_slots_fail_closed() -> None:
    binding = make_binding("boundary", "BoundaryModel")
    with pytest.raises(ValueError, match="unique within a lane"):
        make_lane((binding, binding))

    lane = make_lane((binding,))
    with pytest.raises(PlannerError, match="duplicate lane_id"):
        compile_decision_plan(
            PluginCatalog([make_spec("BoundaryModel", "boundary.v1")]),
            [lane, lane],
        )


def test_planner_has_no_infrastructure_or_model_execution_dependency() -> None:
    source = "\n".join(
        Path(path).read_text()
        for path in (
            Path("src/apps/decision_app/planning/catalog.py"),
            Path("src/apps/decision_app/planning/planner.py"),
        )
    )
    for forbidden in (
        "redis",
        "valkey",
        "asyncpg",
        "httpx",
        "scraper_app",
        "ingestion_app",
        "fastapi",
        "docker",
        ".evaluate(",
    ):
        assert forbidden.lower() not in source.lower()
