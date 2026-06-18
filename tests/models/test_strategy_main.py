from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
@patch("apps.strategy_app.main.configure_logging")
@patch("apps.strategy_app.main.AssetManifestStore.list_assets")
@patch("apps.strategy_app.main.build_strategy_pairs")
@patch("apps.strategy_app.main.create_valkey_client")
@patch("apps.strategy_app.main.ConfigManager")
async def test_run_uses_runtime_runner_for_manifest_pairs(
    MockConfigManager,
    mock_create_valkey_client,
    mock_build_strategy_pairs,
    mock_list_assets,
    _mock_configure_logging,
) -> None:
    from apps.strategy_app.main import _run

    redis_client = AsyncMock()
    mock_create_valkey_client.return_value = redis_client
    mock_list_assets.return_value = [MagicMock(symbol="BTCUSDT", timeframes=["1m", "1h"])]
    mock_build_strategy_pairs.return_value = [
        __import__("apps.strategy_app.state", fromlist=["StrategyPair"]).StrategyPair(asset="BTCUSDT", timeframe="1h", source="asset_manifest"),
        __import__("apps.strategy_app.state", fromlist=["StrategyPair"]).StrategyPair(asset="ETHUSDT", timeframe="4h", source="asset_manifest"),
    ]

    cfg = MockConfigManager.return_value
    cfg.get.side_effect = lambda key, default=None: "INFO" if key == "logging.level" else default

    runner = MagicMock()
    runner.connect = AsyncMock()
    runner.start = AsyncMock()
    runner.stop = AsyncMock()

    with patch("apps.strategy_app.main.StrategyRuntimeRunner", return_value=runner) as mock_runner:
        await _run()

    mock_runner.assert_called_once()
    pairs = mock_runner.call_args.args[0]
    assert [(pair.asset, pair.timeframe, pair.source) for pair in pairs] == [
        ("BTCUSDT", "1h", "asset_manifest"),
        ("ETHUSDT", "4h", "asset_manifest"),
    ]
    assert mock_build_strategy_pairs.call_args.kwargs["live_manifests"] == mock_list_assets.return_value
    runner.connect.assert_awaited_once_with(redis_client)
    runner.start.assert_awaited_once()
    runner.stop.assert_awaited_once()
    redis_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
@patch("apps.strategy_app.main.configure_logging")
@patch("apps.strategy_app.main.AssetManifestStore.list_assets")
@patch("apps.strategy_app.main.build_strategy_pairs")
@patch("apps.strategy_app.main.create_valkey_client")
@patch("apps.strategy_app.main.ConfigManager")
async def test_run_falls_back_to_config_pairs_when_manifest_empty(
    MockConfigManager,
    mock_create_valkey_client,
    mock_build_strategy_pairs,
    mock_list_assets,
    _mock_configure_logging,
) -> None:
    from apps.strategy_app.main import _run

    redis_client = AsyncMock()
    mock_create_valkey_client.return_value = redis_client
    mock_list_assets.return_value = []
    from apps.strategy_app.state import StrategyPair

    mock_build_strategy_pairs.return_value = [
        StrategyPair(asset="SOLUSDT", timeframe="4h", trigger_timeframe="1m", source="config"),
    ]

    cfg = MockConfigManager.return_value
    cfg.get.side_effect = lambda key, default=None: "INFO" if key == "logging.level" else default

    runner = MagicMock()
    runner.connect = AsyncMock()
    runner.start = AsyncMock()
    runner.stop = AsyncMock()

    with patch("apps.strategy_app.main.StrategyRuntimeRunner", return_value=runner) as mock_runner:
        await _run()

    pairs = mock_runner.call_args.args[0]
    assert [(pair.asset, pair.timeframe, pair.source) for pair in pairs] == [
        ("SOLUSDT", "4h", "config"),
    ]
    assert pairs[0].trigger_timeframe == "1m"
    runner.stop.assert_awaited_once()
    redis_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
@patch("apps.strategy_app.main.configure_logging")
@patch("apps.strategy_app.main.AssetManifestStore.list_assets")
@patch("apps.strategy_app.main.build_strategy_pairs")
@patch("apps.strategy_app.main.create_valkey_client")
@patch("apps.strategy_app.main.ConfigManager")
async def test_run_exits_cleanly_when_no_pairs_exist(
    MockConfigManager,
    mock_create_valkey_client,
    mock_build_strategy_pairs,
    mock_list_assets,
    _mock_configure_logging,
) -> None:
    from apps.strategy_app.main import _run

    redis_client = AsyncMock()
    mock_create_valkey_client.return_value = redis_client
    mock_list_assets.return_value = []
    mock_build_strategy_pairs.return_value = []

    cfg = MockConfigManager.return_value
    cfg.get.side_effect = lambda key, default=None: "INFO" if key == "logging.level" else default

    with patch("apps.strategy_app.main.StrategyRuntimeRunner") as mock_runner:
        await _run()

    mock_runner.assert_not_called()
    redis_client.aclose.assert_awaited_once()
