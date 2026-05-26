"""Shared connection factories for Valkey and DB pools."""

from __future__ import annotations

import os
from typing import Any

import valkey.asyncio as valkey

from libs.common.config import ConfigManager
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.CORE_INFRASTRUCTURE)


async def create_valkey_client(
    config_mgr: ConfigManager | None = None,
) -> valkey.Valkey:
    """Create a Valkey (redis-compatible) async client from config.

    Resolution order:
      1. ``VALKEY_URI`` env var  (Docker override)
      2. ``REDIS_URI``  env var  (legacy compat)
      3. ``redis.uri`` from config YAML
      4. Hardcoded fallback ``redis://localhost:6379/0``
    """
    uri = os.getenv("VALKEY_URI") or os.getenv("REDIS_URI")
    if not uri:
        if config_mgr is None:
            config_mgr = ConfigManager()
        uri = config_mgr.get("redis.uri", "redis://localhost:6379/0")

    logger.info(f"Connecting Valkey client → {uri}")
    client: valkey.Valkey = valkey.Valkey.from_url(uri, decode_responses=False)
    # Verify connectivity
    await client.ping()
    logger.info("Valkey client connected")
    return client


async def init_db_pools(config_mgr: ConfigManager | None = None) -> None:
    """Initialize DB connection pools via DBPoolManager.

    This is a thin wrapper that ensures ConfigManager is passed through.
    The actual retry logic and POSTGRES_URI env var override live in
    DBPoolManager.init_pools().
    """
    await DBPoolManager.init_pools(config_manager=config_mgr)
    logger.info("DB pools initialized")
