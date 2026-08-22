from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from apps.decision_app.api.app import create_app
from apps.decision_app.api.routes import health_live, snapshot_payload
from apps.decision_app.bootstrap import build_generation_factory, create_application
from apps.decision_app.composition import build_production_composition
from apps.decision_app.runtime.lifecycle import LifecycleReadResult
from apps.decision_app.runtime.live import DecisionPollResult
from apps.decision_app.runtime.service import (
    DecisionRuntimeGeneration,
    DecisionServiceSnapshot,
)
from apps.decision_app.settings import (
    DecisionConfig,
    DecisionGlobalSettings,
    LiveInputSettings,
    SignalPublicationSettings,
)
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


class _CloseResource:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1
        if self.error is not None:
            raise self.error


def _patch_owned_lifespan(
    monkeypatch,
    *,
    valkey: _CloseResource,
    db_close,
    generation_error: Exception | None = None,
) -> None:
    async def create_valkey(_config_manager):
        return valkey

    async def init_pools(_config_manager):
        return None

    async def ensure_schema(_writer_pool):
        return None

    async def capture_tail(_client):
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
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.DBPoolManager.get_reader_pool",
        lambda: object(),
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.DBPoolManager.get_writer_pool",
        lambda: object(),
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.DBPoolManager.close_pools", db_close
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.ensure_checkpoint_schema", ensure_schema
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.CanonicalMarketHistoryRepository",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.CheckpointRepository",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.ShadowProgressRepository",
        lambda *_args, **_kwargs: SimpleNamespace(),
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

    class Stream:
        async def xrevrange(self, *_args, **_kwargs):
            return [("9-0", {})]

        async def xread(self, *_args, **_kwargs):
            await asyncio.sleep(0)
            return []

    manager = ConfigManagerFake()
    stream = Stream()
    runtime = _BootstrapRuntime()

    async def capture(_client):
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

    monkeypatch.setattr("apps.decision_app.bootstrap.capture_lifecycle_tail", capture)
    monkeypatch.setattr(
        "apps.decision_app.bootstrap.build_generation_factory", fake_factory
    )
    app = create_application(
        config_manager=manager,
        decision_config=_sr_config(),
        stream_client=stream,
        history_repository=SimpleNamespace(),
        checkpoint_repository=SimpleNamespace(),
    )

    async with app.router.lifespan_context(app):
        assert order[:2] == ["capture", "factory"]
        assert order[2:] == ["generation"]
        assert app.state.decision_service.snapshot().lifecycle_cursor == "9-0"
        lifecycle_reader = app.state.decision_service._lifecycle_reader
        assert lifecycle_reader._configured_assets == frozenset({"BTCUSDT"})

    assert manager.shutdown_calls == 1


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
