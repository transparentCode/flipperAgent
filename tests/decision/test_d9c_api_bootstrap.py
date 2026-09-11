from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from valkey.asyncio import Valkey
from valkey.asyncio.retry import Retry
from valkey.backoff import NoBackoff

from apps.decision_app import bootstrap as bootstrap_module
from apps.decision_app.api.app import create_app
from apps.decision_app.api.routes import health_live, snapshot_payload
from apps.decision_app.bootstrap import (
    _require_bounded_injected_stream_client,
    _require_bounded_repository,
    build_generation_factory,
    create_application,
)
from apps.decision_app.composition import build_production_composition
from apps.decision_app.runtime.lifecycle import LifecycleReadResult
from apps.decision_app.runtime.live import DecisionPollResult
from apps.decision_app.runtime.service import (
    DecisionRuntimeGeneration,
    DecisionService,
    DecisionServiceSnapshot,
)
from apps.decision_app.settings import (
    DecisionConfig,
    DecisionDependencyIOSettings,
    DecisionGlobalSettings,
    LiveInputSettings,
    SignalPublicationSettings,
)
from apps.decision_app.storage.checkpoints import CheckpointRepository
from apps.decision_app.storage.market_history import (
    CanonicalMarketHistoryRepository,
)
from apps.decision_app.storage.shadow_progress import ShadowProgressRepository
from tests.decision.test_d9b_live_runtime import _sr_config


class _BootstrapRuntime:
    def __init__(self) -> None:
        self.input = SimpleNamespace(cursors={}, blocked_streams={})
        self.lanes = {}
        self.calls = 0

    async def poll_once(self, *, evaluate_lanes: bool = True) -> DecisionPollResult:
        self.calls += 1
        await asyncio.sleep(0)
        return DecisionPollResult(input_results=(), lane_results={}, cursors={})


def _api_snapshot(
    *,
    service_state: str = "RUNNING",
    desired_state: str = "RUNNING",
    generation_id: int | None = 1,
) -> DecisionServiceSnapshot:
    return DecisionServiceSnapshot(
        service_state=service_state,  # type: ignore[arg-type]
        desired_state=desired_state,  # type: ignore[arg-type]
        generation_id=generation_id,
        started_at=datetime(2026, 8, 14, tzinfo=UTC),
        last_poll_at=None,
        last_rebuild_at=None,
        last_lifecycle_event_at=None,
        last_error=None,
        configured_asset_count=1,
        configured_lane_count=1,
        active_lane_count=0,
        lane_status_counts={},
        blocked_stream_count=0,
        lifecycle_cursor="0-0",
        lanes={},
        inputs={},
        last_lifecycle_evidence={},
    )


class _ControlPlaneService:
    def __init__(self) -> None:
        self.state = "RUNNING"
        self.desired = "RUNNING"
        self.snapshot_calls = 0
        self.control_calls: list[str] = []

    def snapshot(self) -> DecisionServiceSnapshot:
        self.snapshot_calls += 1
        return _api_snapshot(
            service_state=self.state,
            desired_state=self.desired,
        )

    async def pause(self) -> DecisionServiceSnapshot:
        self.control_calls.append("pause")
        self.state = self.desired = "PAUSED"
        return self.snapshot()

    async def resume(self) -> DecisionServiceSnapshot:
        self.control_calls.append("resume")
        self.state = self.desired = "RUNNING"
        return self.snapshot()

    async def reconnect(self) -> DecisionServiceSnapshot:
        self.control_calls.append("reconnect")
        self.state = self.desired = "RUNNING"
        return self.snapshot()


class _NoopLifecycleReader:
    cursor = "0-0"

    async def read_once(self) -> LifecycleReadResult:
        await asyncio.sleep(0)
        return LifecycleReadResult(cursor=self.cursor)


def _CloseResource(
    error: Exception | None = None,
    *,
    io_timeout_seconds: float = 5.0,
    xrevrange_result: list[tuple[str, dict]] | None = None,
) -> Valkey:
    client = Valkey(
        host="127.0.0.1",
        port=1,
        socket_timeout=io_timeout_seconds,
        socket_connect_timeout=io_timeout_seconds,
        retry_on_timeout=False,
        retry_on_error=[],
        decode_responses=True,
    )
    client.error = error
    client.close_calls = 0

    async def aclose() -> None:
        client.close_calls += 1
        if client.error is not None:
            raise client.error

    async def xread(*_args, **_kwargs):
        return []

    async def xrange(*_args, **_kwargs):
        return []

    async def xrevrange(*_args, **_kwargs):
        return xrevrange_result or []

    async def xadd(*_args, **_kwargs):
        return "1-0"

    client.aclose = aclose
    client.xread = xread
    client.xrange = xrange
    client.xrevrange = xrevrange
    client.xadd = xadd
    return client


