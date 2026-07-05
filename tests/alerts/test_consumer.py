from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from apps.alert_app.runtime.consumer import AlertEventConsumer
from apps.alert_app.settings import AlertAppSettings
from libs.contracts.ingestion import IngestionEventType, IngestionRuntimeEvent


class _FakeManifestStore:
    async def list_assets(self):
        return []


class _FakeRedis:
    def __init__(self) -> None:
        self.keys = [
            "execution:failures:BTCUSDT",
            "execution:failures:ETHUSDT",
            "other:key",
        ]

    async def scan_iter(self, match: str):
        prefix = match.rstrip("*")
        for key in self.keys:
            if key.startswith(prefix):
                yield key


class _FakeIncidentService:
    pass


class _SingleBatchRedis:
    def __init__(self, payload: dict[str, str]) -> None:
        self.payload = payload
        self.calls = 0
        self.acks: list[tuple[str, str, str]] = []

    async def xreadgroup(self, *args, **kwargs):
        if self.calls == 0:
            self.calls += 1
            return [("stream:events:ingestion", [("1-0", self.payload)])]
        raise asyncio.CancelledError

    async def xack(self, stream: str, group: str, message_id: str) -> None:
        self.acks.append((stream, group, message_id))


@pytest.mark.asyncio
async def test_refresh_execution_failure_streams_discovers_live_streams(monkeypatch) -> None:
    ensured: list[str] = []

    async def _fake_ensure(redis_client, stream, consumer_group, start_id="$"):
        ensured.append(stream)

    monkeypatch.setattr(
        "apps.alert_app.runtime.consumer.ensure_consumer_group",
        _fake_ensure,
    )

    consumer = AlertEventConsumer(
        redis_client=_FakeRedis(),
        settings=AlertAppSettings(),
        incident_service=_FakeIncidentService(),
    )
    consumer.manifest_store = _FakeManifestStore()

    streams = await consumer._refresh_execution_failure_streams()

    assert streams == [
        "execution:failures:BTCUSDT",
        "execution:failures:ETHUSDT",
    ]
    assert ensured == streams


@pytest.mark.asyncio
async def test_watch_ingestion_events_skips_success_only_runtime_events(monkeypatch) -> None:
    event = IngestionRuntimeEvent(
        event_id="evt_gap_fill_completed",
        event_type=IngestionEventType.GAP_FILL_COMPLETED,
        symbol="BINANCE",
        timeframe="1m",
        severity="info",
        detail={"asset_count": 6},
        emitted_at=123.0,
    )
    redis_client = _SingleBatchRedis(event.model_dump(mode="json"))
    incident_service = AsyncMock()

    consumer = AlertEventConsumer(
        redis_client=redis_client,
        settings=AlertAppSettings(),
        incident_service=incident_service,
    )

    with pytest.raises(asyncio.CancelledError):
        await consumer.watch_ingestion_events()

    incident_service.record_event.assert_not_called()
    assert redis_client.acks == [
        (
            consumer.settings.ingestion_events_stream,
            consumer.settings.consumer_group,
            "1-0",
        )
    ]
