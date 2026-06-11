from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from apps.ingestion_app.constants import EXCHANGE_BINANCE
from apps.ingestion_app_v2.jobs.cleanup import purge_removed_asset, scheduled_asset_cleanup
from apps.ingestion_app_v2.jobs.gap_fill import run_rest_gap_fill
from apps.ingestion_app_v2.jobs.l2_depth import poll_l2_depth
from apps.ingestion_app_v2.jobs.topup import poll_binance_ohlcv
from libs.common.exceptions import DataIngestionError


DEFAULT_MOCK_TIMESTAMP = 1672531200000


@pytest.mark.asyncio
async def test_v2_standard_gap_fill_flow(base_worker_ctx, mock_ccxt_adapter, mock_asyncpg_pool):
    symbol = "BTCUSDT"
    mock_ccxt_adapter.get_historical_ohlcv.return_value = pd.DataFrame(
        [[DEFAULT_MOCK_TIMESTAMP, 16000.0, 16100.0, 15900.0, 16050.0, 100.0]],
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )

    await run_rest_gap_fill(base_worker_ctx, [symbol], EXCHANGE_BINANCE)

    conn = mock_asyncpg_pool.acquire.return_value.__aenter__.return_value
    conn.executemany.assert_awaited_once()
    _, tuples = conn.executemany.call_args[0]
    assert tuples[0][1] == symbol
    assert tuples[0][2] == "1m"


@pytest.mark.asyncio
async def test_v2_gap_fill_partial_failures_emit_event():
    ctx = {
        "ccxt_adapter": AsyncMock(),
        "coordinator": MagicMock(transition=AsyncMock()),
        "valkey_client": AsyncMock(),
    }

    with patch("apps.ingestion_app_v2.jobs.gap_fill._fetch_asset_gap", new=AsyncMock(side_effect=[None, RuntimeError("boom")])), \
         patch("apps.ingestion_app_v2.jobs.gap_fill.config_manager") as mock_config, \
         patch("apps.ingestion_app_v2.jobs.gap_fill.publish_ingestion_runtime_event", new=AsyncMock()) as mock_event:
        mock_config.get.side_effect = lambda key, default=None: {
            "ingestion.timeframes.base_gap_fill": "1m",
            "ingestion.concurrency.gap_fill_limit": 5,
            "ingestion.concurrency.gap_fill_sleep_seconds": 0.0,
        }.get(key, default)

        with pytest.raises(DataIngestionError) as exc_info:
            await run_rest_gap_fill(ctx, ["BTCUSDT", "ETHUSDT"], EXCHANGE_BINANCE)

    mock_event.assert_awaited_once()
    assert exc_info.value.context["failed_assets"] == ["ETHUSDT"]


@pytest.mark.asyncio
async def test_v2_poll_binance_topup_uses_ctx_adapter():
    ctx = {"binance_adapter": AsyncMock()}

    with patch("apps.ingestion_app_v2.jobs.topup._top_up_binance_ohlcv", new=AsyncMock()) as mock_topup, \
         patch("apps.ingestion_app_v2.jobs.topup.config_manager") as mock_config:
        mock_config.get.side_effect = lambda key, default=None: {
            "ingestion.timeframes.default": "15m",
            "ingestion.assets.target_list": ["BTCUSDT", "ETHUSDT"],
        }.get(key, default)
        await poll_binance_ohlcv(ctx)

    assert mock_topup.await_count == 2


@pytest.mark.asyncio
async def test_v2_purge_removed_asset_clears_keys_and_emits_completion_event():
    ctx = {"valkey_client": AsyncMock()}
    janitor = MagicMock()
    janitor.purge_asset_data = AsyncMock(return_value={"ohlcv": 5})
    janitor.finalize_asset_removal = AsyncMock(return_value=True)

    with patch("apps.ingestion_app_v2.jobs.cleanup.IngestionStorageJanitor", return_value=janitor), \
         patch("apps.ingestion_app_v2.jobs.cleanup.DBPoolManager.get_writer_pool", return_value=MagicMock()), \
         patch("apps.ingestion_app_v2.jobs.cleanup.publish_ingestion_runtime_event", new=AsyncMock()) as mock_publish:
        await purge_removed_asset(ctx, "BTCUSDT", "1m")

    assert ctx["valkey_client"].delete.await_count == 4
    mock_publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_v2_scheduled_asset_cleanup_replays_pending_removals():
    ctx = {"valkey_client": AsyncMock()}
    janitor = MagicMock()
    janitor.list_pending_removals = AsyncMock(return_value=[("BTCUSDT", "1m"), ("ETHUSDT", "4h")])

    with patch("apps.ingestion_app_v2.jobs.cleanup.IngestionStorageJanitor", return_value=janitor), \
         patch("apps.ingestion_app_v2.jobs.cleanup.DBPoolManager.get_writer_pool", return_value=MagicMock()), \
         patch("apps.ingestion_app_v2.jobs.cleanup.purge_removed_asset", new=AsyncMock()) as mock_purge:
        await scheduled_asset_cleanup(ctx)

    assert mock_purge.await_count == 2


@pytest.mark.asyncio
async def test_v2_poll_l2_depth_raises_when_all_assets_fail():
    ctx = {"binance_adapter": AsyncMock()}

    with patch("apps.ingestion_app_v2.jobs.l2_depth._fetch_l2_depth_snapshot", new=AsyncMock(side_effect=RuntimeError("depth"))), \
         patch("apps.ingestion_app_v2.jobs.l2_depth.config_manager") as mock_config, \
         patch("apps.ingestion_app_v2.jobs.l2_depth.asyncio.sleep", new=AsyncMock(return_value=None)):
        mock_config.get.side_effect = lambda key, default=None: {
            "ingestion.assets.target_list": ["BTCUSDT", "ETHUSDT"],
            "ingestion.l2_depth.snapshot_levels": 20,
        }.get(key, default)
        with pytest.raises(DataIngestionError):
            await poll_l2_depth(ctx)
