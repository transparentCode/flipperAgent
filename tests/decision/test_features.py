from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.decision_app.domain.market_state import (
    MarketSeriesKey,
    TimeframeGrid,
    compile_bar_store_capacities,
)
from apps.decision_app.features.planning import (
    FeatureCatalog,
    FeatureCatalogError,
    FeatureHistoryRequirement,
    FeaturePlanError,
    FeaturePolicy,
    SharedFeatureDefinition,
    compile_feature_bar_store_capacities,
    compile_feature_plan,
    merge_bar_store_capacities,
    resolve_feature_config_fingerprint,
    resolve_feature_history_requirements,
    validate_feature_plan_against_lane,
)
from apps.decision_app.planning.planner import (
    DecisionLaneSpec,
    ModelBindingSpec,
    compile_decision_plan,
)
from libs.contracts.decision import FeatureRequirement, ModelSpec

BASE = datetime(2026, 1, 1, tzinfo=UTC)
GRID = TimeframeGrid(
    alignment_origin=BASE,
    durations={
        "1m": timedelta(minutes=1),
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "1d": timedelta(days=1),
    },
)


def definition(
    name: str,
    *,
    version: str = "1",
    history: tuple[FeatureHistoryRequirement, ...] = (),
) -> SharedFeatureDefinition:
    return SharedFeatureDefinition(
        name=name,
        version=version,
        history_requirements=history,
        calculator=lambda context: context.market_as_of,
    )


def spec(
    name: str,
    *,
    requirements: tuple[FeatureRequirement, ...] = (),
    warmup: dict[str, int] | None = None,
) -> ModelSpec:
    from libs.contracts.decision import WarmupRequirements

    return ModelSpec(
        name=name,
        version="1",
        stateful=False,
        output_kind="analytical",
        produces_artifact_type=f"{name}.v1",
        intrinsic_feature_requirements=requirements,
        warmup_requirements=WarmupRequirements(bars_by_timeframe=warmup or {"1h": 1}),
    )


def lane(*bindings: ModelBindingSpec, lane_id: str = "BTCUSDT:1h") -> DecisionLaneSpec:
    return DecisionLaneSpec(
        lane_id=lane_id,
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        decision_timeframe="1h",
        trigger_timeframe="1h",
        trigger_mode="on_bar_close",
        policy_name="default",
        policy_version="1",
        risk_profile_key="btc-default",
        bindings=bindings,
    )


def binding(slot: str, plugin: str) -> ModelBindingSpec:
    return ModelBindingSpec(
        slot_name=slot,
        plugin_name=plugin,
        plugin_version="1",
    )


def compile_lane(
    model_specs: list[ModelSpec],
    lane_spec: DecisionLaneSpec,
):
    from apps.decision_app.planning.catalog import PluginCatalog

    return compile_decision_plan(PluginCatalog(model_specs), [lane_spec]).lanes[0]


