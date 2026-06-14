from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.signal_app.models import SignalPair


@pytest.mark.asyncio
@patch("apps.signal_app.main.configure_logging")
@patch("apps.signal_app.main.init_db_pools", new_callable=AsyncMock)
@patch("apps.signal_app.main.create_valkey_client")
@patch("apps.signal_app.main.AssetManifestStore.list_runtime_pairs")
@patch("apps.signal_app.main.SignalPairCatalog")
@patch("apps.signal_app.main.DBPoolManager.close_pools", new_callable=AsyncMock)
@patch("apps.signal_app.main.ConfigManager")
async def test_run_prefers_manifest_pairs_for_runtime(
    MockConfigManager,
    mock_close_pools,
    MockSignalPairCatalog,
    mock_list_runtime_pairs,
    mock_create_valkey_client,
    _mock_init_db_pools,
    _mock_configure_logging,
) -> None:
    from apps.signal_app.main import _run

    redis_client = AsyncMock()
    mock_create_valkey_client.return_value = redis_client
    mock_list_runtime_pairs.return_value = [("BTCUSDT", "1h"), ("ETHUSDT", "4h")]

    cfg = MockConfigManager.return_value
    cfg.register_file = MagicMock()
    cfg.get.side_effect = lambda key, default=None: "INFO" if key == "logging.level" else default

    fallback_catalog = MockSignalPairCatalog.return_value
    fallback_catalog.list_pairs.return_value = [SignalPair(asset="SOLUSDT", timeframe="1h")]

    runner = MagicMock()
    runner.connect = AsyncMock()
    runner.start = AsyncMock()
    runner.stop = AsyncMock()

    with patch("apps.signal_app.main.SignalRuntimeRunner", return_value=runner) as mock_runner:
        await _run()

    catalog = mock_runner.call_args.kwargs["catalog"]
    assert [pair.key for pair in catalog.list_pairs()] == ["BTCUSDT:1h", "ETHUSDT:4h"]
    runner.connect.assert_awaited_once_with(redis_client)
    runner.start.assert_awaited_once()
    runner.stop.assert_awaited_once()
    redis_client.aclose.assert_awaited_once()
    mock_close_pools.assert_awaited_once()
