"""Decision contract adapter tests for the plugin-ready Momentum model."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from libs.contracts.decision import (
    CausalBarView,
    DecisionContext,
    DecisionModelPlugin,
    FeatureSnapshot,
)
from libs.models.momentum.adapters.decision_plugin import (
    MOMENTUM_MODEL_SPEC,
    MomentumDecisionPlugin,
)
from libs.models.momentum.config import MomentumConfig

MARKET_AS_OF = datetime(2024, 1, 1, 1, tzinfo=UTC)


def _bar() -> CausalBarView:
    from decimal import Decimal

    return CausalBarView(
        timeframe="1h",
        bar_open_at=MARKET_AS_OF - timedelta(hours=1),
        bar_close_at=MARKET_AS_OF,
        market_as_of=MARKET_AS_OF,
        open=Decimal(100),
        high=Decimal(110),
        low=Decimal(90),
        close=Decimal(105),
        volume=Decimal(10),
        taker_buy_base=None,
        closed=True,
    )


def _context(
    *,
    rsi: object = 60.0,
    histogram: object = 0.5,
    line: object = 0.3,
    include_rsi: bool = True,
    include_macd: bool = True,
    rsi_version: str = "1",
    macd_version: str = "1",
    feature_cutoff: datetime = MARKET_AS_OF,
) -> DecisionContext:
    features: dict[str, FeatureSnapshot] = {}
    if include_rsi:
        features["RSI"] = FeatureSnapshot(
            name="RSI",
            version=rsi_version,
            market_as_of=feature_cutoff,
            value=rsi,
        )
    if include_macd:
        features["MACD"] = FeatureSnapshot(
            name="MACD",
            version=macd_version,
            market_as_of=feature_cutoff,
            value={"histogram": histogram, "line": line},
        )
    bar = _bar()
    return DecisionContext(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        lane_id="btc-1h",
        binding_id="momentum-primary",
        market_as_of=MARKET_AS_OF,
        trigger_timeframe="1h",
        decision_timeframe="1h",
        trigger_mode="on_bar_close",
        decision_bar=bar,
        decision_bar_closed=True,
        causal_bar_views={"1h": (bar,)},
        shared_features=features,
    )


def test_plugin_structurally_conforms_and_has_exact_stateless_spec() -> None:
    plugin = MomentumDecisionPlugin()
    assert isinstance(plugin, DecisionModelPlugin)
    assert plugin.spec == MOMENTUM_MODEL_SPEC
    assert plugin.spec.name == "momentum"
    assert plugin.spec.version == "1"
    assert plugin.spec.stateful is False
    assert plugin.spec.output_kind == "decision_capable"
    assert plugin.spec.produces_artifact_type == "momentum.signal.v1"
    assert plugin.spec.supported_trigger_modes == ("on_bar_close",)
    assert plugin.spec.supported_timeframes == ()
    assert plugin.spec.supported_trigger_timeframes == ()
    assert {item.name for item in plugin.spec.intrinsic_feature_requirements} == {
        "RSI",
        "MACD",
    }
    assert plugin.spec.intrinsic_data_requirements == ()
    assert plugin.spec.dependency_requirements == ()
    assert dict(plugin.spec.warmup_requirements.bars_by_timeframe) == {}


def test_plugin_has_no_data_requests_and_rejects_state() -> None:
    plugin = MomentumDecisionPlugin()
    context = _context()
    assert plugin.data_requests(context) == ()
    with pytest.raises(ValueError, match="stateless"):
        plugin.data_requests(context, state_snapshot={})
    with pytest.raises(ValueError, match="stateless"):
        plugin.evaluate(_context(), state_snapshot={})


def test_long_output_contains_artifact_and_decision_at_causal_cutoff() -> None:
    plugin = MomentumDecisionPlugin()
    outcome = plugin.evaluate(_context(rsi=60.0, histogram=0.5, line=0.3))
    assert outcome.decision is not None
    assert outcome.decision.direction_hint == 1
    assert outcome.decision.score == 0.2
    assert outcome.decision.conviction == 0.2
    assert outcome.decision.signal_time == MARKET_AS_OF
    assert outcome.artifact.artifact_type == "momentum.signal.v1"
    assert outcome.artifact.market_as_of == MARKET_AS_OF
    assert dict(outcome.artifact.value) == {
        "direction": 1,
        "conviction": 0.2,
        "score": 0.2,
    }
    assert dict(outcome.artifact.metadata) == {
        "rsi": 60.0,
        "macd_histogram": 0.5,
        "macd_line": 0.3,
    }
    assert outcome.proposed_next_state is None


def test_neutral_output_keeps_artifact_without_model_decision() -> None:
    outcome = MomentumDecisionPlugin().evaluate(
        _context(rsi=55.0, histogram=0.0, line=0.0)
    )
    assert outcome.decision is None
    assert dict(outcome.artifact.value)["direction"] == 0
    assert dict(outcome.artifact.value)["conviction"] == 0.0


def test_plugin_evaluation_is_deterministic() -> None:
    plugin = MomentumDecisionPlugin(
        MomentumConfig(
            rsi_long_threshold=70,
            rsi_short_threshold=34,
            require_macd_positive=True,
            histogram_min_abs=0.7,
        )
    )
    first = plugin.evaluate(_context(rsi=71.0, histogram=0.7, line=0.1))
    second = plugin.evaluate(_context(rsi=71.0, histogram=0.7, line=0.1))
    assert first == second


def test_plugin_configuration_cannot_be_rebound_after_construction() -> None:
    plugin = MomentumDecisionPlugin()
    with pytest.raises(FrozenInstanceError):
        plugin.config = MomentumConfig(rsi_long_threshold=90)  # type: ignore[misc]


def test_plugin_copies_mapping_configuration_at_construction() -> None:
    parameters = {"rsi_long_threshold": 55}
    plugin = MomentumDecisionPlugin(parameters)
    before = plugin.evaluate(_context(rsi=60.0, histogram=0.5, line=0.3))

    parameters["rsi_long_threshold"] = 90

    after = plugin.evaluate(_context(rsi=60.0, histogram=0.5, line=0.3))
    assert after == before


def test_separate_plugin_configurations_can_have_different_outputs() -> None:
    default_plugin = MomentumDecisionPlugin()
    strict_plugin = MomentumDecisionPlugin(MomentumConfig(rsi_long_threshold=90))

    default_outcome = default_plugin.evaluate(
        _context(rsi=60.0, histogram=0.5, line=0.3)
    )
    strict_outcome = strict_plugin.evaluate(_context(rsi=60.0, histogram=0.5, line=0.3))

    assert default_outcome.decision is not None
    assert strict_outcome.decision is None


@pytest.mark.parametrize(
    "context_kwargs",
    [
        {"include_rsi": False},
        {"include_macd": False},
        {"rsi_version": "2"},
        {"macd_version": "2"},
        {"feature_cutoff": MARKET_AS_OF - timedelta(seconds=1)},
        {"rsi": 100.1},
        {"histogram": float("inf")},
        {"line": None},
    ],
)
def test_malformed_or_misaligned_feature_evidence_fails_closed(
    context_kwargs: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        MomentumDecisionPlugin().evaluate(_context(**context_kwargs))


def test_plugin_requires_closed_decision_bar() -> None:
    from decimal import Decimal

    bar = CausalBarView(
        timeframe="1h",
        bar_open_at=MARKET_AS_OF - timedelta(hours=1),
        bar_close_at=MARKET_AS_OF + timedelta(hours=1),
        market_as_of=MARKET_AS_OF,
        open=Decimal(100),
        high=Decimal(110),
        low=Decimal(90),
        close=Decimal(105),
        volume=Decimal(10),
        taker_buy_base=None,
        closed=False,
    )
    context = DecisionContext(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        lane_id="btc-1h",
        binding_id="momentum-primary",
        market_as_of=MARKET_AS_OF,
        trigger_timeframe="1h",
        decision_timeframe="1h",
        trigger_mode="on_bar_close",
        decision_bar=bar,
        decision_bar_closed=False,
        causal_bar_views={"1h": (bar,)},
        shared_features=_context().shared_features,
    )
    with pytest.raises(ValueError, match="closed"):
        MomentumDecisionPlugin().evaluate(context)
