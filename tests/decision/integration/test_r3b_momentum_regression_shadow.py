from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.decision_app.composition import build_production_composition
from apps.decision_app.domain.market_state import MarketSeriesKey
from apps.decision_app.domain.view import DecisionViewBuilder
from apps.decision_app.features.regression_context import (
    REGRESSION_CONTEXT_FEATURE_NAME,
)
from apps.decision_app.runtime.policy import DecisionPolicy
from apps.decision_app.runtime.startup import DecisionStartupCoordinator
from apps.decision_app.settings import (
    DecisionConfig,
    FeaturePolicySettings,
    load_decision_config,
)
from apps.decision_app.storage.checkpoints import InMemoryCheckpointRepository
from apps.decision_app.storage.market_history import (
    InMemoryCanonicalMarketHistoryRepository,
)
from apps.decision_app.transport.ingestion import canonical_ingestion_stream_key
from apps.decision_app.transport.publication import (
    PublicationCompatibilityError,
    build_signal_envelope,
)
from libs.common.config import ConfigManager
from libs.contracts.decision import CausalBarView

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = ROOT / "tests" / "decision" / "fixtures" / "regression_r3b"


class _EmptyStreamClient:
    async def xrevrange(self, *_args: object, **_kwargs: object) -> list[object]:
        return []

    async def xread(self, *_args: object, **_kwargs: object) -> list[object]:
        return []


@pytest.fixture(scope="module")
def fixture_config() -> DecisionConfig:
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(ROOT / "configs"))
    try:
        return load_decision_config(
            manager,
            global_file=FIXTURE_ROOT / "global.yaml",
            assets_directory=FIXTURE_ROOT / "assets",
        )
    finally:
        manager.shutdown()
        ConfigManager.reset_singleton()


def _series_key(config: DecisionConfig) -> MarketSeriesKey:
    lane = config.lane_specs()[0]
    return MarketSeriesKey(
        asset=lane.asset,
        venue=lane.venue,
        instrument_id=lane.instrument_id,
        timeframe=lane.decision_timeframe,
    )


def _m4_shadow_bars(
    config: DecisionConfig, *, count: int = 136
) -> tuple[CausalBarView, ...]:
    key = _series_key(config)
    duration = config.timeframe_grid.duration(key.timeframe)
    start = config.timeframe_grid.alignment_origin + duration * 1000
    close = Decimal(100)
    bars: list[CausalBarView] = []
    acceleration_start = count - 36
    for index in range(count):
        if index:
            step = Decimal(1)
            if index >= acceleration_start:
                step += Decimal(5) * Decimal(index - acceleration_start)
            close += step
        opened_at = start + duration * index
        closed_at = opened_at + duration
        bars.append(
            CausalBarView(
                timeframe=key.timeframe,
                bar_open_at=opened_at,
                bar_close_at=closed_at,
                market_as_of=closed_at,
                open=close,
                high=close + Decimal(1),
                low=close - Decimal(1),
                close=close,
                volume=Decimal(10),
                taker_buy_base=Decimal(4),
                closed=True,
            )
        )
    return tuple(bars)


async def _startup(
    config: DecisionConfig,
    histories: Mapping[MarketSeriesKey, tuple[CausalBarView, ...]],
):
    composition = build_production_composition(config)
    repository = InMemoryCanonicalMarketHistoryRepository(
        histories,
        timeframe_grid=config.timeframe_grid,
    )
    startup = await DecisionStartupCoordinator(
        decision_config=config,
        plugin_catalog=composition.plugin_catalog,
        feature_catalog=composition.feature_catalog,
        feature_policy=composition.feature_policy,
        data_policy=composition.data_policy,
        source_catalog=composition.data_source_catalog,
        runtime_plugin_catalog=composition.runtime_plugin_catalog,
        history_repository=repository,
        stream_client=_EmptyStreamClient(),
        checkpoint_repository=InMemoryCheckpointRepository(),
        data_resolver=composition.data_resolver,
        policy_catalog=composition.policy_catalog,
    ).start()
    return composition, startup


def _view(config: DecisionConfig, startup, lane):
    key = _series_key(config)
    cutoff = startup.snapshot.lane_evidence[lane.lane_id].resume_cutoff
    assert cutoff is not None
    return DecisionViewBuilder(startup.bar_store, config.timeframe_grid).build(
        lane,
        startup.lane_requirements[lane.lane_id],
        cutoff,
        input_read_cursor=startup.snapshot.input_cursors[
            canonical_ingestion_stream_key(key)
        ],
        lane_commit_watermark=startup.snapshot.lane_watermarks[lane.lane_id],
    )


