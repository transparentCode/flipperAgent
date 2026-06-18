from __future__ import annotations

from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api_app.routers.ingestion import (
    batch_apply_ingestion_asset_action,
    batch_upsert_ingestion_assets,
    ingestion_asset,
    ingestion_assets,
    ingestion_events,
    ingestion_ops_summary,
    ingestion_scraper_create_job,
    ingestion_scraper_fetch,
    ingestion_scraper_get_job,
    ingestion_status,
    patch_ingestion_asset,
    pause_ingestion_asset,
    remove_ingestion_asset,
    resume_ingestion_asset,
    stop_ingestion_asset,
    upsert_ingestion_asset,
)
from apps.api_app.clients.scraper_service import ScraperServiceClientError
from apps.ingestion_app.models.asset_registry import (
    IngestionAssetActionRequest,
    IngestionAssetBatchActionRequest,
    IngestionAssetBatchUpsertRequest,
    IngestionAssetPatchRequest,
    IngestionAssetRecord,
    IngestionAssetUpsertRequest,
)
from apps.scraper_app.core.models import (
    ScrapeDataset,
    ScrapeIntent,
    ScrapeJobRecord,
    ScrapeJobStatus,
    ScrapeRequest,
    ScrapeResult,
    ScraperProvider,
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
            {"state": "LIVE", "disconnects_in_window": 0, "downstream_ready": True},
            {"state": "WARMING", "disconnects_in_window": 1, "downstream_ready": True},
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
    assert result["BTCUSDT:1m"]["downstream_ready"] is True
    assert result["ETHUSDT:1m"]["disconnects_in_window"] == 1
    fake_valkey.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingestion_events_decodes_and_filters_stream_entries():
    fake_valkey = MagicMock()
    fake_valkey.aclose = AsyncMock()
    fake_valkey.xrevrange = AsyncMock(
        return_value=[
            (
                "2-0",
                {
                    "event_id": "runtime-1",
                    "event_type": "GAP_FILL_FAILED",
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "severity": "error",
                    "detail": '{"failed_assets":["BTCUSDT"]}',
                    "emitted_at": "1717000000.0",
                },
            ),
            (
                "1-0",
                {
                    "event_id": "control-1",
                    "event_type": "COMMAND_ACCEPTED",
                    "command_id": "cmd-1",
                    "command_type": "PAUSE_ASSET",
                    "symbol": "ETHUSDT",
                    "requested_by": "tests",
                    "detail": '{"desired_state":"PAUSED"}',
                    "emitted_at": "1716999999.0",
                },
            ),
        ]
    )

    with patch(
        "apps.api_app.routers.ingestion.create_valkey_client",
        AsyncMock(return_value=fake_valkey),
    ):
        result = await ingestion_events(limit=10, symbol="btcusdt", event_type="gap_fill_failed")

    assert result["count"] == 1
    event = result["events"][0]
    assert event["stream_id"] == "2-0"
    assert event["kind"] == "runtime"
    assert event["detail"]["failed_assets"] == ["BTCUSDT"]
    assert event["symbol"] == "BTCUSDT"
    fake_valkey.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingestion_ops_summary_selects_latest_signals():
    fake_valkey = MagicMock()
    fake_valkey.aclose = AsyncMock()
    fake_valkey.xrevrange = AsyncMock(
        return_value=[
            (
                "5-0",
                {
                    "event_id": "evt-5",
                    "event_type": "ASSET_PURGE_FAILED",
                    "symbol": "SOLUSDT",
                    "timeframe": "1m",
                    "severity": "error",
                    "detail": '{"phase":"delete"}',
                    "emitted_at": "1717000005.0",
                },
            ),
            (
                "4-0",
                {
                    "event_id": "evt-4",
                    "event_type": "RUNTIME_RETRY_EXHAUSTED",
                    "symbol": "BTCUSDT",
                    "timeframe": "1m",
                    "severity": "critical",
                    "detail": '{"disconnect_count":5}',
                    "emitted_at": "1717000004.0",
                },
            ),
            (
                "3-0",
                {
                    "event_id": "evt-3",
                    "event_type": "ASSET_PURGE_COMPLETED",
                    "symbol": "ETHUSDT",
                    "timeframe": "1m",
                    "severity": "info",
                    "detail": '{"deleted_rows":{"ohlcv":42}}',
                    "emitted_at": "1717000003.0",
                },
            ),
            (
                "2.5-0",
                {
                    "event_id": "evt-2b",
                    "event_type": "GAP_FILL_COMPLETED",
                    "symbol": "ADAUSDT",
                    "timeframe": "1m",
                    "severity": "info",
                    "detail": '{"successful_assets":["ADAUSDT"]}',
                    "emitted_at": "1717000002.5",
                },
            ),
            (
                "2-0",
                {
                    "event_id": "evt-2",
                    "event_type": "GAP_FILL_FAILED",
                    "symbol": "BNBUSDT",
                    "timeframe": "1m",
                    "severity": "error",
                    "detail": '{"failed_assets":["BNBUSDT"]}',
                    "emitted_at": "1717000002.0",
                },
            ),
            (
                "1-0",
                {
                    "event_id": "evt-1",
                    "event_type": "COMMAND_ACCEPTED",
                    "command_id": "cmd-1",
                    "command_type": "RESUME_ASSET",
                    "symbol": "DOGEUSDT",
                    "requested_by": "tests",
                    "detail": '{"desired_state":"LIVE"}',
                    "emitted_at": "1717000001.0",
                },
            ),
        ]
    )

    with patch(
        "apps.api_app.routers.ingestion.create_valkey_client",
        AsyncMock(return_value=fake_valkey),
    ):
        result = await ingestion_ops_summary(scan_limit=100)

    assert result["last_command_accepted"]["event_type"] == "COMMAND_ACCEPTED"
    assert result["last_gap_fill_failure"]["symbol"] == "BNBUSDT"
    assert result["last_gap_fill_result"]["event_type"] == "GAP_FILL_COMPLETED"
    assert result["last_runtime_retry_exhausted"]["symbol"] == "BTCUSDT"
    assert result["last_purge_result"]["event_type"] == "ASSET_PURGE_FAILED"
    assert result["last_failure"]["event_type"] == "ASSET_PURGE_FAILED"
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
async def test_batch_upsert_ingestion_assets_uses_control_service():
    expected_a = MagicMock()
    expected_b = MagicMock()

    with patch(
        "apps.api_app.routers.ingestion._safe_create_valkey_client",
        AsyncMock(return_value=None),
    ), patch(
        "apps.api_app.routers.ingestion.DBPoolManager.get_writer_pool",
        return_value=MagicMock(),
    ), patch(
        "apps.api_app.routers.ingestion.IngestionControlService.upsert_asset",
        AsyncMock(side_effect=[expected_a, expected_b]),
    ) as upsert_asset:
        result = await batch_upsert_ingestion_assets(
            IngestionAssetBatchUpsertRequest(
                assets=[
                    IngestionAssetUpsertRequest(symbol="SOLUSDT", publish_timeframes=["1h"]),
                    IngestionAssetUpsertRequest(symbol="ETHUSDT", publish_timeframes=["4h"]),
                ]
            )
        )

    assert result == [expected_a, expected_b]
    assert upsert_asset.await_count == 2


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
async def test_pause_stop_resume_remove_routes_apply_control_actions():
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
        stop_result = await stop_ingestion_asset("BTCUSDT", IngestionAssetActionRequest(reason="maintenance"))
        resume_result = await resume_ingestion_asset("BTCUSDT", IngestionAssetActionRequest())
        remove_result = await remove_ingestion_asset("BTCUSDT", IngestionAssetActionRequest(reason="delist"))

    assert pause_result is expected
    assert stop_result is expected
    assert resume_result is expected
    assert remove_result is expected
    assert apply_action.await_count == 4


@pytest.mark.asyncio
async def test_batch_apply_ingestion_asset_action_uses_control_service():
    btc = IngestionAssetRecord(symbol="BTCUSDT", publish_timeframes=["1h"], source="registry")
    eth = IngestionAssetRecord(symbol="ETHUSDT", publish_timeframes=["4h"], source="registry")
    expected_a = MagicMock()
    expected_b = MagicMock()

    with patch(
        "apps.api_app.routers.ingestion.IngestionAssetCatalog.get_effective_asset",
        AsyncMock(side_effect=[btc, eth]),
    ), patch(
        "apps.api_app.routers.ingestion._safe_create_valkey_client",
        AsyncMock(return_value=None),
    ), patch(
        "apps.api_app.routers.ingestion.DBPoolManager.get_writer_pool",
        return_value=MagicMock(),
    ), patch(
        "apps.api_app.routers.ingestion.IngestionControlService.apply_action",
        AsyncMock(side_effect=[expected_a, expected_b]),
    ) as apply_action:
        result = await batch_apply_ingestion_asset_action(
            IngestionAssetBatchActionRequest(
                symbols=["btcusdt", "ethusdt"],
                desired_state="STOPPED",
                reason="maintenance window",
            )
        )

    assert result == [expected_a, expected_b]
    assert apply_action.await_count == 2


@pytest.mark.asyncio
async def test_ingestion_scraper_fetch_uses_scraper_client():
    expected = ScrapeResult(
        provider=ScraperProvider.TRADINGVIEW,
        dataset=ScrapeDataset.OHLCV,
        intent=ScrapeIntent.ON_DEMAND_REFRESH,
        source="live",
        symbol="CRYPTOCAP:TOTAL3ES",
        timeframe="1h",
        summary={"rows": 1},
        data=[{"timestamp": 1, "close": 2.0}],
    )

    with patch(
        "apps.api_app.routers.ingestion.ScraperServiceClient.fetch_sync",
        AsyncMock(return_value=expected),
    ):
        result = await ingestion_scraper_fetch(
            ScrapeRequest(
                provider=ScraperProvider.TRADINGVIEW,
                dataset=ScrapeDataset.OHLCV,
                symbol="CRYPTOCAP:TOTAL3ES",
                timeframe="1h",
            )
        )

    assert result is expected


@pytest.mark.asyncio
async def test_ingestion_scraper_job_routes_use_scraper_client():
    request = ScrapeRequest(
        provider=ScraperProvider.COINGLASS,
        dataset=ScrapeDataset.HEATMAP,
        coin="SOL",
        symbol="SOLUSDT",
        short_name="SOLUSDT",
    )
    created = ScrapeJobRecord(
        job_id="scrape-coinglass-heatmap-sol",
        status=ScrapeJobStatus.QUEUED,
        request=request,
        created_at=1.0,
        updated_at=1.0,
    )
    fetched = created.model_copy(update={"status": ScrapeJobStatus.SUCCEEDED})

    with patch(
        "apps.api_app.routers.ingestion.ScraperServiceClient.create_job",
        AsyncMock(return_value=created),
    ) as create_job, patch(
        "apps.api_app.routers.ingestion.ScraperServiceClient.get_job",
        AsyncMock(return_value=fetched),
    ) as get_job:
        create_result = await ingestion_scraper_create_job(request)
        get_result = await ingestion_scraper_get_job("scrape-coinglass-heatmap-sol", include_result=False)

    assert create_result is created
    assert get_result is fetched
    create_job.assert_awaited_once()
    get_job.assert_awaited_once_with("scrape-coinglass-heatmap-sol", include_result=False)


@pytest.mark.asyncio
async def test_ingestion_scraper_routes_surface_client_errors():
    with patch(
        "apps.api_app.routers.ingestion.ScraperServiceClient.fetch_sync",
        AsyncMock(
            side_effect=ScraperServiceClientError(
                status_code=502,
                detail="Scraper service unavailable.",
            )
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await ingestion_scraper_fetch(
                ScrapeRequest(
                    provider=ScraperProvider.TRADINGVIEW,
                    dataset=ScrapeDataset.OHLCV,
                    symbol="CRYPTOCAP:TOTAL3ES",
                    timeframe="1h",
                )
            )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "Scraper service unavailable."
