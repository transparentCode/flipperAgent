import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.ingestion_app.orchestration.worker import startup


@pytest.mark.asyncio
async def test_worker_startup_applies_ingestion_schema():
    ctx = {}
    mock_valkey_client = AsyncMock()

    with patch("apps.ingestion_app.orchestration.worker.BinanceNativeAdapter"), \
         patch("apps.ingestion_app.orchestration.worker.CCXTAdapter"), \
         patch("apps.ingestion_app.orchestration.worker.DBPoolManager") as mock_db_pool, \
         patch("apps.ingestion_app.orchestration.worker.apply_ingestion_schema", new=AsyncMock()) as mock_apply_schema, \
         patch("apps.ingestion_app.orchestration.worker.create_valkey_client", new=AsyncMock(return_value=mock_valkey_client)), \
         patch("apps.ingestion_app.orchestration.worker.IngestionCoordinator") as mock_coordinator, \
         patch("apps.ingestion_app.orchestration.worker.config_manager") as mock_config:
        mock_config.get.side_effect = lambda k, default=None: {
            "ingestion.credentials.api_key": "",
            "ingestion.credentials.api_secret": "",
        }.get(k, default)
        mock_db_pool.init_pools = AsyncMock()
        mock_db_pool.get_writer_pool.return_value = MagicMock()
        mock_coordinator.return_value = MagicMock()

        await startup(ctx)

    mock_db_pool.init_pools.assert_awaited_once()
    mock_apply_schema.assert_awaited_once_with(mock_db_pool.get_writer_pool.return_value)
    assert "binance_adapter" in ctx
    assert "ccxt_adapter" in ctx
    assert "coordinator" in ctx
