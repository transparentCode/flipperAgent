from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from apps.decision_app.domain.contracts import (
    DecisionPolicyResult,
    InputReadCursor,
    LaneCommitWatermark,
    ResolvedModelBinding,
)
from libs.contracts.decision import (
    CausalBarView,
    DataRequest,
    DataRequirement,
    DataSnapshot,
    DecisionContext,
    FeatureSnapshot,
    ModelArtifact,
    ModelDecision,
    ModelOutcome,
    ModelRequestContext,
    ModelSpec,
    StateReconstructionRequirement,
    WarmupRequirements,
    freeze_model_state,
    validate_data_snapshot,
)

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def make_bar(
    *, closed: bool = True, market_as_of: datetime | None = None
) -> CausalBarView:
    close = BASE + timedelta(hours=1)
    return CausalBarView(
        timeframe="1h",
        bar_open_at=BASE,
        bar_close_at=close,
        market_as_of=market_as_of or close,
        open=Decimal(100),
        high=Decimal(110),
        low=Decimal(90),
        close=Decimal(105),
        volume=Decimal(1000),
        taker_buy_base=Decimal(400),
        closed=closed,
    )


def make_artifact() -> ModelArtifact:
    return ModelArtifact(
        binding_id="binding-a",
        lane_id="BTCUSDT:1h",
        asset="BTCUSDT",
        decision_timeframe="1h",
        trigger_timeframe="1h",
        market_as_of=BASE + timedelta(hours=1),
        artifact_type="boundary",
        value={"levels": [Decimal(101), Decimal(109)]},
        metadata={"nested": {"source": "test"}},
    )


def make_context() -> ModelRequestContext:
    bar = make_bar()
    return ModelRequestContext(
        asset="BTCUSDT",
        venue="binance",
        instrument_id="BTC-USDT-PERP",
        lane_id="BTCUSDT:1h",
        binding_id="binding-a",
        market_as_of=bar.market_as_of,
        trigger_timeframe="1h",
        decision_timeframe="1h",
        trigger_mode="on_bar_close",
        decision_bar=bar,
        decision_bar_closed=True,
        causal_bar_views={"1h": [bar]},
        shared_features={
            "trend": FeatureSnapshot(
                name="trend",
                version="1",
                market_as_of=bar.market_as_of,
                value={"values": [1, 2]},
            )
        },
        upstream_artifacts={"boundary": make_artifact()},
        provenance={"input": {"stream_id": "1-0"}},
    )


def context_kwargs(
    context: ModelRequestContext, **overrides: object
) -> dict[str, object]:
    values: dict[str, object] = {
        "asset": context.asset,
        "venue": context.venue,
        "instrument_id": context.instrument_id,
        "lane_id": context.lane_id,
        "binding_id": context.binding_id,
        "market_as_of": context.market_as_of,
        "trigger_timeframe": context.trigger_timeframe,
        "decision_timeframe": context.decision_timeframe,
        "trigger_mode": context.trigger_mode,
        "decision_bar": context.decision_bar,
        "decision_bar_closed": context.decision_bar_closed,
        "causal_bar_views": context.causal_bar_views,
        "shared_features": context.shared_features,
        "upstream_artifacts": context.upstream_artifacts,
        "provenance": context.provenance,
    }
    values.update(overrides)
    return values


def make_snapshot(
    *,
    available_at: datetime,
    fetched_at: datetime,
    event_time: datetime | None = None,
    represented_end_at: datetime | None = None,
    request_key: str = "oi:BTCUSDT:2026-01-01T01:00:00Z",
    resolved_capability: str = "LIVE_AND_REPLAY",
) -> DataSnapshot:
    return DataSnapshot(
        request_key=request_key,
        concept="OPEN_INTEREST",
        payload={"value": Decimal(42)},
        event_time=event_time or BASE + timedelta(minutes=55),
        available_at=available_at,
        fetched_at=fetched_at,
        source="pit_database",
        resolved_capability=resolved_capability,  # type: ignore[arg-type]
        represented_end_at=represented_end_at,
    )