def _without_observer(config: DecisionConfig) -> DecisionConfig:
    asset = config.assets["BTC"]
    lane_name, lane = next(iter(asset.lanes.items()))
    primary = lane.bindings["primary"]
    no_observer_lane = lane.model_copy(update={"bindings": {"primary": primary}})
    no_observer_asset = asset.model_copy(
        update={"lanes": {lane_name: no_observer_lane}}
    )
    no_observer_global = config.global_settings.model_copy(
        update={
            "feature_policy": FeaturePolicySettings(
                name="momentum-m4-no-observer",
                version="1",
                allowed_features=("MACD", "RSI"),
            )
        }
    )
    return DecisionConfig(
        global_settings=no_observer_global,
        assets={"BTC": no_observer_asset},
        timeframe_grid=config.timeframe_grid,
        instruments=config.instruments,
    )


def _observer_config_variant(
    config: DecisionConfig,
    *,
    lane_updates: Mapping[str, object] | None = None,
    observer_updates: Mapping[str, object] | None = None,
    primary_updates: Mapping[str, object] | None = None,
) -> DecisionConfig:
    asset = config.assets["BTC"]
    lane_name, lane = next(iter(asset.lanes.items()))
    primary = lane.bindings["primary"].model_copy(update=dict(primary_updates or {}))
    observer = lane.bindings["observer"].model_copy(update=dict(observer_updates or {}))
    updated_lane = lane.model_copy(
        update={
            **dict(lane_updates or {}),
            "bindings": {"primary": primary, "observer": observer},
        }
    )
    updated_asset = asset.model_copy(update={"lanes": {lane_name: updated_lane}})
    return DecisionConfig(
        global_settings=config.global_settings,
        assets={"BTC": updated_asset},
        timeframe_grid=config.timeframe_grid,
        instruments=config.instruments,
    )


def test_r3b_valid_shadow_graph_composes_and_policy_source_is_momentum(
    fixture_config: DecisionConfig,
) -> None:
    lane = fixture_config.lane_specs()[0]
    observer = next(
        binding
        for binding in lane.bindings
        if binding.plugin_name == "momentum_regression_observer"
    )
    provider_slot = observer.dependencies["momentum"]
    provider = next(
        binding for binding in lane.bindings if binding.slot_name == provider_slot
    )
    assert lane.authority == "shadow"
    assert (lane.policy_name, lane.policy_version) == ("passthrough", "1")
    assert lane.policy_parameters["source_slot"] == provider_slot
    assert (provider.plugin_name, provider.plugin_version) == ("momentum", "1")
    composition = build_production_composition(fixture_config)
    assert (
        composition.plugin_catalog.resolve(
            "momentum_regression_observer", "1"
        ).produces_artifact_type
        == "momentum.regression_observation.v1"
    )


def test_r3b_authoritative_observer_lane_fails_composition(
    fixture_config: DecisionConfig,
) -> None:
    config = _observer_config_variant(
        fixture_config,
        lane_updates={
            "authority": "authoritative",
            "risk_profile_key": "r3b-remediation-probe",
        },
    )
    with pytest.raises(ValueError, match="requires a shadow lane"):
        build_production_composition(config)


def test_r3b_observer_selected_passthrough_route_fails_composition(
    fixture_config: DecisionConfig,
) -> None:
    lane = fixture_config.assets["BTC"].lanes[
        next(iter(fixture_config.assets["BTC"].lanes))
    ]
    policy = lane.policy.model_copy(update={"parameters": {"source_slot": "observer"}})
    config = _observer_config_variant(fixture_config, lane_updates={"policy": policy})
    with pytest.raises(ValueError, match="source_slot"):
        build_production_composition(config)


def test_r3b_observer_non_passthrough_policy_fails_composition(
    fixture_config: DecisionConfig,
) -> None:
    lane = fixture_config.assets["BTC"].lanes[
        next(iter(fixture_config.assets["BTC"].lanes))
    ]
    policy = lane.policy.model_copy(
        update={
            "name": "priority",
            "parameters": {"source_slots": ["primary"]},
        }
    )
    config = _observer_config_variant(fixture_config, lane_updates={"policy": policy})
    with pytest.raises(ValueError, match="requires passthrough@1"):
        build_production_composition(config)


