from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from apps.decision_app.runtime.deadlines import OperationTimeout
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
        self.xrange_calls = 0
        self.xrevrange_counts: list[int] = []
        self.xadd_calls = 0
        self.xadd_options: list[tuple[int, bool]] = []

    async def xrange(self, stream: str, minimum: str, maximum: str):
        self.xrange_calls += 1
        return [
            entry
            for entry in self.entries.get(stream, ())
            if entry[0] == minimum == maximum
        ]

    async def xrevrange(self, stream: str, *_args: object, count: int = 1):
        self.xrevrange_counts.append(count)
        return list(reversed(self.entries.get(stream, ())))[:count]

    async def xadd(
        self, stream: str, fields, *, id: str, maxlen: int, approximate: bool
    ):
        self.xadd_calls += 1
        self.xadd_options.append((maxlen, approximate))
        del maxlen, approximate
        if any(existing == id for existing, _ in self.entries.get(stream, ())):
            raise RuntimeError("duplicate explicit ID")
        self.entries.setdefault(stream, []).append((id, dict(fields)))
        return id


class _BlockedPrecheckBroker(_Broker):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def xrange(self, stream: str, minimum: str, maximum: str):
        self.started.set()
        await asyncio.Event().wait()
        return await super().xrange(stream, minimum, maximum)


class _BlockedPublishBroker(_Broker):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def xadd(
        self, stream: str, fields, *, id: str, maxlen: int, approximate: bool
    ):
        self.started.set()
        self.xadd_calls += 1
        self.xadd_options.append((maxlen, approximate))
        await asyncio.Event().wait()


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


@pytest.mark.asyncio
async def test_shadow_precheck_timeout_never_reaches_xadd() -> None:
    broker = _BlockedPrecheckBroker()
    publisher = ValkeyShadowPublisher(broker, io_timeout_seconds=0.01)

    with pytest.raises(OperationTimeout, match="shadow exact-ID"):
        await publisher.publish(_envelope(_observation()))
    assert broker.entries == {}


@pytest.mark.asyncio
async def test_shadow_precheck_cancellation_never_reaches_xadd() -> None:
    broker = _BlockedPrecheckBroker()
    publisher = ValkeyShadowPublisher(broker, io_timeout_seconds=1.0)
    task = asyncio.create_task(publisher.publish(_envelope(_observation())))
    await broker.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert broker.entries == {}


@pytest.mark.asyncio
async def test_shadow_publication_timeout_reconciles_with_bounded_attempts() -> None:
    broker = _BlockedPublishBroker()
    publisher = ValkeyShadowPublisher(
        broker,
        stream_maxlen=17,
        stream_approximate=False,
        io_timeout_seconds=0.01,
    )

    result = await publisher.publish(_envelope(_observation()))

    assert result.outcome == "FAILED"
    assert broker.xadd_calls == 1
    assert broker.xadd_options == [(17, False)]
    assert broker.xrange_calls == 2
    assert broker.xrevrange_counts == [1, 1]
