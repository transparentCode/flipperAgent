from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from apps.decision_app.model_runtime import (
    RewarmError,
    RewarmStep,
    StateTransactionError,
)
from apps.decision_app.planner import ModelBindingSpec
from libs.contracts.decision import (
    DataRequirement,
    DataSnapshot,
    DecisionContext,
    ModelArtifact,
    ModelOutcome,
    ModelRequestContext,
    ModelSpec,
)
from tests.decision.test_model_runtime import (
    BASE,
    Bundle,
    make_bundle,
    make_spec,
)


class CounterPlugin:
    def __init__(self, spec: ModelSpec) -> None:
        self.spec = spec
        self.evaluate_count = 0
        self.fail_at: int | None = None
        self.requested: tuple[DataRequirement, ...] = ()

    def data_requests(
        self,
        base_context: ModelRequestContext,
        state_snapshot: object | None = None,
    ) -> tuple[DataRequirement, ...]:
        return self.requested

    def evaluate(
        self,
        context: DecisionContext,
        state_snapshot: object | None = None,
    ) -> ModelOutcome:
        self.evaluate_count += 1
        if self.fail_at is not None and self.evaluate_count == self.fail_at:
            raise RuntimeError("synthetic replay failure")
        count = 0
        if state_snapshot is not None:
            count = state_snapshot["count"]
        return ModelOutcome(
            artifact=ModelArtifact(
                binding_id=context.binding_id,
                lane_id=context.lane_id,
                asset=context.asset,
                decision_timeframe=context.decision_timeframe,
                trigger_timeframe=context.trigger_timeframe,
                market_as_of=context.market_as_of,
                artifact_type=self.spec.produces_artifact_type,
                value={"count": count},
            ),
            proposed_next_state={"count": count + 1},
        )


def counter_bundle() -> tuple[Bundle, CounterPlugin]:
    spec = make_spec("Counter", "counter.v1", stateful=True)
    plugin = CounterPlugin(spec)
    bundle, plugins = make_bundle(
        [spec],
        (
            ModelBindingSpec(
                slot_name="counter", plugin_name="Counter", plugin_version="1"
            ),
        ),
        plugin_overrides={"Counter": plugin},
    )
    return bundle, plugins["Counter"]  # type: ignore[return-value]


def steps(bundle: Bundle, count: int) -> tuple[RewarmStep, ...]:
    return tuple(
        RewarmStep(
            lane_market_view=bundle.view(index),
            resolver_knowledge_cutoff=BASE + timedelta(hours=index + 1),
        )
        for index in range(count)
    )


@pytest.mark.asyncio
async def test_stateful_binding_starts_warming_and_requires_rewarm_before_live():
    bundle, plugin = counter_bundle()
    prepared = await bundle.runtime.prepare_live(
        bundle.view(0),
        resolver_knowledge_cutoff=BASE + timedelta(hours=1),
    )

    result = next(iter(prepared.binding_results.values()))
    assert result.status == "UNAVAILABLE"
    assert result.reason == "state_rewarm_required"
    assert plugin.evaluate_count == 0
    assert (
        bundle.runtime.state_store.get(
            next(iter(bundle.runtime.stateful_binding_ids))
        ).health
        == "WARMING"
    )


@pytest.mark.asyncio
async def test_rewarm_is_replay_only_and_installs_state_only_after_success():
    bundle, plugin = counter_bundle()
    replay_steps = steps(bundle, 3)
    result = await bundle.runtime.rewarm(replay_steps)

    binding_id = next(iter(bundle.runtime.stateful_binding_ids))
    state = bundle.runtime.state_store.get(binding_id)
    assert result.replay_step_count == 3
    assert result.final_market_as_of == BASE + timedelta(hours=3)
    assert state.health == "LIVE"
    assert state.committed_market_as_of == BASE + timedelta(hours=3)
    assert state.committed_state["count"] == 3

    prepared = await bundle.runtime.prepare_live(
        bundle.view(3),
        resolver_knowledge_cutoff=BASE + timedelta(hours=4),
    )
    assert plugin.evaluate_count == 4
    assert bundle.runtime.state_store.get(binding_id).committed_state["count"] == 3
    receipt = bundle.runtime.commit_prepared(prepared, "published")
    assert receipt.committed_binding_ids == (binding_id,)
    assert bundle.runtime.state_store.get(binding_id).committed_state["count"] == 4


