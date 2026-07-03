from __future__ import annotations

import pytest

from apps.alert_app.runtime.consumer import AlertEventConsumer
from apps.alert_app.settings import AlertAppSettings


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
