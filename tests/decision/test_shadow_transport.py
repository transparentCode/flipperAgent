from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.decision_app.transport.shadow import (
    ShadowDecisionObservation,
    ShadowPublicationEnvelope,
    ValkeyShadowPublisher,
    shadow_payload_fingerprint,
    shadow_stream_entry_id,
    shadow_stream_key,
)
from libs.contracts.serialization import valkey_encode


class _Broker:
    def __init__(self) -> None:
        self.entries: dict[str, list[tuple[str, dict[str, str]]]] = {}

    async def xrange(self, stream: str, minimum: str, maximum: str):
        return [
            entry
            for entry in self.entries.get(stream, ())
            if entry[0] == minimum == maximum
        ]

    async def xrevrange(self, stream: str, *_args: object, count: int = 1):
        return list(reversed(self.entries.get(stream, ())))[:count]

    async def xadd(
        self, stream: str, fields, *, id: str, maxlen: int, approximate: bool
    ):
        del maxlen, approximate
        if any(existing == id for existing, _ in self.entries.get(stream, ())):
            raise RuntimeError("duplicate explicit ID")
        self.entries.setdefault(stream, []).append((id, dict(fields)))
        return id


def _observation() -> ShadowDecisionObservation:
    cutoff = datetime(2026, 1, 1, tzinfo=UTC)
    return ShadowDecisionObservation(
        lane_id="BTCUSDT:momentum_1h",
        asset="BTCUSDT",
        decision_timeframe="1h",
        trigger_timeframe="1h",
        market_as_of=cutoff,
        decision_ready_at=cutoff,
        decision_id="decision-1",
        policy_status="NO_SIGNAL",
        base_lane_revision="lane-revision",
        decision_execution_revision="execution-revision",
        feature_plan_fingerprint="feature-plan",
        data_plan_fingerprint="data-plan",
        policy_name="passthrough",
        policy_version="1",
    )


def _signal_observation() -> ShadowDecisionObservation:
    observation = _observation().model_copy(
        update={
            "policy_status": "SIGNAL",
            "selected_binding_id": "binding-1",
            "direction_hint": 1,
            "score": 0.75,
            "conviction": 0.8,
        }
    )
    return observation


def _envelope(observation: ShadowDecisionObservation) -> ShadowPublicationEnvelope:
    return ShadowPublicationEnvelope(
        decision_id=observation.decision_id,
        stream_key=shadow_stream_key(observation.lane_id),
        stream_entry_id=shadow_stream_entry_id(observation.market_as_of),
        observation=observation,
        payload_fingerprint=shadow_payload_fingerprint(observation),
    )


@pytest.mark.asyncio
async def test_shadow_publisher_exact_id_is_idempotent_and_non_authoritative() -> None:
    broker = _Broker()
    publisher = ValkeyShadowPublisher(broker)
    envelope = _envelope(_observation())

    first = await publisher.publish(envelope)
    second = await publisher.publish(envelope)

    assert first.outcome == "PUBLISHED"
    assert second.outcome == "ALREADY_IDENTICAL"
    assert len(broker.entries[envelope.stream_key]) == 1
    assert envelope.stream_key.startswith("decision:shadow:")
    assert not envelope.stream_key.startswith("signals:")


@pytest.mark.asyncio
async def test_shadow_publisher_conflicts_on_same_id_with_different_payload() -> None:
    broker = _Broker()
    publisher = ValkeyShadowPublisher(broker)
    original = _observation()
    await publisher.publish(_envelope(original))
    changed = original.model_copy(update={"policy_version": "2"})

    acknowledgement = await publisher.publish(_envelope(changed))

    assert acknowledgement.outcome == "CONFLICT"
    assert len(broker.entries[shadow_stream_key(original.lane_id)]) == 1


@pytest.mark.asyncio
async def test_shadow_publisher_decodes_signal_observation_for_exact_retry() -> None:
    broker = _Broker()
    publisher = ValkeyShadowPublisher(broker)
    envelope = _envelope(_signal_observation())

    first = await publisher.publish(envelope)
    second = await publisher.publish(envelope)

    assert first.outcome == "PUBLISHED"
    assert second.outcome == "ALREADY_IDENTICAL"


def test_shadow_observation_is_frozen_and_has_explicit_market_id() -> None:
    observation = _observation()
    assert shadow_stream_entry_id(observation.market_as_of) == "1767225600000-0"
    assert (
        valkey_encode(observation, inject_trace=False)["schema_version"]
        == "decision.shadow.v1"
    )
    with pytest.raises((AttributeError, TypeError, ValueError)):
        observation.policy_name = "other"  # type: ignore[misc]


@pytest.mark.asyncio
async def test_shadow_exact_retry_under_active_trace_has_no_trace_fields() -> None:
    pytest.importorskip("opentelemetry")
    from opentelemetry import trace
    from opentelemetry.trace import (
        NonRecordingSpan,
        SpanContext,
        TraceFlags,
        TraceState,
    )

    span = NonRecordingSpan(
        SpanContext(
            trace_id=0x1234567890ABCDEF1234567890ABCDEF,
            span_id=0x1234567890ABCDEF,
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
            trace_state=TraceState(),
        )
    )
    broker = _Broker()
    publisher = ValkeyShadowPublisher(broker)
    envelope = _envelope(_observation())

    with trace.use_span(span, end_on_exit=False):
        first = await publisher.publish(envelope)
        second = await publisher.publish(envelope)

    fields = broker.entries[envelope.stream_key][0][1]
    assert first.outcome == "PUBLISHED"
    assert second.outcome == "ALREADY_IDENTICAL"
    assert "_traceparent" not in fields
    assert "_tracestate" not in fields
