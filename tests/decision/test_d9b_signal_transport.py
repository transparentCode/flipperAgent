from __future__ import annotations

import asyncio

import pytest

from apps.decision_app.runtime.deadlines import OperationTimeout
from apps.decision_app.transport.publication import (
    SignalPublicationEnvelope,
    signal_idempotency_key,
    signal_payload_fingerprint,
)
from apps.decision_app.transport.signals import ValkeySignalPublisher
from libs.contracts.serialization import valkey_encode
from libs.contracts.signal import TradeSignal


def _envelope() -> SignalPublicationEnvelope:
    signal = TradeSignal(
        asset="BTCUSDT",
        timeframe="1h",
        timestamp=1_700_000_000.0,
        direction=1,
        conviction=0.75,
        price=100.0,
        idempotency_key=signal_idempotency_key("decision-1"),
        model_name="btc-risk",
    )
    return SignalPublicationEnvelope(
        decision_id="decision-1",
        stream_key="signals:BTCUSDT:1h",
        stream_entry_id="1700000000000-0",
        signal=signal,
        payload_fingerprint=signal_payload_fingerprint(signal),
    )


class FakeValkey:
    def __init__(self) -> None:
        self.entries: dict[str, dict[str, str]] = {}
        self.xadd_error: Exception | None = None
        self.xadd_writes_before_error = False
        self.xrange_calls = 0
        self.xrevrange_counts: list[int] = []
        self.xadd_calls = 0
        self.xadd_options: list[tuple[int, bool]] = []

    async def xrange(self, stream: str, minimum: str, maximum: str):
        self.xrange_calls += 1
        fields = self.entries.get(minimum)
        return [] if fields is None else [(minimum, fields)]

    async def xrevrange(self, stream: str, maximum: str, minimum: str, count: int = 1):
        self.xrevrange_counts.append(count)
        if not self.entries:
            return []
        stream_id = max(
            self.entries, key=lambda value: tuple(map(int, value.split("-")))
        )
        return [(stream_id, self.entries[stream_id])]

    async def xadd(
        self,
        stream: str,
        fields: dict[str, str],
        *,
        id: str,
        maxlen: int,
        approximate: bool,
    ):
        self.xadd_calls += 1
        self.xadd_options.append((maxlen, approximate))
        if self.xadd_error is not None:
            if self.xadd_writes_before_error:
                self.entries[id] = dict(fields)
            raise self.xadd_error
        self.entries[id] = dict(fields)
        return id


class _BlockedPrecheckValkey(FakeValkey):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def xrange(self, stream: str, minimum: str, maximum: str):
        self.started.set()
        await asyncio.Event().wait()
        return await super().xrange(stream, minimum, maximum)


class _BlockedPublishValkey(FakeValkey):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def xadd(
        self,
        stream: str,
        fields: dict[str, str],
        *,
        id: str,
        maxlen: int,
        approximate: bool,
    ):
        self.started.set()
        self.xadd_calls += 1
        self.xadd_options.append((maxlen, approximate))
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_explicit_id_publish_and_identical_retry() -> None:
    client = FakeValkey()
    publisher = ValkeySignalPublisher(client)

    first = await publisher.publish(_envelope())
    second = await publisher.publish(_envelope())

    assert first.outcome == "PUBLISHED"
    assert second.outcome == "ALREADY_IDENTICAL"
    assert set(client.entries) == {"1700000000000-0"}


@pytest.mark.asyncio
async def test_different_payload_same_id_is_conflict() -> None:
    client = FakeValkey()
    publisher = ValkeySignalPublisher(client)
    envelope = _envelope()
    client.entries[envelope.stream_entry_id] = valkey_encode(
        envelope.signal.model_copy(update={"price": 101.0})
    )

    result = await publisher.publish(envelope)

    assert result.outcome == "CONFLICT"
    assert "different" in (result.reason or "")


@pytest.mark.asyncio
@pytest.mark.parametrize("writes_before_error", [True, False])
async def test_ambiguous_xadd_is_reconciled_or_failed(
    writes_before_error: bool,
) -> None:
    client = FakeValkey()
    client.xadd_error = RuntimeError("connection lost")
    client.xadd_writes_before_error = writes_before_error
    publisher = ValkeySignalPublisher(client)

    result = await publisher.publish(_envelope())

    assert result.outcome == ("ALREADY_IDENTICAL" if writes_before_error else "FAILED")


@pytest.mark.asyncio
async def test_newer_head_without_exact_id_is_conflict() -> None:
    client = FakeValkey()
    envelope = _envelope()
    client.entries["1700000000001-0"] = valkey_encode(envelope.signal)
    client.xadd_error = RuntimeError("connection lost")
    publisher = ValkeySignalPublisher(client)

    result = await publisher.publish(envelope)

    assert result.outcome == "CONFLICT"
    assert "head advanced" in (result.reason or "")


@pytest.mark.asyncio
async def test_cancellation_is_not_reclassified() -> None:
    client = FakeValkey()
    client.xadd_error = asyncio.CancelledError()
    publisher = ValkeySignalPublisher(client)

    with pytest.raises(asyncio.CancelledError):
        await publisher.publish(_envelope())


@pytest.mark.asyncio
async def test_signal_precheck_timeout_never_reaches_xadd() -> None:
    client = _BlockedPrecheckValkey()
    publisher = ValkeySignalPublisher(client, io_timeout_seconds=0.01)

    with pytest.raises(OperationTimeout, match="signal exact-ID"):
        await publisher.publish(_envelope())
    assert client.entries == {}


@pytest.mark.asyncio
async def test_signal_precheck_cancellation_never_reaches_xadd() -> None:
    client = _BlockedPrecheckValkey()
    publisher = ValkeySignalPublisher(client, io_timeout_seconds=1.0)
    task = asyncio.create_task(publisher.publish(_envelope()))
    await client.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert client.entries == {}


@pytest.mark.asyncio
async def test_signal_publication_timeout_reconciles_with_bounded_attempts() -> None:
    client = _BlockedPublishValkey()
    publisher = ValkeySignalPublisher(
        client,
        stream_maxlen=17,
        stream_approximate=False,
        io_timeout_seconds=0.01,
    )

    result = await publisher.publish(_envelope())

    assert result.outcome == "FAILED"
    assert client.xadd_calls == 1
    assert client.xadd_options == [(17, False)]
    assert client.xrange_calls == 2
    assert client.xrevrange_counts == [1, 1]
