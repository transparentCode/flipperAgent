from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.decision_app.data.resolver import (
    ConceptDataPolicy,
    DataPlanError,
    DataPolicy,
    DataPolicyError,
    DataRequestError,
    DataSourceCatalog,
    DataSourceDefinition,
    compile_data_plan,
    make_data_request_key,
    materialize_data_request,
    validate_data_plan_against_lane,
)
from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.planning.planner import (
    DecisionLaneSpec,
    ModelBindingSpec,
    compile_decision_plan,
)
from libs.contracts.decision import (
    DataRequest,
    DataRequirement,
    DataSnapshot,
    ModelSpec,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


async def noop_fetcher(_: DataRequest) -> DataSnapshot | None:
    return None


def source(
    name: str,
    *,
    kind: str = "pit",
    capability: str = "LIVE_AND_REPLAY",
) -> DataSourceDefinition:
    return DataSourceDefinition(
        name=name,
        version="1",
        kind=kind,  # type: ignore[arg-type]
        capability=capability,  # type: ignore[arg-type]
        fetcher=noop_fetcher,
    )


def lane_with_requirements(
    requirements_by_slot: dict[str, tuple[DataRequirement, ...]],
    *,
    asset: str = "BTCUSDT",
) -> object:
    specs = [
        ModelSpec(
            name=f"Model{slot.title()}",
            version="1",
            stateful=False,
            output_kind="analytical",
            produces_artifact_type=f"{slot}.v1",
            intrinsic_data_requirements=requirements,
        )
        for slot, requirements in requirements_by_slot.items()
    ]
    lane = DecisionLaneSpec(
        lane_id=f"{asset}:1h",
        asset=asset,
        venue="binance",
        instrument_id=f"{asset[:-4]}-USDT-PERP",
        decision_timeframe="1h",
        trigger_timeframe="1h",
        trigger_mode="on_bar_close",
        policy_name="default",
        policy_version="1",
        risk_profile_key="risk",
        bindings=tuple(
            ModelBindingSpec(
                slot_name=slot,
                plugin_name=f"Model{slot.title()}",
                plugin_version="1",
            )
            for slot in requirements_by_slot
        ),
    )
    return compile_decision_plan(PluginCatalog(specs), [lane]).lanes[0]


def policy_for(*concepts: str) -> DataPolicy:
    return DataPolicy(
        name="operator",
        version="1",
        concepts={
            concept: ConceptDataPolicy(
                concept=concept,
                scope_mode="lane_asset",
                live_source_order=("cache", "pit", "live"),
                replay_source_order=("pit",),
            )
            for concept in concepts
        },
    )


def test_source_catalog_and_policy_are_explicit_and_immutable() -> None:
    catalog = DataSourceCatalog(
        [
            source("live", kind="live", capability="LIVE_ONLY"),
            source("pit"),
            source("cache", kind="cache", capability="LIVE_ONLY"),
        ]
    )
    assert [item.name for item in catalog] == ["cache", "live", "pit"]
    assert catalog.resolve("pit").kind == "pit"
    with pytest.raises(AttributeError):
        catalog._sources = {}  # type: ignore[attr-defined]
    with pytest.raises(DataPolicyError, match="duplicate"):
        DataSourceCatalog([source("pit"), source("pit")])
    assert (
        source(
            "replay-safe-cache",
            kind="cache",
            capability="LIVE_AND_REPLAY",
        ).capability
        == "LIVE_AND_REPLAY"
    )
    assert (
        source(
            "replay-safe-live",
            kind="live",
            capability="LIVE_AND_REPLAY",
        ).capability
        == "LIVE_AND_REPLAY"
    )


@pytest.mark.parametrize(
    "live_order",
    [("pit", "cache"), ("live", "pit"), ("cache", "live", "live")],
)
def test_invalid_live_route_order_fails_closed(live_order: tuple[str, ...]) -> None:
    with pytest.raises((DataPolicyError, ValueError)):
        concept_policy = ConceptDataPolicy(
            concept="OPEN_INTEREST",
            scope_mode="lane_asset",
            live_source_order=live_order,
            replay_source_order=("pit",),
        )
        policy = DataPolicy(
            name="operator",
            version="1",
            concepts={"OPEN_INTEREST": concept_policy},
        )
        lane = lane_with_requirements(
            {"oi": (DataRequirement(concept="OPEN_INTEREST"),)}
        )
        compile_data_plan(
            lane,
            policy,
            DataSourceCatalog(
                [
                    source("cache", kind="cache", capability="LIVE_ONLY"),
                    source("pit"),
                    source("live", kind="live", capability="LIVE_ONLY"),
                ]
            ),
        )


def test_replay_route_requires_replay_safe_pit_sources() -> None:
    lane = lane_with_requirements(
        {"primary": (DataRequirement(concept="OPEN_INTEREST"),)}
    )
    with pytest.raises(DataPolicyError, match="REPLAY"):
        compile_data_plan(
            lane,
            DataPolicy(
                name="operator",
                version="1",
                concepts={
                    "OPEN_INTEREST": ConceptDataPolicy(
                        concept="OPEN_INTEREST",
                        scope_mode="lane_asset",
                        live_source_order=("pit_live_only",),
                        replay_source_order=("pit_live_only",),
                    )
                },
            ),
            DataSourceCatalog(
                [
                    source(
                        "pit_live_only",
                        kind="pit",
                        capability="LIVE_ONLY",
                    )
                ]
            ),
        )


@pytest.mark.parametrize("kind", ["cache", "live"])
def test_replay_route_rejects_non_pit_even_when_capability_is_replay_safe(
    kind: str,
) -> None:
    lane = lane_with_requirements(
        {"primary": (DataRequirement(concept="OPEN_INTEREST"),)}
    )
    source_name = f"{kind}_replay_safe"
    with pytest.raises(DataPolicyError, match="REPLAY"):
        compile_data_plan(
            lane,
            DataPolicy(
                name="operator",
                version="1",
                concepts={
                    "OPEN_INTEREST": ConceptDataPolicy(
                        concept="OPEN_INTEREST",
                        scope_mode="lane_asset",
                        live_source_order=(source_name,),
                        replay_source_order=(source_name,),
                    )
                },
            ),
            DataSourceCatalog(
                [
                    source(
                        source_name,
                        kind=kind,
                        capability="LIVE_AND_REPLAY",
                    )
                ]
            ),
        )


def test_data_plan_is_deterministic_and_self_validating() -> None:
    requirements = (
        DataRequirement(
            concept="BTC_DOMINANCE",
            required=False,
            replay_support_required=True,
            max_age_at_market_as_of=timedelta(minutes=5),
            max_available_lag=timedelta(minutes=1),
            alignment="at_or_before",
        ),
        DataRequirement(concept="OPEN_INTEREST"),
    )
    lane = lane_with_requirements({"primary": requirements})
    catalog = DataSourceCatalog([source("pit")])
    first = compile_data_plan(
        lane,
        DataPolicy(
            name="operator",
            version="1",
            concepts={
                "OPEN_INTEREST": ConceptDataPolicy(
                    concept="OPEN_INTEREST",
                    scope_mode="lane_asset",
                    live_source_order=("pit",),
                    replay_source_order=("pit",),
                ),
                "BTC_DOMINANCE": ConceptDataPolicy(
                    concept="BTC_DOMINANCE",
                    scope_mode="global",
                    live_source_order=("pit",),
                    replay_source_order=("pit",),
                ),
                "UNUSED": ConceptDataPolicy(
                    concept="UNUSED",
                    scope_mode="global",
                    live_source_order=("pit",),
                    replay_source_order=("pit",),
                ),
            },
        ),
        catalog,
    )
    second = compile_data_plan(
        lane,
        DataPolicy(
            name="operator",
            version="1",
            concepts={
                concept: ConceptDataPolicy(
                    concept=concept,
                    scope_mode=first.routes[concept].scope_mode,
                    live_source_order=first.routes[concept].live_source_order,
                    replay_source_order=first.routes[concept].replay_source_order,
                )
                for concept in ("BTC_DOMINANCE", "OPEN_INTEREST")
            },
        ),
        catalog,
    )
    assert first.data_plan_fingerprint == second.data_plan_fingerprint
    assert first.requested_concepts == ("BTC_DOMINANCE", "OPEN_INTEREST")
    assert first.unrouted_concepts == ()
    assert first.bindings[next(iter(first.bindings))].required_concepts == (
        "OPEN_INTEREST",
    )
    assert first.bindings[next(iter(first.bindings))].optional_concepts == (
        "BTC_DOMINANCE",
    )

    with pytest.raises(ValueError, match="data_plan_fingerprint"):
        replace(first, data_policy_version="2")
    with pytest.raises(ValueError, match="data_plan_fingerprint"):
        replace(
            first,
            unrouted_concepts=("BTC_DOMINANCE",),
            routes={"OPEN_INTEREST": first.routes["OPEN_INTEREST"]},
        )


def test_unrouted_concept_is_explicit_and_materialization_fails() -> None:
    lane = lane_with_requirements(
        {"primary": (DataRequirement(concept="OPEN_INTEREST"),)}
    )
    plan = compile_data_plan(
        lane,
        DataPolicy(name="operator", version="1"),
        DataSourceCatalog([]),
    )
    assert plan.unrouted_concepts == ("OPEN_INTEREST",)
    binding = next(iter(lane.bindings.values()))
    with pytest.raises(DataRequestError, match="no resolved data route"):
        materialize_data_request(
            resolved_lane=lane,
            resolved_binding=binding,
            data_plan=plan,
            dynamic_requirement=DataRequirement(concept="OPEN_INTEREST"),
            mode="LIVE",
            market_as_of=BASE,
            resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
        )


def test_materialization_owns_scope_and_request_identity() -> None:
    lane = lane_with_requirements(
        {
            "oi": (DataRequirement(concept="OPEN_INTEREST"),),
            "dominance": (DataRequirement(concept="BTC_DOMINANCE", required=False),),
        }
    )
    plan = compile_data_plan(
        lane,
        DataPolicy(
            name="operator",
            version="1",
            concepts={
                "OPEN_INTEREST": ConceptDataPolicy(
                    concept="OPEN_INTEREST",
                    scope_mode="lane_asset",
                    live_source_order=("pit",),
                    replay_source_order=("pit",),
                ),
                "BTC_DOMINANCE": ConceptDataPolicy(
                    concept="BTC_DOMINANCE",
                    scope_mode="global",
                    live_source_order=("pit",),
                    replay_source_order=("pit",),
                ),
            },
        ),
        DataSourceCatalog([source("pit")]),
    )
    bindings = {binding.slot_name: binding for binding in lane.bindings.values()}
    request = materialize_data_request(
        resolved_lane=lane,
        resolved_binding=bindings["oi"],
        data_plan=plan,
        dynamic_requirement=DataRequirement(concept="OPEN_INTEREST"),
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    global_request = materialize_data_request(
        resolved_lane=lane,
        resolved_binding=bindings["dominance"],
        data_plan=plan,
        dynamic_requirement=DataRequirement(concept="BTC_DOMINANCE", required=False),
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    assert request.asset == "BTCUSDT"
    assert request.scope is None
    assert global_request.asset is None
    assert global_request.scope == "global"
    assert request.request_key == make_data_request_key(request, lane_id=lane.lane_id)
    assert request.request_key != global_request.request_key
    assert request.required is True

    assert request.request_key == make_data_request_key(
        replace(request, required=False),
        lane_id=lane.lane_id,
    )

    with pytest.raises(DataRequestError, match="does not match envelope"):
        materialize_data_request(
            resolved_lane=lane,
            resolved_binding=bindings["oi"],
            data_plan=plan,
            dynamic_requirement=DataRequirement(
                concept="OPEN_INTEREST",
                max_age_at_market_as_of=timedelta(seconds=1),
            ),
            mode="LIVE",
            market_as_of=BASE,
            resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
        )


def test_data_plan_validation_rejects_binding_demand_drift() -> None:
    lane = lane_with_requirements(
        {"primary": (DataRequirement(concept="OPEN_INTEREST"),)}
    )
    plan = compile_data_plan(
        lane,
        policy_for("OPEN_INTEREST"),
        DataSourceCatalog(
            [
                source("cache", kind="cache", capability="LIVE_ONLY"),
                source("pit"),
                source("live", kind="live", capability="LIVE_ONLY"),
            ]
        ),
    )
    binding = next(iter(lane.bindings.values()))
    tampered = replace(
        binding,
        effective_data_requirements=(
            DataRequirement(concept="OPEN_INTEREST", required=False),
        ),
    )
    tampered_lane = replace(lane, bindings={binding.slot_name: tampered})
    with pytest.raises(DataPlanError, match="demand mismatch"):
        validate_data_plan_against_lane(plan, tampered_lane)


def test_model_spec_rejects_duplicate_data_concepts() -> None:
    with pytest.raises(ValueError, match="data requirement concepts"):
        ModelSpec(
            name="Duplicate",
            version="1",
            stateful=False,
            output_kind="analytical",
            produces_artifact_type="duplicate.v1",
            intrinsic_data_requirements=(
                DataRequirement(concept="OPEN_INTEREST"),
                DataRequirement(concept="OPEN_INTEREST", required=False),
            ),
        )


def test_request_fields_are_strict_and_explicit() -> None:
    with pytest.raises(TypeError, match="replay_support_required"):
        DataRequest(
            request_key="request",
            concept="OPEN_INTEREST",
            market_as_of=BASE,
            mode="LIVE",
            resolver_knowledge_cutoff=BASE,
            replay_support_required=1,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="alignment"):
        DataRequest(
            request_key="request",
            concept="OPEN_INTEREST",
            market_as_of=BASE,
            mode="LIVE",
            resolver_knowledge_cutoff=BASE,
            alignment="nearest",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="non-negative"):
        DataRequest(
            request_key="request",
            concept="OPEN_INTEREST",
            market_as_of=BASE,
            mode="LIVE",
            resolver_knowledge_cutoff=BASE,
            max_available_lag=-timedelta(seconds=1),
        )
