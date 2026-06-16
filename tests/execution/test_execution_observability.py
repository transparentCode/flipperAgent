from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from apps.execution_app.observability.runtime_state import (
    ExecutionRuntimeStateStore,
    runtime_status_key,
)
from apps.execution_app.observability.status import ExecutionObservabilityService
from apps.execution_app.state import ExecutionAsset, ExecutionAssetState
from libs.contracts.serialization import valkey_encode


@pytest.mark.asyncio
async def test_execution_status_route_returns_runtime_status(monkeypatch) -> None:
    from apps.api_app.routers.execution import execution_status

    redis_client = AsyncMock()
    redis_client.xrevrange.side_effect = [
        [
            (
                "1-0",
                {
                    "timestamp": "1700000000000",
                    "order_id": "ord-1",
                    "status": "filled",
                },
            )
        ],
        [],
    ]
    redis_client.hgetall.return_value = {}
    redis_client.aclose = AsyncMock()

    monkeypatch.setattr(
        "apps.api_app.routers.execution.discover_pairs",
        lambda _config: [("BTCUSDT", "1h")],
    )
    monkeypatch.setattr(
        "apps.api_app.routers.execution.create_valkey_client",
        AsyncMock(return_value=redis_client),
    )

    status = await execution_status()

    assert status["BTCUSDT"].asset.asset == "BTCUSDT"
    assert status["BTCUSDT"].state == ExecutionAssetState.LIVE
    assert status["BTCUSDT"].last_fill_ts == 1_700_000_000_000.0
    assert status["BTCUSDT"].detail["latest_fill_status"] == "ok"
    redis_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_execution_failures_route_returns_latest_failure(monkeypatch) -> None:
    from apps.api_app.routers.execution import execution_failures

    redis_client = AsyncMock()
    redis_client.xrevrange.side_effect = [
        [
            (
                "2-0",
                {
                    "timestamp": "1700000005000",
                    "asset": "BTCUSDT",
                    "consumer_group": "execution_app_group",
                    "consumer_name": "execution_worker_BTCUSDT",
                    "error_type": "RuntimeError",
                    "error_message": "broker unavailable",
                },
            )
        ],
    ]
    redis_client.aclose = AsyncMock()

    monkeypatch.setattr(
        "apps.api_app.routers.execution.discover_pairs",
        lambda _config: [("BTCUSDT", "1h")],
    )
    monkeypatch.setattr(
        "apps.api_app.routers.execution.create_valkey_client",
        AsyncMock(return_value=redis_client),
    )

    failures = await execution_failures()

    assert failures["BTCUSDT"]["status"] == "ok"
    assert failures["BTCUSDT"]["error_type"] == "RuntimeError"
    assert failures["BTCUSDT"]["error_message"] == "broker unavailable"
    redis_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_execution_summary_route_combines_views(monkeypatch) -> None:
    from apps.api_app.routers.execution import execution_summary

    redis_client = AsyncMock()
    redis_client.xrevrange.side_effect = [
        [
            (
                "1-0",
                {"timestamp": "1700000000000", "order_id": "ord-1", "status": "filled"},
            )
        ],
        [
            (
                "1-1",
                {
                    "timestamp": "1700000005000",
                    "asset": "BTCUSDT",
                    "error_type": "RuntimeError",
                    "error_message": "broker unavailable",
                },
            )
        ],
    ]
    redis_client.hgetall.return_value = {}
    redis_client.aclose = AsyncMock()

    monkeypatch.setattr(
        "apps.api_app.routers.execution.discover_pairs",
        lambda _config: [("BTCUSDT", "1h")],
    )
    monkeypatch.setattr(
        "apps.api_app.routers.execution.create_valkey_client",
        AsyncMock(return_value=redis_client),
    )

    summary = await execution_summary()

    assert "status" in summary
    assert "fills" in summary
    assert "failures" in summary
    assert summary["fills"]["BTCUSDT"]["status"] == "ok"
    assert summary["failures"]["BTCUSDT"]["status"] == "ok"
    redis_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_execution_observability_merges_persisted_status() -> None:
    redis_client = AsyncMock()
    redis_client.hgetall.return_value = {}
    asset = ExecutionAsset(asset="BTCUSDT")
    store = ExecutionRuntimeStateStore(redis_client)
    persisted = await store.update(
        asset,
        state=ExecutionAssetState.DEGRADED,
        mode="paper",
        last_order_ts=1_700_000_200_000.0,
        last_error="bootstrap degraded",
        detail={"phase": "bootstrap"},
    )

    async def hgetall(key: str):
        if key == runtime_status_key("BTCUSDT"):
            return valkey_encode(persisted, inject_trace=False)
        return {}

    redis_client.hgetall.side_effect = hgetall
    redis_client.xrevrange.side_effect = [
        [
            (
                "1-0",
                {
                    "timestamp": "1700000300000",
                    "order_id": "ord-1",
                    "status": "filled",
                },
            )
        ],
        [],
    ]

    service = ExecutionObservabilityService(redis_client, [asset])
    status = await service.status()

    assert status["BTCUSDT"].state == ExecutionAssetState.DEGRADED
    assert status["BTCUSDT"].last_error == "bootstrap degraded"
    assert status["BTCUSDT"].last_fill_ts == 1_700_000_300_000.0
    assert status["BTCUSDT"].detail["phase"] == "bootstrap"
    assert status["BTCUSDT"].detail["latest_fill_status"] == "ok"
