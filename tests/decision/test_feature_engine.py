from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.decision_app.catalog import PluginCatalog
from apps.decision_app.feature_engine import (
    BindingFeatureResolution,
    FeatureComputationError,
    FeatureEngine,
    FeatureResolution,
)
from apps.decision_app.features import (
    FeatureCatalog,
    FeatureHistoryRequirement,
    FeaturePlanError,
    FeaturePolicy,
    SharedFeatureDefinition,
    compile_feature_bar_store_capacities,
    compile_feature_plan,
    merge_bar_store_capacities,
)
from apps.decision_app.market_state import (
    BarStore,
    TimeframeGeometryError,
    TimeframeGrid,
    compile_bar_store_capacities,
)
from apps.decision_app.planner import (
    DecisionLaneSpec,
    ModelBindingSpec,
    compile_decision_plan,
)
from apps.decision_app.readiness import compile_lane_market_requirements
from apps.decision_app.view import DecisionViewBuilder
from libs.contracts.decision import (
    CausalBarView,
    FeatureRequirement,
    FeatureSnapshot,
    ModelSpec,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)
GRID = TimeframeGrid(
    alignment_origin=BASE,
    durations={
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
    },
)


def make_bar(
    timeframe: str,
    opened_at: datetime,
    duration: timedelta,
    *,
    close: int,
) -> CausalBarView:
    closed_at = opened_at + duration
    return CausalBarView(
        timeframe=timeframe,
        bar_open_at=opened_at,
        bar_close_at=closed_at,
        market_as_of=closed_at,
        open=Decimal(close - 1),
        high=Decimal(close + 1),
        low=Decimal(close - 2),
        close=Decimal(close),
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )


def model(
    name: str,
    requirements: tuple[FeatureRequirement, ...],
    *,
    decision_timeframe: str = "1h",
    trigger_timeframe: str = "1h",
) -> ModelSpec:
    return ModelSpec(
        name=name,
        version="1",
        stateful=False,
        output_kind="analytical",
        produces_artifact_type=f"{name}.v1",
        intrinsic_feature_requirements=requirements,
    )


def lane_spec(
    bindings: tuple[tuple[str, str], ...],
    *,
    decision_timeframe: str = "1h",
    trigger_timeframe: str = "1h",
) -> DecisionLaneSpec:
    return DecisionLaneSpec(
        lane_id=f"BTCUSDT:{decision_timeframe}",
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        decision_timeframe=decision_timeframe,
        trigger_timeframe=trigger_timeframe,
        trigger_mode="on_bar_close",
        policy_name="default",
        policy_version="1",
        risk_profile_key="btc-default",
        bindings=tuple(
            ModelBindingSpec(
                slot_name=slot,
                plugin_name=plugin,
                plugin_version="1",
            )
            for slot, plugin in bindings
        ),
    )


def compiled(
    specs: list[ModelSpec],
    lane: DecisionLaneSpec,
):
    return compile_decision_plan(PluginCatalog(specs), [lane]).lanes[0]


def make_environment(
    specs: list[ModelSpec],
    lane_definition: DecisionLaneSpec,
    definitions: list[SharedFeatureDefinition],
    policy: FeaturePolicy,
    *,
    market_as_of: datetime,
    append_1h_indices: tuple[int, ...] = (0, 1, 2, 3),
    append_prior_4h: bool = False,
):
    plugin_catalog = PluginCatalog(specs)
    decision_plan = compile_decision_plan(plugin_catalog, [lane_definition])
    lane = decision_plan.lanes[0]
    feature_catalog = FeatureCatalog(definitions)
    feature_plan = compile_feature_plan(lane, feature_catalog, policy, GRID)
    base = compile_bar_store_capacities(decision_plan, GRID)
    feature = compile_feature_bar_store_capacities(
        decision_plan,
        [feature_plan],
        feature_catalog,
        GRID,
    )
    store = BarStore(merge_bar_store_capacities(base, feature))
    one_hour_key = next(key for key in store.series_keys if key.timeframe == "1h")
    for index in append_1h_indices:
        opened_at = BASE + timedelta(hours=index)
        store.append(
            one_hour_key,
            make_bar("1h", opened_at, timedelta(hours=1), close=100 + index),
        )
    if append_prior_4h:
        four_hour_key = next(key for key in store.series_keys if key.timeframe == "4h")
        store.append(
            four_hour_key,
            make_bar(
                "4h",
                BASE - timedelta(hours=4),
                timedelta(hours=4),
                close=90,
            ),
        )
    requirements = compile_lane_market_requirements(lane, GRID)
    view = DecisionViewBuilder(store, GRID).build(lane, requirements, market_as_of)
    return lane, feature_plan, feature_catalog, store, view


