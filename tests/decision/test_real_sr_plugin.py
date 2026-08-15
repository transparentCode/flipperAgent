from __future__ import annotations

import ast
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.decision_app.data.resolver import (
    DataPolicy,
    DataResolver,
    DataSourceCatalog,
    compile_data_plan,
)
from apps.decision_app.domain.market_state import (
    BarStore,
    TimeframeGrid,
    compile_bar_store_capacities,
)
from apps.decision_app.domain.view import DecisionViewBuilder
from apps.decision_app.features.definitions import (
    SR_ATR_DEFINITION,
    SR_ATR_HISTORY_BARS,
    SR_ATR_PERIOD,
    calculate_sr_atr,
)
from apps.decision_app.features.engine import FeatureEngine, SharedFeatureContext
from apps.decision_app.features.planning import (
    FeatureCatalog,
    FeaturePolicy,
    compile_feature_plan,
    merge_bar_store_capacities,
)
from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.planning.planner import (
    DecisionLaneSpec,
    ModelBindingSpec,
    compile_decision_plan,
)
from apps.decision_app.planning.readiness import compile_lane_market_requirements
from apps.decision_app.runtime.models import (
    ModelRuntime,
    RewarmError,
    RewarmStep,
    StateTransactionError,
)
from apps.decision_app.runtime.plugins import (
    RuntimePluginCatalog,
    RuntimePluginDefinition,
)
from libs.contracts.decision import CausalBarView, DecisionContext, FeatureSnapshot
from libs.models.sr.adapters.decision_plugin import (
    SR_ARTIFACT_TYPE,
    SR_MODEL_SPEC,
    SRDecisionPlugin,
    _canonical_bar_id,
    to_sr_closed_bar,
)
from libs.models.sr.config import SRConfigResolver
from libs.models.sr.domain.bars import SRStateKey
from libs.models.sr.domain.errors import ContractValidationError
from libs.models.sr.domain.factory import create_initial_state
from libs.models.sr.lifecycle.engine import SREngine
from libs.models.sr.serialization.state_codec import decode_state, encode_state

BASE = datetime(2026, 1, 1, tzinfo=UTC)
GRID = TimeframeGrid(
    alignment_origin=BASE,
    durations={"1h": timedelta(hours=1)},
)
RAW_SR_CONFIG = {
    "version": "1",
    "defaults": {
        "detection": {"pivot_span_bars": 1, "zone_half_width_atr": 0.0},
        "association": {"merge_distance_atr": 0.5},
        "lifecycle": {
            "touch_tolerance_atr": 0.25,
            "break_buffer_atr": 0.5,
            "break_confirm_closes": 2,
            "max_age_bars": 20,
        },
        "runtime": {"max_active_zones": 8},
    },
}


def _bar(index: int) -> CausalBarView:
    opened_at = BASE + timedelta(hours=index)
    closed_at = opened_at + timedelta(hours=1)
    close = Decimal(101 + (index % 3))
    return CausalBarView(
        timeframe="1h",
        bar_open_at=opened_at,
        bar_close_at=closed_at,
        market_as_of=closed_at,
        open=Decimal(100 + (index % 2)),
        high=close + Decimal(3),
        low=close - Decimal(3),
        close=close,
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )


def _lane_and_runtime(
    *,
    bar_count: int = 24,
    policy_name: str = "default",
    policy_parameters: dict[str, object] | None = None,
) -> tuple[
    ModelRuntime,
    object,
    DecisionViewBuilder,
    BarStore,
    tuple[CausalBarView, ...],
]:
    binding = ModelBindingSpec(
        slot_name="sr_primary",
        plugin_name="sr",
        plugin_version="1",
        parameters={"sr_config": RAW_SR_CONFIG},
    )
    lane_spec = DecisionLaneSpec(
        lane_id="BTCUSDT:1h",
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        decision_timeframe="1h",
        trigger_timeframe="1h",
        trigger_mode="on_bar_close",
        policy_name=policy_name,
        policy_version="1",
        policy_parameters=({} if policy_parameters is None else policy_parameters),
        risk_profile_key="btc-default",
        bindings=(binding,),
    )
    plan = compile_decision_plan(PluginCatalog([SR_MODEL_SPEC]), [lane_spec])
    lane = plan.lanes[0]
    feature_catalog = FeatureCatalog([SR_ATR_DEFINITION])
    feature_plan = compile_feature_plan(
        lane,
        feature_catalog,
        FeaturePolicy(name="operator", version="1", allowed_features=("ATR",)),
        GRID,
    )
    from apps.decision_app.features.planning import compile_feature_bar_store_capacities

    feature_capacities = compile_feature_bar_store_capacities(
        plan,
        [feature_plan],
        feature_catalog,
        GRID,
    )
    capacities = merge_bar_store_capacities(
        compile_bar_store_capacities(plan, GRID),
        feature_capacities,
    )
    # The D4 plan establishes the minimum physical capacity.  The test keeps
    # the complete deterministic replay fixture retained so D6 can consume
    # multiple historical steps without consulting an external source.
    expanded_capacities = {
        key: max(capacity, bar_count) for key, capacity in capacities.items()
    }
    store = BarStore(expanded_capacities)
    bars = tuple(_bar(index) for index in range(bar_count))
    key = store.series_keys[0]
    for bar in bars[:SR_ATR_HISTORY_BARS]:
        store.append(key, bar)
    view_builder = DecisionViewBuilder(store, GRID)
    data_plan = compile_data_plan(
        lane,
        DataPolicy(name="operator", version="1", concepts={}),
        DataSourceCatalog([]),
    )
    runtime = ModelRuntime(
        lane,
        feature_plan,
        data_plan,
        FeatureEngine(feature_catalog, store, GRID),
        DataResolver(DataSourceCatalog([])),
        RuntimePluginCatalog(
            [
                RuntimePluginDefinition(
                    plugin_name="sr",
                    plugin_version="1",
                    factory=SRDecisionPlugin,
                )
            ]
        ),
        GRID,
    )
    return runtime, lane, view_builder, store, bars


def _view(view_builder: DecisionViewBuilder, lane: object, bar: CausalBarView):
    requirements = compile_lane_market_requirements(lane, GRID)
    return view_builder.build(lane, requirements, bar.market_as_of)


def _direct_context(
    binding_id: str,
    bar: CausalBarView,
    *,
    atr: object = 6.0,
    closed: bool = True,
) -> DecisionContext:
    if not closed:
        bar = CausalBarView(
            timeframe=bar.timeframe,
            bar_open_at=bar.bar_open_at,
            bar_close_at=bar.bar_close_at,
            market_as_of=bar.bar_close_at - timedelta(minutes=1),
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            taker_buy_base=bar.taker_buy_base,
            closed=False,
        )
    return DecisionContext(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        lane_id="BTCUSDT:1h",
        binding_id=binding_id,
        market_as_of=bar.market_as_of,
        trigger_timeframe="1h",
        decision_timeframe="1h",
        trigger_mode="on_bar_close",
        decision_bar=bar,
        decision_bar_closed=bar.closed,
        shared_features={
            "ATR": FeatureSnapshot(
                name="ATR",
                version="1",
                market_as_of=bar.market_as_of,
                value=atr,
            )
        },
    )


def test_sr_spec_and_runtime_catalog_contract() -> None:
    assert isinstance(SRDecisionPlugin({"sr_config": RAW_SR_CONFIG}), SRDecisionPlugin)
    assert SR_MODEL_SPEC.stateful is True
    assert SR_MODEL_SPEC.output_kind == "analytical"
    assert SR_MODEL_SPEC.produces_artifact_type == SR_ARTIFACT_TYPE
    assert SR_MODEL_SPEC.state_reconstruction.durable_pit_required is True
    assert SR_MODEL_SPEC.intrinsic_feature_requirements[0].name == "ATR"
    assert SR_MODEL_SPEC.intrinsic_data_requirements == ()


def test_sr_atr_definition_is_bounded_and_matches_reference_indicator() -> None:
    assert SR_ATR_DEFINITION.history_requirements[0].bars == SR_ATR_HISTORY_BARS
    bars = tuple(_bar(index) for index in range(SR_ATR_HISTORY_BARS))
    context = SharedFeatureContext(
        lane_id="BTCUSDT:1h",
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        market_as_of=bars[-1].market_as_of,
        decision_timeframe="1h",
        trigger_timeframe="1h",
        decision_bar=bars[-1],
        decision_bar_closed=True,
        histories={"1h": bars},
        observed_cutoffs={"1h": bars[-1].market_as_of},
    )
    value = calculate_sr_atr(context)
    from libs.features.indicators.volatility.atr import ATR

    expected = ATR(period=SR_ATR_PERIOD).batch(
        [(float(bar.high), float(bar.low), float(bar.close)) for bar in bars]
    )[-1]
    assert expected is not None
    assert value == pytest.approx(expected)


