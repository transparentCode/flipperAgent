from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from apps.ingestion_app.constants import EXCHANGE_BINANCE
from apps.ingestion_app.coordination import IngestionCoordinator
from apps.ingestion_app.jobs.cleanup import purge_removed_asset, scheduled_asset_cleanup
from apps.ingestion_app.jobs.gap_fill import run_rest_gap_fill, scheduled_gap_fill
from apps.ingestion_app.models.asset_registry import IngestionAssetDesiredState, IngestionAssetRecord
from apps.ingestion_app.jobs.l2_depth import poll_l2_depth
from apps.ingestion_app.jobs.topup import poll_binance_ohlcv
from libs.common.exceptions import DataIngestionError


DEFAULT_MOCK_TIMESTAMP = 1672531200000


@pytest.fixture
def mock_asyncpg_pool():
    pool = MagicMock()
    conn = AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__.return_value = conn
    ctx.__aexit__.return_value = None
    pool.acquire.return_value = ctx
    return pool


@pytest.fixture
def mock_ccxt_adapter():
    return AsyncMock()


@pytest.fixture(autouse=True)
def patch_v2_db_pool_manager(mock_asyncpg_pool, mocker):
    mocker.patch(
        "apps.ingestion_app.jobs.gap_fill.DBPoolManager.get_writer_pool",
        return_value=mock_asyncpg_pool,
    )
    mocker.patch(
        "apps.ingestion_app.jobs.gap_fill.DBPoolManager.get_reader_pool",
        return_value=mock_asyncpg_pool,
    )


@pytest.fixture
def base_worker_ctx(mock_ccxt_adapter):
    coordinator = MagicMock(spec=IngestionCoordinator)
    coordinator.transition = AsyncMock()
    coordinator.clear_resume_backfill_required = AsyncMock()
    coordinator.get_state = AsyncMock(return_value="WARMING")
    return {
        "job_id": "test_job_123",
        "ccxt_adapter": mock_ccxt_adapter,
        "binance_adapter": AsyncMock(),
        "coordinator": coordinator,
    }


@pytest.mark.asyncio
async def test_v2_standard_gap_fill_flow(base_worker_ctx, mock_ccxt_adapter, mock_asyncpg_pool):
    symbol = "BTCUSDT"
    mock_ccxt_adapter.get_historical_ohlcv.return_value = pd.DataFrame(
        [[DEFAULT_MOCK_TIMESTAMP, 16000.0, 16100.0, 15900.0, 16050.0, 100.0]],
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )

    with patch("apps.ingestion_app.jobs.gap_fill.publish_ingestion_runtime_event", new=AsyncMock()) as mock_event:
        await run_rest_gap_fill(base_worker_ctx, [symbol], EXCHANGE_BINANCE)

    conn = mock_asyncpg_pool.acquire.return_value.__aenter__.return_value
    conn.executemany.assert_awaited_once()
    _, tuples = conn.executemany.call_args[0]
    assert tuples[0][1] == symbol
    assert tuples[0][2] == "1m"
    base_worker_ctx["coordinator"].clear_resume_backfill_required.assert_awaited_once_with(symbol, "1m")
    mock_event.assert_awaited_once()
    assert mock_event.await_args.kwargs["event_type"].value == "GAP_FILL_COMPLETED"
    assert base_worker_ctx["coordinator"].transition.await_args_list[0].args == (
        symbol,
        "1m",
        "BACKFILLING",
    )
    assert base_worker_ctx["coordinator"].transition.await_args_list[1].args == (
        symbol,
        "1m",
        "WARMING",
    )