def test_shared_feature_is_computed_once_and_binding_visibility_is_isolated() -> None:
    calls: list[str] = []

    def volatility(context):
        calls.append("volatility")
        return {"last": context.histories["1h"][-1].close}

    definitions = [
        SharedFeatureDefinition(
            name="VOLATILITY",
            version="1",
            calculator=volatility,
            history_requirements=(
                FeatureHistoryRequirement(source="decision", bars=3),
            ),
        ),
        SharedFeatureDefinition(
            name="MOMENTUM", version="1", calculator=lambda context: 2
        ),
    ]
    specs = [
        model("A", (FeatureRequirement(name="VOLATILITY"),)),
        model(
            "B",
            (
                FeatureRequirement(name="VOLATILITY"),
                FeatureRequirement(name="MOMENTUM"),
            ),
        ),
    ]
    lane, plan, catalog, store, view = make_environment(
        specs,
        lane_spec((("a", "A"), ("b", "B"))),
        definitions,
        FeaturePolicy(
            name="operator",
            version="1",
            allowed_features=("MOMENTUM", "VOLATILITY"),
        ),
        market_as_of=BASE + timedelta(hours=4),
    )
    resolution = FeatureEngine(catalog, store, GRID).compute(plan, lane, view)
    assert calls == ["volatility"]
    assert set(
        resolution.bindings[
            next(key for key in resolution.bindings if ":a:" in key)
        ].features
    ) == {"VOLATILITY"}
    first = resolution.bindings[
        next(key for key in resolution.bindings if ":a:" in key)
    ].features["VOLATILITY"]
    second = resolution.bindings[
        next(key for key in resolution.bindings if ":b:" in key)
    ].features["VOLATILITY"]
    assert first is second
    assert set(
        resolution.bindings[
            next(key for key in resolution.bindings if ":b:" in key)
        ].features
    ) == {
        "MOMENTUM",
        "VOLATILITY",
    }
    assert first.market_as_of == view.market_as_of
    assert len(catalog) == 2


def test_feature_calculator_receives_exact_bounded_history_and_is_immutable() -> None:
    observed: list[tuple[int, bool]] = []

    def calculator(context):
        observed.append((len(context.histories["1h"]), context.decision_bar_closed))
        return {"values": [bar.close for bar in context.histories["1h"]]}

    feature = SharedFeatureDefinition(
        name="VOLATILITY",
        version="1",
        calculator=calculator,
        history_requirements=(FeatureHistoryRequirement(source="decision", bars=3),),
    )
    lane, plan, catalog, store, view = make_environment(
        [model("A", (FeatureRequirement(name="VOLATILITY"),))],
        lane_spec((("a", "A"),)),
        [feature],
        FeaturePolicy(name="operator", version="1", allowed_features=("VOLATILITY",)),
        market_as_of=BASE + timedelta(hours=4),
        append_1h_indices=(0, 1, 2, 3),
    )
    resolution = FeatureEngine(catalog, store, GRID).compute(plan, lane, view)
    assert observed == [(3, True)]
    snapshot = resolution.shared_features["VOLATILITY"]
    with pytest.raises((TypeError, AttributeError)):
        snapshot.value["values"].append(Decimal(9))  # type: ignore[index]


