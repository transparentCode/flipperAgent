from __future__ import annotations

import pytest

from apps.ingestion_app.api.app import create_app
from apps.ingestion_app.domain.recovery import RecoveryRequest
from apps.ingestion_app.runtime.controller import RuntimeControlConflictError
from apps.ingestion_app.runtime.supervisor import (
    DesiredRuntimeState,
    RuntimeSnapshot,
    RuntimeState,
)
from apps.ingestion_app.services.config_reconciliation import AssetNotFoundError
from apps.ingestion_app.settings import AssetSettings
from tests.ingestion._asgi import request
from tests.ingestion.runtime.test_supervisor import _settings


class _FakeController:
    def __init__(self) -> None:
        self.settings = _settings()
        self.is_started = True
        self._snapshot = RuntimeSnapshot(
            desired_state=DesiredRuntimeState.RUNNING,
            state=RuntimeState.STOPPED,
            last_error=None,
        )
        self.calls: list[str] = []

    @property
    def enabled_asset_count(self) -> int:
        return sum(1 for asset in self.settings.assets.values() if asset.enabled)

    def snapshot(self) -> RuntimeSnapshot:
        return self._snapshot

    async def start(self) -> None:
        self.is_started = True

    async def close(self) -> None:
        self.is_started = False

    async def pause(self) -> RuntimeSnapshot:
        self.calls.append("pause")
        self._snapshot = RuntimeSnapshot(
            desired_state=DesiredRuntimeState.PAUSED,
            state=RuntimeState.STOPPED,
            last_error=None,
        )
        return self._snapshot

    async def resume(self) -> RuntimeSnapshot:
        self.calls.append("resume")
        self._snapshot = RuntimeSnapshot(
            desired_state=DesiredRuntimeState.RUNNING,
            state=RuntimeState.STOPPED,
            last_error=None,
        )
        return self._snapshot

    async def reconnect(self) -> RuntimeSnapshot:
        self.calls.append("reconnect")
        if self._snapshot.desired_state is DesiredRuntimeState.PAUSED:
            raise RuntimeControlConflictError("cannot reconnect a paused runtime")
        return self._snapshot

    async def recover(self, request: RecoveryRequest) -> RuntimeSnapshot:
        self.calls.append(f"recover:{request.reason}")
        return self._snapshot


class _FakeConfigService:
    def __init__(self, controller: _FakeController) -> None:
        self.controller = controller
        self.created: list[AssetSettings] = []
        self.patches: list[tuple[str, dict[str, object]]] = []

    def list_assets(self):
        return tuple(
            self.controller.settings.assets[name]
            for name in sorted(self.controller.settings.assets)
        )

    def get_asset(self, asset: str):
        result = self.controller.settings.assets.get(asset.strip().upper())
        if result is None:
            raise AssetNotFoundError(asset)
        return result

    async def create_asset(self, asset: AssetSettings):
        self.created.append(asset)
        return asset

    async def patch_asset(self, asset: str, updates: dict[str, object]):
        self.patches.append((asset, updates))
        return self.controller.settings.assets[asset.upper()]


def _client() -> tuple[object, _FakeController, _FakeConfigService]:
    controller = _FakeController()
    service = _FakeConfigService(controller)
    app = create_app(runtime_controller=controller, config_service=service)
    return app, controller, service


@pytest.mark.asyncio
async def test_health_routes_and_runtime_snapshot() -> None:
    app, controller, _ = _client()

    live = await request(app, "GET", "/health/live")
    assert live.body == {"status": "live", "runtime": None}
    ready = await request(app, "GET", "/health/ready")
    assert ready.status_code == 200
    assert ready.body["status"] == "ready"
    assert ready.body["runtime"]["state"] == "stopped"

    controller._snapshot = RuntimeSnapshot(
        desired_state=DesiredRuntimeState.RUNNING,
        state=RuntimeState.ERROR,
        last_error="fatal",
    )
    not_ready = await request(app, "GET", "/health/ready")
    assert not_ready.status_code == 503
    assert not_ready.body["detail"]["runtime"]["last_error"] == "fatal"


@pytest.mark.asyncio
async def test_health_ready_requires_controller_initialization() -> None:
    app, controller, _ = _client()
    controller.is_started = False

    not_started = await request(app, "GET", "/health/ready")

    assert not_started.status_code == 503
    assert not_started.body["detail"]["runtime"]["state"] == "stopped"

    controller.is_started = True
    ready = await request(app, "GET", "/health/ready")
    assert ready.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("zero_assets", [False, True])
