from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from valkey.exceptions import ResponseError
from valkey.exceptions import TimeoutError as ValkeyTimeoutError

from libs.common.stream_consumer import (
    BaseStreamConsumer,
    _DEFAULT_PEL_RECLAIM_IDLE_MS,
)


class _TestConsumer(BaseStreamConsumer):
    async def process_message(self, message_id: str, data: dict[str, str]) -> None:
        return None


@pytest.mark.asyncio
async def test_pel_reclaim_uses_idle_threshold() -> None:
    consumer = _TestConsumer(
        stream_key="stream:test",
        group_name="group",
        consumer_name="consumer",
    )

    redis_client = AsyncMock()
    redis_client.xgroup_create = AsyncMock()
    redis_client.xautoclaim = AsyncMock(return_value=("0-0", [], []))
    redis_client.xreadgroup = AsyncMock(side_effect=asyncio.CancelledError())

    await consumer.connect(redis_client)
    await consumer.run()

    assert redis_client.xautoclaim.await_args.kwargs["min_idle_time"] == _DEFAULT_PEL_RECLAIM_IDLE_MS


@pytest.mark.asyncio
async def test_consumer_stops_cleanly_when_stream_group_disappears() -> None:
    consumer = _TestConsumer(
        stream_key="stream:test",
        group_name="group",
        consumer_name="consumer",
    )

    redis_client = AsyncMock()
    redis_client.xgroup_create = AsyncMock()
    redis_client.xautoclaim = AsyncMock(return_value=("0-0", [], []))
    redis_client.xreadgroup = AsyncMock(
        side_effect=ResponseError(
            "NOGROUP No such key 'stream:test' or consumer group 'group' in XREADGROUP with GROUP option"
        )
    )

    await consumer.connect(redis_client)
    await consumer.run()

    assert redis_client.xreadgroup.await_count == 1


@pytest.mark.asyncio
async def test_consumer_retries_timeout_without_erroring() -> None:
    consumer = _TestConsumer(
        stream_key="stream:test",
        group_name="group",
        consumer_name="consumer",
    )

    redis_client = AsyncMock()
    redis_client.xgroup_create = AsyncMock()
    redis_client.xautoclaim = AsyncMock(return_value=("0-0", [], []))
    redis_client.xreadgroup = AsyncMock(
        side_effect=[
            ValkeyTimeoutError("Timeout reading from broker:6379"),
            asyncio.CancelledError(),
        ]
    )

    await consumer.connect(redis_client)
    await consumer.run()

    assert redis_client.xreadgroup.await_count == 2