def test_missing_required_feature_makes_only_affected_binding_unavailable() -> None:
    feature_one = SharedFeatureDefinition(
        name="F1", version="1", calculator=lambda context: 1
    )
    feature_two = SharedFeatureDefinition(
        name="F2",
        version="1",
        calculator=lambda context: 2,
        history_requirements=(FeatureHistoryRequirement(source="decision", bars=3),),
    )
    specs = [
        model("A", (FeatureRequirement(name="F1"),)),
        model("B", (FeatureRequirement(name="F1"), FeatureRequirement(name="F2"))),
    ]
    lane, plan, catalog, store, view = make_environment(
        specs,
        lane_spec((("a", "A"), ("b", "B"))),
        [feature_one, feature_two],
        FeaturePolicy(name="operator", version="1", allowed_features=("F1", "F2")),
        market_as_of=BASE + timedelta(hours=4),
        append_1h_indices=(2, 3, 4),
    )
    resolution = FeatureEngine(catalog, store, GRID).compute(plan, lane, view)
    a = resolution.bindings[next(key for key in resolution.bindings if ":a:" in key)]
    b = resolution.bindings[next(key for key in resolution.bindings if ":b:" in key)]
    assert a.available is True
    assert b.available is False
    assert "F2" not in resolution.shared_features
    assert b.missing_required_features == ("F2",)


def test_optional_missing_feature_does_not_unavailable_binding() -> None:
    feature = SharedFeatureDefinition(
        name="OPTIONAL",
        version="1",
        calculator=lambda context: 1,
        history_requirements=(FeatureHistoryRequirement(source="decision", bars=3),),
    )
    lane, plan, catalog, store, view = make_environment(
        [model("A", (FeatureRequirement(name="OPTIONAL", required=False),))],
        lane_spec((("a", "A"),)),
        [feature],
        FeaturePolicy(name="operator", version="1", allowed_features=("OPTIONAL",)),
        market_as_of=BASE + timedelta(hours=4),
        append_1h_indices=(2, 3, 4),
    )
    resolution = FeatureEngine(catalog, store, GRID).compute(plan, lane, view)
    binding = next(iter(resolution.bindings.values()))
    assert binding.available is True
    assert binding.missing_optional_features == ("OPTIONAL",)


def test_projected_view_is_passed_without_future_canonical_htf() -> None:
    observed: list[tuple[bool, datetime]] = []
    feature = SharedFeatureDefinition(
        name="PROJECTED",
        version="1",
        calculator=lambda context: (
            observed.append(
                (context.decision_bar_closed, context.histories["1h"][-1].market_as_of)
            )
            or 1
        ),
        history_requirements=(FeatureHistoryRequirement(source="trigger", bars=2),),
    )
    lane_definition = lane_spec(
        (("a", "A"),),
        decision_timeframe="4h",
        trigger_timeframe="1h",
    )
    lane, plan, catalog, store, view = make_environment(
        [model("A", (FeatureRequirement(name="PROJECTED"),))],
        lane_definition,
        [feature],
        FeaturePolicy(name="operator", version="1", allowed_features=("PROJECTED",)),
        market_as_of=BASE + timedelta(hours=2),
        append_1h_indices=(0, 1),
        append_prior_4h=True,
    )
    FeatureEngine(catalog, store, GRID).compute(plan, lane, view)
    assert observed == [(False, BASE + timedelta(hours=2))]
    assert view.decision_bar.bar_close_at == BASE + timedelta(hours=4)
    assert view.decision_bar.market_as_of == BASE + timedelta(hours=2)