class _NoopPool:
    def acquire(self, *_args, **_kwargs):
        raise AssertionError("bootstrap fake must not perform DB I/O")


def _patch_owned_lifespan(
    monkeypatch,
    *,
    valkey: Valkey,
    db_close,
    generation_error: Exception | None = None,
    expected_io_timeout_seconds: float = 5.0,
    expected_operation_timeout_seconds: float = 15.0,
    expected_cleanup_timeout_seconds: float = 5.0,
) -> None:
    async def create_valkey(
        _config_manager,
        *,
        io_timeout_seconds,
        cleanup_callback,
    ):
        assert io_timeout_seconds == expected_io_timeout_seconds
        assert callable(cleanup_callback)
        return valkey

    async def init_pools(
        _config_manager,
        *,
        connect_timeout,
        return_created,
        cleanup_timeout,
        retained_cleanup_tasks,
        cleanup_remaining,
    ):
        assert connect_timeout == expected_io_timeout_seconds
        assert return_created is True
        assert cleanup_timeout == expected_cleanup_timeout_seconds
        assert isinstance(retained_cleanup_tasks, set)
        assert callable(cleanup_remaining)
        return True

    async def ensure_schema(
        _writer_pool,
        *,
        io_timeout_seconds,
        operation_timeout_seconds,
        cleanup_timeout_seconds,
        retained_cleanup_tasks,
        cleanup_budget,
    ):
        assert io_timeout_seconds == expected_io_timeout_seconds
        assert operation_timeout_seconds == expected_operation_timeout_seconds
        assert cleanup_timeout_seconds == expected_cleanup_timeout_seconds
        assert isinstance(retained_cleanup_tasks, set)
        assert cleanup_budget is not None

    async def capture_tail(_client, *, io_timeout_seconds):
        assert io_timeout_seconds == expected_io_timeout_seconds
        return "0-0"

    def build_factory(**_kwargs):
        async def build(*, reason: str, generation_id: int):
            del reason
            if generation_error is not None:
                raise generation_error
            startup = SimpleNamespace(
                snapshot=SimpleNamespace(
                    status="STARTUP_READY", active_manifest_assets=()
                ),
                decision_plan=SimpleNamespace(lanes=()),
            )
            return DecisionRuntimeGeneration(
                generation_id=generation_id,
                created_at=datetime(2026, 8, 14, tzinfo=UTC),
                startup=startup,
                live_runtime=_BootstrapRuntime(),
            )

        return build

    monkeypatch.setattr(
        "apps.decision_app.bootstrap.create_valkey_client", create_valkey
    )
    monkeypatch.setattr("apps.decision_app.bootstrap.init_db_pools", init_pools)
    pool = _NoopPool()
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.DBPoolManager.get_reader_pool",
        lambda: pool,
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.DBPoolManager.get_writer_pool",
        lambda: pool,
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.DBPoolManager.close_pools", db_close
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.ensure_checkpoint_schema", ensure_schema
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.CanonicalMarketHistoryRepository",
        CanonicalMarketHistoryRepository,
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.CheckpointRepository",
        CheckpointRepository,
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.ShadowProgressRepository",
        ShadowProgressRepository,
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.AssetManifestStore",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.capture_lifecycle_tail", capture_tail
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.build_production_composition",
        lambda _config: object(),
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.build_generation_factory", build_factory
    )


async def _asgi_request(app, method: str, path: str) -> tuple[int, dict]:
    sent: list[dict] = []
    request_sent = False

    async def receive() -> dict:
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 1234),
            "server": ("testserver", 80),
            "root_path": "",
        },
        receive,
        send,
    )
    start = next(item for item in sent if item["type"] == "http.response.start")
    body = b"".join(
        item.get("body", b"") for item in sent if item["type"] == "http.response.body"
    )
    return start["status"], json.loads(body)


