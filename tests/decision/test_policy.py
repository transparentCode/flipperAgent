from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.decision_app.identity import (
    compute_decision_execution_revision,
    decision_id,
)
from apps.decision_app.model_runtime import BindingExecutionResult
from apps.decision_app.planner import ModelBindingSpec
from apps.decision_app.policy import (
    PASSTHROUGH_V1,
    PRIORITY_V1,
    DecisionPolicy,
    DecisionPolicyCatalog,
    DecisionPolicyError,
    DecisionPolicyEvaluation,
)
from libs.contracts.decision import (
    DecisionContext,
    ModelArtifact,
    ModelDecision,
    ModelOutcome,
    ModelRequestContext,
)
from tests.decision.test_model_runtime import make_bundle, make_spec


class SyntheticDecisionPlugin:
    def __init__(self, spec, *, direction: int | None, conviction: float | None):
        self.spec = spec
        self.direction = direction
        self.conviction = conviction

    def data_requests(
        self,
        base_context: ModelRequestContext,
        state_snapshot: object | None = None,
    ) -> tuple:
        return ()

    def evaluate(
        self,
        context: DecisionContext,
        state_snapshot: object | None = None,
    ) -> ModelOutcome:
        decision = None
        if self.direction is not None or self.conviction is not None:
            decision = ModelDecision(
                binding_id=context.binding_id,
                asset=context.asset,
                decision_timeframe=context.decision_timeframe,
                trigger_timeframe=context.trigger_timeframe,
                market_as_of=context.market_as_of,
                signal_time=context.market_as_of,
                direction_hint=self.direction,
                conviction=self.conviction,
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
            ),
            decision=decision,
        )


def make_signal_bundle(
    *,
    bindings,
    plugins,
    policy_name: str = "passthrough",
    policy_parameters: dict[str, object] | None = None,
    definitions=(),
    allowed_features=(),
):
    specs = [plugin.spec for plugin in plugins.values()]
    overrides = {spec.name: plugins[spec.name] for spec in specs}
    return make_bundle(
        specs,
        bindings,
        definitions=definitions,
        allowed_features=allowed_features,
        plugin_overrides=overrides,
        policy_name=policy_name,
        policy_parameters=policy_parameters,
    )


def decision_plugin(
    name: str,
    *,
    direction: int | None,
    conviction: float | None,
    feature_requirements=(),
):
    spec = replace(
        make_spec(
            name,
            f"{name.lower()}.v1",
            feature_requirements=feature_requirements,
        ),
        output_kind="decision_capable",
    )
    return SyntheticDecisionPlugin(
        spec,
        direction=direction,
        conviction=conviction,
    )


def test_policy_catalog_is_exact_and_rejects_duplicates_or_unknown() -> None:
    catalog = DecisionPolicyCatalog([PASSTHROUGH_V1, PRIORITY_V1])
    assert catalog.resolve("passthrough", "1") == PASSTHROUGH_V1
    with pytest.raises(ValueError, match="duplicate"):
        DecisionPolicyCatalog([PASSTHROUGH_V1, PASSTHROUGH_V1])
    with pytest.raises(DecisionPolicyError, match="unknown"):
        catalog.resolve("missing", "1")


def test_policy_catalog_cannot_change_semantics_in_place() -> None:
    catalog = DecisionPolicyCatalog([PASSTHROUGH_V1, PRIORITY_V1])

    with pytest.raises(AttributeError, match="immutable"):
        catalog._definitions = {}
    with pytest.raises(TypeError):
        catalog._definitions[("passthrough", "1")] = PRIORITY_V1
    with pytest.raises(AttributeError, match="immutable"):
        del catalog._definitions

    assert catalog.resolve("passthrough", "1") == PASSTHROUGH_V1


@pytest.mark.asyncio
async def test_passthrough_selects_exact_decision_and_identity_ignores_ready_time():
    plugin = decision_plugin("Decision", direction=1, conviction=0.75)
    bundle, _ = make_signal_bundle(
        bindings=(
            ModelBindingSpec(
                slot_name="decision",
                plugin_name="Decision",
                plugin_version="1",
            ),
        ),
        plugins={"Decision": plugin},
        policy_parameters={"source_slot": "decision"},
    )
    prepared = await bundle.runtime.prepare_live(
        bundle.view(0),
        resolver_knowledge_cutoff=bundle.view(0).market_as_of,
    )
    policy = DecisionPolicy(DecisionPolicyCatalog([PASSTHROUGH_V1]))
    first = policy.evaluate(
        bundle.lane,
        prepared,
        decision_ready_at=prepared.market_as_of,
    )
    second = policy.evaluate(
        bundle.lane,
        prepared,
        decision_ready_at=prepared.market_as_of + timedelta(seconds=4),
    )
    assert first.status == "SIGNAL"
    assert first.result is not None
    assert (
        first.result.decision
        == prepared.binding_results[
            next(iter(prepared.binding_results))
        ].outcome.decision
    )
    assert first.result.decision_id == second.result.decision_id
    assert (
        first.result.decision_execution_revision
        == second.result.decision_execution_revision
    )
    assert first.result.decision_ready_at != second.result.decision_ready_at