async def test_health_ready_tracks_start_and_close(
    zero_assets: bool,
) -> None:
    app, controller, _ = _client()
    if zero_assets:
        raw = controller.settings.model_dump(mode="json")
        raw["assets"]["BTC"]["enabled"] = False
        controller.settings = type(controller.settings).model_validate(raw)
    controller.is_started = False

    assert (await request(app, "GET", "/health/ready")).status_code == 503
    await controller.start()
    assert (await request(app, "GET", "/health/ready")).status_code == 200
    await controller.close()
    assert (await request(app, "GET", "/health/ready")).status_code == 503


@pytest.mark.asyncio
async def test_read_routes_are_deterministic_and_metadata_only() -> None:
    app, _, _ = _client()

    assets = await request(app, "GET", "/assets")
    assert assets.status_code == 200
    assert [asset["asset"] for asset in assets.body["assets"]] == ["BTC"]
    assert (await request(app, "GET", "/assets/BTC")).status_code == 200
    assert (await request(app, "GET", "/assets/UNKNOWN")).status_code == 404

    providers = await request(app, "GET", "/providers")
    assert providers.status_code == 200
    assert [provider["provider_id"] for provider in providers.body["providers"]] == [
        "binance_native",
        "ccxt_binance",
    ]
    runtime = await request(app, "GET", "/runtime")
    assert runtime.body["desired_state"] == "running"


@pytest.mark.asyncio
async def test_mutation_and_runtime_control_routes_delegate() -> None:
    app, controller, service = _client()
    asset = controller.settings.assets["BTC"].model_dump(mode="json")

    created = await request(app, "POST", "/assets", asset)
    assert created.status_code == 201
    assert len(service.created) == 1
    patched = await request(
        app,
        "PATCH",
        "/assets/BTC",
        {"updates": {"enabled": False}},
    )
    assert patched.status_code == 200
    assert service.patches == [("BTC", {"enabled": False})]

    assert (await request(app, "POST", "/runtime/pause")).status_code == 200
    assert (await request(app, "POST", "/runtime/resume")).status_code == 200
    assert (await request(app, "POST", "/runtime/reconnect")).status_code == 200
    recovery = await request(
        app,
        "POST",
        "/runtime/recover",
        {
            "asset": "BTC",
            "instrument_id": "BTC-TEST-PERP",
            "since": "2026-08-09T09:00:00Z",
            "until": "2026-08-09T10:00:00Z",
        },
    )
    assert recovery.status_code == 200
    assert controller.calls == ["pause", "resume", "reconnect", "recover:manual_api"]
    assert (await request(app, "DELETE", "/assets/BTC")).status_code == 405


@pytest.mark.asyncio
async def test_manual_recovery_rejects_non_utc_bounds() -> None:
    app, _, _ = _client()
    response = await request(
        app,
        "POST",
        "/runtime/recover",
        {
            "asset": "BTC",
            "instrument_id": "BTC-TEST-PERP",
            "since": "2026-08-09T09:00:00+05:30",
            "until": "2026-08-09T10:00:00+05:30",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("since", "until"),
    [
        ("2026-08-09T09:00:30Z", "2026-08-09T10:00:00Z"),
        ("2026-08-09T09:00:00Z", "2026-08-09T10:00:30Z"),
    ],
)
async def test_manual_recovery_rejects_unaligned_grid_without_controller_call(
    since: str,
    until: str,
) -> None:
    app, controller, _ = _client()
    before = controller.snapshot()

    response = await request(
        app,
        "POST",
        "/runtime/recover",
        {
            "asset": "BTC",
            "instrument_id": "BTC-TEST-PERP",
            "since": since,
            "until": until,
        },
    )

    assert response.status_code == 422
    assert controller.calls == []
    assert controller.snapshot() == before


@pytest.mark.asyncio
async def test_manual_recovery_rejects_disabled_asset() -> None:
    app, controller, _ = _client()
    raw = controller.settings.model_dump(mode="json")
    raw["assets"]["BTC"]["enabled"] = False
    controller.settings = type(controller.settings).model_validate(raw)

    response = await request(
        app,
        "POST",
        "/runtime/recover",
        {
            "asset": "BTC",
            "instrument_id": "BTC-TEST-PERP",
            "since": "2026-08-09T09:00:00Z",
            "until": "2026-08-09T10:00:00Z",
        },
    )
    assert response.status_code == 409
