"""Shared connection factories for Valkey and DB pools."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import valkey.asyncio as valkey

from libs.common.config import ConfigManager
from libs.common.db.pool_manager import DBPoolManager
from libs.common.enums import SystemComponent
from libs.common.logging.logger_utils import bind_logger

logger = bind_logger(__name__, system_component=SystemComponent.CORE_INFRASTRUCTURE)

_VALKEY_CONNECT_RETRIES = 3
_VALKEY_RETRY_DELAYS = [1, 2, 4]  # exponential backoff seconds


async def create_valkey_client(
    config_mgr: ConfigManager | None = None,
) -> valkey.Valkey:
    """Create a Valkey (redis-compatible) async client from config.

    Resolution order:
      1. ``VALKEY_URI`` env var  (Docker override)
      2. ``REDIS_URI``  env var  (legacy compat)
      3. ``valkey.uri`` from config YAML
      4. Hardcoded fallback ``redis://localhost:6379/0``

    Retries up to 3 times with exponential backoff (1s, 2s, 4s) on connection failure.
    """
    uri = os.getenv("VALKEY_URI") or os.getenv("REDIS_URI")
    if not uri:
        if config_mgr is None:
            config_mgr = ConfigManager()
        uri = config_mgr.get("valkey.uri", "redis://localhost:6379/0")

    _masked_uri = uri.split('@')[-1] if '@' in uri else uri
    logger.info(f"Connecting Valkey client → ...@{_masked_uri}")

    last_err: Exception | None = None
    for attempt in range(_VALKEY_CONNECT_RETRIES):
        try:
            client: valkey.Valkey = valkey.Valkey.from_url(uri, decode_responses=True)
            await client.ping()
            logger.info("Valkey client connected")
            return client
        except Exception as e:
            last_err = e
            delay = _VALKEY_RETRY_DELAYS[attempt] if attempt < len(_VALKEY_RETRY_DELAYS) else _VALKEY_RETRY_DELAYS[-1]
            logger.warning(
                f"Valkey connection attempt {attempt + 1}/{_VALKEY_CONNECT_RETRIES} failed: {e}. "
                f"Retrying in {delay}s..."
            )
            await asyncio.sleep(delay)

    raise ConnectionError(
        f"Failed to connect to Valkey after {_VALKEY_CONNECT_RETRIES} attempts: {last_err}"
    )


async def init_db_pools(config_mgr: ConfigManager | None = None) -> None:
    """Initialize DB connection pools via DBPoolManager.

    This is a thin wrapper that ensures ConfigManager is passed through.
    The actual retry logic and POSTGRES_URI env var override live in
    DBPoolManager.init_pools().
    """
    await DBPoolManager.init_pools(config_manager=config_mgr)
    logger.info("DB pools initialized")
