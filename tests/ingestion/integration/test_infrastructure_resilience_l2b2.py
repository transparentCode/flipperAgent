"""Real Timescale outage and fail-closed runtime certification for ingestion."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import subprocess
import time
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
import yaml

from apps.ingestion_app.api.app import create_app
from apps.ingestion_app.bootstrap import create_application
from apps.ingestion_app.domain.candle import (
    CandleObservation,
    CanonicalCandle,
)
from apps.ingestion_app.domain.instrument import MarketLane
from apps.ingestion_app.runtime.controller import RuntimeController
from apps.ingestion_app.runtime.supervisor import RuntimeState, RuntimeSupervisor
from apps.ingestion_app.services.candle_ingestion import (
    CandleIngestionService,
    canonicalize_observation,
)
from apps.ingestion_app.services.htf_aggregation import HTFAggregationService
from apps.ingestion_app.services.recovery import RecoveryEngine
from apps.ingestion_app.settings import load_ingestion_settings
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from apps.ingestion_app.storage.repository import CandleRepository
from libs.common.config import ConfigManager
from libs.common.connections import init_db_pools
from libs.common.db.pool_manager import DBPoolManager
from tests.ingestion._asgi import request

if os.getenv("INGESTION_RUN_L2B2_CERTIFICATION") != "1":
    pytest.skip(
        "set INGESTION_RUN_L2B2_CERTIFICATION=1 to run L2B2 certification",
        allow_module_level=True,
    )


DATABASE_CONTAINER = "flipperagent-db-1"
BROKER_CONTAINER = "flipperagent-broker-1"
BASE_BOUNDARY = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
FAILURE_TIMEOUT_SECONDS = 45.0
RECOVERY_TIMEOUT_SECONDS = 30.0
LANE_TIMEFRAME = "1m"
PROVIDER_ID = "binance_native"
PROVIDER_SYMBOL = "L2B2-TEST-SYMBOL"


def _emit(label: str, value: object) -> None:
    print(f"L2B2 {label}: {value}", flush=True)


def _dsn() -> str:
    return os.getenv(
        "POSTGRES_URI",
        "postgresql://flipper:flipperpass@localhost:5432/flipper_db",
    )


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


async def _wait_database_healthy() -> None:
    async with asyncio.timeout(60):
        while True:
            snapshot = _docker_snapshot(DATABASE_CONTAINER)
            if snapshot["status"] == "running" and snapshot["health"] == "healthy":
                return
            await asyncio.sleep(0.5)


async def _wait_database_stopped() -> None:
    async with asyncio.timeout(30):
        while True:
            snapshot = _docker_snapshot(DATABASE_CONTAINER)
            if snapshot["status"] in {"exited", "created"}:
                return
            await asyncio.sleep(0.25)


def _prepare_runtime_config(
    *,
    repository_root: Path,
    config_root: Path,
    instrument_id: str,
    enabled: bool,
) -> None:
    shutil.copytree(
        repository_root / "configs" / "ingestion",
        config_root / "ingestion",
    )
    # The production configuration is now six-asset.  L2B2 uses a controlled
    # single-lane provider, so disable the unrelated production lanes in this
    # temporary fixture before enabling its unique BTC replacement.
    _set_all_assets_enabled(config_root, False)
    asset_path = config_root / "ingestion" / "assets" / "BTC.yaml"
    asset = copy.deepcopy(yaml.safe_load(asset_path.read_text(encoding="utf-8")))
    instrument = copy.deepcopy(asset["instruments"].pop("BTC-USDT-PERP"))
    instrument["historical_providers"] = [PROVIDER_ID]
    instrument["provider_symbols"] = {PROVIDER_ID: PROVIDER_SYMBOL}
    instrument["timeframes"] = [LANE_TIMEFRAME]
    asset["enabled"] = enabled
    asset["instruments"] = {instrument_id: instrument}
    asset_path.write_text(
        yaml.safe_dump(asset, sort_keys=False),
        encoding="utf-8",
    )


def _set_all_assets_enabled(config_root: Path, enabled: bool) -> None:
    for asset_path in sorted((config_root / "ingestion" / "assets").glob("*.yaml")):
        asset = copy.deepcopy(yaml.safe_load(asset_path.read_text(encoding="utf-8")))
        asset["enabled"] = enabled
        asset_path.write_text(
            yaml.safe_dump(asset, sort_keys=False),
            encoding="utf-8",
        )


class _ControlledLiveProvider:
    """Event-driven live boundary; no Binance SDK or network is used."""

    provider_id = PROVIDER_ID

    def __init__(self) -> None:
        self._observations: asyncio.Queue[CandleObservation] = asyncio.Queue()
        self._stream_event = asyncio.Event()
        self.stream_anchors: list[datetime] = []
        self.closed_stream_count = 0

    def stream_closed_candles(
        self,
        subscriptions: Mapping[MarketLane, str],
        *,
        base_timeframe: str,
        timeframe_duration: timedelta,
        alignment_origin: datetime,
        connection_anchor: datetime,
    ) -> AsyncIterator[CandleObservation]:
        assert len(subscriptions) == 1
        assert base_timeframe == LANE_TIMEFRAME
        assert timeframe_duration == timedelta(minutes=1)
        assert alignment_origin.tzinfo is not None
        self.stream_anchors.append(connection_anchor)
        self._stream_event.set()
        return self._stream()

    async def _stream(self) -> AsyncIterator[CandleObservation]:
        try:
            while True:
                yield await self._observations.get()
        finally:
            self.closed_stream_count += 1

    async def wait_for_stream_count(self, count: int) -> None:
        async with asyncio.timeout(RECOVERY_TIMEOUT_SECONDS):
            while len(self.stream_anchors) < count:
                self._stream_event.clear()
                if len(self.stream_anchors) >= count:
                    return
                await self._stream_event.wait()

    async def release(self, observation: CandleObservation) -> None:
        await self._observations.put(observation)


class _ControlledHistoricalProvider:
    """Historical boundary returning only the expected outage-catch-up candle."""

    provider_id = PROVIDER_ID

    def __init__(
        self,
        *,
        lane: MarketLane,
        expected_since: datetime,
        expected_until: datetime,
        observation: CandleObservation,
    ) -> None:
        self.lane = lane
        self.expected_since = expected_since
        self.expected_until = expected_until
        self.observation = observation
        self.requests: list[dict[str, object]] = []

    async def fetch_closed_candles(
        self,
        *,
        lane: MarketLane,
        provider_symbol: str,
        timeframe_duration: timedelta,
        since: datetime,
        until: datetime,
        limit: int,
    ) -> tuple[CandleObservation, ...]:
        self.requests.append(
            {
                "lane": lane,
                "provider_symbol": provider_symbol,
                "timeframe_duration": timeframe_duration,
                "since": since,
                "until": until,
                "limit": limit,
            }
        )
        if (
            lane != self.lane
            or since != self.expected_since
            or until != self.expected_until
        ):
            raise AssertionError(
                f"unexpected historical request: {lane} [{since}, {until})"
            )
        return (self.observation,)


async def _no_wait(_: float) -> None:
    """Skip the configured REST grace in deterministic provider tests."""


def _observation(
    lane: MarketLane,
    *,
    open_time: datetime,
    transport: str,
    received_at: datetime,
) -> CandleObservation:
    base = Decimal(100)
    return CandleObservation(
        lane=lane,
        provider_id=PROVIDER_ID,
        provider_symbol=PROVIDER_SYMBOL,
        transport=transport,
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open=base,
        high=base + Decimal(2),
        low=base - Decimal(1),
        close=base + Decimal(1),
        volume=Decimal(10),
        taker_buy_base=Decimal(4),
        received_at=received_at,
        provider_close_time=open_time + timedelta(minutes=1),
    )


def _canonical_baseline(lane: MarketLane) -> CanonicalCandle:
    return canonicalize_observation(
        _observation(
            lane,
            open_time=BASE_BOUNDARY,
            transport="rest",
            received_at=BASE_BOUNDARY + timedelta(minutes=1),
        )
    )


def _utc_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _build_runtime(
    *,
    settings: Any,
    pool: asyncpg.Pool,
    now_fn: Callable[[], datetime],
    live_provider: _ControlledLiveProvider,
    historical_provider: _ControlledHistoricalProvider,
) -> tuple[
    CandleRepository,
    CandleIngestionService,
    HTFAggregationService,
    RecoveryEngine,
    RuntimeController,
]:
    repository = CandleRepository(pool)
    ingestion_service = CandleIngestionService(repository)
    htf_service = HTFAggregationService(
        repository=repository,
        ingestion_service=ingestion_service,
    )
    recovery_engine = RecoveryEngine(
        providers={PROVIDER_ID: historical_provider},
        repository=repository,
        ingestion_service=ingestion_service,
        htf_service=htf_service,
        max_concurrency=settings.recovery.max_concurrency,
        page_limit=settings.recovery.page_limit,
        max_attempts_per_provider=settings.recovery.max_attempts_per_provider,
        retry_backoff_seconds=settings.recovery.retry_backoff_seconds,
        rest_finalization_grace_seconds=(
            settings.recovery.rest_finalization_grace_seconds
        ),
        now_fn=now_fn,
        settlement_sleep_fn=_no_wait,
    )

    def supervisor_factory(candidate_settings: Any) -> RuntimeSupervisor:
        return RuntimeSupervisor(
            settings=candidate_settings,
            live_provider=live_provider,
            repository=repository,
            ingestion_service=ingestion_service,
            htf_service=htf_service,
            recovery_engine=recovery_engine,
            now_fn=now_fn,
            reconnect_sleep_fn=_no_wait,
        )

    controller = RuntimeController(
        settings=settings,
        supervisor_factory=supervisor_factory,
    )
    return (
        repository,
        ingestion_service,
        htf_service,
        recovery_engine,
        controller,
    )


async def _query_identity(pool: asyncpg.Pool, instrument_id: str) -> dict[str, Any]:
    async with pool.acquire() as connection:
        candle_rows = await connection.fetch(
            """
            SELECT open_time, close_time
            FROM ingestion.candles
            WHERE instrument_id = $1
            ORDER BY open_time
            """,
            instrument_id,
        )
        outbox_rows = await connection.fetch(
            """
            SELECT
                payload->>'open_time' AS open_time,
                payload->>'close_time' AS close_time,
                published_at
            FROM ingestion.outbox
            WHERE payload->>'instrument_id' = $1
            ORDER BY payload->>'open_time'
            """,
            instrument_id,
        )
    return {
        "candles": [(row["open_time"], row["close_time"]) for row in candle_rows],
        "outbox": [
            (row["open_time"], row["close_time"], row["published_at"])
            for row in outbox_rows
        ],
    }


async def _identity_counts(pool: asyncpg.Pool, instrument_id: str) -> dict[str, int]:
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT
                (SELECT COUNT(*) FROM ingestion.candles
                 WHERE instrument_id = $1) AS candles,
                (SELECT COUNT(*) FROM ingestion.outbox
                 WHERE payload->>'instrument_id' = $1) AS outbox,
                (SELECT COUNT(*) FROM ingestion.outbox
                 WHERE payload->>'instrument_id' = $1
                   AND published_at IS NULL) AS pending
            """,
            instrument_id,
        )
    return {name: int(row[name]) for name in ("candles", "outbox", "pending")}


