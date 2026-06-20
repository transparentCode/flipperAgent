from __future__ import annotations

import pytest

from apps.signal_app.models import SignalPair, SignalPairState
from apps.signal_app.observability.runtime_state import (
    SignalRuntimeStateStore,
    runtime_status_key,
)


class _MemoryRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}

    async def hset(self, key: str, mapping: dict[str, str]) -> int:
        self.hashes[key] = dict(mapping)
        return len(mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def delete(self, key: str) -> int:
        self.hashes.pop(key, None)
        return 1


@pytest.mark.asyncio
async def test_runtime_state_store_separates_projected_trigger_lanes() -> None:
    redis = _MemoryRedis()
    store = SignalRuntimeStateStore(redis)
    direct_pair = SignalPair(asset="BTCUSDT", timeframe="4h")
    projected_pair = SignalPair(
        asset="BTCUSDT",
        timeframe="4h",
        trigger_timeframe="1m",
        trigger_mode="on_base_bar_close",
        base_timeframe="1m",
    )

    await store.update(direct_pair, state=SignalPairState.LIVE, detail={"lane": "direct"})
    await store.update(
        projected_pair,
        state=SignalPairState.DEGRADED,
        detail={"lane": "projected"},
    )

    assert runtime_status_key("BTCUSDT", "4h") in redis.hashes
    assert runtime_status_key("BTCUSDT", "4h", "1m") in redis.hashes
    assert await store.read(direct_pair) is not None
    assert (await store.read(direct_pair)).detail["lane"] == "direct"
    assert await store.read(projected_pair) is not None
    assert (await store.read(projected_pair)).detail["lane"] == "projected"
