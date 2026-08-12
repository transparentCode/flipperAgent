from __future__ import annotations

import pytest

from apps.risk_app.runtime.runner import RiskRuntimeRunner
from apps.signal_app.catalog.static import StaticSignalPairCatalog
from apps.signal_app.runtime.runner import SignalRuntimeRunner
from apps.strategy_app.runtime.runner import StrategyRuntimeRunner
from libs.common.asset_manifest import (
    AssetLifecycleEvent,
    AssetLifecycleEventType,
    AssetManifest,
    AssetManifestStore,
)
from libs.risk.account_state import AccountState
from libs.risk.position_tracker import PositionTracker


class _ManifestRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def hset(self, key: str, mapping: dict[str, str]) -> int:
        self.hashes[key] = dict(mapping)
        return len(mapping)

    async def delete(self, key: str) -> int:
        self.hashes.pop(key, None)
        return 1


def _manifest(source: str) -> AssetManifest:
    return AssetManifest(
        symbol="BTCUSDT",
        source=source,
        timeframes=["1m", "1h"],
        publish_timeframes=["1h"],
        updated_at=1.0,
    )


def _event(source: str) -> AssetLifecycleEvent:
    return AssetLifecycleEvent(
        event_id=f"event-{source}",
        event_type=AssetLifecycleEventType.ASSET_RESUMED,
        command_type="RESUME_ASSET",
        symbol="BTCUSDT",
        desired_state="LIVE",
        enabled=True,
        source=source,
        emitted_at=2.0,
    )


async def _seed_manifest(redis: _ManifestRedis, source: str) -> None:
    await AssetManifestStore(redis).sync_manifest(_manifest(source))


async def _authority_results() -> dict[str, tuple[bool, bool]]:
    results: dict[str, tuple[bool, bool]] = {}

    signal_redis = _ManifestRedis()
    await _seed_manifest(signal_redis, "ingestion")
    signal_runner = SignalRuntimeRunner(
        catalog=StaticSignalPairCatalog([]),
        initial_pairs=[],
    )
    await signal_runner.connect(signal_redis)
    results["signal"] = (
        await signal_runner._is_authoritative_event(_event("ingestion_app")),
        await signal_runner._is_authoritative_event(_event("ingestion")),
    )
    await signal_runner.stop()

    strategy_redis = _ManifestRedis()
    await _seed_manifest(strategy_redis, "ingestion")
    strategy_runner = StrategyRuntimeRunner(
        [],
    )
    await strategy_runner.connect(strategy_redis)
    results["strategy"] = (
        await strategy_runner._is_authoritative_event(_event("ingestion_app")),
        await strategy_runner._is_authoritative_event(_event("ingestion")),
    )
    await strategy_runner.stop()

    risk_redis = _ManifestRedis()
    await _seed_manifest(risk_redis, "ingestion")
    risk_runner = RiskRuntimeRunner(
        asset_map={"BTCUSDT": ["1h"]},
        redis_client=risk_redis,
        risk_engine=object(),
        signal_aggregator=object(),
        account=AccountState(10_000.0),
        positions=PositionTracker(),
        risk_config={},
        risk_worker_factory=lambda **kwargs: kwargs,
        fill_listener_factory=lambda **kwargs: kwargs,
        restart_delay_seconds=1,
    )
    results["risk"] = (
        await risk_runner._is_authoritative_event(_event("ingestion_app")),
        await risk_runner._is_authoritative_event(_event("ingestion")),
    )
    return results


@pytest.mark.asyncio
async def test_downstream_runtimes_reject_stale_lifecycle_sources() -> None:
    results = await _authority_results()

    assert results == {
        "signal": (False, True),
        "strategy": (False, True),
        "risk": (False, True),
    }
