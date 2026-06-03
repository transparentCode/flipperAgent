from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FailingWorker:
    def __init__(self, asset: str, timeframe: str) -> None:
        self.asset = asset
        self.timeframe = timeframe

    async def connect(self, redis_client) -> None:
        return None

    async def start(self) -> None:
        raise RuntimeError("boom")


class _HealthyWorker:
    def __init__(self, asset: str, timeframe: str) -> None:
        self.asset = asset
        self.timeframe = timeframe

    async def connect(self, redis_client) -> None:
        return None

    async def start(self) -> None:
        return None


@pytest.mark.asyncio
@patch("apps.strategy_app.main.configure_logging")
@patch("apps.strategy_app.main.discover_pairs")
@patch("apps.strategy_app.main.create_valkey_client")
@patch("apps.strategy_app.main.ConfigManager")
async def test_run_isolates_pair_failure(
    MockConfigManager,
    mock_create_valkey_client,
    mock_discover_pairs,
    _mock_configure_logging,
) -> None:
    from apps.strategy_app.main import _run

    redis_client = AsyncMock()
    mock_create_valkey_client.return_value = redis_client
    mock_discover_pairs.return_value = [("BTCUSDT", "1h"), ("ETHUSDT", "4h")]

    cfg = MockConfigManager.return_value
    cfg.register_file = MagicMock()
    cfg.get.return_value = "INFO"

    with patch(
        "apps.strategy_app.main.StrategyWorker",
        side_effect=[_FailingWorker("BTCUSDT", "1h"), _HealthyWorker("ETHUSDT", "4h")],
    ):
        await _run()

    redis_client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_worker_swallows_pair_failure_and_returns() -> None:
    from apps.strategy_app.main import _run_worker

    redis_client = AsyncMock()
    with patch("apps.strategy_app.main.StrategyWorker", return_value=_FailingWorker("BTCUSDT", "1h")):
        await _run_worker("BTCUSDT", "1h", redis_client)
