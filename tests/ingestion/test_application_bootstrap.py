from __future__ import annotations

import asyncio
import copy
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from apps.ingestion_app import bootstrap
from apps.ingestion_app.api.app import create_app
from apps.ingestion_app.runtime.controller import RuntimeController
from apps.ingestion_app.runtime.supervisor import (
    DesiredRuntimeState,
    RuntimeSnapshot,
    RuntimeState,
)
from apps.ingestion_app.settings import IngestionSettings
from libs.common.config import ConfigManager
from libs.common.db.pool_manager import DBPoolManager
from tests.ingestion._asgi import request
from tests.ingestion.runtime.test_supervisor import _settings


@pytest.fixture
def config_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConfigManager:
    monkeypatch.chdir(tmp_path)
    ConfigManager.reset_singleton()
    manager = ConfigManager(config_dir=str(tmp_path / "configs"))
    yield manager
    manager.shutdown()
    ConfigManager.reset_singleton()


def _zero_asset_settings() -> IngestionSettings:
    raw = copy.deepcopy(_settings().model_dump(mode="json"))
    raw["assets"]["BTC"]["enabled"] = False
    return IngestionSettings.model_validate(raw)


class _ProviderResource:
    def __init__(self, provider_id: str, order: list[str]) -> None:
        self.provider_id = provider_id
        self.order = order
        self.order.append(f"{provider_id}.construct")

    async def close(self) -> None:
        self.order.append(f"{self.provider_id}.close")


class _LiveProvider:
    provider_id = "binance_native"

    def __init__(self, order: list[str]) -> None:
        self.order = order
        order.append("websocket.construct")

    def stream_closed_candles(self, *args, **kwargs):
        del args, kwargs
        raise AssertionError("zero-asset composition must not open a stream")


def _patch_composition(
    monkeypatch: pytest.MonkeyPatch,
    settings: IngestionSettings,
    order: list[str],
    publisher_started: asyncio.Event,
    *,
    patch_publisher_loop: bool = True,
) -> object:
    pool = object()

    monkeypatch.setattr(
        bootstrap,
        "load_ingestion_settings",
        lambda manager: (order.append("settings"), settings)[1],
    )

    async def init_db(_manager) -> None:
        order.append("db.init")

    async def apply_schema(_pool) -> None:
        order.append("schema")

    async def close_db() -> None:
        order.append("db.close")

    monkeypatch.setattr(bootstrap, "init_db_pools", init_db)
    monkeypatch.setattr(bootstrap, "apply_ingestion_schema", apply_schema)
    monkeypatch.setattr(DBPoolManager, "get_writer_pool", lambda: pool)
    monkeypatch.setattr(DBPoolManager, "close_pools", close_db)
    monkeypatch.setattr(
        bootstrap.CandleRepository,
        "fetch_pending_outbox_state",
        AsyncMock(return_value=(0, None)),
    )

    monkeypatch.setattr(
        bootstrap,
        "BinanceNativeHistoricalProvider",
        lambda: _ProviderResource("binance_native", order),
    )

    def ccxt_factory(*, provider_id: str, exchange_id: str) -> _ProviderResource:
        del exchange_id
        return _ProviderResource(provider_id, order)

    monkeypatch.setattr(bootstrap, "CCXTHistoricalProvider", ccxt_factory)
    monkeypatch.setattr(
        bootstrap,
        "BinanceWebSocketManager",
        lambda **kwargs: _LiveProvider(order),
    )

    if patch_publisher_loop:

        async def publisher_loop(**kwargs) -> None:
            del kwargs
            order.append("publisher.start")
            publisher_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                order.append("publisher.cancel")

        monkeypatch.setattr(bootstrap, "_run_publisher_connection_loop", publisher_loop)

    async def controller_start(self: RuntimeController) -> None:
        order.append("controller.start")
        await original_start(self)

    async def controller_close(self: RuntimeController) -> None:
        order.append("controller.close")
        await original_close(self)

    original_start = RuntimeController.start
    original_close = RuntimeController.close
    monkeypatch.setattr(RuntimeController, "start", controller_start)
    monkeypatch.setattr(RuntimeController, "close", controller_close)

    original_shutdown = ConfigManager.shutdown

    def manager_shutdown(self: ConfigManager) -> None:
        order.append("config.close")
        original_shutdown(self)

    monkeypatch.setattr(ConfigManager, "shutdown", manager_shutdown)
    return pool