def make_binding(**overrides: object) -> ResolvedModelBinding:
    values: dict[str, object] = {
        "lane_id": "BTCUSDT:1h",
        "slot_name": "boundary",
        "plugin_name": "BoundaryModel",
        "plugin_version": "1",
        "model_spec": ModelSpec(
            name="BoundaryModel",
            version="1",
            stateful=False,
            output_kind="analytical",
            produces_artifact_type="boundary.v1",
        ),
        "binding_config_fingerprint": "binding-config",
        "binding_id": "binding-a",
        "effective_lane_revision": "revision-1",
        "trigger_timeframe": "1h",
        "decision_timeframe": "1h",
        "trigger_mode": "on_bar_close",
    }
    values.update(overrides)
    return ResolvedModelBinding(**values)  # type: ignore[arg-type]


def test_causal_bar_requires_aware_utc_and_preserves_closed_projected_semantics() -> (
    None
):
    assert make_bar().closed is True
    projected_as_of = BASE + timedelta(minutes=30)
    projected = make_bar(closed=False, market_as_of=projected_as_of)
    assert projected.market_as_of == projected_as_of

    with pytest.raises(ValueError, match="timezone-aware UTC"):
        CausalBarView(
            timeframe="1h",
            bar_open_at=BASE.replace(tzinfo=None),
            bar_close_at=BASE + timedelta(hours=1),
            market_as_of=BASE + timedelta(hours=1),
            open=Decimal(1),
            high=Decimal(2),
            low=Decimal(1),
            close=Decimal(1),
            volume=Decimal(1),
            taker_buy_base=Decimal(1),
            closed=True,
        )

    with pytest.raises(ValueError, match="timezone-aware UTC"):
        make_bar(market_as_of=BASE.astimezone(timezone(timedelta(hours=1))))

    with pytest.raises(ValueError, match="closed bars"):
        make_bar(closed=True, market_as_of=BASE + timedelta(minutes=30))

    with pytest.raises(ValueError, match="projected bars"):
        make_bar(closed=False, market_as_of=BASE + timedelta(hours=1))


@pytest.mark.parametrize("timestamp", [1_700_000_000, 1_700_000_000_000])
def test_causal_bar_rejects_numeric_second_or_millisecond_timestamps(
    timestamp: int,
) -> None:
    with pytest.raises(TypeError, match="bar_open_at must be a datetime"):
        CausalBarView(
            timeframe="1h",
            bar_open_at=timestamp,
            bar_close_at=BASE + timedelta(hours=1),
            market_as_of=BASE + timedelta(hours=1),
            open=Decimal(100),
            high=Decimal(110),
            low=Decimal(90),
            close=Decimal(105),
            volume=Decimal(1000),
            taker_buy_base=Decimal(400),
            closed=True,
        )


def test_causal_bar_rejects_invalid_geometry_and_taker_buy_range() -> None:
    with pytest.raises(ValueError, match="open must be between"):
        CausalBarView(
            timeframe="1h",
            bar_open_at=BASE,
            bar_close_at=BASE + timedelta(hours=1),
            market_as_of=BASE + timedelta(hours=1),
            open=Decimal(111),
            high=Decimal(110),
            low=Decimal(90),
            close=Decimal(105),
            volume=Decimal(1000),
            taker_buy_base=Decimal(400),
            closed=True,
        )

    with pytest.raises(ValueError, match="between zero and volume"):
        CausalBarView(
            timeframe="1h",
            bar_open_at=BASE,
            bar_close_at=BASE + timedelta(hours=1),
            market_as_of=BASE + timedelta(hours=1),
            open=Decimal(100),
            high=Decimal(110),
            low=Decimal(90),
            close=Decimal(105),
            volume=Decimal(100),
            taker_buy_base=Decimal(101),
            closed=True,
        )