def test_feature_requirement_is_typed_and_strict() -> None:
    assert FeatureRequirement(name="VOLATILITY", required=False).required is False
    with pytest.raises(TypeError):
        FeatureRequirement(name="VOLATILITY", required=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique"):
        ModelSpec(
            name="DuplicateFeatures",
            version="1",
            stateful=False,
            output_kind="analytical",
            produces_artifact_type="x.v1",
            intrinsic_feature_requirements=(
                FeatureRequirement(name="VOLATILITY"),
                FeatureRequirement(name="VOLATILITY", required=False),
            ),
        )


def test_catalog_and_policy_are_explicit_and_deterministic() -> None:
    catalog = FeatureCatalog([definition("MOMENTUM"), definition("VOLATILITY")])
    assert [item.name for item in catalog] == ["MOMENTUM", "VOLATILITY"]
    assert catalog.resolve("VOLATILITY").version == "1"
    with pytest.raises(FeatureCatalogError, match="unknown"):
        catalog.resolve("ATR")
    with pytest.raises(FeatureCatalogError, match="duplicate"):
        FeatureCatalog([definition("ATR"), definition("ATR")])
    policy = FeaturePolicy(
        name="operator",
        version="1",
        allowed_features=("VOLATILITY", "MOMENTUM"),
    )
    assert policy.allowed_features == ("MOMENTUM", "VOLATILITY")
    with pytest.raises(ValueError, match="duplicates"):
        FeaturePolicy(name="operator", version="1", allowed_features=("ATR", "ATR"))


def test_feature_plan_preserves_binding_availability_and_fingerprint() -> None:
    model_specs = [
        spec(
            "Boundary",
            requirements=(
                FeatureRequirement(name="VOLATILITY"),
                FeatureRequirement(name="MOMENTUM", required=False),
            ),
        ),
        spec(
            "Breakout",
            requirements=(FeatureRequirement(name="ATR"),),
        ),
    ]
    lane_spec = lane(binding("boundary", "Boundary"), binding("breakout", "Breakout"))
    lane_plan = compile_lane(model_specs, lane_spec)
    catalog = FeatureCatalog([definition("VOLATILITY"), definition("MOMENTUM")])
    plan = compile_feature_plan(
        lane_plan,
        catalog,
        FeaturePolicy(name="operator", version="1", allowed_features=("VOLATILITY",)),
        GRID,
    )
    boundary = plan.bindings[next(key for key in plan.bindings if ":boundary:" in key)]
    breakout = plan.bindings[next(key for key in plan.bindings if ":breakout:" in key)]
    assert plan.effective_shared_features == ("VOLATILITY",)
    assert boundary.statically_available is True
    assert boundary.enabled_features == ("VOLATILITY",)
    assert boundary.disabled_optional_features == ("MOMENTUM",)
    assert breakout.statically_available is False
    assert breakout.undefined_required_features == ("ATR",)
    assert plan.disabled_features == ("MOMENTUM",)
    assert plan.undefined_features == ("ATR",)
    assert "ATR" not in plan.disabled_features
    assert plan.feature_plan_fingerprint


def test_undefined_non_allowed_feature_is_classified_only_as_undefined() -> None:
    model_specs = [
        spec("A", requirements=(FeatureRequirement(name="UNDEFINED"),)),
    ]
    lane_plan = compile_lane(model_specs, lane(binding("a", "A")))

    plan = compile_feature_plan(
        lane_plan,
        FeatureCatalog([]),
        FeaturePolicy(name="operator", version="1"),
        GRID,
    )

    assert plan.effective_shared_features == ()
    assert plan.disabled_features == ()
    assert plan.undefined_features == ("UNDEFINED",)
    binding_plan = next(iter(plan.bindings.values()))
    assert binding_plan.disabled_required_features == ()
    assert binding_plan.undefined_required_features == ("UNDEFINED",)


def test_feature_plan_is_order_independent_and_ignores_unrequested_catalog_entries() -> (
    None
):
    models = [
        spec("A", requirements=(FeatureRequirement(name="VOLATILITY"),)),
        spec("B", requirements=(FeatureRequirement(name="VOLATILITY"),)),
    ]
    first_lane = compile_lane(models, lane(binding("a", "A"), binding("b", "B")))
    second_lane = compile_lane(
        list(reversed(models)), lane(binding("b", "B"), binding("a", "A"))
    )
    policy = FeaturePolicy(
        name="operator", version="1", allowed_features=("VOLATILITY",)
    )
    first = compile_feature_plan(
        first_lane,
        FeatureCatalog([definition("VOLATILITY")]),
        policy,
        GRID,
    )
    second = compile_feature_plan(
        second_lane,
        FeatureCatalog([definition("UNUSED"), definition("VOLATILITY")]),
        policy,
        GRID,
    )
    assert first.feature_plan_fingerprint == second.feature_plan_fingerprint
    assert first.effective_shared_features == second.effective_shared_features


def test_feature_history_resolution_merges_same_series_by_maximum() -> None:
    lane_plan = compile_lane(
        [
            spec("A"),
        ],
        lane(binding("a", "A")),
    )
    resolved = resolve_feature_history_requirements(
        SharedFeatureDefinition(
            name="VOLATILITY",
            version="1",
            history_requirements=(
                FeatureHistoryRequirement(source="decision", bars=3),
                FeatureHistoryRequirement(source="fixed", timeframe="1h", bars=7),
                FeatureHistoryRequirement(source="trigger", bars=2),
            ),
            calculator=lambda context: 1,
        ),
        lane_plan,
        GRID,
    )
    assert dict(resolved) == {
        MarketSeriesKey(
            asset="BTCUSDT",
            venue="binance",
            instrument_id="BTC-USDT-PERP",
            timeframe="1h",
        ): 7
    }


def test_dynamic_history_resolver_is_lane_resolved_and_rejects_ambiguity() -> None:
    with pytest.raises(ValueError, match="cannot be combined"):
        SharedFeatureDefinition(
            name="DYNAMIC",
            version="1",
            calculator=lambda context: 1,
            history_requirements=(
                FeatureHistoryRequirement(source="decision", bars=2),
            ),
            history_requirement_resolver=lambda lane: (
                FeatureHistoryRequirement(source="decision", bars=3),
            ),
        )

    feature = SharedFeatureDefinition(
        name="DYNAMIC",
        version="1",
        calculator=lambda context: 1,
        history_requirement_resolver=lambda resolved_lane: (
            FeatureHistoryRequirement(
                source="decision",
                bars=2 if resolved_lane.lane_id.endswith(":one") else 3,
            ),
        ),
    )
    one_lane = compile_lane(
        [spec("A", requirements=(FeatureRequirement(name="DYNAMIC"),))],
        lane(binding("a", "A"), lane_id="BTCUSDT:one"),
    )
    two_lane = compile_lane(
        [spec("A", requirements=(FeatureRequirement(name="DYNAMIC"),))],
        lane(binding("a", "A"), lane_id="BTCUSDT:two"),
    )
    catalog = FeatureCatalog([feature])
    policy = FeaturePolicy(name="operator", version="1", allowed_features=("DYNAMIC",))
    one = compile_feature_plan(one_lane, catalog, policy, GRID)
    two = compile_feature_plan(two_lane, catalog, policy, GRID)
    assert next(iter(one.history_requirements["DYNAMIC"].values())) == 2
    assert next(iter(two.history_requirements["DYNAMIC"].values())) == 3
    assert one.feature_plan_fingerprint != two.feature_plan_fingerprint


def test_dynamic_history_resolver_rejects_malformed_output() -> None:
    lane_plan = compile_lane(
        [spec("A", requirements=(FeatureRequirement(name="DYNAMIC"),))],
        lane(binding("a", "A")),
    )
    feature = SharedFeatureDefinition(
        name="DYNAMIC",
        version="1",
        calculator=lambda context: 1,
        history_requirement_resolver=lambda resolved_lane: ("not-a-requirement",),  # type: ignore[return-value]
    )
    with pytest.raises(TypeError, match="FeatureHistoryRequirement"):
        resolve_feature_history_requirements(feature, lane_plan, GRID)


def test_feature_config_fingerprint_is_planned_and_validated() -> None:
    lane_plan = compile_lane(
        [spec("A", requirements=(FeatureRequirement(name="F"),))],
        lane(binding("a", "A")),
    )
    policy = FeaturePolicy(name="operator", version="1", allowed_features=("F",))
    history = (FeatureHistoryRequirement(source="decision", bars=2),)

    def make_feature(value: str) -> SharedFeatureDefinition:
        return SharedFeatureDefinition(
            name="F",
            version="1",
            calculator=lambda context: 1,
            history_requirements=history,
            config_fingerprint_resolver=lambda resolved_lane: value,
        )

    first_catalog = FeatureCatalog([make_feature("config-one")])
    second_catalog = FeatureCatalog([make_feature("config-two")])
    first = compile_feature_plan(lane_plan, first_catalog, policy, GRID)
    second = compile_feature_plan(lane_plan, second_catalog, policy, GRID)
    assert first.feature_config_fingerprints == {"F": "config-one"}
    assert resolve_feature_config_fingerprint(
        first_catalog.resolve("F"), lane_plan
    ) == ("config-one")
    assert first.feature_plan_fingerprint != second.feature_plan_fingerprint
    with pytest.raises(FeaturePlanError, match="configuration fingerprint"):
        validate_feature_plan_against_lane(first, lane_plan, second_catalog, GRID)

    static = compile_feature_plan(
        lane_plan,
        FeatureCatalog([definition("F", history=history)]),
        policy,
        GRID,
    )
    assert static.feature_config_fingerprints == {}


@pytest.mark.parametrize(
    "resolver_value",
    ("", 123, None),
    ids=("empty", "non_string", "none"),
)
def test_feature_config_fingerprint_resolver_rejects_invalid_output(
    resolver_value: object,
) -> None:
    lane_plan = compile_lane(
        [spec("A", requirements=(FeatureRequirement(name="F"),))],
        lane(binding("a", "A")),
    )
    feature = SharedFeatureDefinition(
        name="F",
        version="1",
        calculator=lambda context: 1,
        config_fingerprint_resolver=lambda resolved_lane: resolver_value,  # type: ignore[return-value]
    )

    with pytest.raises((TypeError, ValueError), match="feature config fingerprint"):
        resolve_feature_config_fingerprint(feature, lane_plan)


def test_feature_capacity_merges_with_base_by_maximum() -> None:
    model = spec("A", requirements=(FeatureRequirement(name="VOLATILITY"),))
    lane_plan = compile_lane([model], lane(binding("a", "A")))
    decision_plan = compile_decision_plan(
        __import__(
            "apps.decision_app.planning.catalog", fromlist=["PluginCatalog"]
        ).PluginCatalog([model]),
        [lane(binding("a", "A"))],
    )
    feature = definition(
        "VOLATILITY",
        history=(FeatureHistoryRequirement(source="decision", bars=20),),
    )
    feature_plan = compile_feature_plan(
        lane_plan,
        FeatureCatalog([feature]),
        FeaturePolicy(name="operator", version="1", allowed_features=("VOLATILITY",)),
        GRID,
    )
    feature_caps = compile_feature_bar_store_capacities(
        decision_plan,
        [feature_plan],
        FeatureCatalog([feature]),
        GRID,
    )
    base_caps = compile_bar_store_capacities(decision_plan, GRID)
    merged = merge_bar_store_capacities(base_caps, feature_caps)
    key = MarketSeriesKey(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        timeframe="1h",
    )
    assert base_caps[key] == 1
    assert feature_caps[key] == 20
    assert merged[key] == 20


def test_feature_capacity_requires_complete_current_lane_plans() -> None:
    model = spec("A", requirements=(FeatureRequirement(name="VOLATILITY"),))
    decision_plan = compile_decision_plan(
        __import__(
            "apps.decision_app.planning.catalog", fromlist=["PluginCatalog"]
        ).PluginCatalog([model]),
        [lane(binding("a", "A"))],
    )
    feature_catalog = FeatureCatalog([definition("VOLATILITY")])
    policy = FeaturePolicy(
        name="operator", version="1", allowed_features=("VOLATILITY",)
    )
    feature_plan = compile_feature_plan(
        decision_plan.lanes[0], feature_catalog, policy, GRID
    )

    with pytest.raises(FeaturePlanError, match="exactly one current plan"):
        compile_feature_bar_store_capacities(decision_plan, [], feature_catalog, GRID)

    stale_lane = compile_lane(
        [model],
        replace(lane(binding("a", "A")), policy_version="2"),
    )
    stale = compile_feature_plan(stale_lane, feature_catalog, policy, GRID)
    with pytest.raises(FeaturePlanError, match="base lane revision"):
        compile_feature_bar_store_capacities(
            decision_plan, [stale], feature_catalog, GRID
        )

    extra_lane = compile_decision_plan(
        __import__(
            "apps.decision_app.planning.catalog", fromlist=["PluginCatalog"]
        ).PluginCatalog([model]),
        [lane(binding("a", "A"), lane_id="ETHUSDT:1h")],
    ).lanes[0]
    extra_plan = compile_feature_plan(extra_lane, feature_catalog, policy, GRID)
    with pytest.raises(FeaturePlanError, match="exactly one current plan"):
        compile_feature_bar_store_capacities(
            decision_plan,
            [feature_plan, extra_plan],
            feature_catalog,
            GRID,
        )


def test_feature_capacity_rejects_stale_binding_demand() -> None:
    model = spec("A", requirements=(FeatureRequirement(name="VOLATILITY"),))
    decision_plan = compile_decision_plan(
        __import__(
            "apps.decision_app.planning.catalog", fromlist=["PluginCatalog"]
        ).PluginCatalog([model]),
        [lane(binding("a", "A"))],
    )
    feature_catalog = FeatureCatalog([definition("VOLATILITY")])
    optional_model = spec(
        "A",
        requirements=(FeatureRequirement(name="VOLATILITY", required=False),),
    )
    optional_lane = compile_lane(
        [optional_model],
        lane(binding("a", "A")),
    )
    tampered_plan = compile_feature_plan(
        optional_lane,
        feature_catalog,
        FeaturePolicy(name="operator", version="1", allowed_features=("VOLATILITY",)),
        GRID,
    )

    with pytest.raises(FeaturePlanError, match="demand mismatch"):
        compile_feature_bar_store_capacities(
            decision_plan, [tampered_plan], feature_catalog, GRID
        )


def test_unknown_allowed_feature_fails_closed() -> None:
    lane_plan = compile_lane(
        [spec("A", requirements=(FeatureRequirement(name="ATR"),))],
        lane(binding("a", "A")),
    )
    with pytest.raises(FeaturePlanError, match="unknown feature"):
        compile_feature_plan(
            lane_plan,
            FeatureCatalog([]),
            FeaturePolicy(name="operator", version="1", allowed_features=("ATR",)),
            GRID,
        )


def test_feature_fingerprint_tracks_material_demand_and_policy_changes() -> None:
    required_lane = compile_lane(
        [spec("A", requirements=(FeatureRequirement(name="F"),))],
        lane(binding("a", "A")),
    )
    optional_lane = compile_lane(
        [spec("A", requirements=(FeatureRequirement(name="F", required=False),))],
        lane(binding("a", "A")),
    )
    base_policy = FeaturePolicy(name="operator", version="1", allowed_features=("F",))
    base_catalog = FeatureCatalog(
        [
            definition(
                "F",
                version="1",
                history=(FeatureHistoryRequirement(source="decision", bars=2),),
            )
        ]
    )
    base = compile_feature_plan(required_lane, base_catalog, base_policy, GRID)

    assert (
        compile_feature_plan(
            required_lane,
            FeatureCatalog(
                [
                    definition(
                        "F",
                        version="2",
                        history=(FeatureHistoryRequirement(source="decision", bars=2),),
                    )
                ]
            ),
            base_policy,
            GRID,
        ).feature_plan_fingerprint
        != base.feature_plan_fingerprint
    )
    assert (
        compile_feature_plan(
            required_lane,
            FeatureCatalog(
                [
                    definition(
                        "F",
                        history=(FeatureHistoryRequirement(source="decision", bars=3),),
                    )
                ]
            ),
            base_policy,
            GRID,
        ).feature_plan_fingerprint
        != base.feature_plan_fingerprint
    )
    assert (
        compile_feature_plan(
            required_lane,
            base_catalog,
            FeaturePolicy(name="operator", version="2", allowed_features=("F",)),
            GRID,
        ).feature_plan_fingerprint
        != base.feature_plan_fingerprint
    )
    assert (
        compile_feature_plan(
            required_lane,
            FeatureCatalog([definition("F"), definition("UNUSED")]),
            FeaturePolicy(
                name="operator",
                version="1",
                allowed_features=("F", "UNUSED"),
            ),
            GRID,
        ).feature_plan_fingerprint
        != base.feature_plan_fingerprint
    )
    assert (
        compile_feature_plan(
            optional_lane, base_catalog, base_policy, GRID
        ).feature_plan_fingerprint
        != base.feature_plan_fingerprint
    )
    assert (
        compile_feature_plan(
            required_lane,
            FeatureCatalog(
                [
                    SharedFeatureDefinition(
                        name="F",
                        version="1",
                        history_requirements=(
                            FeatureHistoryRequirement(source="decision", bars=2),
                        ),
                        calculator=lambda context: 999,
                    )
                ]
            ),
            base_policy,
            GRID,
        ).feature_plan_fingerprint
        == base.feature_plan_fingerprint
    )


def test_feature_plan_rejects_stale_fingerprint_after_material_drift() -> None:
    lane_plan = compile_lane(
        [
            spec(
                "A",
                requirements=(FeatureRequirement(name="F"),),
            )
        ],
        lane(binding("a", "A")),
    )
    plan = compile_feature_plan(
        lane_plan,
        FeatureCatalog(
            [
                definition(
                    "F",
                    history=(FeatureHistoryRequirement(source="decision", bars=1),),
                )
            ]
        ),
        FeaturePolicy(name="operator", version="1", allowed_features=("F",)),
        GRID,
    )

    with pytest.raises(ValueError, match="feature_plan_fingerprint"):
        replace(plan, feature_policy_name="other")
    with pytest.raises(ValueError, match="feature_plan_fingerprint"):
        replace(plan, feature_policy_version="2")
    with pytest.raises(ValueError, match="feature_plan_fingerprint"):
        replace(plan, operator_allowed_features=("F", "UNUSED"))
    with pytest.raises(ValueError, match="feature_plan_fingerprint"):
        replace(plan, feature_versions={"F": "2"})

    history_key = next(iter(plan.history_requirements["F"]))
    with pytest.raises(ValueError, match="feature_plan_fingerprint"):
        replace(
            plan,
            history_requirements={"F": {history_key: 2}},
        )

    two_feature_lane = compile_lane(
        [
            spec(
                "A",
                requirements=(
                    FeatureRequirement(name="F"),
                    FeatureRequirement(name="G"),
                ),
            )
        ],
        lane(binding("a", "A")),
    )
    two_feature_plan = compile_feature_plan(
        two_feature_lane,
        FeatureCatalog([definition("F"), definition("G")]),
        FeaturePolicy(
            name="operator",
            version="1",
            allowed_features=("F", "G"),
        ),
        GRID,
    )
    binding_id, binding_plan = next(iter(two_feature_plan.bindings.items()))
    tampered_binding = replace(
        binding_plan,
        enabled_features=("F",),
        disabled_required_features=("G",),
        statically_available=False,
    )
    with pytest.raises(ValueError, match="feature_plan_fingerprint"):
        replace(
            two_feature_plan,
            effective_shared_features=("F",),
            disabled_features=("G",),
            feature_versions={"F": "1"},
            history_requirements={"F": {}},
            bindings={binding_id: tampered_binding},
        )