async def _wait_for(
    predicate: Any,
    *,
    timeout: float = RECOVERY_TIMEOUT_SECONDS,
) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.05)


async def _database_metadata(
    pool: asyncpg.Pool,
    config_manager: ConfigManager,
) -> dict[str, object]:
    async with pool.acquire() as connection:
        version = await connection.fetchval("SELECT version()")
        timescale_version = await connection.fetchval(
            "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'"
        )
    return {
        "postgres_version": version,
        "timescale_version": timescale_version,
        "pool_min_size": config_manager.get("postgres.pool.min_size", 2),
        "pool_max_size": config_manager.get("postgres.pool.max_size", 10),
    }


async def _cleanup_identity(instrument_id: str) -> dict[str, int]:
    cleanup_pool = await asyncpg.create_pool(_dsn(), min_size=1, max_size=2)
    try:
        async with cleanup_pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "DELETE FROM ingestion.outbox WHERE payload->>'instrument_id' = $1",
                instrument_id,
            )
            await connection.execute(
                "DELETE FROM ingestion.candles WHERE instrument_id = $1",
                instrument_id,
            )
        counts = await _identity_counts(cleanup_pool, instrument_id)
        return counts
    finally:
        await cleanup_pool.close()


async def _close_controller(controller: RuntimeController | None) -> None:
    if controller is not None and controller.is_started:
        await controller.close()