def test_data_snapshot_enforces_point_in_time_inequalities() -> None:
    market_as_of = BASE + timedelta(hours=1)
    request = DataRequest(
        request_key="oi:BTCUSDT:2026-01-01T01:00:00Z",
        concept="OPEN_INTEREST",
        market_as_of=market_as_of,
        mode="REPLAY",
        resolver_knowledge_cutoff=market_as_of,
    )
    valid = make_snapshot(
        available_at=market_as_of, fetched_at=market_as_of + timedelta(days=1)
    )
    assert validate_data_snapshot(request, valid) is valid

    future_event = DataSnapshot(
        request_key=valid.request_key,
        concept=valid.concept,
        payload=valid.payload,
        event_time=market_as_of + timedelta(seconds=1),
        available_at=valid.available_at,
        fetched_at=valid.fetched_at,
        source=valid.source,
        resolved_capability=valid.resolved_capability,
    )
    with pytest.raises(ValueError, match="event_time"):
        validate_data_snapshot(request, future_event)

    future_available = make_snapshot(
        available_at=market_as_of + timedelta(seconds=1),
        fetched_at=market_as_of,
    )
    with pytest.raises(ValueError, match="available_at"):
        validate_data_snapshot(request, future_available)

    future_window = DataSnapshot(
        request_key=valid.request_key,
        concept=valid.concept,
        payload=valid.payload,
        event_time=valid.event_time,
        available_at=valid.available_at,
        fetched_at=valid.fetched_at,
        source=valid.source,
        resolved_capability=valid.resolved_capability,
        represented_end_at=market_as_of + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="window"):
        validate_data_snapshot(request, future_window)


def test_live_request_requires_explicit_later_resolver_cutoff() -> None:
    market_as_of = BASE + timedelta(hours=1)
    resolver_cutoff = market_as_of + timedelta(seconds=4)
    request = DataRequest(
        request_key="oi:BTCUSDT:2026-01-01T01:00:00Z",
        concept="OPEN_INTEREST",
        market_as_of=market_as_of,
        mode="LIVE",
        resolver_knowledge_cutoff=resolver_cutoff,
    )
    delayed_snapshot = make_snapshot(
        available_at=resolver_cutoff,
        fetched_at=resolver_cutoff,
    )
    assert validate_data_snapshot(request, delayed_snapshot) is delayed_snapshot

    with pytest.raises(TypeError):
        DataRequest(
            request_key=request.request_key,
            concept=request.concept,
            market_as_of=market_as_of,
            resolver_knowledge_cutoff=resolver_cutoff,
        )

    with pytest.raises(ValueError, match="at or after market_as_of"):
        DataRequest(
            request_key=request.request_key,
            concept=request.concept,
            market_as_of=market_as_of,
            mode="LIVE",
            resolver_knowledge_cutoff=market_as_of - timedelta(seconds=1),
        )


def test_unavailable_snapshot_cannot_satisfy_a_request() -> None:
    market_as_of = BASE + timedelta(hours=1)
    request = DataRequest(
        request_key="oi:BTCUSDT:2026-01-01T01:00:00Z",
        concept="OPEN_INTEREST",
        market_as_of=market_as_of,
        mode="LIVE",
        resolver_knowledge_cutoff=market_as_of,
    )
    unavailable = make_snapshot(
        available_at=market_as_of,
        fetched_at=market_as_of,
        resolved_capability="UNAVAILABLE",
    )
    with pytest.raises(ValueError, match="UNAVAILABLE"):
        validate_data_snapshot(request, unavailable)


def test_semantic_boolean_fields_reject_integer_values() -> None:
    with pytest.raises(TypeError, match="required must be a bool"):
        DataRequirement(concept="OPEN_INTEREST", required=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="replay_support_required must be a bool"):
        DataRequirement(
            concept="OPEN_INTEREST",
            replay_support_required=1,  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="required must be a bool"):
        DataRequest(
            request_key="oi:BTCUSDT:2026-01-01T01:00:00Z",
            concept="OPEN_INTEREST",
            market_as_of=BASE + timedelta(hours=1),
            required=1,  # type: ignore[arg-type]
            mode="LIVE",
            resolver_knowledge_cutoff=BASE + timedelta(hours=1),
        )
    with pytest.raises(TypeError, match="durable_pit_required must be a bool"):
        StateReconstructionRequirement(durable_pit_required=1)  # type: ignore[arg-type]