def test_d9c_control_plane_route_inventory_and_cached_payload() -> None:
    app = create_app()
    paths = app.openapi()["paths"]
    assert set(paths) == {
        "/health/live",
        "/health/ready",
        "/runtime",
        "/runtime/lanes",
        "/runtime/inputs",
        "/runtime/pause",
        "/runtime/resume",
        "/runtime/reconnect",
    }
    assert health_live() == {"status": "live"}

    snapshot = DecisionServiceSnapshot(
        service_state="RUNNING",
        desired_state="RUNNING",
        generation_id=1,
        started_at=datetime(2026, 8, 14, tzinfo=UTC),
        last_poll_at=None,
        last_rebuild_at=None,
        last_lifecycle_event_at=None,
        last_error=None,
        configured_asset_count=1,
        configured_lane_count=1,
        active_lane_count=1,
        lane_status_counts={"LIVE": 1},
        blocked_stream_count=0,
        lifecycle_cursor="0-0",
        lanes={"lane": {"status": "LIVE"}},
        inputs={},
        last_lifecycle_evidence={},
    )
    payload = snapshot_payload(snapshot)
    assert payload["service_state"] == "RUNNING"
    assert payload["generation_id"] == 1
    assert payload["lanes"] == {"lane": {"status": "LIVE"}}


def test_injected_native_retry_is_rejected_without_mutating_client() -> None:
    client = Valkey(
        host="127.0.0.1",
        port=1,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
        retry_on_timeout=False,
        retry_on_error=[],
        retry=Retry(NoBackoff(), 3),
    )

    with pytest.raises(TypeError, match="wire contract"):
        _require_bounded_injected_stream_client(
            client,
            io_timeout_seconds=5.0,
        )
    assert client.connection_pool.connection_kwargs["retry"] is not None


def test_injected_valkey_subclass_is_rejected_before_driver_use() -> None:
    class DerivedValkey(Valkey):
        pass

    client = DerivedValkey(
        host="127.0.0.1",
        port=1,
        socket_timeout=5.0,
        socket_connect_timeout=5.0,
        retry_on_timeout=False,
        retry_on_error=[],
    )

    with pytest.raises(TypeError, match="must be a Valkey client"):
        _require_bounded_injected_stream_client(
            client,
            io_timeout_seconds=5.0,
        )


def test_injected_builtin_repository_with_fake_pool_is_rejected() -> None:
    repository = CheckpointRepository(
        _NoopPool(),
        io_timeout_seconds=5.0,
        operation_timeout_seconds=15.0,
        cleanup_timeout_seconds=5.0,
    )

    with pytest.raises(TypeError, match="installed asyncpg.Pool"):
        _require_bounded_repository(
            repository,
            name="checkpoint",
            io_timeout_seconds=5.0,
            operation_timeout_seconds=15.0,
            cleanup_timeout_seconds=5.0,
        )
    assert repository.poisoned is False


@pytest.mark.asyncio
async def test_d9c_http_readiness_and_control_routes_use_cached_service_state() -> None:
    service = _ControlPlaneService()
    app = create_app(decision_service=service)  # type: ignore[arg-type]

    live_status, live_body = await _asgi_request(app, "GET", "/health/live")
    assert live_status == 200
    assert live_body == {"status": "live"}

    service.state = service.desired = "PAUSED"
    paused_status, _ = await _asgi_request(app, "GET", "/health/ready")
    assert paused_status == 503

    service.state = "DEGRADED"
    service.desired = "PAUSED"
    paused_degraded_status, _ = await _asgi_request(app, "GET", "/health/ready")
    assert paused_degraded_status == 503

    service.desired = "RUNNING"
    degraded_status, degraded_body = await _asgi_request(app, "GET", "/health/ready")
    assert degraded_status == 200
    assert degraded_body["status"] == "degraded"

    for path in ("/runtime", "/runtime/lanes", "/runtime/inputs"):
        status, _ = await _asgi_request(app, "GET", path)
        assert status == 200

    for method, path, name in (
        ("POST", "/runtime/pause", "pause"),
        ("POST", "/runtime/resume", "resume"),
        ("POST", "/runtime/reconnect", "reconnect"),
    ):
        status, _ = await _asgi_request(app, method, path)
        assert status == 200
        assert service.control_calls[-1] == name

    assert service.snapshot_calls > 0

    missing_status, _ = await _asgi_request(create_app(), "GET", "/health/ready")
    assert missing_status == 503