def test_malformed_geometry_is_not_downgraded_to_feature_unavailable() -> None:
    feature = SharedFeatureDefinition(
        name="BAD",
        version="1",
        calculator=lambda context: 1,
        history_requirements=(FeatureHistoryRequirement(source="decision", bars=1),),
    )
    lane_definition = lane_spec((("a", "A"),))
    lane, plan, catalog, store, _ = make_environment(
        [model("A", (FeatureRequirement(name="BAD"),))],
        lane_definition,
        [
            SharedFeatureDefinition(
                name="BAD",
                version="1",
                calculator=feature.calculator,
                history_requirements=(
                    FeatureHistoryRequirement(source="fixed", timeframe="4h", bars=1),
                ),
            )
        ],
        FeaturePolicy(name="operator", version="1", allowed_features=("BAD",)),
        market_as_of=BASE + timedelta(hours=1),
        append_1h_indices=(0,),
    )
    key = next(key for key in store.series_keys if key.timeframe == "4h")
    store.append(
        key,
        CausalBarView(
            timeframe="4h",
            bar_open_at=BASE - timedelta(hours=3),
            bar_close_at=BASE,
            market_as_of=BASE,
            open=Decimal(1),
            high=Decimal(2),
            low=Decimal(0),
            close=Decimal(1),
            volume=Decimal(1),
            taker_buy_base=Decimal(1),
            closed=True,
        ),
    )
    with pytest.raises(TimeframeGeometryError):
        # The malformed bar is rejected before the calculator can be called.
        view = DecisionViewBuilder(store, GRID).build(
            lane,
            compile_lane_market_requirements(lane, GRID),
            BASE + timedelta(hours=1),
        )
        FeatureEngine(catalog, store, GRID).compute(plan, lane, view)


def test_invalid_calculator_output_is_identified() -> None:
    class Mutable:
        pass

    feature = SharedFeatureDefinition(
        name="BAD_OUTPUT",
        version="2",
        calculator=lambda context: Mutable(),
    )
    lane, plan, catalog, store, view = make_environment(
        [model("A", (FeatureRequirement(name="BAD_OUTPUT"),))],
        lane_spec((("a", "A"),)),
        [feature],
        FeaturePolicy(name="operator", version="1", allowed_features=("BAD_OUTPUT",)),
        market_as_of=BASE + timedelta(hours=4),
    )
    with pytest.raises(FeatureComputationError, match="BAD_OUTPUT@2"):
        FeatureEngine(catalog, store, GRID).compute(plan, lane, view)


def test_feature_engine_rejects_tampered_required_demand_before_computation() -> None:
    calls: list[str] = []
    feature = SharedFeatureDefinition(
        name="REQUIRED",
        version="1",
        calculator=lambda context: calls.append("computed") or 1,
        history_requirements=(FeatureHistoryRequirement(source="decision", bars=5),),
    )
    lane, _plan, catalog, store, view = make_environment(
        [model("A", (FeatureRequirement(name="REQUIRED"),))],
        lane_spec((("a", "A"),)),
        [feature],
        FeaturePolicy(name="operator", version="1", allowed_features=("REQUIRED",)),
        market_as_of=BASE + timedelta(hours=4),
    )
    tampered_lane = compiled(
        [model("A", (FeatureRequirement(name="REQUIRED", required=False),))],
        lane_spec((("a", "A"),)),
    )
    tampered_plan = compile_feature_plan(
        tampered_lane,
        catalog,
        FeaturePolicy(name="operator", version="1", allowed_features=("REQUIRED",)),
        GRID,
    )

    with pytest.raises(FeaturePlanError, match="demand mismatch"):
        FeatureEngine(catalog, store, GRID).compute(tampered_plan, lane, view)
    assert calls == []


def test_feature_engine_rejects_tampered_optional_demand_before_computation() -> None:
    feature = SharedFeatureDefinition(
        name="OPTIONAL", version="1", calculator=lambda context: 1
    )
    lane, _plan, catalog, store, view = make_environment(
        [model("A", (FeatureRequirement(name="OPTIONAL", required=False),))],
        lane_spec((("a", "A"),)),
        [feature],
        FeaturePolicy(name="operator", version="1", allowed_features=("OPTIONAL",)),
        market_as_of=BASE + timedelta(hours=4),
    )
    tampered_lane = compiled(
        [model("A", (FeatureRequirement(name="OPTIONAL"),))],
        lane_spec((("a", "A"),)),
    )
    tampered_plan = compile_feature_plan(
        tampered_lane,
        catalog,
        FeaturePolicy(name="operator", version="1", allowed_features=("OPTIONAL",)),
        GRID,
    )

    with pytest.raises(FeaturePlanError, match="demand mismatch"):
        FeatureEngine(catalog, store, GRID).compute(tampered_plan, lane, view)