def test_context_rejects_future_or_misaligned_causal_inputs() -> None:
    context = make_context()
    future_bar = CausalBarView(
        timeframe="1h",
        bar_open_at=context.market_as_of,
        bar_close_at=context.market_as_of + timedelta(hours=1),
        market_as_of=context.market_as_of + timedelta(hours=1),
        open=Decimal(100),
        high=Decimal(110),
        low=Decimal(90),
        close=Decimal(105),
        volume=Decimal(1000),
        taker_buy_base=Decimal(400),
        closed=True,
    )
    with pytest.raises(ValueError, match="causal bar"):
        DecisionContext(
            **context_kwargs(context, causal_bar_views={"1h": (future_bar,)}),
        )

    future_snapshot = make_snapshot(
        available_at=context.market_as_of,
        fetched_at=context.market_as_of,
        event_time=context.market_as_of + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="external snapshot event_time"):
        DecisionContext(
            **context_kwargs(
                context,
                external_data={future_snapshot.request_key: future_snapshot},
            ),
        )

    future_window_snapshot = make_snapshot(
        available_at=context.market_as_of,
        fetched_at=context.market_as_of,
        represented_end_at=context.market_as_of + timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="external snapshot window"):
        DecisionContext(
            **context_kwargs(
                context,
                external_data={
                    future_window_snapshot.request_key: future_window_snapshot
                },
            ),
        )

    with pytest.raises(ValueError, match="request_key"):
        DecisionContext(
            **context_kwargs(
                context,
                external_data={
                    "wrong-key": make_snapshot(
                        available_at=context.market_as_of,
                        fetched_at=context.market_as_of,
                    )
                },
            ),
        )

    future_artifact = ModelArtifact(
        binding_id="binding-a",
        lane_id=context.lane_id,
        asset=context.asset,
        decision_timeframe=context.decision_timeframe,
        trigger_timeframe=context.trigger_timeframe,
        market_as_of=context.market_as_of + timedelta(seconds=1),
        artifact_type="boundary",
    )
    with pytest.raises(ValueError, match="upstream artifact market_as_of"):
        ModelRequestContext(
            **context_kwargs(
                context,
                upstream_artifacts={"boundary": future_artifact},
            ),
        )


def test_context_rejects_overlapping_causal_bars() -> None:
    first = CausalBarView(
        timeframe="1h",
        bar_open_at=BASE,
        bar_close_at=BASE + timedelta(hours=1),
        market_as_of=BASE + timedelta(hours=1),
        open=Decimal(100),
        high=Decimal(110),
        low=Decimal(90),
        close=Decimal(105),
        volume=Decimal(1000),
        taker_buy_base=Decimal(400),
        closed=True,
    )
    overlapping = CausalBarView(
        timeframe="1h",
        bar_open_at=BASE + timedelta(minutes=30),
        bar_close_at=BASE + timedelta(hours=1, minutes=30),
        market_as_of=BASE + timedelta(hours=1, minutes=30),
        open=Decimal(100),
        high=Decimal(110),
        low=Decimal(90),
        close=Decimal(105),
        volume=Decimal(1000),
        taker_buy_base=Decimal(400),
        closed=True,
    )
    with pytest.raises(ValueError, match="must not overlap"):
        ModelRequestContext(
            asset="BTCUSDT",
            venue="binance",
            instrument_id="BTC-USDT-PERP",
            lane_id="BTCUSDT:1h",
            binding_id="binding-a",
            market_as_of=overlapping.market_as_of,
            trigger_timeframe="1h",
            decision_timeframe="1h",
            trigger_mode="on_bar_close",
            decision_bar=None,
            decision_bar_closed=True,
            causal_bar_views={"1h": (first, overlapping)},
        )


def test_context_rejects_decision_bar_timeframe_mismatch() -> None:
    wrong_timeframe_bar = CausalBarView(
        timeframe="4h",
        bar_open_at=BASE,
        bar_close_at=BASE + timedelta(hours=4),
        market_as_of=BASE + timedelta(hours=4),
        open=Decimal(100),
        high=Decimal(110),
        low=Decimal(90),
        close=Decimal(105),
        volume=Decimal(1000),
        taker_buy_base=Decimal(400),
        closed=True,
    )
    with pytest.raises(ValueError, match="decision_bar timeframe"):
        ModelRequestContext(
            asset="BTCUSDT",
            venue="binance",
            instrument_id="BTC-USDT-PERP",
            lane_id="BTCUSDT:1h",
            binding_id="binding-a",
            market_as_of=wrong_timeframe_bar.market_as_of,
            trigger_timeframe="1h",
            decision_timeframe="1h",
            trigger_mode="on_bar_close",
            decision_bar=wrong_timeframe_bar,
            decision_bar_closed=True,
        )