@pytest.mark.asyncio
async def test_l2b2_timescale_outage_fail_closed_reconnect_and_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = Path(__file__).parents[3]
    monkeypatch.chdir(tmp_path)
    db_before = _docker_snapshot(DATABASE_CONTAINER)
    broker_before = _docker_snapshot(BROKER_CONTAINER)
    if db_before["status"] != "running" or db_before["health"] != "healthy":
        pytest.fail(f"ENVIRONMENT_PRECONDITION_CHANGED: database={db_before}")
    if broker_before["status"] not in {"exited", "created"}:
        pytest.fail(f"ENVIRONMENT_PRECONDITION_CHANGED: broker={broker_before}")

    prefix = f"l2b2_{uuid4().hex}"
    instrument_id = f"{prefix}_S0000-USDT-PERP"
    lane = MarketLane("binance", instrument_id, LANE_TIMEFRAME)
    b0 = BASE_BOUNDARY
    b1 = b0 + timedelta(minutes=1)
    b2 = b1 + timedelta(minutes=1)
    b3 = b2 + timedelta(minutes=1)
    clock = [b1]

    config_root = tmp_path / "configs"
    _prepare_runtime_config(
        repository_root=repository_root,
        config_root=config_root,
        instrument_id=instrument_id,
        enabled=True,
    )

    managers: list[ConfigManager] = []
    controllers: list[RuntimeController] = []
    db_stopped = False
    manager: ConfigManager | None = None
    pool: asyncpg.Pool | None = None
    try:
        ConfigManager.reset_singleton()
        manager = ConfigManager(config_dir=str(config_root))
        managers.append(manager)
        settings = load_ingestion_settings(manager)
        await init_db_pools(manager)
        pool = DBPoolManager.get_writer_pool()
        await apply_ingestion_schema(pool)
        pool_identity = id(pool)
        _emit("environment", {"db": db_before, "broker": broker_before})
        _emit("database", await _database_metadata(pool, manager))

        live_provider = _ControlledLiveProvider()
        historical_provider = _ControlledHistoricalProvider(
            lane=lane,
            expected_since=b1,
            expected_until=b2,
            observation=_observation(
                lane,
                open_time=b1,
                transport="rest",
                received_at=b2,
            ),
        )
        repository, ingestion, _, _, controller = _build_runtime(
            settings=settings,
            pool=pool,
            now_fn=lambda: clock[0],
            live_provider=live_provider,
            historical_provider=historical_provider,
        )
        controllers.append(controller)
        app = create_app(runtime_controller=controller)

        baseline = _canonical_baseline(lane)
        baseline_status = await ingestion.commit_candle(baseline)
        assert baseline_status.value == "inserted"
        assert await _identity_counts(pool, instrument_id) == {
            "candles": 1,
            "outbox": 1,
            "pending": 1,
        }
        _emit("baseline_commit", "INSERTED B0->B1")

        await controller.start()
        await live_provider.wait_for_stream_count(1)
        assert live_provider.stream_anchors == [b1]
        await live_provider.release(
            _observation(
                lane,
                open_time=b0,
                transport="websocket",
                received_at=b1,
            )
        )
        await _wait_for(lambda: controller.snapshot().state is RuntimeState.LIVE)
        assert (await request(app, "GET", "/health/live")).status_code == 200
        assert (await request(app, "GET", "/health/ready")).status_code == 200
        assert not historical_provider.requests
        _emit("healthy_runtime", {"anchor": b1, "state": "live", "history": 0})

        failed_task = controller._supervisor_task  # certification task audit
        assert failed_task is not None

        await _compose_async(repository_root, "stop", "db")
        db_stopped = True
        await _wait_database_stopped()
        clock[0] = b2
        await live_provider.release(
            _observation(
                lane,
                open_time=b1,
                transport="websocket",
                received_at=b2,
            )
        )
        await _wait_for(lambda: controller.snapshot().state is RuntimeState.ERROR)
        try:
            await failed_task
        except Exception as exc:  # noqa: BLE001
            runtime_failure = exc
        else:  # pragma: no cover - the outage must fail the task
            pytest.fail("database outage did not fail the supervisor task")
        error_snapshot = controller.snapshot()
        assert error_snapshot.state is RuntimeState.ERROR
        assert error_snapshot.last_error
        assert (await request(app, "GET", "/health/live")).status_code == 200
        assert (await request(app, "GET", "/health/ready")).status_code == 503
        assert (await request(app, "POST", "/runtime/resume")).status_code == 409
        assert controller._supervisor_task is failed_task
        _emit(
            "db_outage_fail_closed",
            {
                "error": error_snapshot.last_error,
                "exception_type": type(runtime_failure).__name__,
                "health_live": 200,
                "health_ready": 503,
                "resume": 409,
                "AUTOMATIC_DB_RUNTIME_RECOVERY": "ABSENT",
            },
        )

        await _compose_async(repository_root, "start", "db")
        db_stopped = False
        await _wait_database_healthy()
        await asyncio.sleep(0)
        assert controller.snapshot().state is RuntimeState.ERROR
        assert (await request(app, "GET", "/health/ready")).status_code == 503
        assert id(DBPoolManager.get_writer_pool()) == pool_identity

        probe = await asyncpg.create_pool(_dsn(), min_size=1, max_size=2)
        try:
            outage_state = await _query_identity(probe, instrument_id)
        finally:
            await probe.close()
        assert len(outage_state["candles"]) == 1
        assert len(outage_state["outbox"]) == 1
        assert outage_state["candles"] == [(b0, b1)]
        assert outage_state["outbox"][0][:2] == (_utc_text(b0), _utc_text(b1))
        _emit(
            "failed_transaction_atomicity",
            {
                "candles": len(outage_state["candles"]),
                "outbox": len(outage_state["outbox"]),
            },
        )

        reconnect_response = await request(app, "POST", "/runtime/reconnect")
        assert reconnect_response.status_code == 200
        assert id(repository.pool) == pool_identity
        await live_provider.wait_for_stream_count(2)
        assert live_provider.stream_anchors[-1] == b2
        assert len(historical_provider.requests) == 1
        recovery_request = historical_provider.requests[0]
        assert recovery_request["since"] == b1
        assert recovery_request["until"] == b2
        assert recovery_request["lane"] == lane
        await _wait_for(lambda: controller.snapshot().state is RuntimeState.STARTING)
        assert (await request(app, "GET", "/health/ready")).status_code == 200
        _emit(
            "same_process_reconnect",
            {
                "status": reconnect_response.status_code,
                "anchor": live_provider.stream_anchors[-1],
                "recovery_since": recovery_request["since"],
                "recovery_until": recovery_request["until"],
                "reason": "runtime_catchup",
            },
        )

        clock[0] = b3
        await live_provider.release(
            _observation(
                lane,
                open_time=b2,
                transport="websocket",
                received_at=b3,
            )
        )
        await _wait_for(lambda: controller.snapshot().state is RuntimeState.LIVE)
        assert (await request(app, "GET", "/health/ready")).status_code == 200
        final_state = await _query_identity(pool, instrument_id)
        assert len(final_state["candles"]) == 3
        assert len(final_state["outbox"]) == 3
        assert len(historical_provider.requests) == 1
        _emit(
            "post_reconnect_live_continuation",
            {"state": "live", "chronology": "B0->B1, B1->B2, B2->B3"},
        )

        await controller.close()
        assert controller.is_started is False
        await DBPoolManager.close_pools()
        pool = None
        manager.shutdown()
        ConfigManager.reset_singleton()

        ConfigManager.reset_singleton()
        manager2 = ConfigManager(config_dir=str(config_root))
        managers.append(manager2)
        settings2 = load_ingestion_settings(manager2)
        await init_db_pools(manager2)
        pool2 = DBPoolManager.get_writer_pool()
        await apply_ingestion_schema(pool2)
        live_provider2 = _ControlledLiveProvider()
        historical_provider2 = _ControlledHistoricalProvider(
            lane=lane,
            expected_since=b1,
            expected_until=b2,
            observation=_observation(
                lane,
                open_time=b1,
                transport="rest",
                received_at=b2,
            ),
        )
        _, _, _, _, controller2 = _build_runtime(
            settings=settings2,
            pool=pool2,
            now_fn=lambda: clock[0],
            live_provider=live_provider2,
            historical_provider=historical_provider2,
        )
        controllers.append(controller2)
        app2 = create_app(runtime_controller=controller2)
        await controller2.start()
        await live_provider2.wait_for_stream_count(1)
        assert live_provider2.stream_anchors == [b3]
        assert not historical_provider2.requests
        assert (await request(app2, "GET", "/health/ready")).status_code == 200
        _emit(
            "fresh_resource_restart",
            {"anchor": live_provider2.stream_anchors[0], "recovery_requests": 0},
        )

        await controller2.close()
        await DBPoolManager.close_pools()
        manager2.shutdown()
        ConfigManager.reset_singleton()

        manager_fail: ConfigManager | None = None
        _set_all_assets_enabled(config_root, False)
        await _compose_async(repository_root, "stop", "db")
        db_stopped = True
        await _wait_database_stopped()
        try:
            ConfigManager.reset_singleton()
            manager_fail = ConfigManager(config_dir=str(config_root))
            managers.append(manager_fail)
            failed_app = create_application(config_manager=manager_fail)
            startup_started = time.monotonic()
            with pytest.raises(
                RuntimeError, match="Failed to connect to writer database"
            ):
                async with asyncio.timeout(FAILURE_TIMEOUT_SECONDS):
                    async with failed_app.router.lifespan_context(failed_app):
                        pytest.fail("database-down application unexpectedly started")
            startup_duration = time.monotonic() - startup_started
            _emit(
                "db_down_application_startup",
                {"duration_seconds": round(startup_duration, 3), "failed_closed": True},
            )
        finally:
            await _compose_async(repository_root, "start", "db")
            db_stopped = False
            await _wait_database_healthy()

        ConfigManager.reset_singleton()
        manager_ready = ConfigManager(config_dir=str(config_root))
        managers.append(manager_ready)
        ready_app = create_application(config_manager=manager_ready)
        async with ready_app.router.lifespan_context(ready_app):
            ready_controller = ready_app.state.runtime_controller
            assert ready_controller.is_started is True
            assert (await request(ready_app, "GET", "/health/ready")).status_code == 200
        _emit("db_restored_application_startup", {"ready": True})
    finally:
        if db_stopped:
            await _compose_async(repository_root, "start", "db")
            await _wait_database_healthy()
        for controller in reversed(controllers):
            try:
                await _close_controller(controller)
            except Exception as exc:  # noqa: BLE001
                _emit("controller_close_warning", repr(exc))
        try:
            await DBPoolManager.close_pools()
        except Exception as exc:  # noqa: BLE001
            _emit("pool_close_warning", repr(exc))
        for current_manager in managers:
            current_manager.shutdown()
        ConfigManager.reset_singleton()
        cleanup = await _cleanup_identity(instrument_id)
        assert cleanup == {"candles": 0, "outbox": 0, "pending": 0}
        db_after = _docker_snapshot(DATABASE_CONTAINER)
        broker_after = _docker_snapshot(BROKER_CONTAINER)
        assert db_after["status"] == "running"
        assert db_after["health"] == "healthy"
        assert broker_after["status"] in {"exited", "created"}
        leaked_tasks = [
            task.get_name()
            for task in asyncio.all_tasks()
            if not task.done()
            and task.get_name()
            in {"ingestion-supervisor", "ingestion-outbox-publisher"}
        ]
        assert not leaked_tasks
        _emit(
            "cleanup",
            {
                **cleanup,
                "db_after": db_after,
                "broker_after": broker_after,
                "leaked_tasks": leaked_tasks,
            },
        )