@pytest.mark.asyncio
async def test_d9c_generation_wires_non_default_d9b_settings(monkeypatch) -> None:
    original = _sr_config()
    config = DecisionConfig(
        global_settings=DecisionGlobalSettings(
            live_input=LiveInputSettings(batch_size=3, block_ms=17),
            signal_publication=SignalPublicationSettings(
                stream_maxlen=77,
                stream_approximate=False,
            ),
        ),
        assets=original.assets,
        timeframe_grid=original.timeframe_grid,
        instruments=original.instruments,
    )

    class FakeCoordinator:
        def __init__(self, **_kwargs) -> None:
            pass

        async def start(self):
            return SimpleNamespace(
                snapshot=SimpleNamespace(status="STARTUP_READY"),
                relay_plans=(),
            )

    class FakeRuntime:
        last_kwargs = None

        def __init__(self, **kwargs) -> None:
            FakeRuntime.last_kwargs = kwargs
            self.lanes = {}
            self.input = SimpleNamespace(cursors={}, blocked_streams={})

        async def poll_once(self, *, evaluate_lanes: bool = True):
            raise AssertionError("not part of wiring test")

    class Client:
        async def xread(self, *_args, **_kwargs):
            return []

        async def xrange(self, *_args, **_kwargs):
            return []

        async def xrevrange(self, *_args, **_kwargs):
            return []

        async def xadd(self, *_args, **_kwargs):
            return "1-0"

    monkeypatch.setattr(
        "apps.decision_app.bootstrap.DecisionStartupCoordinator", FakeCoordinator
    )
    monkeypatch.setattr("apps.decision_app.bootstrap.LiveDecisionRuntime", FakeRuntime)
    composition = build_production_composition(config)
    factory = build_generation_factory(
        config=config,
        composition=composition,
        stream_client=Client(),
        history_repository=SimpleNamespace(fetch_bars=lambda *args, **kwargs: ()),
        checkpoint_repository=SimpleNamespace(),
    )
    await factory(reason="test", generation_id=1)
    assert FakeRuntime.last_kwargs["batch_size"] == 3
    assert FakeRuntime.last_kwargs["block_ms"] == 17
    publisher = FakeRuntime.last_kwargs["signal_publisher"]
    assert publisher._stream_maxlen == 77
    assert publisher._stream_approximate is False


@pytest.mark.asyncio
async def test_lifespan_captures_lifecycle_tail_before_generation_build(
    monkeypatch,
) -> None:
    order: list[str] = []

    class ConfigManagerFake:
        def __init__(self) -> None:
            self.shutdown_calls = 0

        def shutdown(self) -> None:
            self.shutdown_calls += 1

    manager = ConfigManagerFake()
    stream = _CloseResource(xrevrange_result=[("9-0", {})])
    runtime = _BootstrapRuntime()

    async def capture(_client, *, io_timeout_seconds):
        assert io_timeout_seconds == 5.0
        order.append("capture")
        return "9-0"

    def fake_factory(**_kwargs):
        order.append("factory")

        async def build(*, reason: str, generation_id: int):
            del reason
            order.append("generation")
            startup = SimpleNamespace(
                snapshot=SimpleNamespace(
                    status="STARTUP_READY", active_manifest_assets=()
                ),
                decision_plan=SimpleNamespace(lanes=()),
            )
            return DecisionRuntimeGeneration(
                generation_id=generation_id,
                created_at=datetime(2026, 8, 14, tzinfo=UTC),
                startup=startup,
                live_runtime=runtime,
            )

        return build

    _patch_owned_lifespan(
        monkeypatch,
        valkey=stream,
        db_close=lambda: asyncio.sleep(0),
    )
    monkeypatch.setattr("apps.decision_app.bootstrap.capture_lifecycle_tail", capture)
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.build_generation_factory", fake_factory
    )
    app = create_application(
        config_manager=manager,
        decision_config=_sr_config(),
        stream_client=stream,
    )

    async with app.router.lifespan_context(app):
        assert order[:2] == ["capture", "factory"]
        assert order[2:] == ["generation"]
        assert app.state.decision_service.snapshot().lifecycle_cursor == "9-0"
        lifecycle_reader = app.state.decision_service._lifecycle_reader
        assert lifecycle_reader._configured_assets == frozenset({"BTCUSDT"})

    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
