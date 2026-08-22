from __future__ import annotations

import pytest

from apps.decision_app.runtime.lifecycle import (
    LifecycleNotificationReader,
    capture_lifecycle_tail,
)
from libs.common.asset_manifest import AssetLifecycleEvent, AssetLifecycleEventType
from libs.contracts.serialization import valkey_encode


class _LifecycleClient:
    def __init__(self, records=None, *, tail=None) -> None:
        self.records = records or []
        self.tail = tail
        self.xread_calls: list[tuple[dict[str, str], int, int]] = []

    async def xrevrange(self, *_args, **_kwargs):
        return [] if self.tail is None else [(self.tail, {})]

    async def xread(self, streams, *, count, block):
        self.xread_calls.append((dict(streams), count, block))
        records, self.records = self.records, []
        return records


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