def test_r3b_observer_missing_logical_momentum_dependency_fails_composition(
    fixture_config: DecisionConfig,
) -> None:
    config = _observer_config_variant(
        fixture_config,
        observer_updates={"dependencies": {}},
    )
    with pytest.raises(ValueError, match="requires a momentum dependency"):
        build_production_composition(config)


def test_r3b_observer_missing_provider_slot_fails_composition(
    fixture_config: DecisionConfig,
) -> None:
    config = _observer_config_variant(
        fixture_config,
        observer_updates={"dependencies": {"momentum": "missing"}},
    )
    with pytest.raises(ValueError, match="same-lane binding"):
        build_production_composition(config)


def test_r3b_observer_non_momentum_provider_fails_composition(
    fixture_config: DecisionConfig,
) -> None:
    config = _observer_config_variant(
        fixture_config,
        primary_updates={"plugin": "sr", "parameters": {"sr_config": {}}},
    )
    with pytest.raises(ValueError, match="momentum@1"):
        build_production_composition(config)


def test_no_observer_m4_composition_remains_without_regression_feature(
    fixture_config: DecisionConfig,
) -> None:
    composition = build_production_composition(_without_observer(fixture_config))
    assert composition.plugin_catalog.get(("momentum_regression_observer", "1")) is None
    assert composition.feature_catalog.get(REGRESSION_CONTEXT_FEATURE_NAME) is None
    assert composition.plugin_catalog.get(("momentum", "1")) is not None


@pytest.mark.asyncio
async def test_r3b_shadow_observer_is_causal_decision_path_and_non_authoritative(
    fixture_config: DecisionConfig,
) -> None:
    histories = {_series_key(fixture_config): _m4_shadow_bars(fixture_config)}
    composition, startup = await _startup(fixture_config, histories)
    lane = startup.decision_plan.lanes[0]
    assert lane.authority == "shadow"
    assert (lane.policy_name, lane.policy_version) == ("passthrough", "1")
    assert {(item.name, item.version) for item in composition.plugin_catalog} == {
        ("momentum", "1"),
        ("momentum_regression_observer", "1"),
        ("sr", "1"),
    }
    assert {
        (item.plugin_name, item.plugin_version)
        for item in composition.runtime_plugin_catalog
    } == {
        ("momentum", "1"),
        ("momentum_regression_observer", "1"),
        ("sr", "1"),
    }
    assert REGRESSION_CONTEXT_FEATURE_NAME in {
        item.name for item in composition.feature_catalog
    }
    key = _series_key(fixture_config)
    assert startup.bar_store.capacity_for(key) == 136
    plan = startup.feature_plans[lane.lane_id]
    assert next(iter(plan.history_requirements["RSI"].values())) == 60
    assert next(iter(plan.history_requirements["MACD"].values())) == 136
    assert (
        next(iter(plan.history_requirements[REGRESSION_CONTEXT_FEATURE_NAME].values()))
        == 74
    )

    view = _view(fixture_config, startup, lane)
    prepared = await startup.runtimes[lane.lane_id].prepare_live(
        view,
        resolver_knowledge_cutoff=view.market_as_of + timedelta(seconds=1),
    )
    primary_binding = lane.bindings["primary"]
    observer_binding = lane.bindings["observer"]
    assert lane.execution_order.index(
        primary_binding.binding_id
    ) < lane.execution_order.index(observer_binding.binding_id)
    primary_result = prepared.binding_results[primary_binding.binding_id]
    observer_result = prepared.binding_results[observer_binding.binding_id]
    assert primary_result.status == observer_result.status == "EXECUTED"
    assert primary_result.outcome is not None
    assert observer_result.outcome is not None
    assert primary_result.outcome.artifact.artifact_type == "momentum.signal.v1"
    assert primary_result.outcome.decision is not None
    assert observer_result.outcome.decision is None
    assert primary_result.outcome.decision.direction_hint == 1

    primary_features = prepared.feature_resolution.bindings[primary_binding.binding_id]
    observer_features = prepared.feature_resolution.bindings[
        observer_binding.binding_id
    ]
    assert set(primary_features.features) == {"MACD", "RSI"}
    assert set(observer_features.features) == {REGRESSION_CONTEXT_FEATURE_NAME}
    assert (
        observer_features.features[REGRESSION_CONTEXT_FEATURE_NAME]
        is prepared.feature_resolution.shared_features[REGRESSION_CONTEXT_FEATURE_NAME]
    )
    observer_artifact = observer_result.outcome.artifact
    assert observer_artifact.value["momentum"] == primary_result.outcome.artifact.value
    regression_value = prepared.feature_resolution.shared_features[
        REGRESSION_CONTEXT_FEATURE_NAME
    ].value
    expected_regression = {
        "slope_log_per_hour": regression_value["structural"]["slope_log_per_hour"],
        "fit_quality": regression_value["structural"]["fit_quality"],
        "region": regression_value["location"]["region"],
        "outer_channel_position": regression_value["location"][
            "outer_channel_position"
        ],
        "outer_width_fraction": regression_value["location"]["outer_width_fraction"],
        "upper_outer_breach": regression_value["location"]["upper_outer_breach"],
        "lower_outer_breach": regression_value["location"]["lower_outer_breach"],
        "previous_region": regression_value["location"]["previous_region"],
        "reentered_from_upper_outer": regression_value["location"][
            "reentered_from_upper_outer"
        ],
        "reentered_from_lower_outer": regression_value["location"][
            "reentered_from_lower_outer"
        ],
    }
    assert observer_artifact.value["regression"] == expected_regression
    assert observer_artifact.provenance["momentum_binding_id"] == (
        primary_result.outcome.artifact.binding_id
    )
    assert observer_artifact.provenance["momentum_artifact_type"] == (
        "momentum.signal.v1"
    )

    evaluation = DecisionPolicy(composition.policy_catalog).evaluate(
        lane,
        prepared,
        decision_ready_at=view.market_as_of + timedelta(seconds=1),
    )
    assert evaluation.status == "SIGNAL"
    assert evaluation.selected_binding_id == primary_binding.binding_id
    assert evaluation.contributing_binding_ids == (primary_binding.binding_id,)
    with pytest.raises(PublicationCompatibilityError, match="authoritative"):
        build_signal_envelope(lane, prepared, evaluation, view)


