from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from apps.risk_app.runtime.runner import RiskRuntimeRunner
from libs.common.asset_manifest import AssetLifecycleEvent, AssetLifecycleEventType
from libs.risk.account_state import AccountState
from libs.risk.position_tracker import PositionTracker


class _FakeConsumer:
    async def connect(self, redis_client: Any) -> None:
        return None

    async def start(self) -> None:
        await asyncio.sleep(3600)


@pytest.mark.asyncio
async def test_runtime_runner_spawns_workers_and_fill_listeners() -> None:
    labels: list[str] = []
    spawned: list[tuple[str, Any]] = []
    persistence_calls: list[int] = []
    persistence_started = asyncio.Event()
    workers_started = asyncio.Event()

    async def fake_supervisor(
        label: str, build_consumer, redis_client: Any, restart_delay_seconds: int
    ) -> None:
        labels.append(label)
        consumer = build_consumer()
        spawned.append((label, consumer))
        if len(labels) == 4:
            workers_started.set()
        await asyncio.sleep(3600)

    async def fake_persistence(
        account: AccountState, positions: PositionTracker, interval_seconds: int
    ) -> None:
        persistence_calls.append(interval_seconds)
        persistence_started.set()
        await asyncio.sleep(3600)

    runner = RiskRuntimeRunner(
        asset_map={"BTCUSDT": ["1h", "4h"], "ETHUSDT": ["15m"]},
        redis_client=AsyncMock(),
        risk_engine=object(),
        signal_aggregator=object(),
        account=AccountState(10_000.0),
        positions=PositionTracker(),
        risk_config={"example": True},
        risk_worker_factory=lambda **kwargs: ("risk_worker", kwargs),
        fill_listener_factory=lambda **kwargs: ("fill_listener", kwargs),
        restart_delay_seconds=7,
        persistence_interval_seconds=45,
        enable_lifecycle=False,
        supervise_consumer_fn=fake_supervisor,
        persistence_loop_fn=fake_persistence,
    )

    task = asyncio.create_task(runner.run())
    await asyncio.wait_for(persistence_started.wait(), timeout=1)
    await asyncio.wait_for(workers_started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert persistence_calls == [45]
    assert sorted(labels) == sorted(
        [
            "RiskWorker[BTCUSDT]",
            "FillListener[BTCUSDT]",
            "RiskWorker[ETHUSDT]",
            "FillListener[ETHUSDT]",
        ]
    )
    spawned_by_label = {label: consumer for label, consumer in spawned}
    assert spawned_by_label["RiskWorker[BTCUSDT]"][0] == "risk_worker"
    assert spawned_by_label["FillListener[BTCUSDT]"][0] == "fill_listener"
    assert spawned_by_label["RiskWorker[BTCUSDT]"][1]["timeframes"] == ["1h", "4h"]
    assert spawned_by_label["FillListener[BTCUSDT]"][1]["asset"] == "BTCUSDT"


def test_v2_runtime_components_keep_stream_contracts() -> None:
    from apps.risk_app.runtime.fill_listener import FillListener
    from apps.risk_app.runtime.worker import RiskWorker
    from libs.risk.engine import RiskEngine
    from libs.risk.mtf.aggregator import SignalAggregator

    worker = RiskWorker(
        asset="BTCUSDT",
        timeframes=["1h", "4h"],
        risk_engine=RiskEngine([], object(), object(), object()),
        signal_aggregator=SignalAggregator(),
        account=AccountState(10_000.0),
        positions=PositionTracker(),
        risk_config={},
    )
    listener = FillListener(
        asset="BTCUSDT",
        account=AccountState(10_000.0),
        positions=PositionTracker(),
    )

    assert worker.signal_stream_keys == ["signals:BTCUSDT:1h", "signals:BTCUSDT:4h"]
    assert worker.price_stream_keys == [
        "price_update:BTCUSDT:1h",
        "price_update:BTCUSDT:4h",
    ]
    assert worker.order_stream_key == "orders:BTCUSDT"
    assert listener.stream_key == "fills:BTCUSDT"


@pytest.mark.asyncio
async def test_lifecycle_pause_stops_risk_worker_but_keeps_fill_listener() -> None:
    cancelled: list[str] = []

    async def fake_supervisor(
        label: str, build_consumer, redis_client: Any, restart_delay_seconds: int
    ) -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.append(label)
            raise

    runner = RiskRuntimeRunner(
        asset_map={"BTCUSDT": ["1h", "4h"]},
        redis_client=object(),
        risk_engine=object(),
        signal_aggregator=object(),
        account=AccountState(10_000.0),
        positions=PositionTracker(),
        risk_config={},
        risk_worker_factory=lambda **kwargs: ("risk_worker", kwargs),
        fill_listener_factory=lambda **kwargs: ("fill_listener", kwargs),
        restart_delay_seconds=5,
        supervise_consumer_fn=fake_supervisor,
    )

    await runner._ensure_risk_worker_started("BTCUSDT", ["1h", "4h"])
    await runner._ensure_fill_listener_started("BTCUSDT")
    await asyncio.sleep(0)

    await runner._apply_lifecycle_event(
        AssetLifecycleEvent(
            event_id="evt-1",
            event_type=AssetLifecycleEventType.ASSET_PAUSED,
            command_type="PAUSE_ASSET",
            symbol="BTCUSDT",
            publish_timeframes=["1h", "4h"],
            timeframes=["1h", "4h"],
            enabled=False,
            desired_state="PAUSED",
            requested_by="test",
            emitted_at=1.0,
        ),
    )

    assert "RiskWorker[BTCUSDT]" in cancelled
    assert "BTCUSDT" not in runner._risk_worker_tasks
    assert "BTCUSDT" in runner._fill_listener_tasks

    await runner._stop_fill_listener("BTCUSDT")


@pytest.mark.asyncio
async def test_lifecycle_live_restores_configured_worker_timeframes() -> None:
    started: list[tuple[str, list[str]]] = []

    async def fake_supervisor(
        label: str, build_consumer, redis_client: Any, restart_delay_seconds: int
    ) -> None:
        consumer = build_consumer()
        started.append(
            (label, consumer[1]["timeframes"] if consumer[0] == "risk_worker" else [])
        )
        await asyncio.sleep(3600)

    runner = RiskRuntimeRunner(
        asset_map={"BTCUSDT": ["1h"]},
        redis_client=object(),
        risk_engine=object(),
        signal_aggregator=object(),
        account=AccountState(10_000.0),
        positions=PositionTracker(),
        risk_config={},
        risk_worker_factory=lambda **kwargs: ("risk_worker", kwargs),
        fill_listener_factory=lambda **kwargs: ("fill_listener", kwargs),
        restart_delay_seconds=5,
        supervise_consumer_fn=fake_supervisor,
    )

    await runner._ensure_risk_worker_started("BTCUSDT", ["1h"])
    await asyncio.sleep(0)
    await runner._apply_lifecycle_event(
        AssetLifecycleEvent(
            event_id="evt-2",
            event_type=AssetLifecycleEventType.ASSET_RESUMED,
            command_type="RESUME_ASSET",
            symbol="BTCUSDT",
            publish_timeframes=["1h", "4h"],
            timeframes=["1h", "4h"],
            enabled=True,
            desired_state="LIVE",
            requested_by="test",
            emitted_at=2.0,
        ),
    )
    await asyncio.sleep(0)

    assert runner._worker_timeframes["BTCUSDT"] == ["1h"]
    assert ("RiskWorker[BTCUSDT]", ["1h"]) in started

    await runner._stop_risk_worker("BTCUSDT")
    await runner._stop_fill_listener("BTCUSDT")


@pytest.mark.asyncio
async def test_lifecycle_removing_stops_fill_listener_only_without_open_exposure() -> (
    None
):
    cancelled: list[str] = []

    async def fake_supervisor(
        label: str, build_consumer, redis_client: Any, restart_delay_seconds: int
    ) -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.append(label)
            raise

    runner = RiskRuntimeRunner(
        asset_map={},
        redis_client=object(),
        risk_engine=object(),
        signal_aggregator=object(),
        account=AccountState(10_000.0),
        positions=PositionTracker(),
        risk_config={},
        risk_worker_factory=lambda **kwargs: ("risk_worker", kwargs),
        fill_listener_factory=lambda **kwargs: ("fill_listener", kwargs),
        restart_delay_seconds=5,
        supervise_consumer_fn=fake_supervisor,
    )

    await runner._ensure_fill_listener_started("BTCUSDT")
    await asyncio.sleep(0)
    await runner._apply_lifecycle_event(
        AssetLifecycleEvent(
            event_id="evt-3",
            event_type=AssetLifecycleEventType.ASSET_REMOVE_REQUESTED,
            command_type="REMOVE_ASSET",
            symbol="BTCUSDT",
            publish_timeframes=["1h"],
            timeframes=["1h"],
            enabled=False,
            desired_state="REMOVING",
            requested_by="test",
            emitted_at=3.0,
        ),
    )

    assert "FillListener[BTCUSDT]" in cancelled
    assert "BTCUSDT" not in runner._fill_listener_tasks