async def test_startup_logs_only_effective_dependency_budget_policy(
    monkeypatch,
    caplog,
) -> None:
    base = _sr_config()
    dependency_io = DecisionDependencyIOSettings(
        io_timeout_seconds=0.25,
        db_operation_timeout_seconds=0.75,
        generation_timeout_seconds=1.5,
        control_wait_timeout_seconds=1.25,
        cleanup_timeout_seconds=0.4,
    )
    config = DecisionConfig(
        global_settings=base.global_settings.model_copy(
            update={"dependency_io": dependency_io}
        ),
        assets=base.assets,
        timeframe_grid=base.timeframe_grid,
        instruments=base.instruments,
    )
    valkey = _CloseResource(io_timeout_seconds=0.25)

    class ConfigManagerFake:
        def shutdown(self) -> None:
            return None

    _patch_owned_lifespan(
        monkeypatch,
        valkey=valkey,
        db_close=lambda: asyncio.sleep(0),
        expected_io_timeout_seconds=0.25,
        expected_operation_timeout_seconds=0.75,
        expected_cleanup_timeout_seconds=0.4,
    )
    caplog.set_level(logging.INFO, logger=bootstrap_module._LOGGER.name)
    app = create_application(
        config_manager=ConfigManagerFake(),
        decision_config=config,
        lifecycle_reader=_NoopLifecycleReader(),
    )

    async with app.router.lifespan_context(app):
        pass

    records = [
        record
        for record in caplog.records
        if record.name == bootstrap_module._LOGGER.name
        and record.getMessage().startswith("Decision bounded startup budget policy:")
    ]
    assert len(records) == 1
    record = records[0]
    assert record.args == (0.25, 0.75, 1.5, 1.25, 0.4)
    rendered = record.getMessage()
    assert "redis://" not in rendered
    assert "secret" not in rendered
    assert "DecisionConfig" not in rendered
    assert "payload" not in rendered


@pytest.mark.asyncio
async def test_lifespan_continues_when_observability_construction_fails(
    monkeypatch,
) -> None:
    valkey = _CloseResource()
    db_calls = 0

    async def close_db() -> None:
        nonlocal db_calls
        db_calls += 1

    class ConfigManagerFake:
        def shutdown(self) -> None:
            return None

    def fail_observability(*_args, **_kwargs):
        raise RuntimeError("metrics unavailable")

    monkeypatch.setattr(
        "apps.decision_app.bootstrap.DecisionObservability", fail_observability
    )
    manager = ConfigManagerFake()
    _patch_owned_lifespan(monkeypatch, valkey=valkey, db_close=close_db)
    app = create_application(
        config_manager=manager,
        decision_config=_sr_config(),
        lifecycle_reader=_NoopLifecycleReader(),
    )

    async with app.router.lifespan_context(app):
        assert app.state.decision_observability is None
        assert app.state.decision_service.service_state == "RUNNING"

    assert valkey.close_calls == 1
    assert db_calls == 1


@pytest.mark.asyncio
async def test_lifespan_continues_when_observability_and_warning_fail(
    monkeypatch,
) -> None:
    valkey = _CloseResource()
    db_calls = 0

    async def close_db() -> None:
        nonlocal db_calls
        db_calls += 1

    class ConfigManagerFake:
        def shutdown(self) -> None:
            return None

    def fail_observability(*_args, **_kwargs):
        raise RuntimeError("metrics unavailable")

    def fail_warning(*_args, **_kwargs):
        raise RuntimeError("logging unavailable")

    monkeypatch.setattr(
        "apps.decision_app.bootstrap.DecisionObservability", fail_observability
    )
    monkeypatch.setattr("apps.decision_app.bootstrap._LOGGER.warning", fail_warning)
    manager = ConfigManagerFake()
    _patch_owned_lifespan(monkeypatch, valkey=valkey, db_close=close_db)
    app = create_application(
        config_manager=manager,
        decision_config=_sr_config(),
        lifecycle_reader=_NoopLifecycleReader(),
    )

    async with app.router.lifespan_context(app):
        assert app.state.decision_observability is None
        assert app.state.decision_service.service_state == "RUNNING"

    assert valkey.close_calls == 1
    assert db_calls == 1


@pytest.mark.asyncio
async def test_lifespan_cleanup_continues_when_generation_start_fails(
    monkeypatch,
) -> None:
    valkey = _CloseResource()
    db_calls = 0

    async def close_db() -> None:
        nonlocal db_calls
        db_calls += 1

    class ConfigManagerFake:
        def __init__(self) -> None:
            self.shutdown_calls = 0

        def shutdown(self) -> None:
            self.shutdown_calls += 1

    manager = ConfigManagerFake()
    _patch_owned_lifespan(
        monkeypatch,
        valkey=valkey,
        db_close=close_db,
        generation_error=RuntimeError("generation failed"),
    )
    app = create_application(
        config_manager=manager,
        decision_config=_sr_config(),
        lifecycle_reader=_NoopLifecycleReader(),
    )

    with pytest.raises(RuntimeError, match="generation failed"):
        async with app.router.lifespan_context(app):
            raise AssertionError("startup should fail before the lifespan body")

    assert valkey.close_calls == 1
    assert db_calls == 1
    assert manager.shutdown_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_resource", ["valkey", "db"])
