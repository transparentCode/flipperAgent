from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import pytest

from apps.decision_app.runtime.deadlines import OperationTimeout
from apps.decision_app.transport.price_relay import (
    PriceRelayPublisher,
    price_relay_entry_id,
)
from apps.decision_app.transport.shadow import ValkeyShadowPublisher
from apps.decision_app.transport.signals import ValkeySignalPublisher
from tests.decision.test_d9b_signal_transport import _envelope as signal_envelope
from tests.decision.test_d9d_price_relay import _bar as price_bar
from tests.decision.test_d9d_price_relay import _plan as price_plan
from tests.decision.test_shadow_transport import (
    _envelope as shadow_envelope,
)
from tests.decision.test_shadow_transport import (
    _observation as shadow_observation,
)


class _MatrixClient:
    def __init__(self) -> None:
        self.entries: dict[str, dict[str, dict[str, str]]] = {}
        self.xadd_calls = 0
        self.xadd_ids: list[str] = []
        self.xrange_calls = 0
        self.xrevrange_calls = 0
        self.commit_before_timeout = False
        self.fail_exact_at: int | None = None
        self.fail_head_at: int | None = None

    async def xrange(self, stream: str, minimum: str, maximum: str):
        del maximum
        self.xrange_calls += 1
        if self.xrange_calls == self.fail_exact_at:
            raise OperationTimeout("matrix exact reconciliation", 0.01)
        fields = self.entries.get(stream, {}).get(minimum)
        return [] if fields is None else [(minimum, fields)]

    async def xrevrange(
        self,
        stream: str,
        maximum: str,
        minimum: str,
        *,
        count: int = 1,
    ):
        del maximum, minimum
        self.xrevrange_calls += 1
        if self.xrevrange_calls == self.fail_head_at:
            raise OperationTimeout("matrix stream-head reconciliation", 0.01)
        values = self.entries.get(stream, {})
        if not values:
            return []
        entry_id = max(values, key=lambda value: tuple(map(int, value.split("-"))))
        return [(entry_id, values[entry_id])][:count]

    async def xadd(
        self,
        stream: str,
        fields: dict[str, str],
        *,
        id: str,
        **_kwargs: Any,
    ):
        self.xadd_calls += 1
        self.xadd_ids.append(id)
        if self.commit_before_timeout:
            self.entries.setdefault(stream, {})[id] = dict(fields)
        raise TimeoutError("XADD response was lost")


@dataclass(frozen=True)
class _PublisherCase:
    name: str
    build: Callable[[_MatrixClient], tuple[Callable[[], Awaitable[Any]], str, str]]


def _build_signal(client: _MatrixClient):
    envelope = signal_envelope()
    publisher = ValkeySignalPublisher(client, io_timeout_seconds=0.1)
    return (
        lambda: publisher.publish(envelope),
        envelope.stream_key,
        envelope.stream_entry_id,
    )


def _build_shadow(client: _MatrixClient):
    observation = shadow_observation()
    envelope = shadow_envelope(observation)
    publisher = ValkeyShadowPublisher(client, io_timeout_seconds=0.1)
    return (
        lambda: publisher.publish(envelope),
        envelope.stream_key,
        envelope.stream_entry_id,
    )


def _build_price(client: _MatrixClient):
    plan = price_plan()
    bar = price_bar(0)
    publisher = PriceRelayPublisher(client, io_timeout_seconds=0.1)
    return (
        lambda: publisher.publish(plan, bar),
        plan.stream_key,
        price_relay_entry_id(bar),
    )


PUBLISHER_CASES = (
    _PublisherCase("signal", _build_signal),
    _PublisherCase("shadow", _build_shadow),
    _PublisherCase("price", _build_price),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", PUBLISHER_CASES, ids=lambda case: case.name)
async def test_committed_xadd_timeout_is_identical_without_a_new_id(
    case: _PublisherCase,
) -> None:
    client = _MatrixClient()
    client.commit_before_timeout = True
    publish, stream_key, required_id = case.build(client)

    acknowledgement = await publish()

    assert acknowledgement.outcome == "ALREADY_IDENTICAL"
    assert client.xadd_calls == 1
    assert client.xadd_ids == [required_id]
    assert set(client.entries[stream_key]) == {required_id}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", PUBLISHER_CASES, ids=lambda case: case.name)
async def test_xadd_timeout_with_unavailable_exact_read_is_typed_failure(
    case: _PublisherCase,
) -> None:
    client = _MatrixClient()
    client.fail_exact_at = 2
    publish, _stream_key, _required_id = case.build(client)

    with pytest.raises(OperationTimeout, match="exact reconciliation"):
        await publish()

    assert client.xadd_calls == 1
    assert client.xrange_calls == 2
    assert client.xrevrange_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", PUBLISHER_CASES, ids=lambda case: case.name)
async def test_absent_exact_read_with_unavailable_head_is_typed_failure(
    case: _PublisherCase,
) -> None:
    client = _MatrixClient()
    client.fail_head_at = 2
    publish, _stream_key, _required_id = case.build(client)

    with pytest.raises(OperationTimeout, match="stream-head reconciliation"):
        await publish()

    assert client.xadd_calls == 1
    assert client.xrange_calls == 2
    assert client.xrevrange_calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("case", PUBLISHER_CASES, ids=lambda case: case.name)
async def test_both_reconciliation_sources_fail_closed_on_first_read(
    case: _PublisherCase,
) -> None:
    client = _MatrixClient()
    client.fail_exact_at = 2
    client.fail_head_at = 2
    publish, _stream_key, _required_id = case.build(client)

    with pytest.raises(OperationTimeout, match="exact reconciliation"):
        await publish()

    assert client.xadd_calls == 1
    assert client.xrange_calls == 2
    assert client.xrevrange_calls == 1