@pytest.mark.asyncio
async def test_application_lifespan_orders_composition_and_cleanup(
    config_manager: ConfigManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    publisher_started = asyncio.Event()
    _patch_composition(
        monkeypatch,
        _zero_asset_settings(),
        order,
        publisher_started,
    )

    app = bootstrap.create_application(config_manager=config_manager)
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(publisher_started.wait(), timeout=1)
        assert app.state.config_manager is config_manager
        assert (
            app.state.config_service.runtime_controller is app.state.runtime_controller
        )
        assert app.state.runtime_controller.is_started is True
        assert (await request(app, "GET", "/health/ready")).status_code == 200
        assert order[:8] == [
            "settings",
            "db.init",
            "schema",
            "binance_native.construct",
            "ccxt_binance.construct",
            "websocket.construct",
            "controller.start",
            "publisher.start",
        ]

    assert order.index("controller.close") < order.index("publisher.cancel")
    assert order.index("publisher.cancel") < order.index("ccxt_binance.close")
    assert order.index("ccxt_binance.close") < order.index("binance_native.close")
    assert order.index("binance_native.close") < order.index("db.close")
    assert order.index("db.close") < order.index("config.close")
    assert app.state.runtime_controller.is_started is False
    assert app.state.publisher_task.done()


@pytest.mark.asyncio
async def test_database_failure_is_fatal_and_cleans_config(
    config_manager: ConfigManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    monkeypatch.setattr(
        bootstrap,
        "load_ingestion_settings",
        lambda manager: (order.append("settings"), _zero_asset_settings())[1],
    )

    async def fail_db(_manager) -> None:
        order.append("db.init")
        raise RuntimeError("database unavailable")

    async def close_db() -> None:
        order.append("db.close")

    monkeypatch.setattr(bootstrap, "init_db_pools", fail_db)
    monkeypatch.setattr(DBPoolManager, "close_pools", close_db)
    original_shutdown = ConfigManager.shutdown

    def manager_shutdown(self: ConfigManager) -> None:
        order.append("config.close")
        original_shutdown(self)

    monkeypatch.setattr(ConfigManager, "shutdown", manager_shutdown)

    app = bootstrap.create_application(config_manager=config_manager)
    with pytest.raises(RuntimeError, match="database unavailable"):
        async with app.router.lifespan_context(app):
            pytest.fail("database failure must prevent lifespan yield")

    assert order == ["settings", "db.init", "db.close", "config.close"]
    assert not hasattr(app.state, "runtime_controller")


@pytest.mark.asyncio
async def test_schema_failure_is_fatal_before_provider_or_runtime_start(
    config_manager: ConfigManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    publisher_started = asyncio.Event()
    _patch_composition(
        monkeypatch,
        _zero_asset_settings(),
        order,
        publisher_started,
    )

    async def fail_schema(_pool) -> None:
        order.append("schema")
        raise RuntimeError("schema unavailable")

    monkeypatch.setattr(bootstrap, "apply_ingestion_schema", fail_schema)

    app = bootstrap.create_application(config_manager=config_manager)
    with pytest.raises(RuntimeError, match="schema unavailable"):
        async with app.router.lifespan_context(app):
            pytest.fail("schema failure must prevent lifespan yield")

    assert order[:4] == ["settings", "db.init", "schema", "db.close"]
    assert "controller.start" not in order
    assert "publisher.start" not in order
    assert "config.close" in order


@pytest.mark.asyncio
async def test_provider_failure_closes_already_created_resources(
    config_manager: ConfigManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    publisher_started = asyncio.Event()
    _patch_composition(
        monkeypatch,
        _zero_asset_settings(),
        order,
        publisher_started,
    )

    def fail_ccxt(*, provider_id: str, exchange_id: str):
        del provider_id, exchange_id
        raise RuntimeError("CCXT unavailable")

    monkeypatch.setattr(bootstrap, "CCXTHistoricalProvider", fail_ccxt)

    app = bootstrap.create_application(config_manager=config_manager)
    with pytest.raises(RuntimeError, match="CCXT unavailable"):
        async with app.router.lifespan_context(app):
            pytest.fail("provider failure must prevent lifespan yield")

    assert "binance_native.construct" in order
    assert order.index("binance_native.construct") < order.index("binance_native.close")
    assert "controller.start" not in order
    assert "publisher.start" not in order
    assert order.index("binance_native.close") < order.index("db.close")


@pytest.mark.asyncio
async def test_controller_start_failure_closes_providers_and_database(
    config_manager: ConfigManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    publisher_started = asyncio.Event()
    _patch_composition(
        monkeypatch,
        _zero_asset_settings(),
        order,
        publisher_started,
    )

    async def fail_start(self: RuntimeController) -> None:
        del self
        order.append("controller.start")
        raise RuntimeError("runtime unavailable")

    monkeypatch.setattr(RuntimeController, "start", fail_start)

    app = bootstrap.create_application(config_manager=config_manager)
    with pytest.raises(RuntimeError, match="runtime unavailable"):
        async with app.router.lifespan_context(app):
            pytest.fail("controller failure must prevent lifespan yield")

    assert "publisher.start" not in order
    assert order.index("controller.start") < order.index("controller.close")
    assert order.index("controller.close") < order.index("ccxt_binance.close")
    assert order.index("binance_native.close") < order.index("db.close")


@pytest.mark.asyncio
async def test_valkey_connection_is_optional_and_retries_without_restarting_runtime(
    config_manager: ConfigManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    publisher_started = asyncio.Event()
    _patch_composition(
        monkeypatch,
        _zero_asset_settings(),
        order,
        publisher_started,
        patch_publisher_loop=False,
    )

    connection_attempts = 0
    connected_client = AsyncMock()

    async def create_client(_manager):
        nonlocal connection_attempts
        connection_attempts += 1
        if connection_attempts == 1:
            raise ConnectionError("Valkey unavailable")
        return connected_client

    monkeypatch.setattr(bootstrap, "create_valkey_client", create_client)
    publisher_run_started = asyncio.Event()

    async def publisher_run(self) -> None:
        del self
        publisher_run_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(bootstrap.OutboxPublisher, "run", publisher_run)
    monkeypatch.setattr(bootstrap.asyncio, "sleep", AsyncMock())

    app = bootstrap.create_application(config_manager=config_manager)
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(publisher_run_started.wait(), timeout=1)
        assert app.state.runtime_controller.is_started is True
        assert (await request(app, "GET", "/health/ready")).status_code == 200
        assert connection_attempts == 2

    connected_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_factory_lifespan_can_install_dependencies_late() -> None:
    class _Controller:
        is_started = True
        enabled_asset_count = 0

        def snapshot(self) -> RuntimeSnapshot:
            return RuntimeSnapshot(
                desired_state=DesiredRuntimeState.RUNNING,
                state=RuntimeState.STOPPED,
                last_error=None,
            )

    class _Service:
        def list_assets(self):
            return ()

    controller = _Controller()
    service = _Service()

    @asynccontextmanager
    async def lifespan(app):
        app.state.runtime_controller = controller
        app.state.config_service = service
        yield
        controller.is_started = False

    app = create_app(lifespan=lifespan)
    assert (await request(app, "GET", "/health/ready")).status_code == 503
    async with app.router.lifespan_context(app):
        assert (await request(app, "GET", "/health/ready")).status_code == 200
    assert (await request(app, "GET", "/health/ready")).status_code == 503