@pytest.mark.asyncio
async def test_v2_gap_fill_partial_failures_emit_event():
    ctx = {
        "ccxt_adapter": AsyncMock(),
        "coordinator": MagicMock(
            transition=AsyncMock(),
            clear_resume_backfill_required=AsyncMock(),
            get_state=AsyncMock(return_value="WARMING"),
        ),
        "valkey_client": None,
    }

    with patch("apps.ingestion_app.jobs.gap_fill._fetch_asset_gap", new=AsyncMock(side_effect=[None, RuntimeError("boom")])), \
         patch("apps.ingestion_app.jobs.gap_fill.config_manager") as mock_config, \
         patch("apps.ingestion_app.jobs.gap_fill.publish_ingestion_runtime_event", new=AsyncMock()) as mock_event:
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
async def test_v2_gap_fill_promotes_resuming_asset_to_live_and_emits_lifecycle():
    ctx = {
        "ccxt_adapter": AsyncMock(),
        "coordinator": MagicMock(
            transition=AsyncMock(),
            clear_resume_backfill_required=AsyncMock(),
            get_state=AsyncMock(return_value="WARMING"),
        ),
        "valkey_client": AsyncMock(),
    }
    ctx["valkey_client"].hgetall = AsyncMock(return_value={})
    resuming_asset = IngestionAssetRecord(
        symbol="BTCUSDT",
        publish_timeframes=["1h"],
        desired_state=IngestionAssetDesiredState.RESUMING,
        source="registry",
    )
    live_asset = resuming_asset.model_copy(update={"desired_state": IngestionAssetDesiredState.LIVE})
    repo = MagicMock()
    repo.get_asset = AsyncMock(return_value=resuming_asset)
    repo.upsert_asset = AsyncMock(return_value=live_asset)

    with patch("apps.ingestion_app.jobs.gap_fill._fetch_asset_gap", new=AsyncMock(return_value=None)), \
         patch("apps.ingestion_app.jobs.gap_fill.IngestionAssetRegistryRepository", return_value=repo), \
         patch("apps.ingestion_app.jobs.gap_fill.config_manager") as mock_config, \
         patch("apps.ingestion_app.jobs.gap_fill.publish_ingestion_runtime_event", new=AsyncMock()):
        mock_config.get.side_effect = lambda key, default=None: {
            "ingestion.timeframes.base_gap_fill": "1m",
            "ingestion.concurrency.gap_fill_limit": 1,
            "ingestion.concurrency.gap_fill_sleep_seconds": 0.0,
        }.get(key, default)
        await run_rest_gap_fill(ctx, ["BTCUSDT"], EXCHANGE_BINANCE)

    repo.upsert_asset.assert_awaited_once()
    xadd_streams = [call.args[0] for call in ctx["valkey_client"].xadd.await_args_list]
    assert "asset:lifecycle" in xadd_streams


@pytest.mark.asyncio
async def test_v2_gap_fill_does_not_downgrade_live_runtime_state():
    ctx = {
        "ccxt_adapter": AsyncMock(),
        "coordinator": MagicMock(
            transition=AsyncMock(),
            clear_resume_backfill_required=AsyncMock(),
            get_state=AsyncMock(return_value="LIVE"),
        ),
        "valkey_client": None,
    }

    with patch("apps.ingestion_app.jobs.gap_fill._fetch_asset_gap", new=AsyncMock(return_value=None)), \
         patch("apps.ingestion_app.jobs.gap_fill.config_manager") as mock_config, \
         patch("apps.ingestion_app.jobs.gap_fill.publish_ingestion_runtime_event", new=AsyncMock()):
        mock_config.get.side_effect = lambda key, default=None: {
            "ingestion.timeframes.base_gap_fill": "1m",
            "ingestion.concurrency.gap_fill_limit": 1,
            "ingestion.concurrency.gap_fill_sleep_seconds": 0.0,
        }.get(key, default)
        await run_rest_gap_fill(ctx, ["BTCUSDT"], EXCHANGE_BINANCE)

    ctx["coordinator"].transition.assert_not_awaited()


@pytest.mark.asyncio
async def test_v2_poll_binance_topup_uses_ctx_adapter():
    ctx = {"binance_adapter": AsyncMock()}

    with patch("apps.ingestion_app.jobs.topup._top_up_binance_ohlcv", new=AsyncMock()) as mock_topup, \
         patch("apps.ingestion_app.jobs.topup.config_manager") as mock_config, \
         patch("apps.ingestion_app.jobs.topup.list_schedulable_symbols", new=AsyncMock(return_value=["BTCUSDT", "ETHUSDT"])):
        mock_config.get.side_effect = lambda key, default=None: {
            "ingestion.timeframes.default": "15m",
        }.get(key, default)
        await poll_binance_ohlcv(ctx)

    assert mock_topup.await_count == 2