async def test_lifespan_cleanup_attempts_all_owned_resources_after_failure(
    monkeypatch,
    failing_resource: str,
) -> None:
    valkey = _CloseResource(
        RuntimeError("valkey close failed") if failing_resource == "valkey" else None
    )
    db_calls = 0
    manager_shutdown_calls = 0

    async def close_db() -> None:
        nonlocal db_calls
        db_calls += 1
        if failing_resource == "db":
            raise RuntimeError("db close failed")

    class ConfigManagerFake:
        def shutdown(self) -> None:
            nonlocal manager_shutdown_calls
            manager_shutdown_calls += 1

    manager = ConfigManagerFake()
    _patch_owned_lifespan(monkeypatch, valkey=valkey, db_close=close_db)
    app = create_application(
        config_manager=manager,
        decision_config=_sr_config(),
        lifecycle_reader=_NoopLifecycleReader(),
    )

    with pytest.raises(RuntimeError, match=failing_resource):
        async with app.router.lifespan_context(app):
            pass

    assert valkey.close_calls == 1
    assert db_calls == 1
    assert manager_shutdown_calls == 1

    with pytest.raises(RuntimeError, match="poisoned"):
        async with app.router.lifespan_context(app):
            pass
    assert valkey.close_calls == 1
    assert db_calls == 1


@pytest.mark.asyncio
async def test_lifespan_normal_shutdown_closes_each_owned_resource_once(
    monkeypatch,
) -> None:
    valkey = _CloseResource()
    db_calls = 0
    manager_shutdown_calls = 0

    async def close_db() -> None:
        nonlocal db_calls
        db_calls += 1

    class ConfigManagerFake:
        def shutdown(self) -> None:
            nonlocal manager_shutdown_calls
            manager_shutdown_calls += 1

    manager = ConfigManagerFake()
    _patch_owned_lifespan(monkeypatch, valkey=valkey, db_close=close_db)
    app = create_application(
        config_manager=manager,
        decision_config=_sr_config(),
        lifecycle_reader=_NoopLifecycleReader(),
    )

    async with app.router.lifespan_context(app):
        pass

    assert valkey.close_calls == 1
    assert db_calls == 1
    assert manager_shutdown_calls == 1


@pytest.mark.asyncio
async def test_lifespan_shares_cleanup_budget_after_service_stop(
    monkeypatch,
) -> None:
    valkey = _CloseResource(io_timeout_seconds=0.1)
    db_calls = 0

    async def close_db() -> None:
        nonlocal db_calls
        db_calls += 1

    class ConfigManagerFake:
        def shutdown(self) -> None:
            return None

    base = _sr_config()
    config = DecisionConfig(
        global_settings=DecisionGlobalSettings(
            live_input=LiveInputSettings(block_ms=10),
            dependency_io=DecisionDependencyIOSettings(
                io_timeout_seconds=0.1,
                db_operation_timeout_seconds=0.1,
                generation_timeout_seconds=0.2,
                control_wait_timeout_seconds=0.1,
                cleanup_timeout_seconds=0.05,
            ),
        ),
        assets=base.assets,
        timeframe_grid=base.timeframe_grid,
        instruments=base.instruments,
    )
    manager = ConfigManagerFake()
    _patch_owned_lifespan(
        monkeypatch,
        valkey=valkey,
        db_close=close_db,
        expected_io_timeout_seconds=0.1,
        expected_operation_timeout_seconds=0.1,
        expected_cleanup_timeout_seconds=0.05,
    )

    original_stop = DecisionService.stop

    async def delayed_stop(self, *, cleanup_budget=None):
        assert cleanup_budget is not None
        await asyncio.sleep(0.06)
        return await original_stop(self, cleanup_budget=cleanup_budget)

    monkeypatch.setattr(DecisionService, "stop", delayed_stop)
    original_cleanup = bootstrap_module.cleanup_with_timeout
    resource_budgets: list[float] = []

    async def capture_cleanup(awaitable, timeout, **kwargs):
        if kwargs["operation"] in {
            "Valkey resource cleanup",
            "DB pool cleanup",
        }:
            resource_budgets.append(timeout)
        return await original_cleanup(awaitable, timeout, **kwargs)

    monkeypatch.setattr(
        "apps.decision_app.bootstrap.cleanup_with_timeout", capture_cleanup
    )
    app = create_application(
        config_manager=manager,
        decision_config=config,
        lifecycle_reader=_NoopLifecycleReader(),
    )

    async with app.router.lifespan_context(app):
        pass

    assert db_calls == 1
    assert len(resource_budgets) == 2
    assert 0.04 < resource_budgets[0] <= 0.05
    assert 0 < resource_budgets[1] <= resource_budgets[0]