def test_sr_closed_bar_conversion_is_deterministic_and_utc() -> None:
    bar = _bar(0)
    context = _direct_context("binding", bar)
    first = to_sr_closed_bar(context, atr_at_close=2.5)
    second = to_sr_closed_bar(context, atr_at_close=2.5)
    assert first == second
    assert first.bar_id == _canonical_bar_id(context)
    assert first.closed_at == context.market_as_of
    assert first.atr_at_close == 2.5


def test_sr_plugin_rejects_projected_or_invalid_feature_inputs() -> None:
    plugin = SRDecisionPlugin({"sr_config": RAW_SR_CONFIG})
    bar = _bar(0)
    with pytest.raises(ValueError, match="closed decision bars"):
        plugin.evaluate(_direct_context("binding", bar, closed=False))
    missing = _direct_context("binding", bar)
    missing = DecisionContext(
        asset=missing.asset,
        venue=missing.venue,
        instrument_id=missing.instrument_id,
        lane_id=missing.lane_id,
        binding_id=missing.binding_id,
        market_as_of=missing.market_as_of,
        trigger_timeframe=missing.trigger_timeframe,
        decision_timeframe=missing.decision_timeframe,
        trigger_mode=missing.trigger_mode,
        decision_bar=missing.decision_bar,
        decision_bar_closed=True,
    )
    with pytest.raises(ValueError, match="requires the ATR"):
        plugin.evaluate(missing)
    with pytest.raises(ValueError, match="positive"):
        plugin.evaluate(_direct_context("binding", bar, atr=0.0))
    with pytest.raises(TypeError, match="numeric"):
        plugin.evaluate(_direct_context("binding", bar, atr="not-a-number"))
    with pytest.raises(TypeError, match="encoded state string"):
        plugin.evaluate(_direct_context("binding", bar), state_snapshot=object())
    with pytest.raises(ContractValidationError):
        SRDecisionPlugin({"sr_config": {"version": "1"}})


def test_sr_plugin_rejects_encoded_state_identity_and_config_mismatch() -> None:
    plugin = SRDecisionPlugin({"sr_config": RAW_SR_CONFIG})
    context = _direct_context("binding", _bar(0))
    state_key = to_sr_closed_bar(context, atr_at_close=6.0).state_key
    resolver = SRConfigResolver(RAW_SR_CONFIG)

    other_key = SRStateKey(venue="binance", symbol="ETHUSDT", timeframe="1h")
    other_config = resolver.resolve(asset="ETHUSDT", timeframe="1h")
    other_state = create_initial_state(other_key, other_config)
    with pytest.raises(ValueError, match="state identity"):
        plugin.evaluate(context, state_snapshot=encode_state(other_state))

    changed_raw_config = deepcopy(RAW_SR_CONFIG)
    changed_raw_config["defaults"]["association"]["merge_distance_atr"] = 0.75
    changed_config = SRConfigResolver(changed_raw_config).resolve(
        asset="BTCUSDT",
        timeframe="1h",
    )
    changed_state = create_initial_state(state_key, changed_config)
    with pytest.raises(ValueError, match="state config"):
        plugin.evaluate(context, state_snapshot=encode_state(changed_state))


def test_sr_plugin_state_codec_and_proposal_are_deterministic() -> None:
    plugin = SRDecisionPlugin({"sr_config": RAW_SR_CONFIG})
    context = _direct_context("binding", _bar(0), atr=2.5)
    first = plugin.evaluate(context)
    second = plugin.evaluate(context)
    assert first.proposed_next_state == second.proposed_next_state
    assert first.artifact.value == second.artifact.value
    decoded = decode_state(first.proposed_next_state)
    assert encode_state(decoded) == first.proposed_next_state
    assert first.decision is None
    assert first.artifact.artifact_type == SR_ARTIFACT_TYPE
    assert (
        first.artifact.provenance["snapshot_id"] == first.artifact.value["snapshot_id"]
    )