def test_context_rejects_out_of_order_bar_sequences() -> None:
    first = CausalBarView(
        timeframe="1h",
        bar_open_at=BASE,
        bar_close_at=BASE + timedelta(minutes=30),
        market_as_of=BASE + timedelta(minutes=30),
        open=Decimal(100),
        high=Decimal(110),
        low=Decimal(90),
        close=Decimal(105),
        volume=Decimal(1000),
        taker_buy_base=Decimal(400),
        closed=True,
    )
    second = CausalBarView(
        timeframe="1h",
        bar_open_at=BASE + timedelta(minutes=30),
        bar_close_at=BASE + timedelta(hours=1),
        market_as_of=BASE + timedelta(hours=1),
        open=Decimal(100),
        high=Decimal(110),
        low=Decimal(90),
        close=Decimal(105),
        volume=Decimal(1000),
        taker_buy_base=Decimal(400),
        closed=True,
    )
    with pytest.raises(ValueError, match="chronologically ordered"):
        ModelRequestContext(
            asset="BTCUSDT",
            venue="binance",
            instrument_id="BTC-USDT-PERP",
            lane_id="BTCUSDT:1h",
            binding_id="binding-a",
            market_as_of=BASE + timedelta(hours=1),
            trigger_timeframe="1h",
            decision_timeframe="1h",
            trigger_mode="on_bar_close",
            decision_bar=second,
            decision_bar_closed=True,
            causal_bar_views={"1h": (second, first)},
        )


def test_context_and_output_timing_boundaries_are_distinct() -> None:
    context = make_context()
    assert not hasattr(context, "decision_ready_at")

    decision = ModelDecision(
        binding_id="binding-a",
        asset="BTCUSDT",
        decision_timeframe="1h",
        trigger_timeframe="1h",
        market_as_of=context.market_as_of,
        signal_time=context.market_as_of,
        direction_hint=1,
        score=0.5,
        conviction=0.8,
    )
    with pytest.raises(ValueError, match="signal_time"):
        ModelDecision(
            binding_id=decision.binding_id,
            asset=decision.asset,
            decision_timeframe=decision.decision_timeframe,
            trigger_timeframe=decision.trigger_timeframe,
            market_as_of=decision.market_as_of,
            signal_time=decision.market_as_of + timedelta(seconds=1),
        )

    result = DecisionPolicyResult(
        lane_id="BTCUSDT:1h",
        effective_lane_revision="revision",
        decision_id="decision",
        policy_version="1",
        market_as_of=context.market_as_of,
        decision_ready_at=context.market_as_of + timedelta(seconds=2),
        decision=decision,
        binding_config_fingerprints={"boundary": "fingerprint"},
    )
    assert result.decision_ready_at > result.market_as_of

    with pytest.raises(ValueError, match="at or after market_as_of"):
        DecisionPolicyResult(
            lane_id="BTCUSDT:1h",
            effective_lane_revision="revision",
            decision_id="decision",
            policy_version="1",
            market_as_of=context.market_as_of,
            decision_ready_at=context.market_as_of - timedelta(seconds=1),
        )


def test_stateful_specs_require_replay_safe_required_data() -> None:
    non_replayable = DataRequirement(
        concept="LIVE_ONLY_SENTIMENT",
        required=False,
        replay_support_required=False,
    )
    with pytest.raises(ValueError, match="replay support"):
        ModelSpec(
            name="stateful",
            version="1",
            stateful=True,
            output_kind="predictive",
            produces_artifact_type="stateful.v1",
            intrinsic_data_requirements=(non_replayable,),
        )

    spec = ModelSpec(
        name="stateful",
        version="1",
        stateful=True,
        output_kind="predictive",
        produces_artifact_type="stateful.v1",
        intrinsic_data_requirements=(
            DataRequirement(
                concept="OPEN_INTEREST",
                required=True,
                replay_support_required=True,
            ),
        ),
        warmup_requirements=WarmupRequirements(bars_by_timeframe={"1h": 200}),
        state_reconstruction=StateReconstructionRequirement(durable_pit_required=True),
    )
    assert spec.warmup_requirements.bars_by_timeframe["1h"] == 200