@pytest.mark.asyncio
async def test_v2_scheduled_gap_fill_uses_effective_asset_catalog():
    ctx = {"ccxt_adapter": AsyncMock(), "coordinator": MagicMock(transition=AsyncMock())}

    with patch(
        "apps.ingestion_app.jobs.gap_fill.list_schedulable_symbols",
        new=AsyncMock(return_value=["BTCUSDT", "SOLUSDT"]),
    ), patch(
        "apps.ingestion_app.jobs.gap_fill.run_rest_gap_fill",
        new=AsyncMock(),
    ) as mock_run_rest_gap_fill:
        await scheduled_gap_fill(ctx)

    mock_run_rest_gap_fill.assert_awaited_once_with(ctx, ["BTCUSDT", "SOLUSDT"], EXCHANGE_BINANCE)


@pytest.mark.asyncio
async def test_v2_purge_removed_asset_clears_keys_and_emits_completion_event():
    ctx = {"valkey_client": AsyncMock()}
    janitor = MagicMock()
    janitor.purge_asset_data = AsyncMock(return_value={"ohlcv": 5})
    janitor.finalize_asset_removal = AsyncMock(return_value=True)
    registry = MagicMock()
    registry.get_asset = AsyncMock(return_value=MagicMock(publish_timeframes=["1m", "1h"]))

    with patch("apps.ingestion_app.jobs.cleanup.IngestionStorageJanitor", return_value=janitor), \
         patch("apps.ingestion_app.jobs.cleanup.IngestionAssetRegistryRepository", return_value=registry), \
         patch("apps.ingestion_app.jobs.cleanup.DBPoolManager.get_writer_pool", return_value=MagicMock()), \
        patch("apps.ingestion_app.jobs.cleanup.publish_ingestion_runtime_event", new=AsyncMock()) as mock_publish:
        await purge_removed_asset(ctx, "BTCUSDT", "1m")

    assert ctx["valkey_client"].delete.await_count == 10
    mock_publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_v2_scheduled_asset_cleanup_replays_pending_removals():
    ctx = {"valkey_client": AsyncMock()}
    janitor = MagicMock()
    janitor.list_pending_removals = AsyncMock(return_value=[("BTCUSDT", "1m"), ("ETHUSDT", "4h")])

    with patch("apps.ingestion_app.jobs.cleanup.IngestionStorageJanitor", return_value=janitor), \
         patch("apps.ingestion_app.jobs.cleanup.DBPoolManager.get_writer_pool", return_value=MagicMock()), \
         patch("apps.ingestion_app.jobs.cleanup.purge_removed_asset", new=AsyncMock()) as mock_purge:
        await scheduled_asset_cleanup(ctx)

    assert mock_purge.await_count == 2


@pytest.mark.asyncio
async def test_v2_poll_l2_depth_raises_when_all_assets_fail():
    ctx = {"binance_adapter": AsyncMock()}

    with patch("apps.ingestion_app.jobs.l2_depth._fetch_l2_depth_snapshot", new=AsyncMock(side_effect=RuntimeError("depth"))), \
         patch("apps.ingestion_app.jobs.l2_depth.list_schedulable_symbols", new=AsyncMock(return_value=["BTCUSDT", "ETHUSDT"])), \
         patch("apps.ingestion_app.jobs.l2_depth.config_manager") as mock_config, \
         patch("apps.ingestion_app.jobs.l2_depth.asyncio.sleep", new=AsyncMock(return_value=None)):
        mock_config.get.side_effect = lambda key, default=None: {
            "ingestion.l2_depth.snapshot_levels": 20,
        }.get(key, default)
        with pytest.raises(DataIngestionError):
            await poll_l2_depth(ctx)
