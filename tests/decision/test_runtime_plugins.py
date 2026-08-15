from __future__ import annotations

import pytest

from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.planning.planner import (
    DecisionLaneSpec,
    ModelBindingSpec,
    compile_decision_plan,
)
from apps.decision_app.runtime.plugins import (
    RuntimePluginCatalog,
    RuntimePluginDefinition,
)
from libs.contracts.decision import (
    DecisionContext,
    DecisionModelPlugin,
    ModelArtifact,
    ModelOutcome,
    ModelRequestContext,
    ModelSpec,
)


class Plugin:
    def __init__(self, spec: ModelSpec) -> None:
        self.spec = spec

    def data_requests(
        self,
        base_context: ModelRequestContext,
        state_snapshot: object | None = None,
    ) -> tuple[()]:
        return ()

    def evaluate(
        self,
        context: DecisionContext,
        state_snapshot: object | None = None,
    ) -> ModelOutcome:
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


SPEC = ModelSpec(
    name="Synthetic",
    version="1",
    stateful=False,
    output_kind="analytical",
    produces_artifact_type="synthetic.v1",
)


def binding():
    lane = DecisionLaneSpec(
        lane_id="BTCUSDT:1h",
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        decision_timeframe="1h",
        trigger_timeframe="1h",
        trigger_mode="on_bar_close",
        policy_name="default",
        policy_version="1",
        risk_profile_key="btc-default",
        bindings=(
            ModelBindingSpec(
                slot_name="primary",
                plugin_name="Synthetic",
                plugin_version="1",
            ),
        ),
    )
    return (
        compile_decision_plan(PluginCatalog([SPEC]), [lane])
        .lanes[0]
        .bindings["primary"]
    )


def test_runtime_catalog_resolves_exact_name_and_version() -> None:
    calls: list[object] = []
    catalog = RuntimePluginCatalog(
        [
            RuntimePluginDefinition(
                plugin_name="Synthetic",
                plugin_version="1",
                factory=lambda parameters: calls.append(parameters) or Plugin(SPEC),
            )
        ]
    )
    resolved = binding()
    plugin = catalog.instantiate(resolved)

    assert isinstance(plugin, DecisionModelPlugin)
    assert plugin.spec == SPEC
    assert len(calls) == 1

    with pytest.raises(ValueError, match="unknown runtime plugin"):
        catalog.resolve("Synthetic", "2")


def test_runtime_catalog_rejects_duplicate_registration_and_bad_factory() -> None:
    definition = RuntimePluginDefinition(
        plugin_name="Synthetic",
        plugin_version="1",
        factory=lambda parameters: Plugin(SPEC),
    )
    with pytest.raises(ValueError, match="duplicate runtime plugin"):
        RuntimePluginCatalog([definition, definition])
    with pytest.raises(TypeError, match="factory"):
        RuntimePluginDefinition(
            plugin_name="Synthetic",
            plugin_version="1",
            factory=object(),  # type: ignore[arg-type]
        )


def test_runtime_catalog_rejects_factory_with_wrong_plugin_spec() -> None:
    wrong = ModelSpec(
        name="Other",
        version="1",
        stateful=False,
        output_kind="analytical",
        produces_artifact_type="other.v1",
    )
    catalog = RuntimePluginCatalog(
        [
            RuntimePluginDefinition(
                plugin_name="Synthetic",
                plugin_version="1",
                factory=lambda parameters: Plugin(wrong),
            )
        ]
    )
    with pytest.raises(ValueError, match="spec does not match"):
        catalog.instantiate(binding())