def test_nested_plugin_visible_contract_data_is_immutable() -> None:
    context = make_context()
    with pytest.raises((TypeError, AttributeError)):
        context.shared_features["trend"]["values"].append(3)  # type: ignore[index]
    with pytest.raises(TypeError):
        context.provenance["input"]["stream_id"] = "2-0"  # type: ignore[index]
    with pytest.raises((TypeError, AttributeError)):
        context.causal_bar_views["1h"].append(make_bar())  # type: ignore[attr-defined]
    with pytest.raises(TypeError):
        context.upstream_artifacts["boundary"].metadata["new"] = "value"  # type: ignore[index]

    with pytest.raises(AttributeError):
        context.shared_features._data = {}  # type: ignore[attr-defined]

    binding = make_binding(
        parameters={"thresholds": {"upper": [1, 2]}},
        dependencies={"source": "other-binding"},
    )
    with pytest.raises((TypeError, AttributeError)):
        binding.parameters["thresholds"]["upper"].append(3)  # type: ignore[index]
    with pytest.raises(TypeError):
        binding.dependencies["source"] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    "field_name",
    ("binding_config_fingerprint", "binding_id", "effective_lane_revision"),
)
def test_resolved_binding_requires_identity_fields(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        make_binding(**{field_name: ""})


def test_resolved_binding_requires_plugin_and_spec_identity_match() -> None:
    with pytest.raises(ValueError, match="plugin_name"):
        make_binding(plugin_name="OtherModel")
    with pytest.raises(ValueError, match="plugin_version"):
        make_binding(plugin_version="2")


def test_model_outcome_allows_analytical_artifact_without_decision() -> None:
    outcome = ModelOutcome(artifact=make_artifact(), proposed_next_state={"count": 1})
    assert outcome.decision is None
    with pytest.raises(TypeError):
        outcome.proposed_next_state["count"] = 2  # type: ignore[index]


def test_model_outcome_rejects_identity_mismatch() -> None:
    artifact = make_artifact()
    mismatched_decision = ModelDecision(
        binding_id=artifact.binding_id,
        asset="ETHUSDT",
        decision_timeframe=artifact.decision_timeframe,
        trigger_timeframe=artifact.trigger_timeframe,
        market_as_of=artifact.market_as_of,
        signal_time=artifact.market_as_of,
    )
    with pytest.raises(ValueError, match="decision asset"):
        ModelOutcome(artifact=artifact, decision=mismatched_decision)


def test_unsupported_mutable_objects_are_rejected_at_contract_boundaries() -> None:
    class MutableObject:
        def __init__(self) -> None:
            self.values = [1]

    with pytest.raises(TypeError, match="unsupported mutable or custom value"):
        ModelOutcome(artifact=make_artifact(), proposed_next_state=MutableObject())

    with pytest.raises(TypeError, match="unsupported mutable or custom value"):
        ModelArtifact(
            binding_id="binding-a",
            lane_id="BTCUSDT:1h",
            asset="BTCUSDT",
            decision_timeframe="1h",
            trigger_timeframe="1h",
            market_as_of=BASE + timedelta(hours=1),
            artifact_type="boundary",
            value=MutableObject(),
        )

    with pytest.raises(TypeError, match="FeatureSnapshot"):
        ModelRequestContext(
            asset="BTCUSDT",
            venue="binance",
            instrument_id="BTC-USDT-PERP",
            lane_id="BTCUSDT:1h",
            binding_id="binding-a",
            market_as_of=BASE + timedelta(hours=1),
            trigger_timeframe="1h",
            decision_timeframe="1h",
            trigger_mode="on_bar_close",
            decision_bar=make_bar(),
            decision_bar_closed=True,
            shared_features={"mutable": MutableObject()},
        )

    frozen_state = freeze_model_state({"values": [1, 2]})
    with pytest.raises((TypeError, AttributeError)):
        frozen_state["values"].append(3)  # type: ignore[index]


def test_progress_contracts_are_independent_data_only_shapes() -> None:
    cursor = InputReadCursor(
        stream_key="stream:ohlcv:ingestion:binance:BTC-USDT-PERP:1h",
        latest_stream_id="10-0",
        latest_market_as_of=BASE + timedelta(hours=1),
    )
    watermark = LaneCommitWatermark(lane_id="BTCUSDT:1h")
    assert cursor.latest_market_as_of is not None
    assert watermark.latest_market_as_of is None
