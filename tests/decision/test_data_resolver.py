from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.data.resolver import (
    BindingDataRequest,
    BindingDataResolution,
    ConceptDataPolicy,
    DataPolicy,
    DataRequestError,
    DataResolution,
    DataResolver,
    DataSourceAttempt,
    DataSourceCatalog,
    DataSourceContractError,
    DataSourceDefinition,
    compile_data_plan,
    materialize_data_request,
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
    validate_data_snapshot,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def make_lane(
    requirements_by_slot: dict[str, tuple[DataRequirement, ...]],
    *,
    asset: str = "BTCUSDT",
):
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


def policy_for(
    concepts: tuple[str, ...],
    *,
    live_sources: tuple[str, ...] = ("cache", "pit", "live"),
    replay_sources: tuple[str, ...] = ("pit",),
) -> DataPolicy:
    return DataPolicy(
        name="operator",
        version="1",
        concepts={
            concept: ConceptDataPolicy(
                concept=concept,
                scope_mode="lane_asset",
                live_source_order=live_sources,
                replay_source_order=replay_sources,
            )
            for concept in concepts
        },
    )


def snapshot(
    request: DataRequest,
    *,
    source: str,
    capability: str = "LIVE_AND_REPLAY",
    event_time: datetime | None = None,
    available_at: datetime | None = None,
    represented_end_at: datetime | None = None,
    fetched_at: datetime | None = None,
) -> DataSnapshot:
    return DataSnapshot(
        request_key=request.request_key,
        concept=request.concept,
        payload={"value": Decimal(1)},
        event_time=event_time or request.market_as_of,
        available_at=available_at or request.market_as_of,
        fetched_at=fetched_at or request.market_as_of,
        source=source,
        resolved_capability=capability,  # type: ignore[arg-type]
        represented_end_at=represented_end_at,
    )


def source(
    name: str,
    fetcher,
    *,
    kind: str,
    capability: str,
) -> DataSourceDefinition:
    return DataSourceDefinition(
        name=name,
        version="1",
        kind=kind,  # type: ignore[arg-type]
        capability=capability,  # type: ignore[arg-type]
        fetcher=fetcher,
    )


def build_request(
    *,
    concepts: tuple[str, ...] = ("OPEN_INTEREST",),
    required: bool = True,
    replay_support_required: bool = False,
    mode: str = "LIVE",
    market_as_of: datetime = BASE,
    resolver_knowledge_cutoff: datetime = BASE + timedelta(seconds=1),
):
    lane = make_lane(
        {
            "primary": (
                DataRequirement(
                    concept=concepts[0],
                    required=required,
                    replay_support_required=replay_support_required,
                ),
            )
        }
    )
    plan = compile_data_plan(
        lane,
        policy_for(concepts),
        DataSourceCatalog(
            [
                source(
                    "cache", lambda request: None, kind="cache", capability="LIVE_ONLY"
                ),
                source(
                    "pit",
                    lambda request: None,
                    kind="pit",
                    capability="LIVE_AND_REPLAY",
                ),
                source(
                    "live", lambda request: None, kind="live", capability="LIVE_ONLY"
                ),
            ]
        ),
    )
    binding = next(iter(lane.bindings.values()))
    request = materialize_data_request(
        resolved_lane=lane,
        resolved_binding=binding,
        data_plan=plan,
        dynamic_requirement=binding.effective_data_requirements[0],
        mode=mode,  # type: ignore[arg-type]
        market_as_of=market_as_of,
        resolver_knowledge_cutoff=resolver_knowledge_cutoff,
    )
    return lane, plan, binding, request


def test_pit_freshness_alignment_and_availability_rules() -> None:
    request = DataRequest(
        request_key="request",
        concept="OPEN_INTEREST",
        market_as_of=BASE,
        mode="LIVE",
        resolver_knowledge_cutoff=BASE + timedelta(seconds=5),
        freshness_bound=timedelta(minutes=1),
        max_available_lag=timedelta(seconds=2),
        alignment="exact",
    )
    accepted = snapshot(
        request,
        source="pit",
        available_at=BASE + timedelta(seconds=2),
        fetched_at=BASE + timedelta(days=1),
    )
    assert validate_data_snapshot(request, accepted) is accepted
    with pytest.raises(ValueError, match="exact alignment"):
        validate_data_snapshot(
            request,
            snapshot(request, source="pit", event_time=BASE - timedelta(seconds=1)),
        )
    with pytest.raises(ValueError, match="future"):
        validate_data_snapshot(
            request,
            snapshot(request, source="pit", event_time=BASE + timedelta(seconds=1)),
        )
    with pytest.raises(ValueError, match="freshness"):
        validate_data_snapshot(
            replace_request(
                request,
                freshness_bound=timedelta(seconds=1),
                alignment="at_or_before",
            ),
            snapshot(request, source="pit", event_time=BASE - timedelta(seconds=2)),
        )
    with pytest.raises(ValueError, match="availability lag"):
        validate_data_snapshot(
            request,
            snapshot(
                request,
                source="pit",
                available_at=BASE + timedelta(seconds=3),
            ),
        )


def replace_request(request: DataRequest, **changes: object) -> DataRequest:
    values = {
        "request_key": request.request_key,
        "concept": request.concept,
        "market_as_of": request.market_as_of,
        "required": request.required,
        "mode": request.mode,
        "resolver_knowledge_cutoff": request.resolver_knowledge_cutoff,
        "replay_support_required": request.replay_support_required,
        "asset": request.asset,
        "scope": request.scope,
        "freshness_bound": request.freshness_bound,
        "max_available_lag": request.max_available_lag,
        "alignment": request.alignment,
    }
    values.update(changes)
    return DataRequest(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_live_cache_hit_stops_before_pit_and_live() -> None:
    calls: list[str] = []

    async def cache(request: DataRequest) -> DataSnapshot:
        calls.append("cache")
        return snapshot(request, source="cache", capability="LIVE_ONLY")

    async def pit(_: DataRequest) -> None:
        calls.append("pit")

    async def live(_: DataRequest) -> None:
        calls.append("live")

    lane = make_lane({"primary": (DataRequirement(concept="OPEN_INTEREST"),)})
    catalog = DataSourceCatalog(
        [
            source("cache", cache, kind="cache", capability="LIVE_ONLY"),
            source("pit", pit, kind="pit", capability="LIVE_AND_REPLAY"),
            source("live", live, kind="live", capability="LIVE_ONLY"),
        ]
    )
    plan = compile_data_plan(lane, policy_for(("OPEN_INTEREST",)), catalog)
    binding = next(iter(lane.bindings.values()))
    request = materialize_data_request(
        resolved_lane=lane,
        resolved_binding=binding,
        data_plan=plan,
        dynamic_requirement=binding.effective_data_requirements[0],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    result = await DataResolver(catalog).resolve(
        plan,
        lane,
        [BindingDataRequest(binding_id=binding.binding_id, request=request)],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    assert calls == ["cache"]
    assert result.bindings[binding.binding_id].available is True
    assert result.attempts[request.request_key][0].outcome == "ACCEPTED"


@pytest.mark.asyncio
async def test_live_ineligible_cache_falls_through_to_pit_without_live() -> None:
    calls: list[str] = []

    async def cache(request: DataRequest) -> DataSnapshot:
        calls.append("cache")
        return snapshot(
            request,
            source="cache",
            capability="LIVE_ONLY",
            event_time=BASE + timedelta(seconds=1),
        )

    async def pit(request: DataRequest) -> DataSnapshot:
        calls.append("pit")
        return snapshot(request, source="pit")

    async def live(_: DataRequest) -> None:
        calls.append("live")

    lane = make_lane({"primary": (DataRequirement(concept="OPEN_INTEREST"),)})
    catalog = DataSourceCatalog(
        [
            source("cache", cache, kind="cache", capability="LIVE_ONLY"),
            source("pit", pit, kind="pit", capability="LIVE_AND_REPLAY"),
            source("live", live, kind="live", capability="LIVE_ONLY"),
        ]
    )
    plan = compile_data_plan(lane, policy_for(("OPEN_INTEREST",)), catalog)
    binding = next(iter(lane.bindings.values()))
    request = materialize_data_request(
        resolved_lane=lane,
        resolved_binding=binding,
        data_plan=plan,
        dynamic_requirement=binding.effective_data_requirements[0],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    result = await DataResolver(catalog).resolve(
        plan,
        lane,
        [BindingDataRequest(binding_id=binding.binding_id, request=request)],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    assert calls == ["cache", "pit"]
    assert [attempt.outcome for attempt in result.attempts[request.request_key]] == [
        "REJECTED",
        "ACCEPTED",
    ]


@pytest.mark.asyncio
async def test_shared_physical_request_normalizes_requiredness_and_input_order() -> (
    None
):
    lane = make_lane(
        {
            "required": (DataRequirement(concept="OPEN_INTEREST"),),
            "optional_a": (DataRequirement(concept="OPEN_INTEREST", required=False),),
            "optional_b": (DataRequirement(concept="OPEN_INTEREST", required=False),),
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
                )
            },
        ),
        DataSourceCatalog(
            [source("pit", lambda _: None, kind="pit", capability="LIVE_AND_REPLAY")]
        ),
    )
    binding_by_slot = {binding.slot_name: binding for binding in lane.bindings.values()}

    async def resolve_in_order(
        order: tuple[str, ...],
    ) -> tuple[DataResolution, list[bool]]:
        source_required_values: list[bool] = []

        async def pit(request: DataRequest) -> DataSnapshot:
            source_required_values.append(request.required)
            if request.required:
                raise AssertionError("physical source received binding requiredness")
            return snapshot(request, source="pit")

        resolver = DataResolver(
            DataSourceCatalog(
                [source("pit", pit, kind="pit", capability="LIVE_AND_REPLAY")]
            )
        )
        requests = [
            BindingDataRequest(
                binding_id=binding_by_slot[slot].binding_id,
                request=materialize_data_request(
                    resolved_lane=lane,
                    resolved_binding=binding_by_slot[slot],
                    data_plan=plan,
                    dynamic_requirement=binding_by_slot[
                        slot
                    ].effective_data_requirements[0],
                    mode="LIVE",
                    market_as_of=BASE,
                    resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
                ),
            )
            for slot in order
        ]
        result = await resolver.resolve(
            plan,
            lane,
            requests,
            mode="LIVE",
            market_as_of=BASE,
            resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
        )
        return result, source_required_values

    required_first, required_first_values = await resolve_in_order(
        ("required", "optional_a", "optional_b")
    )
    optional_first, optional_first_values = await resolve_in_order(
        ("optional_b", "required", "optional_a")
    )

    assert required_first == optional_first
    assert required_first_values == [False]
    assert optional_first_values == [False]
    assert len(required_first.requests) == 1
    assert next(iter(required_first.requests.values())).required is False
    assert all(binding.available for binding in required_first.bindings.values())


@pytest.mark.asyncio
async def test_replay_safe_live_cache_can_satisfy_replay_required_live_request() -> (
    None
):
    calls: list[str] = []

    async def cache(request: DataRequest) -> DataSnapshot:
        calls.append("cache")
        return snapshot(
            request,
            source="cache",
            capability="LIVE_AND_REPLAY",
        )

    async def pit(_: DataRequest) -> None:
        calls.append("pit")

    lane = make_lane(
        {
            "primary": (
                DataRequirement(
                    concept="OPEN_INTEREST",
                    replay_support_required=True,
                ),
            )
        }
    )
    catalog = DataSourceCatalog(
        [
            source("cache", cache, kind="cache", capability="LIVE_AND_REPLAY"),
            source("pit", pit, kind="pit", capability="LIVE_AND_REPLAY"),
        ]
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
                    live_source_order=("cache", "pit"),
                    replay_source_order=("pit",),
                )
            },
        ),
        catalog,
    )
    binding = next(iter(lane.bindings.values()))
    request = materialize_data_request(
        resolved_lane=lane,
        resolved_binding=binding,
        data_plan=plan,
        dynamic_requirement=binding.effective_data_requirements[0],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    result = await DataResolver(catalog).resolve(
        plan,
        lane,
        [BindingDataRequest(binding_id=binding.binding_id, request=request)],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    assert calls == ["cache"]
    assert result.bindings[binding.binding_id].available is True


@pytest.mark.asyncio
async def test_replay_required_live_only_cache_falls_through_to_pit() -> None:
    calls: list[str] = []

    async def cache(request: DataRequest) -> DataSnapshot:
        calls.append("cache")
        return snapshot(request, source="cache", capability="LIVE_ONLY")

    async def pit(request: DataRequest) -> DataSnapshot:
        calls.append("pit")
        return snapshot(request, source="pit")

    lane = make_lane(
        {
            "primary": (
                DataRequirement(
                    concept="OPEN_INTEREST",
                    replay_support_required=True,
                ),
            )
        }
    )
    catalog = DataSourceCatalog(
        [
            source("cache", cache, kind="cache", capability="LIVE_ONLY"),
            source("pit", pit, kind="pit", capability="LIVE_AND_REPLAY"),
        ]
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
                    live_source_order=("cache", "pit"),
                    replay_source_order=("pit",),
                )
            },
        ),
        catalog,
    )
    binding = next(iter(lane.bindings.values()))
    request = materialize_data_request(
        resolved_lane=lane,
        resolved_binding=binding,
        data_plan=plan,
        dynamic_requirement=binding.effective_data_requirements[0],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    result = await DataResolver(catalog).resolve(
        plan,
        lane,
        [BindingDataRequest(binding_id=binding.binding_id, request=request)],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    assert calls == ["cache", "pit"]
    assert result.bindings[binding.binding_id].available is True
    assert [attempt.outcome for attempt in result.attempts[request.request_key]] == [
        "REJECTED",
        "ACCEPTED",
    ]


@pytest.mark.asyncio
async def test_live_pit_miss_attempts_exactly_one_live_source() -> None:
    calls: list[str] = []

    async def pit(_: DataRequest) -> None:
        calls.append("pit")

    async def live(request: DataRequest) -> DataSnapshot:
        calls.append("live")
        return snapshot(request, source="live", capability="LIVE_ONLY")

    lane = make_lane({"primary": (DataRequirement(concept="OPEN_INTEREST"),)})
    catalog = DataSourceCatalog(
        [
            source("pit", pit, kind="pit", capability="LIVE_AND_REPLAY"),
            source("live", live, kind="live", capability="LIVE_ONLY"),
        ]
    )
    plan = compile_data_plan(
        lane,
        policy_for(("OPEN_INTEREST",), live_sources=("pit", "live")),
        catalog,
    )
    binding = next(iter(lane.bindings.values()))
    request = materialize_data_request(
        resolved_lane=lane,
        resolved_binding=binding,
        data_plan=plan,
        dynamic_requirement=binding.effective_data_requirements[0],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    result = await DataResolver(catalog).resolve(
        plan,
        lane,
        [BindingDataRequest(binding_id=binding.binding_id, request=request)],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    assert calls == ["pit", "live"]
    assert result.bindings[binding.binding_id].available is True
    assert [attempt.outcome for attempt in result.attempts[request.request_key]] == [
        "MISS",
        "ACCEPTED",
    ]


@pytest.mark.asyncio
async def test_source_exception_records_error_and_falls_through() -> None:
    calls: list[str] = []

    async def pit(_: DataRequest) -> None:
        calls.append("pit")
        raise RuntimeError("synthetic source failure")

    async def live(request: DataRequest) -> DataSnapshot:
        calls.append("live")
        return snapshot(request, source="live", capability="LIVE_ONLY")

    lane = make_lane({"primary": (DataRequirement(concept="OPEN_INTEREST"),)})
    catalog = DataSourceCatalog(
        [
            source("pit", pit, kind="pit", capability="LIVE_AND_REPLAY"),
            source("live", live, kind="live", capability="LIVE_ONLY"),
        ]
    )
    plan = compile_data_plan(
        lane,
        policy_for(("OPEN_INTEREST",), live_sources=("pit", "live")),
        catalog,
    )
    binding = next(iter(lane.bindings.values()))
    request = materialize_data_request(
        resolved_lane=lane,
        resolved_binding=binding,
        data_plan=plan,
        dynamic_requirement=binding.effective_data_requirements[0],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    result = await DataResolver(catalog).resolve(
        plan,
        lane,
        [BindingDataRequest(binding_id=binding.binding_id, request=request)],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    assert calls == ["pit", "live"]
    assert [attempt.outcome for attempt in result.attempts[request.request_key]] == [
        "ERROR",
        "ACCEPTED",
    ]


@pytest.mark.asyncio
async def test_replay_never_calls_cache_or_live_and_requires_replay_safe_source() -> (
    None
):
    calls: list[str] = []

    async def forbidden(name: str, _: DataRequest) -> None:
        calls.append(name)

    async def cache(request: DataRequest) -> None:
        return await forbidden("cache", request)

    async def live(request: DataRequest) -> None:
        return await forbidden("live", request)

    async def pit(request: DataRequest) -> DataSnapshot:
        calls.append("pit")
        return snapshot(request, source="pit", fetched_at=BASE + timedelta(days=2))

    lane = make_lane(
        {
            "primary": (
                DataRequirement(
                    concept="OPEN_INTEREST",
                    replay_support_required=True,
                ),
            )
        }
    )
    catalog = DataSourceCatalog(
        [
            source("cache", cache, kind="cache", capability="LIVE_ONLY"),
            source("pit", pit, kind="pit", capability="LIVE_AND_REPLAY"),
            source("live", live, kind="live", capability="LIVE_ONLY"),
        ]
    )
    plan = compile_data_plan(lane, policy_for(("OPEN_INTEREST",)), catalog)
    binding = next(iter(lane.bindings.values()))
    request = materialize_data_request(
        resolved_lane=lane,
        resolved_binding=binding,
        data_plan=plan,
        dynamic_requirement=binding.effective_data_requirements[0],
        mode="REPLAY",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    result = await DataResolver(catalog).resolve(
        plan,
        lane,
        [BindingDataRequest(binding_id=binding.binding_id, request=request)],
        mode="REPLAY",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    assert calls == ["pit"]
    assert result.bindings[binding.binding_id].available is True


@pytest.mark.asyncio
async def test_replay_rejects_late_pit_snapshot_without_calling_live_sources() -> None:
    calls: list[str] = []

    async def cache(_: DataRequest) -> None:
        calls.append("cache")

    async def live(_: DataRequest) -> None:
        calls.append("live")

    async def pit(request: DataRequest) -> DataSnapshot:
        calls.append("pit")
        return snapshot(
            request,
            source="pit",
            available_at=BASE + timedelta(seconds=2),
        )

    lane = make_lane(
        {
            "primary": (
                DataRequirement(
                    concept="OPEN_INTEREST",
                    replay_support_required=True,
                ),
            )
        }
    )
    catalog = DataSourceCatalog(
        [
            source("cache", cache, kind="cache", capability="LIVE_ONLY"),
            source("pit", pit, kind="pit", capability="LIVE_AND_REPLAY"),
            source("live", live, kind="live", capability="LIVE_ONLY"),
        ]
    )
    plan = compile_data_plan(lane, policy_for(("OPEN_INTEREST",)), catalog)
    binding = next(iter(lane.bindings.values()))
    request = materialize_data_request(
        resolved_lane=lane,
        resolved_binding=binding,
        data_plan=plan,
        dynamic_requirement=binding.effective_data_requirements[0],
        mode="REPLAY",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    result = await DataResolver(catalog).resolve(
        plan,
        lane,
        [BindingDataRequest(binding_id=binding.binding_id, request=request)],
        mode="REPLAY",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    assert calls == ["pit"]
    assert result.bindings[binding.binding_id].available is False
    assert result.attempts[request.request_key][0].outcome == "REJECTED"


@pytest.mark.asyncio
async def test_equivalent_requests_deduplicate_and_missing_required_is_binding_local() -> (
    None
):
    calls: list[str] = []

    async def pit(request: DataRequest) -> DataSnapshot | None:
        calls.append(request.concept)
        if request.concept == "OPEN_INTEREST":
            return None
        return snapshot(request, source="pit")

    requirements = {
        "required": (DataRequirement(concept="OPEN_INTEREST"),),
        "optional": (DataRequirement(concept="OPEN_INTEREST", required=False),),
        "other": (DataRequirement(concept="BTC_DOMINANCE"),),
    }
    lane = make_lane(requirements)
    catalog = DataSourceCatalog(
        [source("pit", pit, kind="pit", capability="LIVE_AND_REPLAY")]
    )
    plan = compile_data_plan(
        lane,
        DataPolicy(
            name="operator",
            version="1",
            concepts={
                concept: ConceptDataPolicy(
                    concept=concept,
                    scope_mode="lane_asset",
                    live_source_order=("pit",),
                    replay_source_order=("pit",),
                )
                for concept in {
                    item.concept for values in requirements.values() for item in values
                }
            },
        ),
        catalog,
    )
    requests: list[BindingDataRequest] = []
    for binding in lane.bindings.values():
        request = materialize_data_request(
            resolved_lane=lane,
            resolved_binding=binding,
            data_plan=plan,
            dynamic_requirement=binding.effective_data_requirements[0],
            mode="LIVE",
            market_as_of=BASE,
            resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
        )
        requests.append(
            BindingDataRequest(binding_id=binding.binding_id, request=request)
        )
    result = await DataResolver(catalog).resolve(
        plan,
        lane,
        requests,
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    assert sorted(calls) == ["BTC_DOMINANCE", "OPEN_INTEREST"]
    by_slot = {
        lane_binding.slot_name: result.bindings[lane_binding.binding_id]
        for lane_binding in lane.bindings.values()
    }
    assert by_slot["required"].available is False
    assert by_slot["optional"].available is True
    assert by_slot["optional"].missing_optional_requests
    assert by_slot["other"].available is True
    assert next(
        item.request.request_key
        for item in requests
        if item.binding_id
        == next(
            binding.binding_id
            for binding in lane.bindings.values()
            if binding.slot_name == "required"
        )
    ) == next(
        item.request.request_key
        for item in requests
        if item.binding_id
        == next(
            binding.binding_id
            for binding in lane.bindings.values()
            if binding.slot_name == "optional"
        )
    )
    assert set(result.shared_snapshots) == {
        next(
            request.request.request_key
            for request in requests
            if request.request.concept == "BTC_DOMINANCE"
        )
    }


@pytest.mark.parametrize(
    ("required_keys", "optional_keys"),
    [("overlap", "overlap"), ("omitted", "empty"), ("empty", "foreign")],
)
def test_binding_resolution_rejects_invalid_required_optional_partition(
    required_keys: str,
    optional_keys: str,
) -> None:
    required = {"overlap": ("request",), "omitted": (), "empty": ()}[required_keys]
    optional = {
        "overlap": ("request",),
        "empty": (),
        "foreign": ("other",),
    }[optional_keys]
    with pytest.raises(ValueError):
        BindingDataResolution(
            binding_id="binding",
            requested_request_keys=("request",),
            required_request_keys=required,
            optional_request_keys=optional,
            available=True,
        )


def test_binding_resolution_rejects_required_optional_missingness_relabeling() -> None:
    with pytest.raises(ValueError, match="optional requests"):
        BindingDataResolution(
            binding_id="required-binding",
            requested_request_keys=("request",),
            required_request_keys=("request",),
            optional_request_keys=(),
            available=True,
            missing_optional_requests=("request",),
        )
    with pytest.raises(ValueError, match="required requests"):
        BindingDataResolution(
            binding_id="optional-binding",
            requested_request_keys=("request",),
            required_request_keys=(),
            optional_request_keys=("request",),
            available=False,
            missing_required_requests=("request",),
        )


@pytest.mark.asyncio
async def test_data_resolution_rejects_contradictory_attempt_evidence() -> None:
    async def pit(request: DataRequest) -> DataSnapshot:
        return snapshot(request, source="pit")

    lane = make_lane({"primary": (DataRequirement(concept="OPEN_INTEREST"),)})
    catalog = DataSourceCatalog(
        [source("pit", pit, kind="pit", capability="LIVE_AND_REPLAY")]
    )
    plan = compile_data_plan(
        lane,
        policy_for(("OPEN_INTEREST",), live_sources=("pit",)),
        catalog,
    )
    binding = next(iter(lane.bindings.values()))
    request = materialize_data_request(
        resolved_lane=lane,
        resolved_binding=binding,
        data_plan=plan,
        dynamic_requirement=binding.effective_data_requirements[0],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    valid = await DataResolver(catalog).resolve(
        plan,
        lane,
        [BindingDataRequest(binding_id=binding.binding_id, request=request)],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    key = request.request_key
    accepted = DataSourceAttempt(
        source="pit",
        source_kind="pit",
        outcome="ACCEPTED",
        reason="accepted",
    )
    miss = DataSourceAttempt(
        source="pit",
        source_kind="pit",
        outcome="MISS",
        reason="miss",
    )
    with pytest.raises(ValueError, match="exactly one accepted"):
        replace(valid, attempts={key: (miss,)})
    with pytest.raises(ValueError, match="final attempt"):
        replace(valid, attempts={key: (accepted, miss)})
    with pytest.raises(ValueError, match="source"):
        replace(
            valid,
            attempts={
                key: (
                    DataSourceAttempt(
                        source="other",
                        source_kind="pit",
                        outcome="ACCEPTED",
                        reason="accepted",
                    ),
                )
            },
        )
    with pytest.raises(ValueError, match="exactly one accepted"):
        replace(valid, attempts={key: (accepted, accepted)})

    async def miss_source(_: DataRequest) -> None:
        pass

    unavailable_catalog = DataSourceCatalog(
        [
            source(
                "pit",
                miss_source,
                kind="pit",
                capability="LIVE_AND_REPLAY",
            )
        ]
    )
    unavailable = await DataResolver(unavailable_catalog).resolve(
        plan,
        lane,
        [BindingDataRequest(binding_id=binding.binding_id, request=request)],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="unavailable"):
        replace(unavailable, attempts={key: (accepted,)})


@pytest.mark.asyncio
async def test_noncanonical_request_key_is_rejected_before_source_call() -> None:
    calls: list[str] = []

    async def pit(request: DataRequest) -> DataSnapshot:
        calls.append(request.concept)
        return snapshot(request, source="pit")

    lane = make_lane({"primary": (DataRequirement(concept="OPEN_INTEREST"),)})
    catalog = DataSourceCatalog(
        [source("pit", pit, kind="pit", capability="LIVE_AND_REPLAY")]
    )
    plan = compile_data_plan(
        lane,
        policy_for(("OPEN_INTEREST",), live_sources=("pit",)),
        catalog,
    )
    binding = next(iter(lane.bindings.values()))
    request = materialize_data_request(
        resolved_lane=lane,
        resolved_binding=binding,
        data_plan=plan,
        dynamic_requirement=binding.effective_data_requirements[0],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    with pytest.raises(DataRequestError, match="canonical"):
        await DataResolver(catalog).resolve(
            plan,
            lane,
            [
                BindingDataRequest(
                    binding_id=binding.binding_id,
                    request=replace_request(request, request_key="not-canonical"),
                )
            ],
            mode="LIVE",
            market_as_of=BASE,
            resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
        )
    assert calls == []


@pytest.mark.asyncio
async def test_source_contract_corruption_fails_closed() -> None:
    async def corrupt(request: DataRequest) -> DataSnapshot:
        return snapshot(request, source="different")

    lane = make_lane({"primary": (DataRequirement(concept="OPEN_INTEREST"),)})
    catalog = DataSourceCatalog(
        [source("pit", corrupt, kind="pit", capability="LIVE_AND_REPLAY")]
    )
    plan = compile_data_plan(
        lane,
        policy_for(("OPEN_INTEREST",), live_sources=("pit",)),
        catalog,
    )
    binding = next(iter(lane.bindings.values()))
    request = materialize_data_request(
        resolved_lane=lane,
        resolved_binding=binding,
        data_plan=plan,
        dynamic_requirement=binding.effective_data_requirements[0],
        mode="LIVE",
        market_as_of=BASE,
        resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
    )
    with pytest.raises(DataSourceContractError, match="source"):
        await DataResolver(catalog).resolve(
            plan,
            lane,
            [BindingDataRequest(binding_id=binding.binding_id, request=request)],
            mode="LIVE",
            market_as_of=BASE,
            resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
        )


def test_cancelled_source_is_not_converted_to_a_miss() -> None:
    async def run() -> None:
        async def cancel(_: DataRequest) -> None:
            raise asyncio.CancelledError

        lane = make_lane({"primary": (DataRequirement(concept="OPEN_INTEREST"),)})
        catalog = DataSourceCatalog(
            [source("pit", cancel, kind="pit", capability="LIVE_AND_REPLAY")]
        )
        plan = compile_data_plan(
            lane,
            policy_for(("OPEN_INTEREST",), live_sources=("pit",)),
            catalog,
        )
        binding = next(iter(lane.bindings.values()))
        request = materialize_data_request(
            resolved_lane=lane,
            resolved_binding=binding,
            data_plan=plan,
            dynamic_requirement=binding.effective_data_requirements[0],
            mode="LIVE",
            market_as_of=BASE,
            resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
        )
        with pytest.raises(asyncio.CancelledError):
            await DataResolver(catalog).resolve(
                plan,
                lane,
                [BindingDataRequest(binding_id=binding.binding_id, request=request)],
                mode="LIVE",
                market_as_of=BASE,
                resolver_knowledge_cutoff=BASE + timedelta(seconds=1),
            )

    asyncio.run(run())
