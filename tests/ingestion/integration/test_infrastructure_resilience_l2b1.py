"""Real Valkey outage and durable outbox resilience certification for ingestion."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
import valkey.asyncio as valkey
import yaml

from apps.ingestion_app.bootstrap import create_application
from apps.ingestion_app.domain.candle import CanonicalCandle
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.providers.binance_native import (
    BinanceNativeHistoricalProvider,
)
from apps.ingestion_app.providers.ccxt import CCXTHistoricalProvider
from apps.ingestion_app.publication.publisher import OutboxPublisher
from apps.ingestion_app.runtime.websocket import BinanceWebSocketManager
from apps.ingestion_app.services.candle_ingestion import CandleIngestionService
from apps.ingestion_app.settings import load_ingestion_settings
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.repository import (
    CandleCommitStatus,
    CandleRepository,
)
from libs.common.config import ConfigManager
from libs.common.connections import init_db_pools
from libs.common.db.pool_manager import DBPoolManager
from tests.ingestion._asgi import request

if os.getenv("INGESTION_RUN_L2B1_CERTIFICATION") != "1":
    pytest.skip(
        "set INGESTION_RUN_L2B1_CERTIFICATION=1 to run L2B1 certification",
        allow_module_level=True,
    )


LANE_COUNT = 500
WAVE_COUNT = 2
BASE_BOUNDARY = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
CAPACITY_DEADLINE_SECONDS = 60.0
BROKER_CONTAINER = "flipperagent-broker-1"
DATABASE_CONTAINER = "flipperagent-db-1"


def _emit(label: str, value: object) -> None:
    print(f"L2B1 {label}: {value}", flush=True)


def _dsn() -> str:
    return os.getenv(
        "POSTGRES_URI",
        "postgresql://flipper:flipperpass@localhost:5432/flipper_db",
    )


def _valkey_uri() -> str:
    return os.getenv("VALKEY_URI", "redis://localhost:6380/0")


def _docker_snapshot(container: str) -> dict[str, object]:
    completed = subprocess.run(
        ["docker", "inspect", container],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)[0]
    state = payload["State"]
    health = state.get("Health") or {}
    return {
        "status": state.get("Status"),
        "health": health.get("Status"),
        "restart_count": int(payload.get("RestartCount", 0)),
        "memory_limit": payload.get("HostConfig", {}).get("Memory"),
        "nano_cpus": payload.get("HostConfig", {}).get("NanoCpus"),
    }


def _compose(repository_root: Path, *arguments: str) -> None:
    subprocess.run(
        ["docker", "compose", *arguments],
        cwd=repository_root,
        check=True,
    )


async def _compose_async(repository_root: Path, *arguments: str) -> None:
    await asyncio.to_thread(_compose, repository_root, *arguments)


async def _wait_broker_healthy() -> None:
    async with asyncio.timeout(60):
        while True:
            snapshot = _docker_snapshot(BROKER_CONTAINER)
            if snapshot["status"] == "running" and snapshot["health"] == "healthy":
                return
            await asyncio.sleep(0.5)


async def _wait_broker_stopped() -> None:
    async with asyncio.timeout(30):
        while True:
            snapshot = _docker_snapshot(BROKER_CONTAINER)
            if snapshot["status"] in {"exited", "created"}:
                return
            await asyncio.sleep(0.25)


async def _connect_valkey() -> Any:
    client = valkey.Valkey.from_url(_valkey_uri(), decode_responses=True)
    try:
        await client.ping()
    except BaseException:
        await client.aclose()
        raise
    return client


async def _close_valkey(client: Any | None) -> None:
    if client is None:
        return
    try:
        await client.aclose()
    except Exception as exc:  # noqa: BLE001
        _emit("valkey_close_warning", repr(exc))


async def _valkey_snapshot(client: Any) -> dict[str, object]:
    server = await client.info("server")
    memory = await client.info("memory")
    maxmemory = await client.config_get("maxmemory")
    policy = await client.config_get("maxmemory-policy")
    return {
        "version": server.get("redis_version"),
        "maxmemory": maxmemory.get("maxmemory"),
        "maxmemory_policy": policy.get("maxmemory-policy"),
        "used_memory": int(memory.get("used_memory", 0)),
        "dbsize": int(await client.dbsize()),
    }


def _prepare_disabled_config(repository_root: Path, config_root: Path) -> None:
    shutil_source = repository_root / "configs" / "ingestion"
    shutil.copytree(shutil_source, config_root / "ingestion")
    for asset_path in sorted((config_root / "ingestion" / "assets").glob("*.yaml")):
        asset = yaml.safe_load(asset_path.read_text(encoding="utf-8"))
        asset = copy.deepcopy(asset)
        asset["enabled"] = False
        asset_path.write_text(
            yaml.safe_dump(asset, sort_keys=False),
            encoding="utf-8",
        )


def _instrument_id(prefix: str, index: int) -> str:
    return f"{prefix}_S{index:04d}-USDT-PERP"


def _candle_for_instrument(
    instrument_id: str,
    *,
    open_time: datetime,
    ordinal: int,
) -> CanonicalCandle:
    lane = MarketLane(
        venue="binance",
        instrument_id=instrument_id,
        timeframe="1m",
    )
    base = Decimal(100) + Decimal(ordinal)
    return CanonicalCandle(
        lane=lane,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open=base,
        high=base + Decimal(2),
        low=base - Decimal(1),
        close=base + Decimal(1),
        volume=Decimal(10) + Decimal(ordinal % 100),
        taker_buy_base=Decimal(4) + Decimal(ordinal % 50),
        source_type="provider",
        source_provider="binance_native",
        source_timeframe=None,
    )


def _wave(prefix: str, wave: int) -> tuple[CanonicalCandle, ...]:
    open_time = BASE_BOUNDARY + timedelta(minutes=wave)
    return tuple(
        _candle_for_instrument(
            _instrument_id(prefix, index),
            open_time=open_time,
            ordinal=wave * LANE_COUNT + index,
        )
        for index in range(LANE_COUNT)
    )


async def _commit_wave(
    ingestion: CandleIngestionService,
    candles: tuple[CanonicalCandle, ...],
) -> tuple[CandleCommitStatus, ...]:
    tasks = [
        asyncio.create_task(
            ingestion.commit_candle(candle),
            name=f"l2b1-commit-{candle.lane.instrument_id}",
        )
        for candle in candles
    ]
    try:
        async with asyncio.timeout(CAPACITY_DEADLINE_SECONDS):
            return tuple(await asyncio.gather(*tasks))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _prefix_counts(pool: asyncpg.Pool, prefix: str) -> dict[str, int]:
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT
                (SELECT COUNT(*)
                 FROM ingestion.candles
                 WHERE position($1 in instrument_id) = 1) AS candles,
                (SELECT COUNT(*)
                 FROM ingestion.outbox
                 WHERE position($1 in payload->>'instrument_id') = 1) AS outbox,
                (SELECT COUNT(*)
                 FROM ingestion.outbox
                 WHERE position($1 in payload->>'instrument_id') = 1
                   AND published_at IS NULL) AS pending
            """,
            prefix,
        )
    return {key: int(row[key]) for key in ("candles", "outbox", "pending")}