@pytest.mark.asyncio
async def test_rewarm_resolves_external_data_in_replay_mode_only():
    requirement = DataRequirement(
        concept="REPLAY_SAFE",
        required=True,
        replay_support_required=True,
    )
    spec = make_spec(
        "CounterWithData",
        "counter-data.v1",
        stateful=True,
        data_requirements=(requirement,),
    )
    plugin = CounterPlugin(spec)
    modes: list[str] = []

    async def source_fetcher(request):
        modes.append(request.mode)
        return DataSnapshot(
            request_key=request.request_key,
            concept=request.concept,
            payload={"value": 1},
            event_time=request.market_as_of,
            available_at=request.market_as_of,
            fetched_at=request.market_as_of,
            source="pit",
            resolved_capability="LIVE_AND_REPLAY",
        )

    bundle, _ = make_bundle(
        [spec],
        (
            ModelBindingSpec(
                slot_name="counter",
                plugin_name="CounterWithData",
                plugin_version="1",
            ),
        ),
        source_fetcher=source_fetcher,
        plugin_overrides={"CounterWithData": plugin},
    )
    plugin.requested = (requirement,)

    await bundle.runtime.rewarm(steps(bundle, 2))

    assert modes == ["REPLAY", "REPLAY"]


@pytest.mark.asyncio
async def test_two_stateful_commit_validates_all_bindings_before_mutation():
    first_spec = make_spec("First", "first.v1", stateful=True)
    second_spec = make_spec("Second", "second.v1", stateful=True)
    first_plugin = CounterPlugin(first_spec)
    second_plugin = CounterPlugin(second_spec)
    bindings = (
        ModelBindingSpec(slot_name="first", plugin_name="First", plugin_version="1"),
        ModelBindingSpec(slot_name="second", plugin_name="Second", plugin_version="1"),
    )
    bundle, _ = make_bundle(
        [first_spec, second_spec],
        bindings,
        plugin_overrides={"First": first_plugin, "Second": second_plugin},
    )
    await bundle.runtime.rewarm(steps(bundle, 1))
    prepared = await bundle.runtime.prepare_live(
        bundle.view(1),
        resolver_knowledge_cutoff=BASE + timedelta(hours=2),
    )
    binding_ids = {
        binding.slot_name: binding.binding_id
        for binding in bundle.lane.bindings.values()
    }
    first_before = bundle.runtime.state_store.get(binding_ids["first"])
    second_before = bundle.runtime.state_store.get(binding_ids["second"])
    bundle.runtime.state_store.mark_health(
        binding_ids["second"],
        "DEGRADED",
        reason="synthetic stale commit",
    )

    with pytest.raises(StateTransactionError, match="stale"):
        bundle.runtime.commit_prepared(prepared, "published")

    assert bundle.runtime.state_store.get(binding_ids["first"]) == first_before
    assert bundle.runtime.pending_state_execution is prepared
    second_after = bundle.runtime.state_store.get(binding_ids["second"])
    assert second_after.health == "DEGRADED"
    assert second_after.committed_market_as_of == second_before.committed_market_as_of


@pytest.mark.asyncio
async def test_failed_middle_rewarm_leaves_real_store_unchanged():
    bundle, plugin = counter_bundle()
    before = dict(bundle.runtime.state_store.records)
    plugin.fail_at = 2

    with pytest.raises(RewarmError, match="rewarm step failed"):
        await bundle.runtime.rewarm(steps(bundle, 3))

    assert dict(bundle.runtime.state_store.records) == before


@pytest.mark.asyncio
async def test_rewarm_requires_contiguous_steps_and_baseline_continuation():
    bundle, _ = counter_bundle()
    replay_steps = steps(bundle, 3)
    await bundle.runtime.rewarm(replay_steps)

    with pytest.raises(RewarmError, match="first rewarm step"):
        await bundle.runtime.rewarm(
            (
                RewarmStep(
                    lane_market_view=bundle.view(2),
                    resolver_knowledge_cutoff=BASE + timedelta(hours=4),
                ),
            )
        )

    with pytest.raises(RewarmError, match="contiguous"):
        await bundle.runtime.rewarm(
            (
                RewarmStep(
                    lane_market_view=bundle.view(3),
                    resolver_knowledge_cutoff=BASE + timedelta(hours=5),
                ),
                RewarmStep(
                    lane_market_view=bundle.view(5),
                    resolver_knowledge_cutoff=BASE + timedelta(hours=7),
                ),
            )
        )


@pytest.mark.asyncio
async def test_abort_discards_proposal_and_forces_rewarm():
    bundle, _ = counter_bundle()
    await bundle.runtime.rewarm(steps(bundle, 2))
    binding_id = next(iter(bundle.runtime.stateful_binding_ids))
    before = bundle.runtime.state_store.get(binding_id)
    prepared = await bundle.runtime.prepare_live(
        bundle.view(2),
        resolver_knowledge_cutoff=BASE + timedelta(hours=3),
    )
    bundle.runtime.abort_prepared(prepared, "publication_failed")
    after = bundle.runtime.state_store.get(binding_id)
    assert after.committed_state == before.committed_state
    assert after.committed_market_as_of == before.committed_market_as_of
    assert after.health == "DEGRADED"

    blocked = await bundle.runtime.prepare_live(
        bundle.view(2),
        resolver_knowledge_cutoff=BASE + timedelta(hours=3),
    )
    assert (
        next(iter(blocked.binding_results.values())).reason == "state_rewarm_required"
    )


