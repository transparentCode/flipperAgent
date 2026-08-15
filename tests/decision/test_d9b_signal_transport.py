from __future__ import annotations

import asyncio

import pytest

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

    async def xrange(self, stream: str, minimum: str, maximum: str):
        fields = self.entries.get(minimum)
        return [] if fields is None else [(minimum, fields)]

    async def xrevrange(self, stream: str, maximum: str, minimum: str, count: int = 1):
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
        if self.xadd_error is not None:
            if self.xadd_writes_before_error:
                self.entries[id] = dict(fields)
            raise self.xadd_error
        self.entries[id] = dict(fields)
        return id


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