async def _global_pending_count(pool: asyncpg.Pool) -> int:
    async with pool.acquire() as connection:
        return int(
            await connection.fetchval(
                "SELECT COUNT(*) FROM ingestion.outbox WHERE published_at IS NULL"
            )
        )


async def _published_event_ids(pool: asyncpg.Pool, prefix: str) -> set[str]:
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT event_id
            FROM ingestion.outbox
            WHERE position($1 in payload->>'instrument_id') = 1
              AND published_at IS NOT NULL
            ORDER BY occurred_at ASC, event_id ASC
            """,
            prefix,
        )
    return {str(row["event_id"]) for row in rows}


async def _wait_pending_zero(
    pool: asyncpg.Pool,
    prefix: str,
    publisher_task: asyncio.Task[Any],
) -> float:
    started = time.perf_counter()
    async with asyncio.timeout(CAPACITY_DEADLINE_SECONDS):
        while True:
            if publisher_task.done():
                if publisher_task.cancelled():
                    raise RuntimeError("publisher task was cancelled during catch-up")
                exception = publisher_task.exception()
                raise RuntimeError(
                    "publisher task exited during catch-up"
                ) from exception
            if (await _prefix_counts(pool, prefix))["pending"] == 0:
                return time.perf_counter() - started
            await asyncio.sleep(0.2)


def _stream_key(instrument_id: str) -> str:
    return f"stream:ohlcv:ingestion:binance:{instrument_id}:1m"


def _wave_stream_keys(prefix: str) -> tuple[str, ...]:
    return tuple(
        _stream_key(_instrument_id(prefix, index)) for index in range(LANE_COUNT)
    )


async def _stream_event_ids(client: Any, keys: tuple[str, ...]) -> set[str]:
    event_ids: set[str] = set()
    for key in keys:
        for _, fields in await client.xrange(key, "-", "+"):
            event_id = fields.get("event_id")
            if event_id is not None:
                event_ids.add(str(event_id))
    return event_ids


async def _assert_stream_reconciliation(
    client: Any,
    durable_event_ids: set[str],
    keys: tuple[str, ...],
) -> dict[str, int]:
    stream_event_ids = await _stream_event_ids(client, keys)
    lengths = [int(await client.xlen(key)) for key in keys]
    assert durable_event_ids == stream_event_ids
    assert len(stream_event_ids) == len(durable_event_ids)
    return {
        "stream_count": sum(length > 0 for length in lengths),
        "entry_count": sum(lengths),
    }


async def _cleanup_database(pool: asyncpg.Pool, prefix: str) -> dict[str, int]:
    async with pool.acquire() as connection, connection.transaction():
        outbox_status = await connection.execute(
            """
            DELETE FROM ingestion.outbox
            WHERE position($1 in payload->>'instrument_id') = 1
            """,
            prefix,
        )
        candle_status = await connection.execute(
            """
            DELETE FROM ingestion.candles
            WHERE position($1 in instrument_id) = 1
            """,
            prefix,
        )
    counts = await _prefix_counts(pool, prefix)
    return {
        "outbox_deleted": int(outbox_status.rsplit(" ", 1)[-1]),
        "candles_deleted": int(candle_status.rsplit(" ", 1)[-1]),
        "candles_remaining": counts["candles"],
        "outbox_remaining": counts["outbox"],
    }


class _FailOnceMarkRepository:
    def __init__(self, repository: CandleRepository) -> None:
        self._repository = repository
        self._failed = False

    async def fetch_pending_outbox(self, *, limit: int):
        return await self._repository.fetch_pending_outbox(limit=limit)

    async def mark_outbox_published(self, *, event_id, published_at):
        if not self._failed:
            self._failed = True
            raise RuntimeError("injected DB mark failure after real XADD")
        return await self._repository.mark_outbox_published(
            event_id=event_id,
            published_at=published_at,
        )


@pytest.mark.asyncio
async def test_l2b1_real_valkey_resilience(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Certify Valkey outage, restart, backlog and publisher crash semantics."""
    repository_root = Path(__file__).parents[3]
    prefix = f"l2b1_{uuid4().hex}"
    config_root = tmp_path / "configs"
    _prepare_disabled_config(repository_root, config_root)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POSTGRES_URI", _dsn())
    monkeypatch.setenv("VALKEY_URI", _valkey_uri())

    async def _forbid_provider_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Binance REST network work is forbidden in L2B1")

    def _forbid_websocket_network(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Binance WebSocket work is forbidden in L2B1")

    monkeypatch.setattr(
        BinanceNativeHistoricalProvider,
        "fetch_closed_candles",
        _forbid_provider_network,
    )
    monkeypatch.setattr(
        CCXTHistoricalProvider,
        "fetch_closed_candles",
        _forbid_provider_network,
    )
    monkeypatch.setattr(
        BinanceWebSocketManager,
        "stream_closed_candles",
        _forbid_websocket_network,
    )

    pre_broker = _docker_snapshot(BROKER_CONTAINER)
    pre_database = _docker_snapshot(DATABASE_CONTAINER)
    _emit("pre_broker", pre_broker)
    _emit("pre_database", pre_database)
    if pre_broker["status"] not in {"exited", "created"}:
        pytest.fail("ENVIRONMENT_PRECONDITION_CHANGED: broker is not stopped")
    if not (
        pre_database["status"] == "running" and pre_database["health"] == "healthy"
    ):
        pytest.fail("ENVIRONMENT_PRECONDITION_CHANGED: Timescale is not healthy")

    broker_started = False
    observer: Any | None = None
    manager3: ConfigManager | None = None
    pool3: asyncpg.Pool | None = None
    original_valkey_config: dict[str, object] | None = None
    maxmemory_was_changed = False
    exact_stream_keys: set[str] = set(_wave_stream_keys(prefix))
    publisher_tasks: list[asyncio.Task[Any]] = []

    try:
        # Stage A: startup and canonical readiness while Valkey is stopped.
        ConfigManager.reset_singleton()
        manager1 = ConfigManager(config_dir=str(config_root))
        app1 = create_application(config_manager=manager1)
        async with app1.router.lifespan_context(app1):
            controller1 = app1.state.runtime_controller
            publisher_task1 = app1.state.publisher_task
            publisher_tasks.append(publisher_task1)
            assert controller1.is_started is True
            assert controller1.enabled_asset_count == 0
            assert (await request(app1, "GET", "/health/live")).status_code == 200
            assert (await request(app1, "GET", "/health/ready")).status_code == 200
            assert publisher_task1.done() is False

            pool1 = DBPoolManager.get_writer_pool()
            assert await _global_pending_count(pool1) == 0
            repository1 = CandleRepository(pool1)
            ingestion1 = CandleIngestionService(repository1)

            inserted = 0
            for wave in range(WAVE_COUNT):
                statuses = await _commit_wave(ingestion1, _wave(prefix, wave))
                assert statuses.count(CandleCommitStatus.INSERTED) == LANE_COUNT
                inserted += len(statuses)
            counts = await _prefix_counts(pool1, prefix)
            assert counts == {
                "candles": inserted,
                "outbox": inserted,
                "pending": inserted,
            }
            assert (await request(app1, "GET", "/health/ready")).status_code == 200
            assert publisher_task1.done() is False
            _emit("broker_down_commits", counts)

        assert publisher_task1.done() is True

        # Stage C: the first application is gone, but durable rows remain.
        probe = await asyncpg.create_pool(_dsn(), min_size=1, max_size=2)
        try:
            after_shutdown = await _prefix_counts(probe, prefix)
            assert after_shutdown == {
                "candles": 1_000,
                "outbox": 1_000,
                "pending": 1_000,
            }
            _emit("after_first_shutdown", after_shutdown)
        finally:
            await probe.close()

        # Stage D: restore the broker and let a fresh application drain the backlog.
        await _compose_async(repository_root, "start", "broker")
        broker_started = True
        await _wait_broker_healthy()
        observer = await _connect_valkey()
        original_valkey_config = await _valkey_snapshot(observer)
        _emit("valkey_original", original_valkey_config)
        assert original_valkey_config["maxmemory_policy"] == "noeviction"

        ConfigManager.reset_singleton()
        manager2 = ConfigManager(config_dir=str(config_root))
        app2 = create_application(config_manager=manager2)
        async with app2.router.lifespan_context(app2):
            controller2 = app2.state.runtime_controller
            publisher_task2 = app2.state.publisher_task
            publisher_tasks.append(publisher_task2)
            assert controller2.is_started is True
            assert controller2.enabled_asset_count == 0
            assert (await request(app2, "GET", "/health/ready")).status_code == 200
            pool2 = DBPoolManager.get_writer_pool()
            drain_seconds = await _wait_pending_zero(
                pool2,
                prefix,
                publisher_task2,
            )
            durable_ids = await _published_event_ids(pool2, prefix)
            stream_evidence = await _assert_stream_reconciliation(
                observer,
                durable_ids,
                tuple(sorted(exact_stream_keys)),
            )
            assert stream_evidence == {
                "stream_count": LANE_COUNT,
                "entry_count": 1_000,
            }
            stream_lengths = await asyncio.gather(
                *(observer.xlen(key) for key in exact_stream_keys)
            )
            assert all(int(length) == WAVE_COUNT for length in stream_lengths)
            assert publisher_task2.done() is False
            _emit(
                "fresh_app_backlog_drain",
                {
                    "seconds": round(drain_seconds, 3),
                    **stream_evidence,
                    "event_ids": len(durable_ids),
                },
            )

            # Stage E: lose the broker while this publisher task is connected.
            await _close_valkey(observer)
            observer = None
            await _compose_async(repository_root, "stop", "broker")
            broker_started = False
            await _wait_broker_stopped()
            stage_e_statuses = await _commit_wave(
                CandleIngestionService(CandleRepository(pool2)),
                _wave(prefix, WAVE_COUNT),
            )
            assert stage_e_statuses.count(CandleCommitStatus.INSERTED) == LANE_COUNT
            outage_counts = await _prefix_counts(pool2, prefix)
            assert outage_counts == {
                "candles": 1_500,
                "outbox": 1_500,
                "pending": 500,
            }
            assert (await request(app2, "GET", "/health/ready")).status_code == 200
            assert publisher_task2.done() is False
            _emit("connected_publisher_outage", outage_counts)

            # Stage F: the same connection-loop task drains after broker return.
            await _compose_async(repository_root, "start", "broker")
            broker_started = True
            await _wait_broker_healthy()
            observer = await _connect_valkey()
            all_after_restart = await _wait_pending_zero(
                pool2,
                prefix,
                publisher_task2,
            )
            all_ids = await _published_event_ids(pool2, prefix)
            stage_e_ids = all_ids - durable_ids
            assert len(stage_e_ids) == LANE_COUNT
            stream_after_restart = await _stream_event_ids(
                observer,
                tuple(sorted(exact_stream_keys)),
            )
            assert stage_e_ids <= stream_after_restart
            assert app2.state.publisher_task is publisher_task2
            assert publisher_task2.done() is False
            _emit(
                "same_process_recovery",
                {
                    "seconds": round(all_after_restart, 3),
                    "new_event_ids": len(stage_e_ids),
                    "publisher_task_same": app2.state.publisher_task is publisher_task2,
                },
            )

            # Stage G: published stream deletion is an explicit replay audit.
            loss_keys = tuple(sorted(exact_stream_keys))[:2]
            await observer.delete(*loss_keys)
            await asyncio.sleep(2.2)
            loss_exists = await asyncio.gather(
                *(observer.exists(key) for key in loss_keys)
            )
            assert all(int(exists) == 0 for exists in loss_exists)
            automatic_replay = "ABSENT"
            _emit(
                "published_stream_loss_audit",
                {
                    "keys_deleted": len(loss_keys),
                    "AUTOMATIC_PUBLISHED_OUTBOX_REPLAY": automatic_replay,
                },
            )

        assert publisher_task2.done() is True

        # Stages H/I use the real repository and publisher without an app task
        # racing the injected failure or broker limit.
        ConfigManager.reset_singleton()
        manager3 = ConfigManager(config_dir=str(config_root))
        settings3 = load_ingestion_settings(manager3)
        await init_db_pools(manager3)
        pool3 = DBPoolManager.get_writer_pool()
        await apply_ingestion_schema(pool3)
        repository3 = CandleRepository(pool3)
        ingestion3 = CandleIngestionService(repository3)
        normal_publisher = OutboxPublisher(
            repository=repository3,
            valkey_client=observer,
            publication=settings3.publication,
        )

        crash_instrument = f"{prefix}_CRASH-USDT-PERP"
        crash_key = _stream_key(crash_instrument)
        exact_stream_keys.add(crash_key)
        crash_status = await _commit_wave(
            ingestion3,
            (
                _candle_for_instrument(
                    crash_instrument,
                    open_time=BASE_BOUNDARY,
                    ordinal=10_000,
                ),
            ),
        )
        assert crash_status == (CandleCommitStatus.INSERTED,)
        crash_event = (await repository3.fetch_pending_outbox(limit=10))[0]
        flaky_repository = _FailOnceMarkRepository(repository3)
        failing_publisher = OutboxPublisher(
            repository=flaky_repository,
            valkey_client=observer,
            publication=settings3.publication,
        )
        with pytest.raises(RuntimeError, match="injected DB mark failure"):
            await failing_publisher.publish_once()
        assert (await _prefix_counts(pool3, prefix))["pending"] == 1
        crash_entries = await observer.xrange(crash_key, "-", "+")
        assert len(crash_entries) == 1
        assert crash_entries[0][1]["event_id"] == str(crash_event.event_id)

        assert await normal_publisher.publish_once() == 1
        assert (await _prefix_counts(pool3, prefix))["pending"] == 0
        crash_entries = await observer.xrange(crash_key, "-", "+")
        assert len(crash_entries) == 2
        assert {fields["event_id"] for _, fields in crash_entries} == {
            str(crash_event.event_id)
        }
        _emit(
            "crash_window",
            {
                "xadd_entries": len(crash_entries),
                "same_event_id": True,
                "pending_after_retry": 0,
            },
        )

        oom_instrument = f"{prefix}_OOM-USDT-PERP"
        oom_key = _stream_key(oom_instrument)
        exact_stream_keys.add(oom_key)
        oom_status = await _commit_wave(
            ingestion3,
            (
                _candle_for_instrument(
                    oom_instrument,
                    open_time=BASE_BOUNDARY,
                    ordinal=20_000,
                ),
            ),
        )
        assert oom_status == (CandleCommitStatus.INSERTED,)
        assert original_valkey_config is not None
        assert original_valkey_config["maxmemory_policy"] == "noeviction"
        await observer.config_set("maxmemory", "1")
        maxmemory_was_changed = True
        try:
            with pytest.raises(Exception) as oom_error:
                await normal_publisher.publish_once()
            assert (
                "maxmemory" in str(oom_error.value).lower()
                or "oom" in str(oom_error.value).lower()
            )
            assert (await _prefix_counts(pool3, prefix))["pending"] == 1
        finally:
            await observer.config_set(
                "maxmemory",
                str(original_valkey_config["maxmemory"]),
            )
            await observer.config_set(
                "maxmemory-policy",
                str(original_valkey_config["maxmemory_policy"]),
            )
            maxmemory_was_changed = False
        assert await normal_publisher.publish_once() == 1
        assert (await _prefix_counts(pool3, prefix))["pending"] == 0
        oom_entries = await observer.xrange(oom_key, "-", "+")
        assert len(oom_entries) == 1
        _emit(
            "noeviction",
            {
                "error": str(oom_error.value),
                "pending_before_restore_retry": 1,
                "pending_after_restore_retry": 0,
                "entries_after_restore_retry": len(oom_entries),
            },
        )
    finally:
        if pool3 is not None:
            try:
                await DBPoolManager.close_pools()
            except Exception as exc:  # noqa: BLE001
                _emit("db_pool_close_warning", repr(exc))
        if manager3 is not None:
            manager3.shutdown()

        if original_valkey_config is not None:
            current_broker = _docker_snapshot(BROKER_CONTAINER)
            if current_broker["status"] not in {"running", "restarting"}:
                await _compose_async(repository_root, "start", "broker")
                broker_started = True
                await _wait_broker_healthy()
            cleanup_client = observer
            if cleanup_client is None:
                cleanup_client = await _connect_valkey()
            try:
                if maxmemory_was_changed:
                    await cleanup_client.config_set(
                        "maxmemory",
                        str(original_valkey_config["maxmemory"]),
                    )
                await cleanup_client.config_set(
                    "maxmemory-policy",
                    str(original_valkey_config["maxmemory_policy"]),
                )
                if exact_stream_keys:
                    await cleanup_client.delete(*sorted(exact_stream_keys))
                remaining_keys = [
                    key for key in exact_stream_keys if await cleanup_client.exists(key)
                ]
                assert remaining_keys == []
            finally:
                await _close_valkey(cleanup_client)

        cleanup_pool = await asyncpg.create_pool(_dsn(), min_size=1, max_size=2)
        try:
            cleanup_result = await _cleanup_database(cleanup_pool, prefix)
            assert cleanup_result["candles_remaining"] == 0
            assert cleanup_result["outbox_remaining"] == 0
            _emit("cleanup", cleanup_result)
        finally:
            await cleanup_pool.close()

        if broker_started:
            await _compose_async(repository_root, "stop", "broker")
            broker_started = False
        final_broker = _docker_snapshot(BROKER_CONTAINER)
        final_database = _docker_snapshot(DATABASE_CONTAINER)
        assert final_broker["status"] in {"exited", "created"}
        assert final_database["status"] == "running"
        assert final_database["health"] == "healthy"
        assert not [
            task
            for task in asyncio.all_tasks()
            if not task.done()
            and task.get_name()
            in {"ingestion-outbox-publisher", "ingestion-supervisor"}
        ]
        for task in publisher_tasks:
            assert task.done() is True
        ConfigManager.reset_singleton()
        _emit(
            "final_environment",
            {
                "broker": final_broker,
                "database": final_database,
                "publisher_tasks_closed": len(publisher_tasks),
            },
        )