@pytest.mark.asyncio
async def test_copied_prepared_commit_is_rejected_without_changing_pending_state():
    bundle, _ = counter_bundle()
    await bundle.runtime.rewarm(steps(bundle, 2))
    prepared = await bundle.runtime.prepare_live(
        bundle.view(2),
        resolver_knowledge_cutoff=BASE + timedelta(hours=3),
    )
    copied = replace(prepared)
    state_before = dict(bundle.runtime.state_store.records)

    with pytest.raises(StateTransactionError, match="current pending"):
        bundle.runtime.commit_prepared(copied, "published")
    assert dict(bundle.runtime.state_store.records) == state_before
    assert bundle.runtime.pending_state_execution is prepared

    with pytest.raises(StateTransactionError, match="current pending"):
        bundle.runtime.abort_prepared(copied, "publication_failed")
    assert bundle.runtime.pending_state_execution is prepared
    bundle.runtime.abort_prepared(prepared, "publication_failed")
    assert bundle.runtime.pending_state_execution is None


@pytest.mark.asyncio
async def test_stateful_same_cutoff_is_rejected_before_second_evaluation():
    bundle, plugin = counter_bundle()
    await bundle.runtime.rewarm(steps(bundle, 1))
    view = bundle.view(1)
    prepared = await bundle.runtime.prepare_live(
        view,
        resolver_knowledge_cutoff=BASE + timedelta(hours=2),
    )
    bundle.runtime.commit_prepared(prepared, "published")
    evaluations = plugin.evaluate_count

    with pytest.raises(StateTransactionError, match="cutoff"):
        await bundle.runtime.prepare_live(
            view,
            resolver_knowledge_cutoff=BASE + timedelta(hours=2),
        )
    assert plugin.evaluate_count == evaluations


@pytest.mark.asyncio
async def test_stateful_live_requires_exact_next_trigger_cutoff():
    bundle, _ = counter_bundle()
    backward_view = bundle.view(0)
    replay_steps = steps(bundle, 2)
    await bundle.runtime.rewarm(replay_steps)

    same_view = replay_steps[-1].lane_market_view
    accepted_view = bundle.view(2)
    skipped_view = bundle.view(3)
    for view in (backward_view, same_view, skipped_view):
        with pytest.raises(StateTransactionError, match="next trigger cutoff"):
            await bundle.runtime.prepare_live(
                view,
                resolver_knowledge_cutoff=view.market_as_of + timedelta(hours=1),
            )

    prepared = await bundle.runtime.prepare_live(
        accepted_view,
        resolver_knowledge_cutoff=BASE + timedelta(hours=3),
    )
    bundle.runtime.abort_prepared(prepared, "continuity_test")


@pytest.mark.asyncio
async def test_one_pending_state_transaction_blocks_duplicate_and_future_prepare():
    bundle, plugin = counter_bundle()
    await bundle.runtime.rewarm(steps(bundle, 2))
    prepared = await bundle.runtime.prepare_live(
        bundle.view(2),
        resolver_knowledge_cutoff=BASE + timedelta(hours=3),
    )
    evaluations = plugin.evaluate_count

    with pytest.raises(StateTransactionError, match="pending finalization"):
        await bundle.runtime.prepare_live(
            bundle.view(2),
            resolver_knowledge_cutoff=BASE + timedelta(hours=3),
        )
    with pytest.raises(StateTransactionError, match="pending finalization"):
        await bundle.runtime.prepare_live(
            bundle.view(3),
            resolver_knowledge_cutoff=BASE + timedelta(hours=4),
        )
    assert plugin.evaluate_count == evaluations
    assert bundle.runtime.pending_state_execution is prepared

    bundle.runtime.commit_prepared(prepared, "published")
    assert bundle.runtime.pending_state_execution is None
    next_prepared = await bundle.runtime.prepare_live(
        bundle.view(3),
        resolver_knowledge_cutoff=BASE + timedelta(hours=4),
    )
    bundle.runtime.abort_prepared(next_prepared, "continuity_test")