@pytest.mark.asyncio
async def test_observer_does_not_change_certified_momentum_semantics(
    fixture_config: DecisionConfig,
) -> None:
    histories = {_series_key(fixture_config): _m4_shadow_bars(fixture_config)}
    with_observer, observer_startup = await _startup(fixture_config, histories)
    without_observer_config = _without_observer(fixture_config)
    without_observer, plain_startup = await _startup(
        without_observer_config,
        histories,
    )
    observer_lane = observer_startup.decision_plan.lanes[0]
    plain_lane = plain_startup.decision_plan.lanes[0]
    observer_view = _view(fixture_config, observer_startup, observer_lane)
    plain_view = _view(without_observer_config, plain_startup, plain_lane)
    observer_prepared = await observer_startup.runtimes[
        observer_lane.lane_id
    ].prepare_live(
        observer_view,
        resolver_knowledge_cutoff=observer_view.market_as_of + timedelta(seconds=1),
    )
    plain_prepared = await plain_startup.runtimes[plain_lane.lane_id].prepare_live(
        plain_view,
        resolver_knowledge_cutoff=plain_view.market_as_of + timedelta(seconds=1),
    )
    observer_primary = observer_prepared.binding_results[
        observer_lane.bindings["primary"].binding_id
    ].outcome
    plain_primary = plain_prepared.binding_results[
        plain_lane.bindings["primary"].binding_id
    ].outcome
    assert observer_primary is not None
    assert plain_primary is not None
    assert observer_primary.artifact.value == plain_primary.artifact.value
    assert observer_primary.artifact.metadata == plain_primary.artifact.metadata
    assert observer_primary.decision == plain_primary.decision
    observer_evaluation = DecisionPolicy(with_observer.policy_catalog).evaluate(
        observer_lane,
        observer_prepared,
        decision_ready_at=observer_view.market_as_of + timedelta(seconds=1),
    )
    plain_evaluation = DecisionPolicy(without_observer.policy_catalog).evaluate(
        plain_lane,
        plain_prepared,
        decision_ready_at=plain_view.market_as_of + timedelta(seconds=1),
    )
    assert observer_evaluation.status == plain_evaluation.status == "SIGNAL"
    assert observer_evaluation.result is not None
    assert plain_evaluation.result is not None
    assert observer_evaluation.result.decision == plain_evaluation.result.decision
    assert (
        observer_evaluation.selected_binding_id == plain_evaluation.selected_binding_id
    )


def test_observer_is_not_in_production_asset_configuration() -> None:
    production_assets = ROOT / "configs" / "decision" / "assets"
    assert all(
        "momentum_regression_observer" not in path.read_text()
        for path in production_assets.glob("*.yaml")
    )