def test_sr_plugin_matches_direct_engine_step() -> None:
    plugin = SRDecisionPlugin({"sr_config": RAW_SR_CONFIG})
    context = _direct_context("binding", _bar(0), atr=2.5)
    outcome = plugin.evaluate(context)
    resolver = SRConfigResolver(RAW_SR_CONFIG)
    config = resolver.resolve(asset="BTCUSDT", timeframe="1h")
    state_key = to_sr_closed_bar(context, atr_at_close=2.5).state_key
    initial = create_initial_state(state_key, config)
    next_state, snapshot, events = SREngine().step(
        initial,
        to_sr_closed_bar(context, atr_at_close=2.5),
        config,
    )
    assert outcome.proposed_next_state == encode_state(next_state)
    assert outcome.artifact.value["snapshot_id"] == snapshot.snapshot_id
    assert outcome.artifact.value["zone_count"] == len(snapshot.zones)
    assert (
        outcome.artifact.value["active_zone_count"]
        + outcome.artifact.value["terminal_zone_count"]
        == outcome.artifact.value["zone_count"]
    )
    assert outcome.artifact.value["projected_zone_count"] == len(
        outcome.artifact.value["zones"]
    )
    assert outcome.artifact.value["event_count"] == len(events)
    assert tuple(
        event["event_id"] for event in outcome.artifact.value["events"]
    ) == tuple(event.event_id for event in events)


def test_sr_artifact_zone_projection_remains_bounded_over_long_horizon() -> None:
    plugin = SRDecisionPlugin({"sr_config": RAW_SR_CONFIG})
    state: str | None = None
    max_active_zones = 8
    terminal_accumulated = False
    max_total_zones = 0
    max_projected_zones = 0

    for index in range(1000):
        outcome = plugin.evaluate(
            _direct_context("binding", _bar(index), atr=6.0),
            state_snapshot=state,
        )
        value = outcome.artifact.value
        state = outcome.proposed_next_state
        zone_count = value["zone_count"]
        active_zone_count = value["active_zone_count"]
        terminal_zone_count = value["terminal_zone_count"]
        projected_zone_count = value["projected_zone_count"]
        max_total_zones = max(max_total_zones, zone_count)
        max_projected_zones = max(max_projected_zones, projected_zone_count)
        terminal_accumulated = terminal_accumulated or terminal_zone_count > 0

        assert active_zone_count + terminal_zone_count == zone_count
        assert projected_zone_count == len(value["zones"])
        assert projected_zone_count == active_zone_count
        assert projected_zone_count <= max_active_zones
        assert all(
            zone["status"] not in {"BROKEN", "EXPIRED"} for zone in value["zones"]
        )
        assert value["event_count"] == len(value["events"])

    assert terminal_accumulated is True
    assert max_total_zones > max_active_zones
    assert max_projected_zones <= max_active_zones