def test_feature_plan_rejects_added_or_omitted_binding_demand() -> None:
    feature = SharedFeatureDefinition(
        name="DECLARED", version="1", calculator=lambda context: 1
    )
    lane, plan, _, _, _ = make_environment(
        [model("A", (FeatureRequirement(name="DECLARED"),))],
        lane_spec((("a", "A"),)),
        [feature],
        FeaturePolicy(name="operator", version="1", allowed_features=("DECLARED",)),
        market_as_of=BASE + timedelta(hours=4),
    )
    del lane
    binding_id, binding_plan = next(iter(plan.bindings.items()))

    with pytest.raises(ValueError):
        replace(
            plan,
            bindings={
                binding_id: replace(
                    binding_plan,
                    required_features=(),
                    enabled_features=(),
                    statically_available=True,
                )
            },
        )

    with pytest.raises(ValueError):
        replace(
            plan,
            bindings={
                binding_id: replace(
                    binding_plan,
                    required_features=("DECLARED", "EXTRA"),
                    enabled_features=("DECLARED", "EXTRA"),
                )
            },
        )


def _snapshot(
    *,
    name: str = "F",
    version: str = "1",
    market_as_of: datetime = BASE + timedelta(hours=1),
    value: object = 1,
) -> FeatureSnapshot:
    return FeatureSnapshot(
        name=name,
        version=version,
        market_as_of=market_as_of,
        value=value,
        provenance={"source": "test"},
    )


def test_feature_resolution_rejects_shared_snapshot_mismatch() -> None:
    shared = _snapshot()
    binding = BindingFeatureResolution(
        binding_id="binding-a",
        available=True,
        features={"F": _snapshot(version="2", value=999)},
    )

    with pytest.raises(ValueError, match="reuse the shared snapshot"):
        FeatureResolution(
            lane_id="BTCUSDT:1h",
            base_lane_revision="lane-1",
            feature_plan_fingerprint="plan-1",
            market_as_of=shared.market_as_of,
            shared_features={"F": shared},
            bindings={"binding-a": binding},
        )


def test_feature_resolution_rejects_present_unavailable_and_missing_contradictions() -> (
    None
):
    shared = _snapshot()
    with pytest.raises(ValueError, match="both shared and unavailable"):
        FeatureResolution(
            lane_id="BTCUSDT:1h",
            base_lane_revision="lane-1",
            feature_plan_fingerprint="plan-1",
            market_as_of=shared.market_as_of,
            shared_features={"F": shared},
            unavailable_features={"F": "not_ready"},
        )

    with pytest.raises(ValueError, match="present features cannot also be missing"):
        BindingFeatureResolution(
            binding_id="binding-a",
            available=False,
            features={"F": shared},
            missing_required_features=("F",),
        )

    with pytest.raises(ValueError, match="present features cannot also be missing"):
        BindingFeatureResolution(
            binding_id="binding-a",
            available=True,
            features={"F": shared},
            missing_optional_features=("F",),
        )


def test_feature_resolution_accepts_equal_shared_snapshot_for_multiple_bindings() -> (
    None
):
    shared = _snapshot()
    equivalent = _snapshot()
    resolution = FeatureResolution(
        lane_id="BTCUSDT:1h",
        base_lane_revision="lane-1",
        feature_plan_fingerprint="plan-1",
        market_as_of=shared.market_as_of,
        shared_features={"F": shared},
        bindings={
            "binding-a": BindingFeatureResolution(
                binding_id="binding-a",
                available=True,
                features={"F": equivalent},
            ),
            "binding-b": BindingFeatureResolution(
                binding_id="binding-b",
                available=True,
                features={"F": shared},
            ),
        },
    )

    assert set(resolution.bindings) == {"binding-a", "binding-b"}


def test_feature_resolution_missing_features_require_unavailable_evidence() -> None:
    with pytest.raises(ValueError, match="represented as unavailable"):
        FeatureResolution(
            lane_id="BTCUSDT:1h",
            base_lane_revision="lane-1",
            feature_plan_fingerprint="plan-1",
            market_as_of=BASE + timedelta(hours=1),
            bindings={
                "binding-a": BindingFeatureResolution(
                    binding_id="binding-a",
                    available=False,
                    missing_required_features=("F",),
                )
            },
        )