@pytest.mark.asyncio
async def test_pending_transaction_blocks_rewarm_until_abort():
    bundle, _ = counter_bundle()
    await bundle.runtime.rewarm(steps(bundle, 2))
    prepared = await bundle.runtime.prepare_live(
        bundle.view(2),
        resolver_knowledge_cutoff=BASE + timedelta(hours=3),
    )
    pending_lane_view = bundle.view(2)

    with pytest.raises(RewarmError, match="pending"):
        await bundle.runtime.rewarm(
            (
                RewarmStep(
                    lane_market_view=pending_lane_view,
                    resolver_knowledge_cutoff=BASE + timedelta(hours=3),
                ),
            )
        )

    bundle.runtime.abort_prepared(prepared, "publication_failed")
    result = await bundle.runtime.rewarm(
        (
            RewarmStep(
                lane_market_view=bundle.view(2),
                resolver_knowledge_cutoff=BASE + timedelta(hours=3),
            ),
        )
    )
    assert result.final_market_as_of == BASE + timedelta(hours=3)


@pytest.mark.asyncio
async def test_partial_multi_stateful_failure_blocks_stale_continuation():
    first_spec = make_spec("First", "first.v1", stateful=True)
    second_spec = make_spec("Second", "second.v1", stateful=True)
    first_plugin = CounterPlugin(first_spec)
    second_plugin = CounterPlugin(second_spec)
    bundle, _ = make_bundle(
        [first_spec, second_spec],
        (
            ModelBindingSpec(
                slot_name="first", plugin_name="First", plugin_version="1"
            ),
            ModelBindingSpec(
                slot_name="second", plugin_name="Second", plugin_version="1"
            ),
        ),
        plugin_overrides={"First": first_plugin, "Second": second_plugin},
    )
    await bundle.runtime.rewarm(steps(bundle, 1))
    second_plugin.fail_at = second_plugin.evaluate_count + 1

    live_view = bundle.view(1)
    prepared = await bundle.runtime.prepare_live(
        live_view,
        resolver_knowledge_cutoff=BASE + timedelta(hours=2),
    )
    binding_ids = {
        binding.slot_name: binding.binding_id
        for binding in bundle.lane.bindings.values()
    }
    assert prepared.state_commit_eligible is False
    assert prepared.binding_results[binding_ids["first"]].status == "EXECUTED"
    assert prepared.binding_results[binding_ids["second"]].status == "INVALID"
    assert bundle.runtime.pending_state_execution is prepared
    first_evaluations = first_plugin.evaluate_count
    assert bundle.runtime.state_store.get(binding_ids["first"]).health == "LIVE"
    assert bundle.runtime.state_store.get(binding_ids["second"]).health == "INVALID"

    with pytest.raises(StateTransactionError, match="pending finalization"):
        await bundle.runtime.prepare_live(
            bundle.view(2),
            resolver_knowledge_cutoff=BASE + timedelta(hours=3),
        )
    assert first_plugin.evaluate_count == first_evaluations
    bundle.runtime.abort_prepared(prepared, "partial_state_failure")
    assert bundle.runtime.pending_state_execution is None
    assert bundle.runtime.state_store.get(binding_ids["first"]).health == "DEGRADED"
    assert bundle.runtime.state_store.get(binding_ids["second"]).health == "INVALID"
    blocked = await bundle.runtime.prepare_live(
        live_view,
        resolver_knowledge_cutoff=BASE + timedelta(hours=2),
    )
    assert all(
        result.status == "UNAVAILABLE" for result in blocked.binding_results.values()
    )
    assert first_plugin.evaluate_count == first_evaluations


def test_rewarm_install_rejects_mixed_stateful_cutoffs():
    first_spec = make_spec("First", "first.v1", stateful=True)
    second_spec = make_spec("Second", "second.v1", stateful=True)
    bundle, _ = make_bundle(
        [first_spec, second_spec],
        (
            ModelBindingSpec(
                slot_name="first", plugin_name="First", plugin_version="1"
            ),
            ModelBindingSpec(
                slot_name="second", plugin_name="Second", plugin_version="1"
            ),
        ),
    )
    binding_ids = sorted(bundle.runtime.stateful_binding_ids)
    records = dict(bundle.runtime.state_store.records)
    records[binding_ids[0]] = replace(
        records[binding_ids[0]],
        health="LIVE",
        committed_market_as_of=BASE + timedelta(hours=1),
    )
    records[binding_ids[1]] = replace(
        records[binding_ids[1]],
        health="LIVE",
        committed_market_as_of=BASE + timedelta(hours=2),
    )

    with pytest.raises(ValueError, match="share one committed cutoff"):
        bundle.runtime.state_store.install_rewarm(bundle.runtime.identity, records)
    assert all(
        record.health == "WARMING"
        for record in bundle.runtime.state_store.records.values()
    )
