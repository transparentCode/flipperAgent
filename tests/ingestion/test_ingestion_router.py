from __future__ import annotations

from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api_app.routers.ingestion import (
    ingestion_asset,
    ingestion_assets,
    ingestion_status,
    patch_ingestion_asset,
    pause_ingestion_asset,
    remove_ingestion_asset,
    resume_ingestion_asset,
    upsert_ingestion_asset,
)
from apps.ingestion_app.models.asset_registry import (
    IngestionAssetActionRequest,
    IngestionAssetPatchRequest,
    IngestionAssetRecord,
    IngestionAssetUpsertRequest,
)


@pytest.mark.asyncio
async def test_ingestion_assets_route_returns_catalog_records():
    assets = [
        IngestionAssetRecord(
            symbol="BTCUSDT",
            publish_timeframes=["1h", "4h"],
            source="config",
        )
    ]

    with patch(
        "apps.api_app.routers.ingestion.IngestionAssetCatalog.list_effective_assets",
        AsyncMock(return_value=assets),
    ):
        result = await ingestion_assets()

    assert len(result) == 1
    assert result[0].symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_ingestion_asset_route_raises_not_found_when_missing():
    with patch(
        "apps.api_app.routers.ingestion.IngestionAssetCatalog.get_effective_asset",
        AsyncMock(return_value=None),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await ingestion_asset("adausdt")

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_ingestion_status_uses_effective_asset_catalog():
    assets = [
        IngestionAssetRecord(
            symbol="BTCUSDT",
            base_timeframe="1m",
            publish_timeframes=["1h", "4h"],
            source="registry",
        ),
        IngestionAssetRecord(
            symbol="ETHUSDT",
            base_timeframe="1m",
            publish_timeframes=["4h"],
            source="registry",
        ),
    ]
    fake_valkey = MagicMock()
    fake_valkey.aclose = AsyncMock()
    fake_coordinator = MagicMock()
    fake_coordinator.get_observability_snapshot = AsyncMock(
        side_effect=[
            {"state": "LIVE", "disconnects_in_window": 0},
            {"state": "WARMING", "disconnects_in_window": 1},
        ]
    )

    with patch(
        "apps.api_app.routers.ingestion.IngestionAssetCatalog.list_effective_assets",
        AsyncMock(return_value=assets),
    ), patch(
        "apps.api_app.routers.ingestion.create_valkey_client",
        AsyncMock(return_value=fake_valkey),
    ), patch(
        "apps.api_app.routers.ingestion.IngestionCoordinator",
        return_value=fake_coordinator,
    ):
        result = await ingestion_status()

    assert result["BTCUSDT:1m"]["state"] == "LIVE"
    assert result["ETHUSDT:1m"]["disconnects_in_window"] == 1
    fake_valkey.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_upsert_ingestion_asset_uses_control_service():
    expected = MagicMock()

    with patch(
        "apps.api_app.routers.ingestion._safe_create_valkey_client",
        AsyncMock(return_value=None),
    ), patch(
        "apps.api_app.routers.ingestion.DBPoolManager.get_writer_pool",
        return_value=MagicMock(),
    ), patch(
        "apps.api_app.routers.ingestion.IngestionControlService.upsert_asset",
        AsyncMock(return_value=expected),
    ):
        result = await upsert_ingestion_asset(
            IngestionAssetUpsertRequest(symbol="SOLUSDT", publish_timeframes=["1h"])
        )

    assert result is expected


@pytest.mark.asyncio
async def test_patch_ingestion_asset_uses_control_service():
    asset = IngestionAssetRecord(symbol="BTCUSDT", publish_timeframes=["1h"], source="registry")
    expected = MagicMock()

    with patch(
        "apps.api_app.routers.ingestion.IngestionAssetCatalog.get_effective_asset",
        AsyncMock(return_value=asset),
    ), patch(
        "apps.api_app.routers.ingestion._safe_create_valkey_client",
        AsyncMock(return_value=None),
    ), patch(
        "apps.api_app.routers.ingestion.DBPoolManager.get_writer_pool",
        return_value=MagicMock(),
    ), patch(
        "apps.api_app.routers.ingestion.IngestionControlService.patch_asset",
        AsyncMock(return_value=expected),
    ):
        result = await patch_ingestion_asset(
            "BTCUSDT",
            IngestionAssetPatchRequest(publish_timeframes=["4h"]),
        )

    assert result is expected


@pytest.mark.asyncio
async def test_pause_resume_remove_routes_apply_control_actions():
    asset = IngestionAssetRecord(symbol="BTCUSDT", publish_timeframes=["1h"], source="registry")
    expected = MagicMock()

    with patch(
        "apps.api_app.routers.ingestion.IngestionAssetCatalog.get_effective_asset",
        AsyncMock(return_value=asset),
    ), patch(
        "apps.api_app.routers.ingestion._safe_create_valkey_client",
        AsyncMock(return_value=None),
    ), patch(
        "apps.api_app.routers.ingestion.DBPoolManager.get_writer_pool",
        return_value=MagicMock(),
    ), patch(
        "apps.api_app.routers.ingestion.IngestionControlService.apply_action",
        AsyncMock(return_value=expected),
    ) as apply_action:
        pause_result = await pause_ingestion_asset("BTCUSDT", IngestionAssetActionRequest())
        resume_result = await resume_ingestion_asset("BTCUSDT", IngestionAssetActionRequest())
        remove_result = await remove_ingestion_asset("BTCUSDT", IngestionAssetActionRequest(reason="delist"))

    assert pause_result is expected
    assert resume_result is expected
    assert remove_result is expected
    assert apply_action.await_count == 3