@pytest.mark.asyncio
async def test_d6_rewarm_and_transaction_boundary_use_real_sr_plugin() -> None:
    runtime, lane, view_builder, store, bars = _lane_and_runtime()
    binding_id = next(iter(runtime.lane.bindings.values())).binding_id
    replay_bars = bars[SR_ATR_HISTORY_BARS - 1 : SR_ATR_HISTORY_BARS + 4]
    key = store.series_keys[0]
    steps = []
    for bar in replay_bars:
        if store.latest_cutoff(key) != bar.market_as_of:
            store.append(key, bar)
        steps.append(
            RewarmStep(
                lane_market_view=_view(view_builder, lane, bar),
                resolver_knowledge_cutoff=bar.market_as_of,
            )
        )
    result = await runtime.rewarm(tuple(steps))
    assert result.final_market_as_of == replay_bars[-1].market_as_of
    record_before = runtime.state_store.get(binding_id)
    assert record_before.health == "LIVE"
    committed_before = record_before.committed_state

    resolver = SRConfigResolver(RAW_SR_CONFIG)
    config = resolver.resolve(asset="BTCUSDT", timeframe="1h")
    reference_state = create_initial_state(
        to_sr_closed_bar(
            _direct_context(binding_id, replay_bars[0]), atr_at_close=6.0
        ).state_key,
        config,
    )
    reference_engine = SREngine()
    for replay_bar in replay_bars:
        reference_state, _, _ = reference_engine.step(
            reference_state,
            to_sr_closed_bar(
                _direct_context(binding_id, replay_bar),
                atr_at_close=6.0,
            ),
            config,
        )
    assert committed_before == encode_state(reference_state)

    next_bar = bars[SR_ATR_HISTORY_BARS + 4]
    store.append(key, next_bar)
    prepared = await runtime.prepare_live(
        _view(view_builder, lane, next_bar),
        resolver_knowledge_cutoff=next_bar.market_as_of,
    )
    assert prepared.state_commit_eligible is True
    assert runtime.state_store.get(binding_id).committed_state == committed_before
    transition = prepared.prepared_state_transitions[binding_id]
    assert isinstance(transition.proposed_next_state, str)
    proposed = decode_state(transition.proposed_next_state)
    assert proposed.last_processed_bar is not None
    reference_next, reference_snapshot, _ = reference_engine.step(
        reference_state,
        to_sr_closed_bar(_direct_context(binding_id, next_bar), atr_at_close=6.0),
        config,
    )
    assert transition.proposed_next_state == encode_state(reference_next)
    assert (
        prepared.binding_results[binding_id].outcome.artifact.value["snapshot_id"]
        == reference_snapshot.snapshot_id
    )

    runtime.abort_prepared(prepared, "publication boundary test")
    after_abort = runtime.state_store.get(binding_id)
    assert after_abort.committed_state == committed_before
    assert after_abort.committed_market_as_of == record_before.committed_market_as_of
    assert after_abort.health == "DEGRADED"
    blocked = await runtime.prepare_live(
        _view(view_builder, lane, next_bar),
        resolver_knowledge_cutoff=next_bar.market_as_of,
    )
    assert blocked.binding_results[binding_id].status == "UNAVAILABLE"
    assert blocked.binding_results[binding_id].reason == "state_rewarm_required"
    await runtime.rewarm(
        (
            RewarmStep(
                lane_market_view=_view(view_builder, lane, next_bar),
                resolver_knowledge_cutoff=next_bar.market_as_of,
            ),
        )
    )
    commit_bar = bars[SR_ATR_HISTORY_BARS + 5]
    store.append(key, commit_bar)
    prepared = await runtime.prepare_live(
        _view(view_builder, lane, commit_bar),
        resolver_knowledge_cutoff=commit_bar.market_as_of,
    )
    receipt = runtime.commit_prepared(prepared, "no_signal")
    assert receipt.committed_binding_ids == (binding_id,)
    final_record = runtime.state_store.get(binding_id)
    assert final_record.health == "LIVE"
    assert final_record.committed_market_as_of == commit_bar.market_as_of
    assert isinstance(final_record.committed_state, str)

    next_cutoff = bars[SR_ATR_HISTORY_BARS + 6]
    future_cutoff = bars[SR_ATR_HISTORY_BARS + 7]
    store.append(key, next_cutoff)
    store.append(key, future_cutoff)
    with pytest.raises(StateTransactionError):
        await runtime.prepare_live(
            _view(view_builder, lane, future_cutoff),
            resolver_knowledge_cutoff=future_cutoff.market_as_of,
        )


@pytest.mark.asyncio
async def test_d6_rewarm_rejects_out_of_order_steps_with_real_sr_plugin() -> None:
    runtime, lane, view_builder, store, bars = _lane_and_runtime()
    key = store.series_keys[0]
    for bar in bars[SR_ATR_HISTORY_BARS : SR_ATR_HISTORY_BARS + 2]:
        store.append(key, bar)
    first = bars[SR_ATR_HISTORY_BARS - 1]
    skipped = bars[SR_ATR_HISTORY_BARS + 1]
    with pytest.raises(RewarmError, match="contiguous"):
        await runtime.rewarm(
            (
                RewarmStep(
                    lane_market_view=_view(view_builder, lane, first),
                    resolver_knowledge_cutoff=first.market_as_of,
                ),
                RewarmStep(
                    lane_market_view=_view(view_builder, lane, skipped),
                    resolver_knowledge_cutoff=skipped.market_as_of,
                ),
            )
        )


def test_sr_adapter_has_no_infrastructure_or_legacy_boundary_imports() -> None:
    path = Path("src/libs/models/sr/adapters/decision_plugin.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    forbidden = (
        "apps.decision_app",
        "redis",
        "valkey",
        "asyncpg",
        "fastapi",
        "signal_app",
        "strategy_app",
        "risk_app",
        "execution_app",
    )
    assert not any(module.startswith(forbidden) for module in modules)
    source = path.read_text(encoding="utf-8")
    assert "FeatureVector" not in source
    assert "ModelOutput" not in source