@pytest.mark.asyncio
async def test_passthrough_analytical_none_is_final_no_signal():
    plugin = decision_plugin("Analytical", direction=None, conviction=None)
    bundle, _ = make_signal_bundle(
        bindings=(
            ModelBindingSpec(
                slot_name="analytical",
                plugin_name="Analytical",
                plugin_version="1",
            ),
        ),
        plugins={"Analytical": plugin},
        policy_parameters={"source_slot": "analytical"},
    )
    view = bundle.view(0)
    prepared = await bundle.runtime.prepare_live(
        view,
        resolver_knowledge_cutoff=view.market_as_of,
    )
    evaluation = DecisionPolicy(DecisionPolicyCatalog([PASSTHROUGH_V1])).evaluate(
        bundle.lane,
        prepared,
        decision_ready_at=view.market_as_of,
    )
    assert evaluation == DecisionPolicyEvaluation(
        status="NO_SIGNAL",
        result=evaluation.result,
        selected_binding_id=evaluation.selected_binding_id,
        contributing_binding_ids=evaluation.contributing_binding_ids,
        reason="no_tradable_decision",
    )
    assert evaluation.result is not None
    assert evaluation.result.decision is None


@pytest.mark.asyncio
async def test_priority_uses_declared_order_without_score_comparison():
    first = decision_plugin("First", direction=None, conviction=None)
    second = decision_plugin("Second", direction=-1, conviction=0.2)
    bundle, _ = make_signal_bundle(
        bindings=(
            ModelBindingSpec(
                slot_name="first", plugin_name="First", plugin_version="1"
            ),
            ModelBindingSpec(
                slot_name="second", plugin_name="Second", plugin_version="1"
            ),
        ),
        plugins={"First": first, "Second": second},
        policy_name="priority",
        policy_parameters={"source_slots": ["first", "second"]},
    )
    view = bundle.view(0)
    prepared = await bundle.runtime.prepare_live(
        view,
        resolver_knowledge_cutoff=view.market_as_of,
    )
    evaluation = DecisionPolicy(DecisionPolicyCatalog([PRIORITY_V1])).evaluate(
        bundle.lane,
        prepared,
        decision_ready_at=view.market_as_of,
    )
    assert evaluation.status == "SIGNAL"
    assert evaluation.selected_binding_id == next(
        binding.binding_id
        for binding in bundle.lane.bindings.values()
        if binding.slot_name == "second"
    )
    assert evaluation.result.decision.direction_hint == -1


@pytest.mark.asyncio
async def test_policy_source_statuses_fail_closed():
    plugin = decision_plugin("Decision", direction=1, conviction=0.5)
    bundle, _ = make_signal_bundle(
        bindings=(
            ModelBindingSpec(
                slot_name="decision", plugin_name="Decision", plugin_version="1"
            ),
        ),
        plugins={"Decision": plugin},
        policy_parameters={"source_slot": "decision"},
    )
    view = bundle.view(0)
    prepared = await bundle.runtime.prepare_live(
        view,
        resolver_knowledge_cutoff=view.market_as_of,
    )
    binding_id = next(iter(prepared.binding_results))
    blocked = replace(
        prepared,
        binding_results={
            binding_id: BindingExecutionResult(
                binding_id=binding_id,
                status="UNAVAILABLE",
                reason="missing",
            )
        },
    )
    evaluation = DecisionPolicy(DecisionPolicyCatalog([PASSTHROUGH_V1])).evaluate(
        bundle.lane,
        blocked,
        decision_ready_at=view.market_as_of,
    )
    assert evaluation.status == "BLOCKED"


@pytest.mark.asyncio
async def test_bad_passthrough_configuration_is_invalid_not_no_signal():
    plugin = decision_plugin("Decision", direction=1, conviction=0.5)
    bundle, _ = make_signal_bundle(
        bindings=(_binding_for_policy_test(),),
        plugins={"Decision": plugin},
        policy_parameters={},
    )
    view = bundle.view(0)
    prepared = await bundle.runtime.prepare_live(
        view,
        resolver_knowledge_cutoff=view.market_as_of,
    )
    evaluation = DecisionPolicy(DecisionPolicyCatalog([PASSTHROUGH_V1])).evaluate(
        bundle.lane,
        prepared,
        decision_ready_at=view.market_as_of,
    )
    assert evaluation.status == "INVALID"
    assert evaluation.reason == "passthrough requires source_slot"


def _binding_for_policy_test() -> ModelBindingSpec:
    return ModelBindingSpec(
        slot_name="decision",
        plugin_name="Decision",
        plugin_version="1",
    )


def test_final_execution_identity_includes_all_material_policy_inputs() -> None:
    common = {
        "lane_id": "BTCUSDT:1h",
        "base_lane_revision": "lane-a",
        "feature_plan_fingerprint": "feature-a",
        "data_plan_fingerprint": "data-a",
        "policy_name": "passthrough",
        "policy_version": "1",
        "policy_parameters": {"source_slot": "decision"},
    }
    baseline = compute_decision_execution_revision(**common)
    for field, value in (
        ("base_lane_revision", "lane-b"),
        ("feature_plan_fingerprint", "feature-b"),
        ("data_plan_fingerprint", "data-b"),
        ("policy_name", "priority"),
        ("policy_version", "2"),
        ("policy_parameters", {"source_slot": "other"}),
    ):
        changed = dict(common)
        changed[field] = value
        assert compute_decision_execution_revision(**changed) != baseline

    first_id = decision_id(
        lane_id="BTCUSDT:1h",
        lane_revision=baseline,
        market_as_of=datetime(
            2026,
            1,
            1,
            1,
            tzinfo=UTC,
        ),
    )
    second_id = decision_id(
        lane_id="BTCUSDT:1h",
        lane_revision=baseline,
        market_as_of=datetime(
            2026,
            1,
            1,
            2,
            tzinfo=UTC,
        ),
    )
    assert first_id != second_id