@pytest.mark.asyncio
async def test_startup_failure_teardown_keeps_remaining_generation_budget(
    monkeypatch,
) -> None:
    valkey = _CloseResource(io_timeout_seconds=0.1)

    class ConfigManagerFake:
        def shutdown(self) -> None:
            return None

    base = _sr_config()
    config = DecisionConfig(
        global_settings=DecisionGlobalSettings(
            live_input=LiveInputSettings(block_ms=10),
            dependency_io=DecisionDependencyIOSettings(
                io_timeout_seconds=0.1,
                db_operation_timeout_seconds=0.1,
                generation_timeout_seconds=0.2,
                control_wait_timeout_seconds=0.1,
                cleanup_timeout_seconds=0.05,
            ),
        ),
        assets=base.assets,
        timeframe_grid=base.timeframe_grid,
        instruments=base.instruments,
    )
    _patch_owned_lifespan(
        monkeypatch,
        valkey=valkey,
        db_close=lambda: None,
        expected_io_timeout_seconds=0.1,
        expected_operation_timeout_seconds=0.1,
        expected_cleanup_timeout_seconds=0.05,
    )

    async def fail_after_partial_start(*_args, **_kwargs):
        await asyncio.sleep(0.04)
        raise RuntimeError("database startup failed")

    monkeypatch.setattr(bootstrap_module, "init_db_pools", fail_after_partial_start)
    original_cleanup = bootstrap_module.cleanup_with_timeout
    resource_budgets: list[float] = []

    async def capture_cleanup(awaitable, timeout, **kwargs):
        if kwargs["operation"] == "Valkey resource cleanup":
            resource_budgets.append(timeout)
        return await original_cleanup(awaitable, timeout, **kwargs)

    monkeypatch.setattr(bootstrap_module, "cleanup_with_timeout", capture_cleanup)
    app = create_application(
        config_manager=ConfigManagerFake(),
        decision_config=config,
        lifecycle_reader=_NoopLifecycleReader(),
    )

    with pytest.raises(RuntimeError, match="database startup failed"):
        async with app.router.lifespan_context(app):
            pass

    assert valkey.close_calls == 1
    assert len(resource_budgets) == 1
    assert 0 < resource_budgets[0] <= 0.05


@pytest.mark.asyncio
async def test_startup_failure_shares_cleanup_budget_across_db_schema_and_final(
    monkeypatch,
) -> None:
    valkey = _CloseResource(io_timeout_seconds=0.1)
    budget_samples: list[float] = []
    resource_budgets: list[float] = []

    class ConfigManagerFake:
        def shutdown(self) -> None:
            return None

    base = _sr_config()
    config = DecisionConfig(
        global_settings=DecisionGlobalSettings(
            live_input=LiveInputSettings(block_ms=10),
            dependency_io=DecisionDependencyIOSettings(
                io_timeout_seconds=0.1,
                db_operation_timeout_seconds=0.1,
                generation_timeout_seconds=0.5,
                control_wait_timeout_seconds=0.1,
                cleanup_timeout_seconds=0.05,
            ),
        ),
        assets=base.assets,
        timeframe_grid=base.timeframe_grid,
        instruments=base.instruments,
    )

    async def close_db() -> None:
        await asyncio.sleep(0)

    _patch_owned_lifespan(
        monkeypatch,
        valkey=valkey,
        db_close=close_db,
        expected_io_timeout_seconds=0.1,
        expected_operation_timeout_seconds=0.1,
        expected_cleanup_timeout_seconds=0.05,
    )

    async def init_pools(_config_manager, **kwargs):
        cleanup_remaining = kwargs["cleanup_remaining"]
        budget_samples.append(cleanup_remaining())
        await asyncio.sleep(0.01)
        return True

    async def ensure_schema(_writer_pool, **kwargs):
        cleanup_budget = kwargs["cleanup_budget"]
        budget_samples.append(cleanup_budget.remaining())
        await asyncio.sleep(0.01)
        raise RuntimeError("schema startup failed")

    monkeypatch.setattr(bootstrap_module, "init_db_pools", init_pools)
    monkeypatch.setattr(bootstrap_module, "ensure_checkpoint_schema", ensure_schema)
    original_cleanup = bootstrap_module.cleanup_with_timeout

    async def capture_cleanup(awaitable, timeout, **kwargs):
        if kwargs["operation"] == "Valkey resource cleanup":
            resource_budgets.append(timeout)
        return await original_cleanup(awaitable, timeout, **kwargs)

    monkeypatch.setattr(bootstrap_module, "cleanup_with_timeout", capture_cleanup)
    app = create_application(
        config_manager=ConfigManagerFake(),
        decision_config=config,
        lifecycle_reader=_NoopLifecycleReader(),
    )

    with pytest.raises(RuntimeError, match="schema startup failed"):
        async with app.router.lifespan_context(app):
            pass

    assert len(budget_samples) == 2
    assert budget_samples[0] > budget_samples[1] > 0
    assert len(resource_budgets) == 1
    assert 0 < resource_budgets[0] < budget_samples[1]


