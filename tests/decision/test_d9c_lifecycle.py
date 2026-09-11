from __future__ import annotations

import asyncio

import pytest
import valkey.asyncio as valkey
from valkey.connection import Connection

from apps.decision_app.runtime.lifecycle import (
    LifecycleNotificationReader,
    capture_lifecycle_tail,
)
from libs.common.asset_manifest import (
    ASSET_LIFECYCLE_STREAM,
    AssetLifecycleEvent,
    AssetLifecycleEventType,
)
from libs.contracts.serialization import valkey_encode


class _LifecycleClient:
    def __init__(self, records=None, *, tail=None) -> None:
        self.records = records or []
        self.tail = tail
        self.xread_calls: list[tuple[dict[str, str], int, int | None]] = []

    async def xrevrange(self, *_args, **_kwargs):
        return [] if self.tail is None else [(self.tail, {})]

    async def xread(self, streams, *, count, block=None):
        self.xread_calls.append((dict(streams), count, block))
        records, self.records = self.records, []
        return records


class _EncodedXRead(valkey.Valkey):
    def __init__(self, response):
        super().__init__()
        self.response = response
        self.commands = []

    async def execute_command(self, *args, **kwargs):
        del kwargs
        self.commands.append(args)
        return self.response


def _wire_command(command) -> bytes:
    return b"".join(Connection().pack_command(*command))


def _event(symbol: str = "BTCUSDT") -> dict[str, str]:
    event = AssetLifecycleEvent(
        event_id=f"event-{symbol}",
        event_type=AssetLifecycleEventType.ASSET_UPDATED,
        command_type="UPDATE_ASSET",
        symbol=symbol,
        emitted_at=1760000000.0,
        source="ingestion",
        requested_by="ingestion",
    )
    return valkey_encode(event, inject_trace=False)


@pytest.mark.asyncio
async def test_missing_lifecycle_stream_uses_zero_cursor() -> None:
    client = _LifecycleClient()
    assert await capture_lifecycle_tail(client) == "0-0"
    reader = LifecycleNotificationReader(
        stream_client=client,
        cursor="0-0",
        configured_manifest_assets=("BTCUSDT",),
    )
    result = await reader.read_once()
    assert result.cursor == "0-0"
    assert client.xread_calls == [({"asset:lifecycle": "0-0"}, 100, 1000)]


@pytest.mark.asyncio
@pytest.mark.parametrize("block_ms", (0, 17))
async def test_lifecycle_reader_uses_valkey_nonblocking_encoding_for_zero(
    block_ms: int,
) -> None:
    client = _EncodedXRead([])
    reader = LifecycleNotificationReader(
        stream_client=client,
        cursor="0-0",
        configured_manifest_assets=("BTCUSDT",),
        block_ms=block_ms,
    )

    result = await reader.read_once()

    assert result.cursor == "0-0"
    expected_args = (
        ("XREAD", "COUNT", "100", "STREAMS", ASSET_LIFECYCLE_STREAM, "0-0")
        if block_ms == 0
        else (
            "XREAD",
            "BLOCK",
            "17",
            "COUNT",
            "100",
            "STREAMS",
            ASSET_LIFECYCLE_STREAM,
            "0-0",
        )
    )
    wire = _wire_command(client.commands[0])
    assert wire == _wire_command(expected_args)
    assert (b"$5\r\nBLOCK\r\n" in wire) is (block_ms > 0)
    await client.aclose()


@pytest.mark.asyncio
async def test_lifecycle_reader_zero_delay_still_processes_events() -> None:
    client = _EncodedXRead([(ASSET_LIFECYCLE_STREAM, [("4-0", _event("BTCUSDT"))])])
    reader = LifecycleNotificationReader(
        stream_client=client,
        cursor="3-0",
        configured_manifest_assets=("BTCUSDT",),
        block_ms=0,
    )

    result = await reader.read_once()

    assert result.cursor == "4-0"
    assert result.event_ids == ("4-0",)
    assert [event.symbol for event in result.relevant_events] == ["BTCUSDT"]
    assert b"$5\r\nBLOCK\r\n" not in _wire_command(client.commands[0])
    await client.aclose()


@pytest.mark.asyncio
async def test_lifecycle_reader_cancellation_is_propagated() -> None:
    class _CancelledClient:
        async def xread(self, *_args, **_kwargs):
            raise asyncio.CancelledError

    reader = LifecycleNotificationReader(
        stream_client=_CancelledClient(),
        cursor="0-0",
        configured_manifest_assets=("BTCUSDT",),
        block_ms=0,
    )

    with pytest.raises(asyncio.CancelledError):
        await reader.read_once()


@pytest.mark.asyncio
async def test_lifecycle_direct_cursor_advances_and_malformed_requests_rebuild() -> (
    None
):
    client = _LifecycleClient(
        [
            (
                "asset:lifecycle",
                [
                    ("4-0", _event("BTCUSDT")),
                    ("5-0", {"event_type": "bad"}),
                ],
            )
        ],
        tail="3-0",
    )
    assert await capture_lifecycle_tail(client) == "3-0"
    reader = LifecycleNotificationReader(
        stream_client=client,
        cursor="3-0",
        configured_manifest_assets=("BTCUSDT",),
    )
    result = await reader.read_once()
    assert result.cursor == "5-0"
    assert result.event_ids == ("4-0", "5-0")
    assert [event.symbol for event in result.relevant_events] == ["BTCUSDT"]
    assert result.malformed_ids == ("5-0",)
    assert result.rebuild_requested is True
    assert client.xread_calls[0][0] == {"asset:lifecycle": "3-0"}


@pytest.mark.asyncio
async def test_unconfigured_lifecycle_event_is_notification_only() -> None:
    client = _LifecycleClient(
        [
            (
                "asset:lifecycle",
                [("1-0", _event("ETH")), ("2-0", _event("BTC"))],
            )
        ]
    )
    reader = LifecycleNotificationReader(
        stream_client=client,
        cursor="0-0",
        configured_manifest_assets=("BTCUSDT",),
    )
    result = await reader.read_once()
    assert result.cursor == "2-0"
    assert result.relevant_events == ()
    assert result.ignored_symbols == ("BTC", "ETH")
    assert result.rebuild_requested is False
