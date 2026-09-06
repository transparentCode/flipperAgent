"""Decision adapter contracts for Trendlines V4 geometry.v2."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.decision_app.domain.contracts import ResolvedModelBinding
from libs.contracts.decision import CausalBarView, DecisionContext, ModelRequestContext
from libs.models.trendlines_v4.adapters.decision_plugin import (
    TrendlinesV4DecisionPlugin,
)
from libs.models.trendlines_v4.adapters.decision_plugin_v2 import (
    TRENDLINES_V2_ARTIFACT_TYPE,
    TRENDLINES_V2_MODEL_SPEC,
    TRENDLINES_V2_PLUGIN_NAME,
    TRENDLINES_V2_PLUGIN_VERSION,
    TRENDLINES_V2_STATE_SCHEMA_VERSION,
    TrendlinesV4V2DecisionPlugin,
    trendlines_v2_initialization_requirement,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _bar(index: int) -> CausalBarView:
    close = Decimal(100 + (index % 11))
    opened_at = BASE + index * timedelta(hours=1)
    closed_at = opened_at + timedelta(hours=1)
    return CausalBarView(
        timeframe="1h",
        bar_open_at=opened_at,
        bar_close_at=closed_at,
        market_as_of=closed_at,
        open=close - Decimal(1),
        high=close + Decimal(3),
        low=close - Decimal(3),
        close=close,
        volume=Decimal(1),
        taker_buy_base=Decimal("0.5"),
        closed=True,
    )


def _context(
    index: int, *, binding_id: str = "trendlines-v2-binding"
) -> DecisionContext:
    bar = _bar(index)
    return DecisionContext(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        lane_id="BTCUSDT:trendlines",
        binding_id=binding_id,
        market_as_of=bar.market_as_of,
        trigger_timeframe="1h",
        decision_timeframe="1h",
        trigger_mode="on_bar_close",
        decision_bar=bar,
        decision_bar_closed=True,
    )


def _request(context: DecisionContext) -> ModelRequestContext:
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


def test_v2_spec_and_initialization_are_additive_and_parameter_free() -> None:
    assert (TRENDLINES_V2_PLUGIN_NAME, TRENDLINES_V2_PLUGIN_VERSION) == (
        "trendlines",
        "2",
    )
    assert TRENDLINES_V2_ARTIFACT_TYPE == "trendlines.geometry.v2"
    assert TRENDLINES_V2_STATE_SCHEMA_VERSION == "trendlines.state.v1"
    assert TRENDLINES_V2_MODEL_SPEC.stateful is True
    assert TRENDLINES_V2_MODEL_SPEC.output_kind == "analytical"
    assert TRENDLINES_V2_MODEL_SPEC.supported_trigger_modes == ("on_bar_close",)
    assert TRENDLINES_V2_MODEL_SPEC.intrinsic_feature_requirements == ()
    assert TRENDLINES_V2_MODEL_SPEC.intrinsic_data_requirements == ()
    assert TRENDLINES_V2_MODEL_SPEC.dependency_requirements == ()
    assert TRENDLINES_V2_MODEL_SPEC.state_reconstruction.durable_pit_required is True


def test_v2_state_and_output_are_exactly_cross_version_compatible() -> None:
    v1 = TrendlinesV4DecisionPlugin({})
    v2 = TrendlinesV4V2DecisionPlugin({})
    v1_state: str | None = None
    v2_state: str | None = None
    for index in range(301):
        context = _context(index)
        v1_outcome = v1.evaluate(context, state_snapshot=v1_state)
        v2_outcome = v2.evaluate(context, state_snapshot=v2_state)
        v1_state = v1_outcome.proposed_next_state
        v2_state = v2_outcome.proposed_next_state
        assert v1_state == v2_state
        assert v1_outcome.decision is None
        assert v2_outcome.decision is None
        assert v1_outcome.artifact.artifact_type == "trendlines.geometry.v1"
        assert v2_outcome.artifact.artifact_type == TRENDLINES_V2_ARTIFACT_TYPE
        assert v2_outcome.artifact.value["schema_version"] == "trendlines.geometry.v2"
        for side_name in ("support", "resistance"):
            old_side = v1_outcome.artifact.value[side_name]
            new_side = v2_outcome.artifact.value[side_name]
            assert new_side["structural"] == old_side["structural"]
            assert new_side["current_valid"] == old_side["current_valid"]
            assert new_side["same_geometry"] == old_side["same_geometry"]
            assert set(new_side) == {
                "structural",
                "current_valid",
                "secondary",
                "same_geometry",
            }
    assert v1_state is not None and v2_state is not None
    assert v2.data_requests(_request(_context(300)), state_snapshot=v1_state) == ()
    assert v1.data_requests(_request(_context(300)), state_snapshot=v2_state) == ()


def test_v2_rejects_non_closed_or_mismatched_timeframe_and_requires_empty_parameters() -> (
    None
):
    v2 = TrendlinesV4V2DecisionPlugin({})
    try:
        TrendlinesV4V2DecisionPlugin({"unexpected": True})
    except ValueError:
        pass
    else:
        raise AssertionError("V2 accepted binding parameters")
    context = _context(0)
    with_context = ModelRequestContext(
        asset=context.asset,
        venue=context.venue,
        instrument_id=context.instrument_id,
        lane_id=context.lane_id,
        binding_id=context.binding_id,
        market_as_of=context.market_as_of,
        trigger_timeframe="4h",
        decision_timeframe="1h",
        trigger_mode="on_bar_close",
        decision_bar=context.decision_bar,
        decision_bar_closed=True,
    )
    try:
        v2.data_requests(with_context)
    except ValueError:
        pass
    else:
        raise AssertionError("V2 accepted mismatched timeframes")


def test_v2_initialization_requires_explicit_v2_binding() -> None:
    # Use a real resolved binding from the V2 model spec without enabling a lane.
    binding = ResolvedModelBinding(
        lane_id="BTCUSDT:trendlines",
        slot_name="trendlines_v2",
        plugin_name="trendlines",
        plugin_version="2",
        model_spec=TRENDLINES_V2_MODEL_SPEC,
        binding_config_fingerprint="fingerprint",
        binding_id="binding",
        effective_lane_revision="revision",
        parameters={},
        trigger_timeframe="1h",
        decision_timeframe="1h",
        trigger_mode="on_bar_close",
        dependencies={},
        effective_feature_requirements=(),
        effective_data_requirements=(),
        risk_profile_key=None,
        publication_authority="shadow",
    )
    assert trendlines_v2_initialization_requirement(binding).trigger_steps == 300
