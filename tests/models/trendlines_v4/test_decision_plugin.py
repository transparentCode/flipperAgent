"""Decision-boundary contracts for the Trendlines V4 analytical adapter."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from apps.decision_app.data.resolver import (
    DataPolicy,
    DataResolver,
    DataSourceCatalog,
    compile_data_plan,
)
from apps.decision_app.domain.market_state import BarStore, MarketSeriesKey
from apps.decision_app.domain.view import LaneMarketView
from apps.decision_app.features.engine import FeatureEngine
from apps.decision_app.features.planning import (
    FeatureCatalog,
    FeaturePolicy,
    compile_feature_plan,
)
from apps.decision_app.planning.catalog import PluginCatalog
from apps.decision_app.planning.planner import (
    DecisionLaneSpec,
    ModelBindingSpec,
    compile_decision_plan,
)
from apps.decision_app.runtime.models import ModelRuntime, RewarmStep
from apps.decision_app.runtime.plugins import (
    RuntimePluginCatalog,
    RuntimePluginDefinition,
)
from apps.decision_app.storage.state_codec import (
    decode_state_payload,
    encode_state_payload,
)
from libs.contracts.decision import (
    CausalBarView,
    DecisionContext,
    ModelRequestContext,
)
from libs.models.trendlines_v4.adapters.decision_plugin import (
    TRENDLINES_ARTIFACT_TYPE,
    TRENDLINES_MODEL_SPEC,
    TRENDLINES_PLUGIN_NAME,
    TRENDLINES_PLUGIN_VERSION,
    TRENDLINES_STATE_SCHEMA_VERSION,
    TrendlinesV4DecisionPlugin,
    _snapshot_value,
    trendlines_initialization_requirement,
)
from libs.models.trendlines_v4.core import (
    HISTORY_CAPACITY_BARS,
    TrendlineBar,
    analyze_trendlines,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)
GRID = __import__(
    "apps.decision_app.domain.market_state",
    fromlist=["TimeframeGrid"],
).TimeframeGrid(
    alignment_origin=BASE,
    durations={"1h": timedelta(hours=1)},
)


def _bar(index: int, *, timeframe: str = "1h") -> CausalBarView:
    duration = timedelta(hours=4 if timeframe == "4h" else 1)
    opened_at = BASE + index * duration
    closed_at = opened_at + duration
    close = Decimal(100 + (index % 7))
    return CausalBarView(
        timeframe=timeframe,
        bar_open_at=opened_at,
        bar_close_at=closed_at,
        market_as_of=closed_at,
        open=close - Decimal(1),
        high=close + Decimal(3),
        low=close - Decimal(3),
        close=close,
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        closed=True,
    )


def _context(
    index: int = 0,
    *,
    trigger_timeframe: str = "1h",
    decision_timeframe: str = "1h",
    trigger_mode: str = "on_bar_close",
    closed: bool = True,
    with_bar: bool = True,
    binding_id: str = "trendlines-binding",
) -> DecisionContext:
    bar = _bar(index, timeframe=decision_timeframe) if with_bar else None
    if bar is not None and not closed:
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
    market_as_of = (
        bar.market_as_of if bar is not None else BASE + timedelta(hours=index + 1)
    )
    return DecisionContext(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        lane_id="BTCUSDT:trendlines",
        binding_id=binding_id,
        market_as_of=market_as_of,
        trigger_timeframe=trigger_timeframe,
        decision_timeframe=decision_timeframe,
        trigger_mode=trigger_mode,
        decision_bar=bar,
        decision_bar_closed=bar.closed if bar is not None else False,
    )


def _request_context(context: DecisionContext) -> ModelRequestContext:
    return ModelRequestContext(
        asset=context.asset,
        venue=context.venue,
        instrument_id=context.instrument_id,
        lane_id=context.lane_id,
        binding_id=context.binding_id,
        market_as_of=context.market_as_of,
        trigger_timeframe=context.trigger_timeframe,
        decision_timeframe=context.decision_timeframe,
        trigger_mode=context.trigger_mode,
        decision_bar=context.decision_bar,
        decision_bar_closed=context.decision_bar_closed,
    )


def _production_bar(bar: CausalBarView) -> TrendlineBar:
    return TrendlineBar(
        closed_at=bar.market_as_of,
        open=float(bar.open),
        high=float(bar.high),
        low=float(bar.low),
        close=float(bar.close),
    )


def _state_mapping(payload: str) -> dict[str, Any]:
    state = decode_state_payload(payload)
    assert isinstance(state, Mapping)
    return dict(state)


def _state_payload(payload: str, **changes: object) -> str:
    state = _state_mapping(payload)
    state.update(changes)
    return encode_state_payload(state)


def _runtime_environment() -> tuple[ModelRuntime, object, RuntimePluginCatalog]:
    lane_spec = DecisionLaneSpec(
        lane_id="BTCUSDT:trendlines",
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        decision_timeframe="1h",
        trigger_timeframe="1h",
        trigger_mode="on_bar_close",
        policy_name="passthrough",
        policy_version="1",
        policy_parameters={},
        authority="shadow",
        bindings=(
            ModelBindingSpec(
                slot_name="trendlines_primary",
                plugin_name=TRENDLINES_PLUGIN_NAME,
                plugin_version=TRENDLINES_PLUGIN_VERSION,
                parameters={},
            ),
        ),
    )
    lane = compile_decision_plan(
        PluginCatalog([TRENDLINES_MODEL_SPEC]),
        [lane_spec],
    ).lanes[0]
    feature_catalog = FeatureCatalog([])
    feature_plan = compile_feature_plan(
        lane,
        feature_catalog,
        FeaturePolicy(name="empty", version="1", allowed_features=()),
        GRID,
    )
    data_plan = compile_data_plan(
        lane,
        DataPolicy(name="empty", version="1", concepts={}),
        DataSourceCatalog([]),
    )
    runtime_catalog = RuntimePluginCatalog(
        [
            RuntimePluginDefinition(
                plugin_name=TRENDLINES_PLUGIN_NAME,
                plugin_version=TRENDLINES_PLUGIN_VERSION,
                factory=TrendlinesV4DecisionPlugin,
                initialization_requirement=trendlines_initialization_requirement,
            )
        ]
    )
    runtime = ModelRuntime(
        lane,
        feature_plan,
        data_plan,
        FeatureEngine(
            feature_catalog,
            BarStore(
                {
                    MarketSeriesKey(
                        asset="BTCUSDT",
                        venue="binance",
                        instrument_id="BTC-USDT-PERP",
                        timeframe="1h",
                    ): HISTORY_CAPACITY_BARS,
                }
            ),
            GRID,
        ),
        DataResolver(DataSourceCatalog([])),
        runtime_catalog,
        GRID,
    )
    return runtime, lane, runtime_catalog


def _view(lane: object, bar: CausalBarView) -> LaneMarketView:
    return LaneMarketView(
        lane_id=lane.lane_id,
        asset=lane.asset,
        venue=lane.venue,
        instrument_id=lane.instrument_id,
        market_as_of=bar.market_as_of,
        decision_timeframe=lane.decision_timeframe,
        trigger_timeframe=lane.trigger_timeframe,
        trigger_mode=lane.trigger_mode,
        decision_bar=bar,
        decision_bar_closed=bar.closed,
    )


def test_spec_factory_and_initialization_contract() -> None:
    plugin = TrendlinesV4DecisionPlugin({})
    assert isinstance(plugin, TrendlinesV4DecisionPlugin)
    assert TRENDLINES_MODEL_SPEC.stateful is True
    assert TRENDLINES_MODEL_SPEC.output_kind == "analytical"
    assert TRENDLINES_MODEL_SPEC.produces_artifact_type == TRENDLINES_ARTIFACT_TYPE
    assert TRENDLINES_MODEL_SPEC.supported_trigger_modes == ("on_bar_close",)
    assert TRENDLINES_MODEL_SPEC.supported_timeframes == ()
    assert TRENDLINES_MODEL_SPEC.intrinsic_feature_requirements == ()
    assert TRENDLINES_MODEL_SPEC.intrinsic_data_requirements == ()
    assert TRENDLINES_MODEL_SPEC.dependency_requirements == ()
    assert TRENDLINES_MODEL_SPEC.state_reconstruction.durable_pit_required is True
    with pytest.raises(ValueError, match="parameters"):
        TrendlinesV4DecisionPlugin({"unexpected": 1})
    with pytest.raises(TypeError, match="mapping"):
        TrendlinesV4DecisionPlugin(None)  # type: ignore[arg-type]

    _runtime, lane, runtime_catalog = _runtime_environment()
    binding = next(iter(lane.bindings.values()))
    requirement = runtime_catalog.initialization_for(binding)
    assert requirement is not None
    assert requirement.trigger_steps == HISTORY_CAPACITY_BARS
    assert requirement == trendlines_initialization_requirement(binding)
    with pytest.raises(ValueError, match="matching"):
        trendlines_initialization_requirement(
            binding.__class__(
                lane_id=binding.lane_id,
                slot_name=binding.slot_name,
                plugin_name=binding.plugin_name,
                plugin_version=binding.plugin_version,
                model_spec=binding.model_spec,
                binding_config_fingerprint=binding.binding_config_fingerprint,
                binding_id=binding.binding_id,
                effective_lane_revision=binding.effective_lane_revision,
                parameters=binding.parameters,
                trigger_timeframe="4h",
                decision_timeframe=binding.decision_timeframe,
                trigger_mode=binding.trigger_mode,
                dependencies=binding.dependencies,
                effective_feature_requirements=binding.effective_feature_requirements,
                effective_data_requirements=binding.effective_data_requirements,
                risk_profile_key=binding.risk_profile_key,
                publication_authority=binding.publication_authority,
            )
        )


def test_data_requests_is_empty_and_validates_context_and_state() -> None:
    plugin = TrendlinesV4DecisionPlugin({})
    context = _context()
    first = plugin.evaluate(context)
    assert plugin.data_requests(_request_context(context)) == ()
    assert (
        plugin.data_requests(
            _request_context(context), state_snapshot=first.proposed_next_state
        )
        == ()
    )
    with pytest.raises(ValueError, match="matching"):
        plugin.data_requests(_request_context(_context(trigger_timeframe="4h")))
    with pytest.raises(ValueError, match="on_bar_close"):
        plugin.data_requests(_request_context(_context(trigger_mode="on_tick")))
    with pytest.raises(TypeError, match="ModelRequestContext"):
        plugin.data_requests(object())  # type: ignore[arg-type]


def test_evaluate_requires_closed_same_timeframe_cutoff_and_emits_no_decision() -> None:
    plugin = TrendlinesV4DecisionPlugin({})
    outcome = plugin.evaluate(_context())
    assert outcome.decision is None
    assert outcome.artifact.artifact_type == TRENDLINES_ARTIFACT_TYPE
    assert outcome.artifact.market_as_of == BASE + timedelta(hours=1)
    with pytest.raises(ValueError, match="closed decision bars"):
        plugin.evaluate(_context(closed=False))
    with pytest.raises(ValueError, match="matching"):
        plugin.evaluate(_context(trigger_timeframe="4h"))
    with pytest.raises(ValueError, match="on_bar_close"):
        plugin.evaluate(_context(trigger_mode="on_tick"))
    with pytest.raises(ValueError, match="decision bar"):
        plugin.evaluate(_context(with_bar=False))


def test_adapter_artifact_matches_core_and_state_is_bounded() -> None:
    plugin = TrendlinesV4DecisionPlugin({})
    state: str | None = None
    production_bars: list[TrendlineBar] = []
    for index in range(305):
        context = _context(index)
        outcome = plugin.evaluate(context, state_snapshot=state)
        state = outcome.proposed_next_state
        assert isinstance(state, str)
        current = _production_bar(context.decision_bar)
        production_bars.append(current)
        retained = tuple(production_bars[-HISTORY_CAPACITY_BARS:])
        expected = analyze_trendlines(retained)
        assert outcome.artifact.value == _snapshot_value(expected)
        decoded = decode_state_payload(state)
        assert len(decoded["bars"]) <= HISTORY_CAPACITY_BARS
        assert decoded["bars"][-1][0] == context.market_as_of
    assert len(decoded["bars"]) == HISTORY_CAPACITY_BARS
    assert decoded["bars"][0][0] == production_bars[-HISTORY_CAPACITY_BARS].closed_at


def test_state_codec_round_trip_and_fail_closed_identity_schema_order_and_capacity() -> (
    None
):
    plugin = TrendlinesV4DecisionPlugin({})
    first_context = _context()
    valid_payload = plugin.evaluate(first_context).proposed_next_state
    assert isinstance(valid_payload, str)
    assert encode_state_payload(decode_state_payload(valid_payload)) == valid_payload

    with pytest.raises(ValueError, match="schema"):
        plugin.data_requests(
            _request_context(_context()),
            state_snapshot=_state_payload(
                valid_payload,
                schema_version="wrong",
            ),
        )
    with pytest.raises(ValueError, match="asset"):
        plugin.data_requests(
            _request_context(_context()),
            state_snapshot=_state_payload(valid_payload, asset="ETHUSDT"),
        )
    with pytest.raises(ValueError, match="timeframe"):
        plugin.data_requests(
            _request_context(_context()),
            state_snapshot=_state_payload(valid_payload, timeframe="4h"),
        )
    with pytest.raises(ValueError, match="final bar"):
        plugin.data_requests(
            _request_context(_context()),
            state_snapshot=_state_payload(
                valid_payload,
                last_market_as_of=BASE + timedelta(hours=2),
            ),
        )
    second_payload = plugin.evaluate(
        _context(1), state_snapshot=valid_payload
    ).proposed_next_state
    assert isinstance(second_payload, str)
    with pytest.raises(ValueError, match="strictly increasing"):
        plugin.data_requests(
            _request_context(_context()),
            state_snapshot=_state_payload(
                second_payload,
                bars=tuple(reversed(_state_mapping(second_payload)["bars"])),
            ),
        )

    oversized_bars = tuple(
        (
            _bar(index).market_as_of,
            float(_bar(index).open),
            float(_bar(index).high),
            float(_bar(index).low),
            float(_bar(index).close),
        )
        for index in range(HISTORY_CAPACITY_BARS + 1)
    )
    with pytest.raises(ValueError, match="capacity"):
        plugin.data_requests(
            _request_context(_context()),
            state_snapshot=_state_payload(
                valid_payload,
                bars=oversized_bars,
                last_market_as_of=oversized_bars[-1][0],
            ),
        )

    with pytest.raises(ValueError, match="strictly"):
        plugin.evaluate(first_context, state_snapshot=valid_payload)


@pytest.mark.asyncio
async def test_runtime_checkpoint_rewarm_and_uninterrupted_execution_are_exact() -> (
    None
):
    uninterrupted, lane, _catalog = _runtime_environment()
    binding_id = next(iter(lane.bindings.values())).binding_id
    uninterrupted_steps = tuple(
        RewarmStep(
            lane_market_view=_view(lane, _bar(index)),
            resolver_knowledge_cutoff=_bar(index).market_as_of,
        )
        for index in range(HISTORY_CAPACITY_BARS + 1)
    )
    await uninterrupted.rewarm(uninterrupted_steps)
    uninterrupted_state = uninterrupted.state_store.get(binding_id).committed_state

    cold, cold_lane, cold_catalog = _runtime_environment()
    cold_binding_id = next(iter(cold_lane.bindings.values())).binding_id
    requirement = cold_catalog.initialization_for(
        next(iter(cold_lane.bindings.values()))
    )
    assert requirement is not None and requirement.trigger_steps == 300
    steps = tuple(
        RewarmStep(
            lane_market_view=_view(cold_lane, _bar(index)),
            resolver_knowledge_cutoff=_bar(index).market_as_of,
        )
        for index in range(HISTORY_CAPACITY_BARS)
    )
    result = await cold.rewarm(steps)
    assert result.replay_step_count == HISTORY_CAPACITY_BARS
    checkpoint_state = cold.state_store.get(cold_binding_id).committed_state
    assert isinstance(checkpoint_state, str)
    assert (
        encode_state_payload(decode_state_payload(checkpoint_state)) == checkpoint_state
    )
    next_bar = _bar(HISTORY_CAPACITY_BARS)
    prepared = await cold.prepare_live(
        _view(cold_lane, next_bar),
        resolver_knowledge_cutoff=next_bar.market_as_of,
    )
    cold_outcome = prepared.binding_results[cold_binding_id].outcome
    reference_plugin = TrendlinesV4DecisionPlugin({})
    reference_state: str | None = None
    reference_outcome = None
    for index in range(HISTORY_CAPACITY_BARS + 1):
        reference_outcome = reference_plugin.evaluate(
            _context(index, binding_id=cold_binding_id),
            state_snapshot=reference_state,
        )
        reference_state = reference_outcome.proposed_next_state
    assert cold_outcome == reference_outcome
    cold.commit_prepared(prepared, "shadow")
    assert cold.state_store.get(cold_binding_id).committed_state == uninterrupted_state


def test_root_v4_import_does_not_pull_decision_or_legacy_dependencies() -> None:
    root = os.environ.copy()
    root["PYTHONPATH"] = str(
        __import__("pathlib").Path(__file__).resolve().parents[3] / "src"
    )
    root["PYTHONDONTWRITEBYTECODE"] = "1"
    script = """
import sys
import libs.models.trendlines_v4
forbidden = (
    'libs.models.trendlines', 'apps.decision_app', 'research', 'numpy',
    'pandas', 'scipy', 'sklearn', 'optuna', 'pydantic',
)
loaded = sorted(
    name for name in sys.modules
    if any(name == prefix or name.startswith(prefix + '.') for prefix in forbidden)
)
if loaded:
    raise SystemExit(','.join(loaded))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root["PYTHONPATH"].rsplit("/src", 1)[0],
        env=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


assert TRENDLINES_STATE_SCHEMA_VERSION == "trendlines.state.v1"
