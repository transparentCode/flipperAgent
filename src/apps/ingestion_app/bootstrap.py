from __future__ import annotations

import os
from typing import Any

from arq.connections import RedisSettings

from apps.ingestion_app.adapters.binance_native import BinanceNativeAdapter
from apps.ingestion_app.adapters.crypto_ccxt import CCXTAdapter
from apps.ingestion_app.constants import EXCHANGE_BINANCE
from apps.ingestion_app.coordination import IngestionCoordinator
from apps.ingestion_app.storage.bootstrap import apply_ingestion_schema
from libs.common.config import ConfigManager
from libs.common.connections import create_valkey_client
from libs.common.db.pool_manager import DBPoolManager


def build_redis_settings(config_manager: ConfigManager) -> RedisSettings:
    return RedisSettings.from_dsn(
        os.getenv("VALKEY_URI")
        or os.getenv("REDIS_URI")
        or config_manager.get("valkey.uri", "redis://localhost:6379/0")
    )


async def initialize_storage(config_manager: ConfigManager) -> None:
    await DBPoolManager.init_pools(config_manager=config_manager)
    await apply_ingestion_schema(DBPoolManager.get_writer_pool())


async def create_runtime_coordinator(
    config_manager: ConfigManager,
) -> tuple[Any, IngestionCoordinator]:
    valkey_client = await create_valkey_client(config_manager)
    return valkey_client, IngestionCoordinator(valkey_client, config_manager)


async def populate_worker_context(ctx: dict[str, Any], config_manager: ConfigManager) -> None:
    binance_key = config_manager.get("ingestion.credentials.api_key", "")
    binance_secret = config_manager.get("ingestion.credentials.api_secret", "")
    ctx["binance_adapter"] = BinanceNativeAdapter(key=binance_key, secret=binance_secret)
    ctx["ccxt_adapter"] = CCXTAdapter(exchange_id=EXCHANGE_BINANCE)

    await initialize_storage(config_manager)
    valkey_client, coordinator = await create_runtime_coordinator(config_manager)
    ctx["valkey_client"] = valkey_client
    ctx["coordinator"] = coordinator


async def cleanup_worker_context(ctx: dict[str, Any]) -> None:
    await DBPoolManager.close_pools()

    ccxt_adapter = ctx.get("ccxt_adapter")
    if ccxt_adapter:
        await ccxt_adapter.close()

    valkey_client = ctx.get("valkey_client")
    if valkey_client:
        await valkey_client.aclose()
