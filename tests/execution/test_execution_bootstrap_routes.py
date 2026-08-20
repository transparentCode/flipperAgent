from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeConfig:
    def __init__(self) -> None:
        self.lookups: list[tuple[str, object]] = []

    def get(self, key: str, default=None):
        self.lookups.append((key, default))
        if key == "risk.runtime.signal_routes":
            return ["BTCUSDT:1h", "BTCUSDT:4h", "ETHUSDT:4h"]
        if key == "execution":
            return {"mode": "paper"}
        if key == "logging.level":
            return "INFO"
        return default


@pytest.mark.asyncio
async def test_bootstrap_execution_app_derives_assets_from_risk_runtime_routes() -> (
    None
):
    from apps.execution_app.bootstrap import bootstrap_execution_app

    config = _FakeConfig()
    redis_client = AsyncMock()
    writer_pool = object()

    with (
        patch("apps.execution_app.bootstrap.build_config_manager", return_value=config),
        patch("apps.execution_app.bootstrap.configure_execution_logging"),
        patch("apps.execution_app.bootstrap.init_db_pools", new_callable=AsyncMock),
        patch(
            "apps.execution_app.bootstrap.create_valkey_client",
            new=AsyncMock(return_value=redis_client),
        ),
        patch(
            "apps.execution_app.bootstrap.DBPoolManager.get_writer_pool",
            return_value=writer_pool,
        ),
    ):
        context = await bootstrap_execution_app()

    assert context.assets == ["BTCUSDT", "ETHUSDT"]
    assert context.redis_client is redis_client
    assert context.writer_pool is writer_pool
    assert ("risk.runtime.signal_routes", ()) in config.lookups


@pytest.mark.asyncio
async def test_bootstrap_execution_app_returns_empty_context_when_no_routes() -> None:
    from apps.execution_app.bootstrap import bootstrap_execution_app

    config = _FakeConfig()
    config.get = MagicMock(
        side_effect=lambda key, default=None: {
            "risk.runtime.signal_routes": (),
            "execution": {"mode": "paper"},
            "logging.level": "INFO",
        }.get(key, default)
    )

    with (
        patch("apps.execution_app.bootstrap.build_config_manager", return_value=config),
        patch("apps.execution_app.bootstrap.configure_execution_logging"),
    ):
        context = await bootstrap_execution_app()

    assert context.assets == []
    assert context.redis_client is None
    assert context.writer_pool is None