@pytest.mark.asyncio
async def test_successful_retry_startup_gets_fresh_final_cleanup_budget(
    monkeypatch,
) -> None:
    valkey = _CloseResource(io_timeout_seconds=0.1)

    class ConfigManagerFake:
        def shutdown(self) -> None:
            return None

    base = _sr_config()
    config = DecisionConfig(
        global_settings=DecisionGlobalSettings(
            live_input=LiveInputSettings(block_ms=10),
            dependency_io=DecisionDependencyIOSettings(
                io_timeout_seconds=0.1,
                db_operation_timeout_seconds=0.1,
                generation_timeout_seconds=0.5,
                control_wait_timeout_seconds=0.1,
                cleanup_timeout_seconds=0.05,
            ),
        ),
        assets=base.assets,
        timeframe_grid=base.timeframe_grid,
        instruments=base.instruments,
    )

    async def close_db() -> None:
        await asyncio.sleep(0)

    _patch_owned_lifespan(
        monkeypatch,
        valkey=valkey,
        db_close=close_db,
        expected_io_timeout_seconds=0.1,
        expected_operation_timeout_seconds=0.1,
        expected_cleanup_timeout_seconds=0.05,
    )

    async def retry_then_healthy(
        _config_manager,
        *,
        io_timeout_seconds,
        cleanup_callback,
    ):
        assert io_timeout_seconds == 0.1
        await cleanup_callback(asyncio.sleep(0), True)
        await asyncio.sleep(0.07)
        return valkey

    monkeypatch.setattr(
        bootstrap_module,
        "create_valkey_client",
        retry_then_healthy,
    )
    original_cleanup = bootstrap_module.cleanup_with_timeout
    resource_budgets: list[float] = []

    async def capture_cleanup(awaitable, timeout, **kwargs):
        if kwargs["operation"] == "Valkey resource cleanup":
            resource_budgets.append(timeout)
        return await original_cleanup(awaitable, timeout, **kwargs)

    monkeypatch.setattr(bootstrap_module, "cleanup_with_timeout", capture_cleanup)
    app = create_application(
        config_manager=ConfigManagerFake(),
        decision_config=config,
        lifecycle_reader=_NoopLifecycleReader(),
    )

    async with app.router.lifespan_context(app):
        pass

    assert len(resource_budgets) == 1
    assert resource_budgets[0] > 0.03


@pytest.mark.asyncio
async def test_lifespan_retained_cleanup_poison_fences_reentry(monkeypatch) -> None:
    valkey = _CloseResource()
    db_calls = 0

    async def close_db() -> None:
        nonlocal db_calls
        db_calls += 1

    class ConfigManagerFake:
        def shutdown(self) -> None:
            return None

    manager = ConfigManagerFake()
    _patch_owned_lifespan(monkeypatch, valkey=valkey, db_close=close_db)
    app = create_application(
        config_manager=manager,
        decision_config=_sr_config(),
        lifecycle_reader=_NoopLifecycleReader(),
    )

    retained: asyncio.Task[object] | None = None
    with pytest.raises(RuntimeError, match="unclean"):
        async with app.router.lifespan_context(app):
            retained = asyncio.create_task(asyncio.Event().wait())
            app.state.decision_lifespan_owner["retained_cleanup_tasks"].add(retained)

    assert retained is not None
    retained.cancel()
    await asyncio.gather(retained, return_exceptions=True)
    app.state.decision_lifespan_owner["retained_cleanup_tasks"].discard(retained)
    assert valkey.close_calls == 1
    assert db_calls == 1

    with pytest.raises(RuntimeError, match="poisoned"):
        async with app.router.lifespan_context(app):
            pass
